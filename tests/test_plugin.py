"""Subject wiring, reply payloads, the job handshake, and the no-throw send."""
import asyncio
import json

import pytest

from inflow_plugin_sdk import (
    Action,
    Conclusion,
    Frame,
    Job,
    Meta,
    PluginIntro,
    PluginSignal,
    Request,
    Response,
    Settings,
    canceled,
    succeeded,
)

from conftest import MockMsg


async def _drain() -> None:
    """Let detached handler tasks (job handlers, signal handlers) run to completion."""
    for _ in range(5):
        await asyncio.sleep(0)


async def test_start_wires_all_subjects(plugin, conn):
    plugin.intro(PluginIntro(name="T", author="a", version="v1"))
    plugin.add_action(Action(method="act", request_handler=lambda job: None))
    plugin.add_meta(Meta(method="list", request_handler=lambda req: {"tools": []}))
    plugin.required_params(Settings(submit_handler=lambda req: Response(data={})))

    await plugin.start()

    assert set(conn.subs) == {
        "inflow.v1.PID.@intro",
        "inflow.v1.PID.@settings",
        "inflow.v1.PID.@actions",
        "inflow.v1.PID.act.@form",
        "inflow.cpu.PID.act",
        "inflow.v1.PID.list",
        "inflow.v1.PID._settings.config.submit",  # default submit subject
    }


async def test_intro_and_settings_replies(plugin, conn):
    plugin.intro(PluginIntro(name="T", author="a", version="v1"))
    await plugin.start()

    m = MockMsg()
    await conn.subs["inflow.v1.PID.@intro"](m)
    assert json.loads(m.responses[0]) == {"name": "T", "author": "a", "version": "v1"}

    # no settings registered -> empty object, not an empty body
    m = MockMsg()
    await conn.subs["inflow.v1.PID.@settings"](m)
    assert m.responses[0] == b"{}"


async def test_meta_reply_is_verbatim(plugin, conn):
    plugin.add_meta(Meta(method="list", request_handler=lambda req: [1, 2, 3]))
    await plugin.start()
    m = MockMsg()
    await conn.subs["inflow.v1.PID.list"](m)
    assert json.loads(m.responses[0]) == [1, 2, 3]


async def test_action_handshake_and_job_commands(plugin, conn):
    seen = {}

    async def handler(job: Job):
        seen["job_id"] = job.job_id
        await job.progress(10, Frame(title="s", content="c"))
        seen["done"] = await job.done({"ok": 1}, "path", "sub")

    plugin.add_action(Action(method="act", request_handler=handler))
    await plugin.start()

    m = MockMsg(data=json.dumps({"_registry": {}, "body": {}}).encode())
    await conn.subs["inflow.cpu.PID.act"](m)
    # The handler runs in a detached task so it cannot head-of-line-block the
    # subscription (see with_job_handler); yield until it has finished.
    await _drain()

    # the request is acked with the minted jobId
    ack = json.loads(m.responses[0])
    assert ack["jobId"] == seen["job_id"]

    # job.done committed on "path.sub"
    progress_sub, progress_body = conn.requests[0]
    done_sub, done_body = conn.requests[1]
    assert progress_sub == f"inflow.cpu.PID.{seen['job_id']}.progress"
    assert json.loads(done_body)["commit_on"] == "path.sub"
    assert seen["done"] == conn.reply


async def test_send_never_raises_and_returns_error(plugin, conn, monkeypatch):
    # A stopped workflow leaves no responders; Go returns (nil, err) — never panics.
    # Stub the retry backoff so the test doesn't wait the real 1+2+3+4+5s.
    import inflow_plugin_sdk.plugin as plugin_mod

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(plugin_mod.asyncio, "sleep", no_sleep)
    conn.raise_no_responders = True
    msg, err = await plugin.send("x", b"body")
    assert msg is None
    assert isinstance(err, Exception)
    assert str(err) == "exception occurred"


async def test_send_success_returns_msg(plugin, conn):
    msg, err = await plugin.send("x", b"body")
    assert err is None
    assert msg.data == conn.reply


