# Field is one property of a form: its JSON Schema entry, and the UI Schema
# control that renders it. Both are generated from this one declaration, so a
# control can never point at a property that is not there. Mirrors formkit/field.go
# (schema/UI) and formkit/lookup.go (buttons/messages).
from __future__ import annotations

from typing import Any, Optional

from .notification import NotifKey, Notification, help as _help, uiKey


class Field:
    def __init__(self, name: str, schema: dict[str, Any]):
        self.name: str = name
        self.schema: dict[str, Any] = schema
        self.options: Optional[dict[str, Any]] = None
        self.inflow_ui: Optional[dict[str, Any]] = None
        self.notifs: list[Notification] = []
        self.rule: Optional[dict[str, Any]] = None
        self.required_flag: bool = False


# ------------------------------------------------------------ constructors --


def _field(name: str, title: str, json_type: str) -> Field:
    schema: dict[str, Any] = {"type": json_type}
    if title != "":
        schema["title"] = title
    return Field(name, schema)


def text(name: str, title: str) -> Field:
    """A single-line string."""
    return _field(name, title, "string")


def text_area(name: str, title: str) -> Field:
    """A string rendered as a multi-line box."""
    return text(name, title).option("multi", True)


def secret(name: str, title: str) -> Field:
    """A string rendered with its characters masked. Masking is presentation only;
    the value travels and is stored like any other field, so it belongs on a
    settings profile, not on an action form."""
    return text(name, title).option("format", "password")


def integer(name: str, title: str) -> Field:
    """A whole number."""
    return _field(name, title, "integer")


def number(name: str, title: str) -> Field:
    """A decimal number."""
    return _field(name, title, "number")


def boolean(name: str, title: str) -> Field:
    """A checkbox."""
    return _field(name, title, "boolean")


def date(name: str, title: str) -> Field:
    """A string holding a calendar date, YYYY-MM-DD."""
    return text(name, title).format("date")


def date_time(name: str, title: str) -> Field:
    """A string holding an RFC 3339 instant."""
    return text(name, title).format("date-time")


def enum_(name: str, title: str, *values: str) -> Field:
    """A fixed set of values, rendered as a drop-down. Use it when the value the
    API wants is the one a human should read; when they differ, use choice."""
    return text(name, title).set("enum", list(values))


def choice(name: str, title: str, *options) -> Field:
    """A drop-down whose entries have two halves: the value the API needs, and the
    label a human recognises. `oneOf` rather than `enum` because an enum can only
    carry one of the two."""
    from .notification import one_of

    return text(name, title).set("oneOf", one_of(list(options)))


def list_(name: str, title: str) -> Field:
    """An array of strings — the renderer draws add/remove rows."""
    return list_of(name, title, "string")


def list_of(name: str, title: str, item_type: str) -> Field:
    """An array whose items are of the given JSON type."""
    return _field(name, title, "array").set("items", {"type": item_type})


def custom(name: str, title: str, schema: Optional[dict[str, Any]]) -> Field:
    """A field whose schema this package does not model: the JSON Schema fragment
    is used as-is, while the control, layout, lookup button and messages are still
    generated. The fragment is taken over, not copied."""
    if schema is None:
        schema = {}
    if title != "":
        schema["title"] = title
    return Field(name, schema)


# -------------------------------------------------------------- the schema --


def _describe(self: Field, text_: str) -> Field:
    """Set the property's `description`: a statement of what the field is."""
    return self.set("description", text_)


def _required(self: Field) -> Field:
    """Add the field to the schema's `required` list."""
    self.required_flag = True
    return self


def _default(self: Field, value: Any) -> Field:
    """The value the form starts with, and what the action receives when untouched."""
    return self.set("default", value)


def _format(self: Field, fmt: str) -> Field:
    """Set the JSON Schema `format` — date, date-time, uri, email …"""
    return self.set("format", fmt)


def _min(self: Field, value: Any) -> Field:
    """The smallest accepted number."""
    return self.set("minimum", value)


def _max(self: Field, value: Any) -> Field:
    """The largest accepted number."""
    return self.set("maximum", value)


def _between(self: Field, minimum: Any, maximum: Any) -> Field:
    """Bound a number on both sides."""
    return self.min(minimum).max(maximum)


def _set(self: Field, key: str, value: Any) -> Field:
    """Write a JSON Schema keyword verbatim — pattern, minLength, items, …"""
    self.schema[key] = value
    return self


# ------------------------------------------------------------------ the UI --


def _option(self: Field, key: str, value: Any) -> Field:
    """Set a JSON Forms renderer hint under the control's `options`, e.g. "multi"
    for a text area or "slider" for a bounded number."""
    if self.options is None:
        self.options = {}
    self.options[key] = value
    return self


