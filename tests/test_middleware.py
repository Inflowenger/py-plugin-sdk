"""The request pipeline: middleware order, naming, rejection, the job's context.
The Python counterpart of sdkv1/middleware_test.go."""
from __future__ import annotations

import asyncio
import json

import pytest

from inflow_plugin_sdk import (
    Action,
    JobContext,
    Request,
    background,
    chain_signals,
    job_id,
    job_id_from_context,
    log_signals,
    run_pipeline,
    signal_port_note,
    use,
    with_job_id_context,
)
from inflow_plugin_sdk.models import Signal

from conftest import MockMsg, RecordingPlugin


async def run_one(p: RecordingPlugin, action: Action, body=None) -> MockMsg:
    """Run one request of `action` through p's pipeline, to the end."""
    data = b"" if body is None else json.dumps(body).encode()
    msg = MockMsg(data=data, subject="inflow.cpu.PID.run")
    if action.method == "":
        action.method = "run"
    if action.request_handler is None:
        action.request_handler = lambda job: None
    await run_pipeline(p, action, Request(data=data, plugin=p), msg)
    return msg


def reply(msg: MockMsg) -> dict:
    return json.loads(msg.responses[0]) if msg.responses else {}


# ---- order & naming -------------------------------------------------------


async def test_middleware_runs_in_order_after_the_namer(rec):
    order: list[str] = []

    def mark(name):
        def fn(ctx, job):
            order.append(name)
            return ctx

        return fn

    rec.use(mark("plugin-1"), mark("plugin-2"))
    await run_one(
        rec,
        Action(
            middleware=use(mark("action-1"), mark("action-2")),
            request_handler=lambda job: order.append("handler"),
        ),
    )
    assert order == ["plugin-1", "plugin-2", "action-1", "action-2", "handler"]


async def test_use_skips_none_and_keeps_order():
    a = lambda ctx, job: ctx  # noqa: E731
    b = lambda ctx, job: ctx  # noqa: E731
    assert use(a, None, b) == [a, b]
    assert use() == []


async def test_job_id_names_the_job_before_anything_else_sees_it(rec):
    seen = {}

    def spy(ctx, job):
        seen["job"] = job.job_id
        seen["ctx"] = job_id_from_context(ctx)
        return ctx

    msg = await run_one(rec, Action(middleware=[spy]))
    assert len(seen["job"]) == 36
    assert seen["ctx"] == seen["job"]
    assert reply(msg)["jobId"] == seen["job"]


async def test_job_id_is_fresh_per_request(rec):
    ids = set()
    for _ in range(3):
        ids.add(reply(await run_one(rec, Action()))["jobId"])
    assert len(ids) == 3


async def test_a_later_function_may_rename_the_job(rec):
    handler_saw = {}

    def rename(ctx, job):
        return with_job_id_context(ctx, "upstream-12345")

    def after(ctx, job):
        assert job.job_id == "upstream-12345"
        return ctx

    msg = await run_one(
        rec,
        Action(
            middleware=[rename, after],
            request_handler=lambda job: handler_saw.setdefault("id", job.job_id),
        ),
    )
    assert reply(msg)["jobId"] == "upstream-12345"
    assert handler_saw["id"] == "upstream-12345"


async def test_with_job_id_replaces_the_namer(rec):
    rec.job_id_fn = lambda ctx, job: with_job_id_context(ctx, "named-by-plugin")
    msg = await run_one(rec, Action())
    assert reply(msg)["jobId"] == "named-by-plugin"


async def test_a_nameless_job_is_rejected(rec):
    rec.job_id_fn = lambda ctx, job: ctx  # binds nothing
    ran = []
    msg = await run_one(rec, Action(request_handler=lambda job: ran.append(1)))
    assert "no jobId" in reply(msg)["error"]
    assert ran == []


# ---- the context ----------------------------------------------------------


async def test_the_context_flows_to_the_handler_and_ends_when_it_returns(rec):
    key = object()
    seen = {}

    async def handler(job):
        ctx = job.context()
        seen["ctx"] = ctx
        seen["value"] = ctx.value(key)
        seen["live"] = not ctx.canceled

    await run_one(
        rec,
        Action(middleware=[lambda ctx, job: ctx.with_value(key, "bound")], request_handler=handler),
    )
    assert seen["value"] == "bound"
    assert seen["live"] is True
    assert seen["ctx"].canceled is True


async def test_on_done_fires_when_the_jobs_context_ends(rec):
    causes = []

    def register(ctx, job):
        ctx.on_done(causes.append)
        return ctx

    await run_one(rec, Action(middleware=[register]))
    await asyncio.sleep(0)
    assert len(causes) == 1


async def test_job_with_context_copies_the_job(rec):
    seen = {}

    def handler(job):
        narrowed = job.with_context(background().with_value("k", 1))
        seen["value"] = narrowed.context().value("k")
        seen["same_id"] = narrowed.job_id == job.job_id

    await run_one(rec, Action(request_handler=handler))
    assert seen == {"value": 1, "same_id": True}


