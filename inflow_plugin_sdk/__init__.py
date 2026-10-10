# inflow_plugin_sdk — public API.
# The Python port of go-plugin-sdk (sdkv1).
from . import formkit, jobstop
from .compose import chain_signals, log_signals
from .context import (
    ERR_CANCELED,
    ERR_DEADLINE_EXCEEDED,
    Canceled,
    DeadlineExceeded,
    JobContext,
    background,
)
from .inflow_v1 import (
    dispatch_action,
    parse_signal,
    run_pipeline,
    signal_port_note,
)
from .job import Job
from .middleware import (
    MiddlewareFunc,
    job_id,
    job_id_from_context,
    use,
    with_job_id_context,
)
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
    with_job_id,
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
    "with_job_id",
    "DEFAULT_SEND_TIMEOUT",
    "REQ_TIMEOUT_ENV",
    # job / req
    "Job",
    "ActionRequest",
    "cast_request_to",
    "with_job_handler",
    # the job's context — cancellation + values
    "JobContext",
    "background",
    "Canceled",
    "DeadlineExceeded",
    "ERR_CANCELED",
    "ERR_DEADLINE_EXCEEDED",
    # middleware — functions run before a job is accepted
    "MiddlewareFunc",
    "use",
    "job_id",
    "with_job_id_context",
    "job_id_from_context",
    # signal-port composition
    "chain_signals",
    "log_signals",
    # jobstop — stop a job when the runtime stops its flow (opt-in per action)
    "jobstop",
    # the request path, for tests and for a plugin that drives the handshake
    "dispatch_action",
    "run_pipeline",
    "parse_signal",
    "signal_port_note",
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
