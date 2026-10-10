"""Stop a plugin's job when the runtime stops its flow.

Mirrors the Go SDK's `jobstop` package
(github.com/Inflowenger/go-plugin-sdk/jobstop).

It is built from the SDK's public pieces only, and the plugin composes it in
itself — a middleware function on each action that should stop with its flow,
and a signal handler on the plugin's signal port::

    from inflow_plugin_sdk import jobstop

    stops = jobstop.Registry()        # one per plugin

    p.on_signal(stops.on_signal)      # before await p.start()
    p.add_action(Action(
        method="run",
        middleware=[stops.middleware],
        request_handler=run_handler,
    ))

    async def run_handler(job):
        ctx = job.context()                       # ends when the flow is stopped
        try:
            rows = await ctx.run(slow_query())    # cancelled with it
        except jobstop.JobStopped:
            return                                # the runtime is gone: do not report
        if ctx.canceled:
            return
        await job.done({"rows": rows})

Each piece sits beside others the same way: ``use(trace, stops.middleware)`` on
an action (or ``p.use`` for every action), ``chain_signals(stops.on_signal,
audit)`` on the port.

It is opt-in per action, and that is the point: a job the plugin accepted keeps
running after its flow stops — a later run of the node may build on its
progress, the runtime handing the previous jobId back in ``_registry`` — so only
the actions whose work must not outlive the process take ``stops.middleware``: a
paid call nobody will read, a stream to close, a lock to release.

Isolation
---------
Stops are matched by jobId, and only by jobId. The runtime publishes process
signals on ONE subject per plugin, ``inflow.plugin.<PLUGIN_ID>.proc``, so every
process of a plugin receives every one of that plugin's signals: those of jobs
in other flows running at the same time, and, when the plugin is deployed as
several replicas, those of jobs this process never accepted. There is no flowId
on the wire. A signal for a job this registry does not hold is the ordinary
case, and does nothing.

Because middleware runs before the runtime is told the jobId, a job is always
filed before any stop for it can arrive.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .context import CancelFunc, Canceled, JobContext
from .models import Signal
from .types import PluginSignal, canceled

if TYPE_CHECKING:
    from .job import Job


class JobStopped(Canceled):
    """The cause a stopped job's context carries — read it with ``ctx.cause``, or
    catch it out of ``await ctx.run(...)``.

    It means the runtime stopped the job's process: a user stop, a stop command,
    the workflow's timeout, the node's idle window. The runtime has concluded the
    job and stopped listening: **return without reporting**."""


# The cause of a stop by the runtime. Mirrors Go's jobstop.ErrStopped.
ErrStopped = JobStopped("jobstop: the runtime stopped the job's process")

# The cause a job's context carries when the plugin cancelled every job it holds
# (Registry.cancel_all), typically because it is exiting. Mirrors Go's
# jobstop.ErrShutdown.
ErrShutdown = JobStopped("jobstop: the plugin is shutting down")


class Registry:
    """Holds the jobs filed by its `middleware`, keyed by jobId, from before each
    is accepted until its context ends. One per plugin."""

    __slots__ = ("_jobs",)

    def __init__(self) -> None:
        self._jobs: dict[str, CancelFunc] = {}

    def middleware(self, parent: JobContext, job: "Job") -> JobContext:
        """A MiddlewareFunc: it files the job under its jobId with a context
        derived from the one it is given — the one the handler gets — which
        on_signal cancels when the runtime stops the job's process. It runs
        before the runtime knows the jobId; the job leaves the registry whenever
        its context ends — a stop, cancel_all, or the SDK ending it when the
        handler returns or the request is rejected — so nothing is left behind
        however the job ends."""
        ctx, cancel = parent.with_cancel()
        job_id = job.job_id
        self._jobs[job_id] = cancel

        def unfile(_cause: BaseException) -> None:
            # Only unfile our own entry: by the time a context ends, the jobId
            # may have been re-filed by a later run (an adopted external id is
            # reused across runs — see external-job-identity).
            if self._jobs.get(job_id) is cancel:
                del self._jobs[job_id]

        ctx.on_done(unfile)
        return ctx

    def on_signal(self, sig: Signal) -> None:
        """A SignalHandler. A process signal for a job this registry holds
        unfiles it, and when its conclusion is canceled() — flow_stop_by_user,
        stop_command, timeout, long_time_without_command — cancels its context
        with ErrStopped and logs the jobId and that conclusion. Any other ending
        (done, failure, …) leaves the context alone, and logs nothing: the job
        has finished or is finishing on its own, and must not be cut short.

        Only a job this registry holds is logged, so the line always means work
        of this process was cut short — the signals of other flows' and other
        replicas' jobs, which arrive on the same subject, pass in silence."""
        if sig.kind != PluginSignal.PROC or sig.job_id == "":
            return
        cancel = self._jobs.pop(sig.job_id, None)
        if cancel is None:
            return  # somebody else's job — another flow's, another replica's
        if not canceled(sig.conclusion):
            return
        # Logged because this is the one moment the plugin's own work is cut
        # short from outside: the handler just sees its context end, so without a
        # line here a stopped job is indistinguishable in the log from one that
        # wound down by itself.
        print(
            f"jobstop: job {sig.job_id} cancelled: "
            f"the runtime concluded its process {sig.conclusion}"
        )
        cancel(ErrStopped)

    def cancel_all(self) -> None:
        """Cancel every job the registry holds, with ErrShutdown — for a plugin
        about to exit, so its handlers see their contexts end and wind down. It
        sends nothing to the runtime: what a job reports, if anything, is its
        handler's call."""
        held = list(self._jobs.values())
        self._jobs.clear()
        for cancel in held:
            cancel(ErrShutdown)

    def __len__(self) -> int:
        """How many jobs the registry currently holds. For tests and health
        output."""
        return len(self._jobs)
