# Request parsing and the request -> job handshake. Mirrors sdkv1/req.go.
from __future__ import annotations

import inspect
import json
from typing import Callable

from .job import Job
from .models import JobHandler, Request, RequestBody


class ActionRequest:
    """An incoming action execution, before it's accepted as a Job."""

    def __init__(self, job_id: str, action: str, req: Request):
        self.job_id = job_id
        self.action = action
        self.req = req

    async def accept(self, msg) -> Job:
        """Acknowledge the request with its jobId and return the live Job."""
        j = Job(self.req.plugin, self.action, self.job_id, self.req)
        await msg.respond(json.dumps({"jobId": self.job_id}, separators=(",", ":")).encode())
        return j

    async def reject(self, msg, cause: str) -> None:
        """Reject the request, replying with a cause."""
        await msg.respond(cause.encode())


def cast_request_to(data: bytes) -> RequestBody:
    """Decode a raw request body into a `{ _registry, body }` envelope.
    Mirrors Go's generic CastRequestTo[T]."""
    d = json.loads(data.decode())
    return RequestBody(registry=d.get("_registry"), body=d.get("body"))


def with_job_handler(job_handler: JobHandler) -> Callable:
    """Wrap a handler so an incoming request is accepted then run.

    Once the request is accepted the jobId is assigned and the runtime is waiting
    for a terminal command (Done / DoneWithError). So if the handler raises
    instead of finishing the job itself, the failure is reported back to the
    runtime as DoneWithError — never swallowed, or the runtime hangs waiting for a
    result that never comes. (DoneWithError goes through Plugin.send, which
    returns its own error rather than raising, so this reporting cannot itself
    crash the plugin.)"""

    async def run(ar: ActionRequest, msg) -> None:
        job = await ar.accept(msg)
        try:
            result = job_handler(job)
            if inspect.isawaitable(result):
                await result
        except Exception as e:
            await job.done_with_error(str(e))

    return run