async def test_an_action_without_middleware_gets_a_working_context(rec):
    seen = {}
    await run_one(rec, Action(request_handler=lambda job: seen.setdefault("c", job.context().canceled)))
    assert seen["c"] is False


# ---- rejection & failure --------------------------------------------------


async def test_a_middleware_error_rejects_and_the_handler_never_runs(rec):
    ran = []
    later = []

    def boom(ctx, job):
        raise RuntimeError("joern refused the query")

    def after(ctx, job):
        later.append(1)
        return ctx

    msg = await run_one(
        rec,
        Action(middleware=[boom, after], request_handler=lambda job: ran.append(1)),
    )
    assert reply(msg) == {"error": "joern refused the query"}
    assert ran == [] and later == []
    assert rec.sent == [], "a rejected request sends no command"


async def test_an_async_middleware_failure_is_the_same_as_a_raised_one(rec):
    async def boom(ctx, job):
        await asyncio.sleep(0)
        raise RuntimeError("upstream down")

    msg = await run_one(rec, Action(middleware=[boom]))
    assert reply(msg) == {"error": "upstream down"}


async def test_a_handler_error_is_reported_as_a_failure(rec):
    def handler(job):
        raise RuntimeError("boom")

    await run_one(rec, Action(request_handler=handler))
    assert len(rec.sent) == 1
    subject, body = rec.sent[0]
    assert subject.endswith(".progress")
    assert json.loads(body)["error"]["message"] == "boom"


async def test_a_handler_raising_after_its_job_was_stopped_reports_nothing(rec):
    """In Python a cancellation unwinds out of the handler (ctx.run, an aborted
    client). The runtime has stopped listening by then, so the SDK must not try
    to report — Go cannot reach this path, where cancellation is a return value."""
    from inflow_plugin_sdk import jobstop

    stops = jobstop.Registry()

    async def handler(job):
        await job.context().run(asyncio.sleep(10))

    action = Action(method="run", middleware=[stops.middleware], request_handler=handler)
    msg = MockMsg(subject="inflow.cpu.PID.run")
    task = asyncio.create_task(run_pipeline(rec, action, Request(data=b"", plugin=rec), msg))
    await asyncio.sleep(0.01)
    stops.on_signal(Signal(kind="proc", subject="s", job_id=reply(msg)["jobId"], conclusion="flow_stop_by_user"))
    await task
    assert rec.sent == []


async def test_dispatch_does_not_wait_for_one_requests_middleware(rec):
    gate = asyncio.Event()
    started: list[str] = []

    async def slow(ctx, job):
        started.append(job.job_id)
        await gate.wait()
        return ctx

    action = Action(method="run", middleware=[slow], request_handler=lambda job: None)
    first, second = MockMsg(subject="inflow.cpu.PID.run"), MockMsg(subject="inflow.cpu.PID.run")
    a = asyncio.create_task(run_pipeline(rec, action, Request(data=b"", plugin=rec), first))
    b = asyncio.create_task(run_pipeline(rec, action, Request(data=b"", plugin=rec), second))
    await asyncio.sleep(0.01)
    assert len(started) == 2, "the second request started while the first was blocked"
    assert first.responses == [], "neither is accepted yet"
    gate.set()
    await asyncio.gather(a, b)
    assert reply(first)["jobId"] and reply(second)["jobId"]


# ---- the signal port ------------------------------------------------------


async def test_chain_signals_gives_every_handler_every_signal_in_order():
    seen: list[str] = []

    def blow_up(sig):
        raise RuntimeError("handler blew up")

    chained = chain_signals(lambda s: seen.append("first"), blow_up, lambda s: seen.append("third"), None)
    await chained(Signal(kind="proc", subject="s", job_id="j", conclusion="done"))
    assert seen == ["first", "third"]


async def test_log_signals_prints_one_line_per_signal(capsys):
    log = log_signals("ai-decision")
    log(Signal(kind="proc", subject="inflow.plugin.PID.proc", job_id="job-1", conclusion="flow_stop_by_user"))
    log(Signal(kind="future", subject="inflow.plugin.PID.future", data=b'{"x":1}'))
    lines = capsys.readouterr().out.strip().split("\n")
    assert lines[0] == (
        "ai-decision: signal proc job=job-1 conclusion=flow_stop_by_user canceled=True succeeded=False"
    )
    assert lines[1] == (
        'ai-decision: signal future subject=inflow.plugin.PID.future data={"x":1}'
    )


async def test_the_port_note_names_the_actions_whose_middleware_will_never_fire(rec):
    rec.add_action(Action(method="run", middleware=[job_id], request_handler=lambda j: None))
    rec.add_action(Action(method="plain", request_handler=lambda j: None))
    note = signal_port_note(rec)
    assert "Signals not subscribed on : inflow.plugin.PID.>" in note
    assert note.endswith("actions with middleware: run")
    assert "plain" not in note
