"""Subject wiring, reply payloads, the job handshake, and the no-throw send."""
import json

import pytest

from inflow_plugin_sdk import (
    Action,
    Frame,
    Job,
    Meta,
    PluginIntro,
    Request,
    Response,
    Settings,
)

from conftest import MockMsg


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
