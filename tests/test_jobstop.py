"""jobstop, and the two patterns built on it: a job named by an external service,
and work observed across runs. The Python counterpart of jobstop/jobstop_test.go
+ sdkv1/{jobstop,externalid,detached}_integration_test.go."""
from __future__ import annotations

import asyncio
import json

from inflow_plugin_sdk import (
    Action,
    Request,
    cast_request_to,
    chain_signals,
    jobstop,
    run_pipeline,
    use,
    with_job_id_context,
)
from inflow_plugin_sdk.models import Signal
from inflow_plugin_sdk.types import canceled

from conftest import MockMsg, RecordingPlugin


def proc(job_id: str, conclusion: str) -> Signal:
    return Signal(
        kind="proc",
        subject="inflow.plugin.PID.proc",
        job_id=job_id,
        conclusion=conclusion,
        data=json.dumps({"jobId": job_id, "conclusion": conclusion}).encode(),
    )


def start(p: RecordingPlugin, action: Action, body=None):
    """Run one request through p's pipeline; returns (msg, task)."""
    data = b"" if body is None else json.dumps(body).encode()
    msg = MockMsg(data=data, subject="inflow.cpu.PID.run")
    if action.method == "":
        action.method = "run"
    if action.request_handler is None:
        action.request_handler = lambda job: None
    task = asyncio.create_task(run_pipeline(p, action, Request(data=data, plugin=p), msg))
    return msg, task


def job_id_of(msg: MockMsg) -> str:
    return json.loads(msg.responses[0])["jobId"]


def held_handler(ctx_box: dict, gate: asyncio.Event):
    async def handler(job):
        ctx_box["ctx"] = job.context()
        await gate.wait()

    return handler


# ---- the registry on its own ----------------------------------------------


async def test_a_stop_cancels_the_job_it_names(rec, capsys):
    stops = jobstop.Registry()
    gate, box = asyncio.Event(), {}
    msg, task = start(
        rec, Action(middleware=use(stops.middleware), request_handler=held_handler(box, gate))
    )
    await asyncio.sleep(0.01)
    assert len(stops) == 1
    assert box["ctx"].canceled is False

    stops.on_signal(proc(job_id_of(msg), "flow_stop_by_user"))
    assert box["ctx"].canceled is True
    assert box["ctx"].cause is jobstop.ErrStopped
    assert len(stops) == 0, "a stopped job leaves the registry"
    gate.set()
    await task


async def test_stops_are_isolated_by_job_id(rec):
    stops = jobstop.Registry()
    gate, box = asyncio.Event(), {}
    _, task = start(
        rec, Action(middleware=use(stops.middleware), request_handler=held_handler(box, gate))
    )
    await asyncio.sleep(0.01)
    stops.on_signal(proc("a-job-this-process-never-accepted", "flow_stop_by_user"))
    assert box["ctx"].canceled is False
    assert len(stops) == 1
    gate.set()
    await task


async def test_an_ending_that_is_not_a_cancellation_unfiles_without_cancelling(rec, capsys):
    stops = jobstop.Registry()
    gate, box = asyncio.Event(), {}
    msg, task = start(
        rec, Action(middleware=use(stops.middleware), request_handler=held_handler(box, gate))
    )
    await asyncio.sleep(0.01)
    capsys.readouterr()
    stops.on_signal(proc(job_id_of(msg), "done"))
    assert box["ctx"].canceled is False, "a finishing job must not be cut short"
    assert len(stops) == 0
    assert capsys.readouterr().out == "", "and nothing is logged"
    gate.set()
    await task


async def test_signals_the_sdk_does_not_model_are_ignored():
    stops = jobstop.Registry()
    stops.on_signal(Signal(kind="future", subject="s", job_id="x"))
    stops.on_signal(proc("", "flow_stop_by_user"))
    assert len(stops) == 0


async def test_a_job_leaves_the_registry_when_its_context_ends_on_its_own(rec):
    stops = jobstop.Registry()
    _, task = start(rec, Action(middleware=use(stops.middleware)))
    await task
    await asyncio.sleep(0)
    assert len(stops) == 0


async def test_cancel_all_cancels_every_job_it_holds(rec):
    stops = jobstop.Registry()
    gate = asyncio.Event()
    contexts = []

    async def handler(job):
        contexts.append(job.context())
        await gate.wait()

    tasks = [
        start(rec, Action(middleware=use(stops.middleware), request_handler=handler))[1]
        for _ in range(3)
    ]
    await asyncio.sleep(0.01)
    assert len(stops) == 3
    stops.cancel_all()
    assert len(stops) == 0
    assert [c.cause for c in contexts] == [jobstop.ErrShutdown] * 3
    gate.set()
    await asyncio.gather(*tasks)


