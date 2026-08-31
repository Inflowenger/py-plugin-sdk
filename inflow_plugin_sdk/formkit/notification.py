# Messages, options, and the reserved UI keys. Mirrors formkit/lookup.go.
from __future__ import annotations

from dataclasses import dataclass, field as dfield
from typing import Any, Optional

# uiKey is the UI Schema extension that hangs a button off a control. A renderer
# that does not know it ignores it and draws a plain field — the correct
# fallback, so every field a button fills stays typable.
uiKey = "x-inflow-ui"

# NotifKey is the reserved key a message travels under, both on a form control
# and in a meta function's answer. The host lifts it out of an answer, so it is
# not form data: no schema declares it and no action receives it.
NotifKey = "x-inflow-notif"


@dataclass
class Notification:
    """One thing to say about a field. The host decides where it appears — inline
    under the control, a toast, a dialog. `field` is optional: a message answering
    a button defaults to the field that button targets. Only the properties that
    are set are serialized (Go's omitempty)."""

    severity: str = dfield(default="", metadata={"json": "severity", "omitempty": True})
    message: str = dfield(default="", metadata={"json": "message", "omitempty": True})
    field: str = dfield(default="", metadata={"json": "field", "omitempty": True})
    display: str = dfield(default="", metadata={"json": "display", "omitempty": True})

    def about(self, field: str) -> "Notification":
        """Point the message at a named field instead of the one the button targets."""
        return Notification(severity=self.severity, message=self.message, field=field, display=self.display)

    def patch(self, values: Optional[dict[str, Any]]) -> dict[str, Any]:
        """The answer a button handler returns when it resolved a value: the fields
        to write into the open form, plus this message. Keys are absolute leaf
        paths — patching a nested object replaces it wholesale. A message on its
        own is a valid answer."""
        out: dict[str, Any] = dict(values or {})
        out[NotifKey] = self
        return out


def _say(severity: str, fmt: str, *args: Any) -> Notification:
    return Notification(severity=severity, message=(fmt % args if args else fmt))


def info(fmt: str, *args: Any) -> Notification:
    """Guidance: what to fill in first, what the button will do next."""
    return _say("info", fmt, *args)


def success(fmt: str, *args: Any) -> Notification:
    """Confirms what a lookup found, next to the value it just wrote."""
    return _say("success", fmt, *args)


def warning(fmt: str, *args: Any) -> Notification:
    """A search that ran and found nothing."""
    return _say("warning", fmt, *args)


def failure(fmt: str, *args: Any) -> Notification:
    """The remote service or the connection saying no."""
    return _say("error", fmt, *args)


def help(fmt: str, *args: Any) -> Notification:
    """A standing hint the field carries from the moment it renders."""
    return _say("help", fmt, *args)


@dataclass
class Option:
    """One candidate a lookup matched, or one entry of a Choice: the value the API
    needs, and the label a human recognises."""

    value: str = ""
    label: str = ""


def one_of(options: list[Option]) -> list[Any]:
    choices: list[Any] = []
    for option in options:
        label = option.label or option.value
        choices.append({"const": option.value, "title": label})
    return choices


def or_default(value: str, fallback: str) -> str:
    return value if value != "" else fallback