def _when(self: Field, effect: str, other: str, is_: Any) -> Field:
    self.rule = {
        "effect": effect,
        "condition": {"scope": scope_of(other), "schema": {"const": is_}},
    }
    return self


def _show_when(self: Field, other: str, is_: Any) -> Field:
    """Render this field only while another field holds the given value."""
    return self.when("SHOW", other, is_)


def _hide_when(self: Field, other: str, is_: Any) -> Field:
    """The field disappears while the other field holds that value."""
    return self.when("HIDE", other, is_)


def _enable_when(self: Field, other: str, is_: Any) -> Field:
    """Leave the field on screen but grey it out until the other holds the value."""
    return self.when("ENABLE", other, is_)


def scope_of(name: str) -> str:
    """The JSON-pointer-ish reference a UI Schema uses to name a property. A caller
    that already wrote one out in full keeps it."""
    if len(name) > 0 and name[0] == "#":
        return name
    return "#/properties/" + name


def _control(self: Field) -> dict[str, Any]:
    """Render the field's UI Schema element."""
    element: dict[str, Any] = {"type": "Control", "scope": scope_of(self.name)}
    if self.options:
        element["options"] = self.options
    if self.inflow_ui:
        element[uiKey] = self.inflow_ui
    if self.rule is not None:
        element["rule"] = self.rule

    # One message is written as an object rather than a one-element array: both
    # are accepted, and the common case should read as the single thing it is.
    if len(self.notifs) == 1:
        element[NotifKey] = self.notifs[0]
    elif len(self.notifs) > 1:
        element[NotifKey] = self.notifs
    return element


# ----------------------------------------------------------- lookup buttons --


def _lookup(self: Field, fn: str, label: str) -> Field:
    """Hang a button off the field that calls one of the plugin's meta functions
    and patches the answer back into the open form. The host posts the form as it
    stands, plus the settings profile, plus this control's contents as `value`."""
    self.inflow_ui = {
        "action": {
            "name": "pluginFn",
            "fn": fn,
            "body": {"targetField": self.name},
        },
        "button": {"position": "append", "label": label, "icon": "↻"},
    }
    return self


def _into(self: Field, target: str) -> Field:
    """Point the answer at another property, for a button that fills in a field
    other than the one it sits on."""
    self.body()["targetField"] = target
    return self


def _picks(self: Field, method: str) -> Field:
    """Name the action whose form is rebuilt when the lookup finds more than one
    candidate (see picker)."""
    self.body()["form"] = method
    return self


def _send(self: Field, key: str, value: Any) -> Field:
    """Add a static value to the body every press of this button posts."""
    self.body()[key] = value
    return self


def _button(self: Field, position: str, icon: str) -> Field:
    """Override the look of the lookup button: where it sits ("append", "prepend")
    and the icon on it."""
    button = (self.inflow_ui or {}).get("button")
    if button is None:
        return self
    if position != "":
        button["position"] = position
    if icon != "":
        button["icon"] = icon
    return self


def _body(self: Field) -> dict[str, Any]:
    """Reach the static body this field's button posts, creating the button
    scaffolding if lookup has not been called yet so chain order does not matter."""
    if self.inflow_ui is None:
        self.lookup("", "")
    action = self.inflow_ui.get("action", {})
    return action.get("body", {})


# ---------------------------------------------------------------- messages --


def _field_help(self: Field, fmt: str, *args: Any) -> Field:
    """Attach a standing hint to the field — shown from the moment it renders."""
    self.notifs.append(_help(fmt, *args))
    return self


def _inline(self: Field) -> Field:
    """Mark the field as the place messages about it are shown. Every lookup needs
    one somewhere; this is for fields a different control fills in."""
    self.notifs.append(Notification(display="inline"))
    return self


def _says(self: Field, n: Notification) -> Field:
    """Attach a message built by hand, for a severity or target the helpers do not
    cover."""
    self.notifs.append(n)
    return self


# Bind the chaining methods onto Field (kept as free functions above so each
# reads on its own, mirroring the Go method set).
Field.name_of = lambda self: self.name
Field.describe = _describe
Field.required = _required
Field.default = _default
Field.format = _format
Field.min = _min
Field.max = _max
Field.between = _between
Field.set = _set
Field.option = _option
Field.when = _when
Field.show_when = _show_when
Field.hide_when = _hide_when
Field.enable_when = _enable_when
Field.control = _control
Field.lookup = _lookup
Field.into = _into
Field.picks = _picks
Field.send = _send
Field.button = _button
Field.body = _body
Field.help = _field_help
Field.inline = _inline
Field.says = _says
