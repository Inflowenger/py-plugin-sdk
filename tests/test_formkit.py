"""formkit parity with the Go formkit_test.go demo() form: the schema and the UI
schema cannot drift — every control names a real property, in declaration order."""
import json

import pytest

from inflow_plugin_sdk import formkit as fk


def demo():
    return (
        fk.form("Create issue")
        .describe("Opens a new issue.")
        .submit_to("demo.validate")
        .add(
            fk.text("projectKey", "Project key")
            .required()
            .describe("e.g. OPS")
            .lookup("demo.project.resolve", "Find")
            .picks("demo.issue.create"),
            fk.text("issueKey", "Issue key").inline(),
            fk.text_area("description", "Description"),
            fk.integer("maxResults", "Max results").default(50).between(1, 100),
            fk.enum_("adjust", "Adjust estimate", "auto", "leave", "new"),
            fk.boolean("notify", "Notify watchers").default(True),
            fk.list_("labels", "Labels"),
        )
        .group(
            "Advanced",
            fk.text("extra", "Extra fields (JSON)").help("Merged last, so it overrides anything above."),
            fk.text("newEstimate", "New estimate").show_when("adjust", "new"),
        )
    )


def _controls(ui):
    out = []

    def walk(elements):
        for e in elements:
            if e.get("type") == "Control":
                out.append(e)
            else:
                walk(e.get("elements", []))

    walk(ui["elements"])
    return out


def test_every_control_names_a_property():
    built = demo().build()
    schema = json.loads(built.jsonschema)
    props = schema["properties"]
    controls = _controls(json.loads(built.jsonui))
    for c in controls:
        name = c["scope"].removeprefix("#/properties/")
        assert name in props, f"control {c['scope']} has no property behind it"
    assert len(controls) == len(props)


def test_controls_keep_declaration_order():
    form = demo()
    want = [f.name for f in form.fields()]
    got = [c["scope"].removeprefix("#/properties/") for c in _controls(json.loads(form.ui()))]
    assert got == want


def test_schema_types_required_defaults():
    schema = json.loads(demo().schema())
    assert schema["title"] == "Create issue"
    assert schema["description"] == "Opens a new issue."
    assert schema["required"] == ["projectKey"]
    props = schema["properties"]
    mr = props["maxResults"]
    assert mr["type"] == "integer" and mr["default"] == 50 and mr["minimum"] == 1 and mr["maximum"] == 100
    assert props["labels"]["type"] == "array" and props["labels"]["items"]["type"] == "string"
    assert props["adjust"]["enum"] == ["auto", "leave", "new"]
    assert props["notify"]["default"] is True


def test_show_when_rule():
    controls = _controls(json.loads(demo().ui()))
    ne = next(c for c in controls if c["scope"].endswith("newEstimate"))
    assert ne["rule"]["effect"] == "SHOW"
    assert ne["rule"]["condition"]["schema"]["const"] == "new"


def test_lookup_button_targets_and_picks():
    control = _controls(json.loads(demo().ui()))[0]  # projectKey
    action = control[fk.uiKey]["action"]
    assert action["fn"] == "demo.project.resolve"
    assert action["body"]["targetField"] == "projectKey"
    assert action["body"]["form"] == "demo.issue.create"


def test_duplicate_field_name_rejected():
    with pytest.raises(ValueError):
        fk.form("x").add(fk.text("a", "A"), fk.text("a", "B")).build()


def test_choose_falls_back_to_text_when_form_has_no_schema():
    # No schema -> picker cannot rebuild -> choose returns a notification patch.
    from inflow_plugin_sdk import FormBuilder

    out = fk.choose(FormBuilder(), "target", [fk.Option("v1", "One")], {}, fk.info("pick one"))
    assert fk.NotifKey in out
    assert "One" in out[fk.NotifKey].message