# ---- the registry in the pipeline -----------------------------------------


async def test_the_job_is_filed_before_the_runtime_is_told_its_job_id(rec):
    stops = jobstop.Registry()
    seen = {}

    def spy(ctx, job):
        # Anything after stops.middleware still runs before the accept reply, so
        # this is the window a stop could arrive in — and the job is filed.
        seen["filed"] = len(stops) == 1 and job.job_id != ""
        return ctx

    _, task = start(rec, Action(middleware=use(stops.middleware, spy)))
    await task
    assert seen["filed"] is True


async def test_jobstop_is_per_action(rec):
    stops = jobstop.Registry()
    gate, box = asyncio.Event(), {}
    msg, task = start(rec, Action(method="detached", request_handler=held_handler(box, gate)))
    await asyncio.sleep(0.01)
    stops.on_signal(proc(job_id_of(msg), "flow_stop_by_user"))
    assert box["ctx"].canceled is False, "the job keeps running, by design"
    gate.set()
    await task


async def test_a_stopped_handler_reports_nothing(rec):
    stops = jobstop.Registry()

    async def handler(job):
        ctx = job.context()
        while await ctx.sleep(10):
            await job.progress(10, None)
        if ctx.canceled:
            return  # the runtime is gone: do not report
        await job.done({"ok": True})

    msg, task = start(rec, Action(middleware=use(stops.middleware), request_handler=handler))
    await asyncio.sleep(0.01)
    stops.on_signal(proc(job_id_of(msg), "timeout"))
    await task
    assert rec.sent == [], "no progress, no done — the subject has no responder"


async def test_the_stop_is_logged_once_with_its_conclusion(rec, capsys):
    stops = jobstop.Registry()
    gate, box = asyncio.Event(), {}
    msg, task = start(
        rec, Action(middleware=use(stops.middleware), request_handler=held_handler(box, gate))
    )
    await asyncio.sleep(0.01)
    jid = job_id_of(msg)
    capsys.readouterr()
    stops.on_signal(proc(jid, "stop_command"))
    out = capsys.readouterr().out.strip()
    assert out == (
        f"jobstop: job {jid} cancelled: the runtime concluded its process stop_command"
    )
    gate.set()
    await task


async def test_jobstop_composes_with_other_handlers_on_the_one_port(rec):
    stops = jobstop.Registry()
    gate, box = asyncio.Event(), {}
    audited = []
    port = chain_signals(
        stops.on_signal,
        lambda sig: audited.append(sig.job_id) if canceled(sig.conclusion) else None,
    )
    msg, task = start(
        rec, Action(middleware=use(stops.middleware), request_handler=held_handler(box, gate))
    )
    await asyncio.sleep(0.01)
    jid = job_id_of(msg)
    await port(proc(jid, "flow_stop_by_user"))
    assert box["ctx"].cause is jobstop.ErrStopped
    assert audited == [jid]
    gate.set()
    await task


async def test_ctx_run_abandons_the_work_when_the_flow_is_stopped(rec):
    """The Python answer to "pass ctx down": the awaited task is cancelled."""
    stops = jobstop.Registry()
    inner_cancelled = []

    async def slow():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            inner_cancelled.append(True)
            raise

    async def handler(job):
        try:
            await job.context().run(slow())
        except jobstop.JobStopped:
            return  # the runtime is gone: do not report

    msg, task = start(rec, Action(middleware=use(stops.middleware), request_handler=handler))
    await asyncio.sleep(0.01)
    stops.on_signal(proc(job_id_of(msg), "flow_stop_by_user"))
    await task
    assert inner_cancelled == [True]
    assert rec.sent == []


# ---- one id across two systems (external-job-identity) --------------------


class FakeJoern:
    """A stand-in for a service that names work itself and can be told to drop it."""

    def __init__(self):
        self._next = 1
        self.live: set[str] = set()
        self.aborted: list[str] = []
        self.register_fails = False
        self.id_prefix = "q-8f21c47b3d"

    def register(self) -> str:
        if self.register_fails:
            raise RuntimeError("joern refused the query")
        qid = f"{self.id_prefix}-{self._next}"
        self._next += 1
        self.live.add(qid)
        return qid

    def has(self, qid: str) -> bool:
        return qid in self.live

    def cancel(self, qid: str) -> None:
        self.aborted.append(qid)
        self.live.discard(qid)


