# Protocol data types. Mirrors sdkv1/models.go + req.go.
#
# JSON field names are chosen to match the Go wire format exactly, so a Python
# plugin is interchangeable with a Go plugin from the runtime's point of view.
# `marshal` below is the Python counterpart of Go's sonic.Marshal: it walks the
# dataclasses honoring the per-field json name and `omitempty`, and produces the
# same compact JSON Go emits.
from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Awaitable, Callable, Optional, Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:
    from nats.aio.msg import Msg
    from .job import Job


# ---- wire metadata helpers -------------------------------------------------


def _wire(json_name: Optional[str] = None, omitempty: bool = False, skip: bool = False):
    """Field metadata: the json key, whether to drop empties, or skip entirely
    (the func fields Go marks `json:"-"`)."""
    return {"json": json_name, "omitempty": omitempty, "skip": skip}


def _is_empty(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def to_wire(obj: Any) -> Any:
    """Turn dataclasses / dicts / lists into JSON-ready primitives, applying the
    Go json tags (name + omitempty). Skipped (handler) fields are dropped."""
    if is_dataclass(obj) and not isinstance(obj, type):
        out: dict[str, Any] = {}
        for f in fields(obj):
            meta = f.metadata
            if meta.get("skip"):
                continue
            value = getattr(obj, f.name)
            if meta.get("omitempty") and _is_empty(value):
                continue
            out[meta.get("json") or f.name] = to_wire(value)
        return out
    if isinstance(obj, dict):
        return {k: to_wire(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_wire(v) for v in obj]
    return obj


def marshal(obj: Any) -> bytes:
    """Compact JSON bytes, the Python counterpart of sonic.Marshal (raw UTF-8)."""
    return json.dumps(to_wire(obj), separators=(",", ":"), ensure_ascii=False).encode()


# ---- interfaces ------------------------------------------------------------


@runtime_checkable
class IPlugin(Protocol):
    """Anything the runtime can talk to over NATS. Mirrors Go's IPlugin."""

    async def send(self, subject: str, data: bytes) -> "tuple[Optional[Msg], Optional[Exception]]": ...

    def get_plugin_id(self) -> str: ...


# A handler for one action execution. Mirrors Go's JobHandler.
JobHandler = Callable[["Job"], Awaitable[None] | None]


# ---- descriptors -----------------------------------------------------------


@dataclass
class Icon:
    """Icon for an action."""

    ref: str = field(default="", metadata=_wire("ref"))
    icon: str = field(default="", metadata=_wire("icon"))


@dataclass
class FormBuilder:
    """Action form configuration — JSON Schema (data model) + UI Schema (layout),
    rendered by JSON Forms. Reply to inflow.v1.<PLUGIN_ID>.<ACTION>.@form."""

    submit_to: str = field(default="", metadata=_wire("submit_to"))
    jsonui: str = field(default="", metadata=_wire("jsonui"))
    jsonschema: str = field(default="", metadata=_wire("jsonschema"))


@dataclass
class PluginIntro:
    """Plugin identity — reply to inflow.v1.<PLUGIN_ID>.@intro."""

    name: str = field(default="", metadata=_wire("name"))
    author: str = field(default="", metadata=_wire("author"))
    version: str = field(default="", metadata=_wire("version"))
    # Optional onboarding/settings form shown before any action.
    settings: Optional[FormBuilder] = field(default=None, metadata=_wire("settings", omitempty=True))
    # Optional Markdown manual the host renders on the plugin's page. A fenced
    # ```inflow-meta block (its body a meta method name) becomes a Run button.
    manual: str = field(default="", metadata=_wire("manual", omitempty=True))


@dataclass
class OutboundPort:
    """One statically declared outbound branch of an action. The design-time
    counterpart of runtime tag routing (Job.cmd_next_filter / `next_tags`)."""

    title: str = field(default="", metadata=_wire("title"))
    tags: list[str] = field(default_factory=list, metadata=_wire("tags"))
    description: str = field(default="", metadata=_wire("description", omitempty=True))


@dataclass
class Action:
    """A single action the node can perform."""

    method: str = field(default="", metadata=_wire("method"))
    description: str = field(default="", metadata=_wire("description"))
    title: str = field(default="", metadata=_wire("title"))
    icon: Icon = field(default_factory=Icon, metadata=_wire("icon"))
    form: FormBuilder = field(default_factory=FormBuilder, metadata=_wire("form"))
    # Statically declared outbound branches; leave empty for the single-output action.
    outbound: list[OutboundPort] = field(default_factory=list, metadata=_wire("outbound", omitempty=True))
    # Open bag of labels for grouping/classifying an action ("class" is reserved).
    tags: dict[str, str] = field(default_factory=dict, metadata=_wire("tags", omitempty=True))
    # Not serialized to the wire (Go marks it `json:"-"`).
    request_handler: Optional[JobHandler] = field(default=None, metadata=_wire(skip=True))


@dataclass
class Settings(FormBuilder):
    """Plugin-level settings: a form plus a submit handler. Mirrors Go's Settings,
    which embeds FormBuilder — so it marshals to the same three fields."""

    # Excluded from JSON like every other handler (a func field makes marshal fail).
    submit_handler: Optional[Callable[["Request"], Any]] = field(default=None, metadata=_wire(skip=True))


@dataclass
class Meta:
    """A synchronous request/reply "meta function" (no job, no context access).

    The handler returns any JSON-able value — the SDK marshals it verbatim — so a
    meta method can answer with a bare array, a formkit patch/envelope, or the
    {data, error} Response envelope, whichever the caller expects. Mirrors Go's
    `RequestHandler func(Request) any`."""

    method: str = field(default="", metadata=_wire("method"))
    request_handler: Optional[Callable[["Request"], Any]] = field(default=None, metadata=_wire(skip=True))


@dataclass
class Frame:
    """A titled progress frame shown on the canvas."""

    title: str = field(default="", metadata=_wire("title"))
    content: str = field(default="", metadata=_wire("content"))
    # Reserved, open bag for frontend extras; leave empty when unused.
    meta: dict[str, Any] = field(default_factory=dict, metadata=_wire("meta", omitempty=True))


@dataclass
class CommandPayload:
    """Payload of a `progress` command. Mirrors Go's CommandPayload."""

    progress: int = field(default=0, metadata=_wire("progress"))
    frame: Frame = field(default_factory=Frame, metadata=_wire("frame"))
    details: Optional[dict[str, Any]] = field(default=None, metadata=_wire("details"))
    commit_on: str = field(default="", metadata=_wire("commit_on"))


@dataclass
class JobBodyContent:
    """Payload of a `commit` command / the init response. Mirrors Go's JobBodyContent."""

    job_id: str = field(default="", metadata=_wire("jobId"))
    progress: int = field(default=0, metadata=_wire("progress"))
    details: Optional[dict[str, Any]] = field(default=None, metadata=_wire("details"))
    commit_on: str = field(default="", metadata=_wire("commit_on"))


@dataclass
class Response:
    """Reply shape for meta functions & settings submit."""

    data: Optional[dict[str, Any]] = field(default=None, metadata=_wire("data"))
    error: Any = field(default=None, metadata=_wire("error"))


@dataclass
class Request:
    """The raw request delivered to a handler. Not serialized to the wire."""

    data: bytes
    header: Optional[dict[str, Any]] = None
    plugin: Optional[IPlugin] = None


@dataclass
class RequestBody:
    """The `{ _registry, body }` envelope an execution request arrives in.
    `body` is the user's form input; `registry` is runtime metadata (notably this
    node's previous run). See cast_request_to. Mirrors Go's generic RequestBody[T]."""

    registry: Optional[dict[str, Any]] = field(default=None, metadata=_wire("_registry"))
    body: Any = field(default=None, metadata=_wire("body"))


@dataclass
class ActionRequestContent:
    """The untyped form of RequestBody. Mirrors Go's ActionRequestContent."""

    registry: dict[str, Any] = field(default_factory=dict, metadata=_wire("_registry"))
    body: dict[str, Any] = field(default_factory=dict, metadata=_wire("body"))


@dataclass
class CallSvcBody:
    """Body of a plugin-originated service call (Job.cmd_svc_call). `data` is the
    payload; `op` carries operation metadata. Mirrors Go's CallSvcBody."""

    data: Any = field(default=None, metadata=_wire("data"))
    op: Optional[dict[str, Any]] = field(default=None, metadata=_wire("op"))
