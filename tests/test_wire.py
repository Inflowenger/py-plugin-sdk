"""The wire format must stay byte-compatible with the Go SDK (sonic.Marshal)."""
import json

from inflow_plugin_sdk import (
    Action,
    CallSvcBody,
    CommandPayload,
    Frame,
    JobBodyContent,
    PluginIntro,
    Response,
    marshal,
)


def test_intro_omits_empty_settings_and_manual():
    assert marshal(PluginIntro(name="T", author="a", version="v1")) == (
        b'{"name":"T","author":"a","version":"v1"}'
    )


def test_action_emits_zero_valued_fields_like_go():
    # Go has no omitempty on description/title/icon/form, so they are always sent.
    out = json.loads(marshal([Action(method="act")]))
    assert out == [
        {
            "method": "act",
            "description": "",
            "title": "",
            "icon": {"ref": "", "icon": ""},
            "form": {"submit_to": "", "jsonui": "", "jsonschema": ""},
        }
    ]


def test_done_payload():
    out = marshal(CommandPayload(progress=100, details={"action": "done"}, commit_on=""))
    assert out == b'{"progress":100,"frame":{"title":"","content":""},"details":{"action":"done"},"commit_on":""}'


def test_progress_details_null_when_unset():
    # Go's Details map is nil for a progress frame -> marshals to null, not {}.
    out = json.loads(marshal(CommandPayload(progress=10, frame=Frame(title="t", content="c"))))
    assert out["details"] is None
    assert out["frame"] == {"title": "t", "content": "c"}


def test_job_body_content_keys():
    out = json.loads(marshal(JobBodyContent(commit_on="$.x", details={"a": 1})))
    assert out == {"jobId": "", "progress": 0, "details": {"a": 1}, "commit_on": "$.x"}


def test_response_and_callsvc():
    assert marshal(Response(data={"ok": 1})) == b'{"data":{"ok":1},"error":null}'
    assert marshal(CallSvcBody(data={"x": 1}, op={"k": "v"})) == b'{"data":{"x":1},"op":{"k":"v"}}'


def test_raw_utf8_not_escaped():
    # sonic emits raw UTF-8; ensure_ascii=False matches it (the ↻ lookup icon).
    assert "↻".encode() in marshal(Frame(title="↻", content=""))
