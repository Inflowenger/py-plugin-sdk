# Middleware — the functions an action's request runs before the job is accepted.
# Mirrors sdkv1/middleware.go.
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Awaitable, Callable, Optional, Union

from .context import JobContext

if TYPE_CHECKING:
    from .job import Job


# One function of an action's middleware: run for each of the action's requests,
# in order with the others, BEFORE the job is accepted. It gets the job's context
# so far and returns it — with whatever it bound — for the next function, and in
# the end for the handler (Job.context()).
#
#     def register(ctx, job):
#         runs[job.job_id] = {"status": "running"}  # before the runtime knows the jobId
#         return ctx
#
# Returning None keeps the context it was given, so a function that only has a
# side effect needs no return at all.
#
# It runs before the job is accepted — before the SDK replies the jobId to the
# runtime — so nothing can happen to the job (a stop, a query from a later run)
# before what a function set up under that jobId is in place. That is where
# per-job registration goes.
#
# RAISING REJECTS THE REQUEST: the runtime gets the error instead of a jobId, and
# neither the functions after it nor the handler run. (Go's equivalent returns an
# error; an exception is the same thing here, and a Go panic's recovery too.)
#
# The job's context ends when the handler returns, or when the request is
# rejected: a function that must clean up when the job ends does it with
# ctx.on_done(...) on the context it returns.
#
# It may be a coroutine function, and the SDK awaits it — but the runtime gives
# up on a jobId it waits too long for (15s), so keep it quick.
MiddlewareFunc = Callable[
    [JobContext, "Job"], Union[Optional[JobContext], Awaitable[Optional[JobContext]]]
]

# An ordered list of middleware functions — the value of Action.middleware. A
# plain list works; use(...) builds one while skipping None entries.
Middlewares = list


def use(*fns: Optional[MiddlewareFunc]) -> list[MiddlewareFunc]:
    """List middleware functions, in the order they run — the helper for
    Action.middleware:

        middleware=use(stops.middleware, trace, register)

    A plain list is equally valid (`middleware=[stops.middleware]`); `use` exists
    to mirror Go's sdkv1.Use and to drop None entries, so a conditionally-built
    list needs no filtering."""
    return [fn for fn in fns if fn is not None]


# The key the jobId is bound to on the context. Module-private, so nothing else
# can read or overwrite it by accident.
_JOB_ID_KEY = object()


def job_id(ctx: JobContext, job: "Job") -> JobContext:
    """The middleware function that names a request's job: it binds a fresh UUID
    to the context as the jobId (read with job_id_from_context), and the SDK sets
    Job.job_id from it, so every function after it sees the job named. Every
    request runs it first; with_job_id replaces it, for a plugin that names its
    jobs its own way."""
    return with_job_id_context(ctx, str(uuid.uuid4()))


def with_job_id_context(ctx: JobContext, job_id: str) -> JobContext:
    """`ctx` carrying `job_id` as the job's id. A replacement for the namer binds
    its id with this; the SDK takes Job.job_id from there."""
    return ctx.with_value(_JOB_ID_KEY, job_id)


def job_id_from_context(ctx: JobContext) -> str:
    """The jobId bound to `ctx`, or "" — for code deep in a call chain that has
    the context but not the Job: a logger, a tracer."""
    value = ctx.value(_JOB_ID_KEY)
    return value if isinstance(value, str) else ""