def namer(joern: FakeJoern):
    def register_query(ctx, job):
        body = cast_request_to(job.req.data) if job.req.data else None
        prev = (body.registry or {}).get("jobId") if body else None
        if prev and joern.has(prev):
            return with_job_id_context(ctx, prev)  # reattach, don't duplicate
        qid = joern.register()
        if len(qid) < 10:
            joern.cancel(qid)  # never accepted: undo it
            raise ValueError(f"jobId {qid} from joern is shorter than 10 characters")
        return with_job_id_context(ctx, qid)

    return register_query


async def test_the_services_id_becomes_the_job_id(rec):
    joern = FakeJoern()
    stops = jobstop.Registry()

    async def handler(job):
        await job.done({"queryId": job.job_id}, "joern")

    msg, task = start(
        rec,
        Action(middleware=use(namer(joern), stops.middleware), request_handler=handler),
        {"body": {"project": "acme/api"}},
    )
    await task
    jid = job_id_of(msg)
    assert jid == "q-8f21c47b3d-1"
    assert rec.job_ids_seen() == [jid], "the command subject carries the service's id"


async def test_a_stop_reaches_the_service_with_no_local_lookup_table(rec):
    joern = FakeJoern()
    stops = jobstop.Registry()
    gate, box = asyncio.Event(), {}

    def abort_upstream(sig):  # stateless: the signal already names the query
        if sig.kind == "proc" and canceled(sig.conclusion):
            joern.cancel(sig.job_id)

    port = chain_signals(stops.on_signal, abort_upstream)
    msg, task = start(
        rec,
        Action(
            middleware=use(namer(joern), stops.middleware),
            request_handler=held_handler(box, gate),
        ),
        {"body": {}},
    )
    await asyncio.sleep(0.01)
    jid = job_id_of(msg)
    await port(proc(jid, "flow_stop_by_user"))
    assert joern.aborted == [jid]
    gate.set()
    await task


async def test_filing_before_the_namer_misses_the_stop(rec):
    """The ordering rule, as a test: stops.middleware files job.job_id as of when
    it runs, so placed before the namer it files a uuid nothing will look up."""
    joern = FakeJoern()
    stops = jobstop.Registry()
    gate, box = asyncio.Event(), {}
    msg, task = start(
        rec,
        Action(
            middleware=use(stops.middleware, namer(joern)),  # WRONG ON PURPOSE
            request_handler=held_handler(box, gate),
        ),
        {"body": {}},
    )
    await asyncio.sleep(0.01)
    stops.on_signal(proc(job_id_of(msg), "flow_stop_by_user"))
    assert box["ctx"].canceled is False, "the stop was lost: the namer comes first"
    gate.set()
    await task


async def test_a_registration_failure_rejects_the_request(rec):
    joern = FakeJoern()
    joern.register_fails = True
    ran = []
    msg, task = start(
        rec,
        Action(middleware=use(namer(joern)), request_handler=lambda job: ran.append(1)),
        {"body": {}},
    )
    await task
    assert json.loads(msg.responses[0]) == {"error": "joern refused the query"}
    assert ran == []
    assert rec.sent == []


async def test_an_id_too_short_for_the_runtime_is_refused_and_compensated(rec):
    joern = FakeJoern()
    joern.id_prefix = "q7"  # "q7-1" — under fractal-core's 10-character floor
    msg, task = start(rec, Action(middleware=use(namer(joern))), {"body": {}})
    await task
    assert "shorter than 10 characters" in json.loads(msg.responses[0])["error"]
    assert joern.aborted == ["q7-1"], "what was registered was un-registered"
    assert joern.live == set()


async def test_a_rejection_after_registration_runs_the_on_done_compensation(rec):
    joern = FakeJoern()

    def register_then(ctx, job):
        nxt = namer(joern)(ctx, job)
        qid = next(iter(joern.live))
        # The job's context ends on rejection too, so the undo needs no special
        # casing for "a later function said no".
        nxt.on_done(lambda _cause: joern.cancel(qid))
        return nxt

    def refuse(ctx, job):
        raise ValueError("the input failed validation")

    _, task = start(rec, Action(middleware=use(register_then, refuse)), {"body": {}})
    await task
    await asyncio.sleep(0)
    assert len(joern.aborted) == 1
    assert joern.live == set()


