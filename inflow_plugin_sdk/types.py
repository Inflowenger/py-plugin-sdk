# Job command names — the <CMD> segment of inflow.cpu.<PLUGIN_ID>.<JOB_ID>.<CMD>.
# Mirrors sdkv1/types.go.
from enum import StrEnum


class Command(StrEnum):
    PROGRESS = "progress"
    CONTEXT_CURRENT = "context/current"
    CONTEXT_PATH = "context/path"
    COMMIT = "commit"
    # next_tags — fire only the outbound branch(es) whose tags are named.
    NEXT_TAGS = "next_tags"
    # request/svc — a plugin-originated call to a downstream service.
    REQUEST = "request/svc"


class PluginSignal(StrEnum):
    """The kind of a runtime signal: the subject remainder after
    `inflow.plugin.<PLUGIN_ID>.` — see Signal and Plugin.on_signal. The signal port
    is a one-way, fire-and-forget channel OUT of the runtime, parallel to the
    `inflow.v1` (describe me) and `inflow.cpu` (run me) planes; nothing on it is a
    request, so a handler never replies. Mirrors Go's PluginSignal."""

    # "proc" — published once per plugin node process, the moment the runtime stops
    # attending it, on every outcome and not only cancellation. Payload:
    # {"conclusion":"<Conclusion>","jobId":"<uuid>"}, where jobId is the same id the
    # SDK minted for that job.
    PROC = "proc"


class Conclusion(StrEnum):
    """How the runtime ended a plugin node process, as carried by a
    PluginSignal.PROC signal. Mirrors models.PluginConclusion in fractal-core (and
    Go's Conclusion).

    Whatever the value, the runtime is no longer listening on that job's command
    subjects once the signal is out: further progress/done/context calls from a
    still-running handler will find no responder."""

    # The job reported progress 100 and its details were committed.
    DONE = "done"
    # The process ended on a routing command (`next_tags`).
    NEXT = "next"
    # A user halted the running flow — the cancellation case.
    FLOW_STOP_BY_USER = "flow_stop_by_user"
    # The flow was stopped by an explicit stop command.
    COMMAND_STOP = "stop_command"
    # The workflow's own deadline expired while the job ran.
    TIMEOUT = "timeout"
    # The node's idle window (`idle_min`) passed with no command from the plugin.
    LONG_TIME_WITHOUT_COMMAND = "long_time_without_command"
    # A command carried a payload or path the runtime could not accept.
    BAD_REQUEST = "bad_request"
    # The job issued an abnormal number of commands (>1500) and was cut off.
    EXCEEDED_REQUEST_ANOMALY = "anomaly_request"
    # The flow was failed with an error.
    FAILURE = "failure"
    # The runtime failed on its own side (e.g. the commit could not be written).
    INTERNAL_ERROR = "internal_error"
    # The plugin never acknowledged the execution request with a jobId.
    PLUGIN_NOT_RESPONDED = "plugin_not_responded"
    # Cancelled with no recognizable cause (the runtime's spelling is deliberate).
    UNKNOWN_CAUSE = "unknow_cause"


def succeeded(conclusion: str) -> bool:
    """Whether the process ended the way the job intended — the handler finished
    (`done`) or routed onward (`next`). Mirrors Go's Conclusion.Succeeded."""
    return conclusion in (Conclusion.DONE, Conclusion.NEXT)


def canceled(conclusion: str) -> bool:
    """Whether the process was cut short by a decision outside the job — a user
    stopping the flow, a workflow timeout, or the idle window expiring — rather than
    by the handler finishing or erroring. This is the condition to test when a
    handler holds work that should be abandoned; see Plugin.on_signal for why
    abandoning is opt-in and not the default. Mirrors Go's Conclusion.Canceled."""
    return conclusion in (
        Conclusion.FLOW_STOP_BY_USER,
        Conclusion.COMMAND_STOP,
        Conclusion.TIMEOUT,
        Conclusion.LONG_TIME_WITHOUT_COMMAND,
    )
