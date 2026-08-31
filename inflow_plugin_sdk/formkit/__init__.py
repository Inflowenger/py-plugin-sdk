# formkit — builds an Inflowenger form's JSON Schema + JSON Forms UI Schema from
# a single declaration of each field. The Python port of the Go `formkit` package.
#
# The package is additive and optional: nothing in the core SDK imports it, and
# what it produces is ordinary schema text, so a plugin may build every form with
# it, build one and hand-write the next, or use only picker / form_data / the
# Notification helpers against raw schema strings it wrote by hand.
#
#   from inflow_plugin_sdk import formkit
#
#   f = formkit.form("Create issue").add(
#       formkit.text("projectKey", "Project key").required()
#           .lookup("jira.meta.project.resolve", "Find").picks("jira.issue.create"),
#       formkit.text("summary", "Summary").required(),
#       formkit.text_area("description", "Description"),
#   ).build()
from .field import (
    Field,
    boolean,
    choice,
    custom,
    date,
    date_time,
    enum_,
    integer,
    list_,
    list_of,
    number,
    scope_of,
    secret,
    text,
    text_area,
)
from .form import Form, form
from .notification import (
    NotifKey,
    Notification,
    Option,
    failure,
    help,
    info,
    one_of,
    or_default,
    success,
    uiKey,
    warning,
)
from .picker import choices, choose, form_data, lines, picker

__all__ = [
    "Field",
    "Form",
    "form",
    "text",
    "text_area",
    "secret",
    "integer",
    "number",
    "boolean",
    "date",
    "date_time",
    "enum_",
    "choice",
    "list_",
    "list_of",
    "custom",
    "scope_of",
    "Notification",
    "NotifKey",
    "uiKey",
    "Option",
    "info",
    "success",
    "warning",
    "failure",
    "help",
    "one_of",
    "or_default",
    "form_data",
    "choices",
    "picker",
    "choose",
    "lines",
]
