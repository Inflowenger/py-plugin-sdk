# Picker: answer an ambiguous lookup with a form the user can choose from, or
# fall back to a text list. Mirrors formkit/picker.go.
from __future__ import annotations

import json
from typing import Any, Optional

from ..models import FormBuilder
from .notification import NotifKey, Notification, Option, one_of, or_default

# hostKeys are the keys the host and the button add to a meta call on top of the
# form's own fields. They are not form data and must not be echoed back into it —
# `settings` above all, which carries the target system's credentials.
_HOST_KEYS = {"settings": True, "value": True, "targetField": True, "form": True}


def form_data(call: dict[str, Any]) -> dict[str, Any]:
    """Echo a meta call's form back unchanged, minus what the host and the button
    added. A form envelope replaces the form's data wholesale, so the echo has to
    be exact."""
    return {k: v for k, v in call.items() if k not in _HOST_KEYS}


def choices(schema_json: str, target: str, options: list[Option]) -> dict[str, Any]:
    """Rewrite one property of a JSON Schema into a drop-down of the given
    candidates, returning the whole schema with that one change. `oneOf` rather
    than `enum` because each candidate needs a value and a label; any `enum` on the
    property is dropped. Raises ValueError when the property is absent."""
    try:
        schema = json.loads(schema_json)
    except Exception as e:
        raise ValueError(f"formkit: form schema does not parse: {e}")

    properties = schema.get("properties") if isinstance(schema, dict) else None
    property_ = properties.get(target) if isinstance(properties, dict) else None
    if not isinstance(property_, dict):
        raise ValueError(f"formkit: the form has no property {target!r} to turn into a drop-down")

    property_["oneOf"] = one_of(options)
    property_.pop("enum", None)
    return schema


def picker(
    form: FormBuilder,
    target: str,
    options: list[Option],
    data: dict[str, Any],
    heading: Notification,
) -> dict[str, Any]:
    """Answer an ambiguous lookup with a form the user can choose from — a *form
    envelope* the host re-renders the open dialog as, with the target field turned
    into a drop-down of exactly what the lookup found. Raises when the form has no
    schema or the target is not one of its properties. The returned map carries
    envelope keys only (the heading rides under NotifKey)."""
    if form.jsonschema == "":
        raise ValueError("formkit: cannot rebuild a form that has no schema")

    schema = choices(form.jsonschema, target, options)

    envelope: dict[str, Any] = {
        "schema": schema,
        "uischema": form.jsonui,
        "data": data,
    }
    if heading.message != "":
        envelope[NotifKey] = heading
    return envelope


def choose(
    form: FormBuilder,
    target: str,
    options: list[Option],
    data: dict[str, Any],
    heading: Notification,
) -> Any:
    """picker with the fallback every caller wants: when the form cannot be rebuilt
    (the action was named wrong, the target is not one of its properties) the
    candidates are reported as text instead."""
    try:
        return picker(form, target, options, data, heading)
    except Exception:
        message = heading.message.rstrip("\n")
        return Notification(
            severity=or_default(heading.severity, "info"),
            field=heading.field,
            message=(message + "\n" + lines(options)).strip(),
        ).patch(None)


# listed caps how many candidates a text fallback prints.
_LISTED = 15


def lines(options: list[Option]) -> str:
    """Render candidates one per line — the text form of a picker."""
    out: list[str] = []
    for option in options[: min(len(options), _LISTED)]:
        label = option.label or option.value
        out.append("  " + label)
    if len(options) > _LISTED:
        out.append(f"  … and {len(options) - _LISTED} more — narrow the search")
    return "\n".join(out)