# ---- work observed across runs (detached-work) ----------------------------


async def test_the_registry_handle_is_adopted_at_the_accept_stage(rec):
    joern = FakeJoern()
    previous = joern.register()  # what the last run started, still running

    async def handler(job):
        await job.done({"state": "running"}, "joern")

    msg, task = start(
        rec,
        Action(middleware=use(namer(joern)), request_handler=handler),
        {"_registry": {"jobId": previous, "reqAt": 1782773000}, "body": {}},
    )
    await task
    assert job_id_of(msg) == previous, "it observes; it starts nothing"
    assert len(joern.live) == 1


async def test_no_registry_handle_starts_new_work(rec):
    joern = FakeJoern()
    msg, task = start(rec, Action(middleware=use(namer(joern))), {"_registry": {}, "body": {}})
    await task
    assert job_id_of(msg) == "q-8f21c47b3d-1"
    assert len(joern.live) == 1


async def test_a_stale_handle_starts_new_work(rec):
    joern = FakeJoern()
    msg, task = start(
        rec,
        Action(middleware=use(namer(joern))),
        {"_registry": {"jobId": "q-forgotten-by-the-service"}, "body": {}},
    )
    await task
    assert job_id_of(msg) == "q-8f21c47b3d-1"
    assert len(joern.live) == 1


# ---- through the real start() wiring -------------------------------------


async def test_end_to_end_through_start(conn, rec, capsys):
    """The whole path as the runtime drives it: the cpu subscription runs the
    pipeline, the signal subscription cancels the job it names."""
    stops = jobstop.Registry()
    rec.infra_conn = type("Infra", (), {"get_connection": lambda self: conn})()
    rec.on_signal(chain_signals(stops.on_signal))
    box = {}

    async def handler(job):
        box["ctx"] = job.context()
        if not await job.context().sleep(10):
            return  # stopped: wind down without reporting
        await job.done({"ok": True})

    rec.add_action(
        Action(method="act", middleware=use(stops.middleware), request_handler=handler)
    )
    await rec.start()
    assert "inflow.plugin.PID.>" in conn.subs, "the signal port is subscribed"

    msg = MockMsg(data=json.dumps({"_registry": {}, "body": {}}).encode())
    await conn.subs["inflow.cpu.PID.act"](msg)
    for _ in range(10):
        await asyncio.sleep(0)
    jid = job_id_of(msg)
    assert len(stops) == 1

    sig = MockMsg(
        data=json.dumps({"conclusion": "flow_stop_by_user", "jobId": jid}).encode(),
        subject="inflow.plugin.PID.proc",
    )
    await conn.subs["inflow.plugin.PID.>"](sig)
    for _ in range(10):
        await asyncio.sleep(0)

    assert box["ctx"].cause is jobstop.ErrStopped
    assert rec.sent == [], "a stopped job reported nothing"
    assert len(stops) == 0


async def test_an_action_with_no_middleware_still_works_unchanged(conn, rec):
    """Backward compatibility: a plugin written before middleware existed gets a
    uuid jobId, a usable context, and the same handshake."""
    rec.infra_conn = type("Infra", (), {"get_connection": lambda self: conn})()
    seen = {}

    async def handler(job):
        seen["job_id"] = job.job_id
        seen["canceled"] = job.context().canceled
        await job.done({"ok": True})

    rec.add_action(Action(method="plain", request_handler=handler))
    await rec.start()
    msg = MockMsg(data=json.dumps({"_registry": {}, "body": {}}).encode())
    await conn.subs["inflow.cpu.PID.plain"](msg)
    for _ in range(10):
        await asyncio.sleep(0)
    assert len(seen["job_id"]) == 36
    assert seen["canceled"] is False
    assert job_id_of(msg) == seen["job_id"]
    assert rec.sent[0][0] == f"inflow.cpu.PID.{seen['job_id']}.progress"


async def test_no_on_signal_logs_the_port_note(conn, rec, capsys):
    rec.infra_conn = type("Infra", (), {"get_connection": lambda self: conn})()
    stops = jobstop.Registry()
    rec.add_action(
        Action(method="act", middleware=use(stops.middleware), request_handler=lambda j: None)
    )
    await rec.start()
    out = capsys.readouterr().out
    assert "Signals not subscribed on : inflow.plugin.PID.>" in out
    assert "actions with middleware: act" in out
    assert "inflow.plugin.PID.>" not in conn.subs