async def test_cmd_svc_call_rejects_blank_action(plugin):
    job = Job(plugin, "act", "jid", Request(data=b""))
    result = await job.cmd_svc_call("  ", {"a": 1})
    assert isinstance(result, ValueError)


async def test_raising_action_handler_reports_done_with_error(plugin, conn):
    async def boom(job: Job):
        raise RuntimeError("handler exploded")

    plugin.add_action(Action(method="act", request_handler=boom))
    await plugin.start()

    m = MockMsg(data=b"{}")
    # Must not raise out of the dispatch callback — the plugin keeps running.
    await conn.subs["inflow.cpu.PID.act"](m)
    await _drain()  # the handler runs detached; let it report the failure

    # The request was still acked with a jobId...
    ack = json.loads(m.responses[0])
    assert "jobId" in ack

    # ...and the failure was reported to the runtime as a terminal DoneWithError
    # (progress 100, reason on the command's own "error" field), not swallowed.
    assert len(conn.requests) == 1
    sub, body = conn.requests[0]
    assert sub == f"inflow.cpu.PID.{ack['jobId']}.progress"
    payload = json.loads(body)
    assert payload["progress"] == 100
    assert payload["error"] == {"code": 0, "message": "handler exploded"}
    # The reason is no longer a detail: the panic commits nothing.
    assert payload["details"] is None


async def test_cmd_svc_call_unserializable_data_returns_error_not_raise(plugin):
    job = Job(plugin, "act", "jid", Request(data=b""))
    result = await job.cmd_svc_call("svc", data=object())  # object() is not JSON-able
    assert isinstance(result, Exception)


# ---- the signal port -------------------------------------------------------
#
# A signal is a publish, not a request: nothing on the wire tells the plugin it
# mis-read one. So what is checked here is that the port stays opt-in, that the kind
# is the subject past the plugin's own prefix, that the runtime's {conclusion, jobId}
# body lands in the typed fields — and the case that has no answer yet: a future kind
# with a payload this SDK does not model still reaches the handler, bytes intact.


async def test_signal_port_is_opt_in(plugin, conn):
    plugin.add_action(Action(method="act", request_handler=lambda job: None))
    await plugin.start()
    assert "inflow.plugin.PID.>" not in conn.subs


async def test_on_signal_subscribes_and_parses_proc(plugin, conn):
    seen = []
    plugin.on_signal(lambda sig: seen.append(sig))
    await plugin.start()

    assert "inflow.plugin.PID.>" in conn.subs

    await conn.subs["inflow.plugin.PID.>"](
        MockMsg(
            subject="inflow.plugin.PID.proc",
            data=b'{"conclusion":"flow_stop_by_user","jobId":"job-1"}',
        )
    )
    await _drain()

    assert len(seen) == 1
    sig = seen[0]
    assert sig.kind == PluginSignal.PROC
    assert sig.job_id == "job-1"
    assert sig.conclusion == Conclusion.FLOW_STOP_BY_USER
    assert canceled(sig.conclusion) and not succeeded(sig.conclusion)
    # a signal is a publish — the SDK must not reply to it
    assert sig.msg.responses == []


async def test_signal_of_unmodelled_kind_keeps_its_payload(plugin, conn):
    seen = []
    plugin.on_signal(lambda sig: seen.append(sig))
    await plugin.start()

    await conn.subs["inflow.plugin.PID.>"](
        MockMsg(subject="inflow.plugin.PID.future.kind", data=b"not json")
    )
    await _drain()

    sig = seen[0]
    assert sig.kind == "future.kind"  # the whole subject remainder
    assert sig.data == b"not json"
    assert sig.job_id == "" and sig.conclusion == ""


async def test_failing_signal_handler_does_not_break_the_port(plugin, conn):
    def boom(sig):
        raise RuntimeError("signal handler exploded")

    plugin.on_signal(boom)
    await plugin.start()

    # Must not raise out of the dispatch callback — the plugin keeps serving.
    await conn.subs["inflow.plugin.PID.>"](
        MockMsg(subject="inflow.plugin.PID.proc", data=b'{"conclusion":"done"}')
    )
    await _drain()
