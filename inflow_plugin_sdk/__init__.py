# inflow_plugin_sdk — public API.
# The Python port of go-plugin-sdk (sdkv1).
from . import formkit
from .job import Job
from .models import (
    Action,
    ActionRequestContent,
    CallSvcBody,
    CommandPayload,
    ErrorPayload,
    FormBuilder,
    Frame,
    Icon,
    IPlugin,
    JobBodyContent,
    JobHandler,
    Meta,
    OutboundPort,
    PluginIntro,
    Request,
    RequestBody,
    Response,
    Settings,
    Signal,
    SignalHandler,
    marshal,
)
from .nats_box import NatsBox
from .plugin import (
    DEFAULT_SEND_TIMEOUT,
    REQ_TIMEOUT_ENV,
    Plugin,
    new_plugin,
    with_dot_env,
    with_infra_connection,
    with_plugin_id,
    with_timeout,
)
from .req import ActionRequest, cast_request_to, with_job_handler
from .types import Command, Conclusion, PluginSignal, canceled, succeeded

__all__ = [
    # plugin
    "Plugin",
    "new_plugin",
    "with_dot_env",
    "with_plugin_id",
    "with_infra_connection",
    "with_timeout",
    "DEFAULT_SEND_TIMEOUT",
    "REQ_TIMEOUT_ENV",
    # job / req
    "Job",
    "ActionRequest",
    "cast_request_to",
    "with_job_handler",
    # types
    "Command",
    "PluginSignal",
    "Conclusion",
    "succeeded",
    "canceled",
    "NatsBox",
    # models
    "IPlugin",
    "JobHandler",
    "PluginIntro",
    "Icon",
    "FormBuilder",
    "Action",
    "OutboundPort",
    "Settings",
    "Meta",
    "Frame",
    "CommandPayload",
    "ErrorPayload",
    "JobBodyContent",
    "Response",
    "Request",
    "RequestBody",
    "ActionRequestContent",
    "CallSvcBody",
    "Signal",
    "SignalHandler",
    "marshal",
    # formkit (optional form builder)
    "formkit",
]
