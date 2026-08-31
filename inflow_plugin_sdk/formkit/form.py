# Form assembly: a single declaration of each field generates both the JSON
# Schema (data) and the JSON Forms UI Schema (layout). Mirrors formkit/form.go.
from __future__ import annotations

import json
from dataclasses import dataclass, field as dfield
from typing import Any, Callable, Optional

from ..models import FormBuilder, Settings, to_wire
from .field import Field


@dataclass
class _Section:
    title: str = ""
    fields: list[Field] = dfield(default_factory=list)


class Form:
    """A form under construction: the fields it holds, in the order they were
    added, and the sections they are laid out in. Start from `form(title)`."""

    def __init__(self, title: str):
        self._title = title
        self._description = ""
        self._submit_to = ""
        self._sections: list[_Section] = []

    def describe(self, text: str) -> "Form":
        """Set the schema's `description` — a line under the heading."""
        self._description = text
        return self

    def submit_to(self, method: str) -> "Form":
        """Name the meta function the host calls to validate the form on submit."""
        self._submit_to = method
        return self

    def add(self, *fields: Field) -> "Form":
        """Append fields to the form, in the order they will be rendered."""
        if self._sections and self._sections[-1].title == "":
            self._sections[-1].fields.extend(fields)
            return self
        self._sections.append(_Section(fields=list(fields)))
        return self

    def group(self, title: str, *fields: Field) -> "Form":
        """Append a labelled section. Its fields are ordinary properties of the same
        flat schema — the grouping is layout only."""
        self._sections.append(_Section(title=title, fields=list(fields)))
        return self

    def fields(self) -> list[Field]:
        """Every field in declaration order, groups flattened."""
        out: list[Field] = []
        for s in self._sections:
            out.extend(s.fields)
        return out

    def validate(self) -> None:
        """Raise ValueError on what would make the generated documents wrong: a
        field with no name, a name used twice, or a schema that will not marshal."""
        seen: dict[str, bool] = {}
        for field_ in self.fields():
            if field_ is None:
                raise ValueError(f"formkit: form {self._title!r} has a nil field")
            if field_.name.strip() == "":
                raise ValueError(f"formkit: form {self._title!r} has a field with no name")
            if seen.get(field_.name):
                raise ValueError(f"formkit: form {self._title!r} declares {field_.name!r} twice")
            seen[field_.name] = True
            try:
                json.dumps(to_wire(field_.schema))
            except Exception as e:
                raise ValueError(f"formkit: field {field_.name!r} has a schema that will not marshal: {e}")

    def schema(self) -> str:
        """The JSON Schema document as text."""
        return _must_encode(self.schema_map())

    def ui(self) -> str:
        """The JSON Forms UI Schema document as text."""
        return _must_encode(self.ui_map())

    def schema_map(self) -> dict[str, Any]:
        """The JSON Schema as a dict, for callers that go on to edit it."""
        properties: dict[str, Any] = {}
        required: list[Any] = []
        for field_ in self.fields():
            properties[field_.name] = field_.schema
            if field_.required_flag:
                required.append(field_.name)
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if self._title != "":
            schema["title"] = self._title
        if self._description != "":
            schema["description"] = self._description
        if required:
            schema["required"] = required
        return schema

    def ui_map(self) -> dict[str, Any]:
        """The UI Schema as a dict."""
        elements: list[Any] = []
        for s in self._sections:
            controls = [field_.control() for field_ in s.fields]
            if s.title == "":
                elements.extend(controls)
                continue
            elements.append({"type": "Group", "label": s.title, "elements": controls})
        return {"type": "VerticalLayout", "elements": elements}

    def build(self) -> FormBuilder:
        """Render the form into the FormBuilder an action or settings profile
        carries. Raises if validate() fails — forms are declared from literals at
        start-up, so a failure here is a programming error."""
        self.validate()
        return FormBuilder(submit_to=self._submit_to, jsonschema=self.schema(), jsonui=self.ui())

    def settings(self, submit: Callable) -> Settings:
        """Render the form as a plugin settings profile: the same two documents,
        plus the handler the host calls when the profile is submitted. The handler
        is a validator, not a store — the platform ships the profile back with every
        call as body.settings."""
        fb = self.build()
        return Settings(
            submit_to=fb.submit_to,
            jsonui=fb.jsonui,
            jsonschema=fb.jsonschema,
            submit_handler=submit,
        )


def form(title: str) -> Form:
    """Start a form. The title is the JSON Schema `title`, shown as the dialog
    heading."""
    return Form(title)


def _must_encode(document: dict[str, Any]) -> str:
    try:
        return json.dumps(to_wire(document), separators=(",", ":"), ensure_ascii=False)
    except Exception as e:
        raise RuntimeError("formkit: encode: " + str(e))
