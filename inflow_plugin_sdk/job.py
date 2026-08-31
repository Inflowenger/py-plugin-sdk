# The Job handle passed to an action handler. Mirrors sdkv1/job.go.
from __future__ import annotations

from typing import Any, Optional

from .models import CallSvcBody, CommandPayload, Frame, IPlugin, JobBodyContent, Request, marshal
from .types import Command


class Job:
    def __init__(self, plugin: IPlugin, action: str, job_id: str, req: Request):
        self.plugin = plugin
        self.action = action
        self.job_id = job_id
        self.req = req

    async def done(self, data: dict[str, Any], *key: str) -> Any:
        """Complete the job (progress 100) and emit `data` as this node's output."""
        return await self.command(
            Command.PROGRESS,
            CommandPayload(progress=100, details=data, commit_on=".".join(key)),
        )

    async def done_with_error(self, error: str) -> Any:
        """End the job as failed, reporting the reason as its only detail."""
        return await self.done_with_error_data(error, None)

    async def done_with_error_data(self, error: str, data: Optional[dict[str, Any]], *key: str) -> Any:
        """End the job as failed exactly like done_with_error, but keep a payload:
        `data` is reported (and committed, at `key` when given) next to the reason,
        which always lands on the canonical "error" detail — so a key named "error"
        inside `data` is overwritten. Use it when the failure still carries state
        the flow needs: a terminal command's details ARE what gets committed onto
        the node's scope, so a bare done_with_error drops anything the node had
        persisted there. Hand it back through `data` to keep it."""
        details: dict[str, Any] = dict(data or {})
        details["error"] = error
        return await self.command(
            Command.PROGRESS,
            CommandPayload(progress=100, details=details, commit_on=".".join(key)),
        )

    async def progress(self, progress_percent: int, step: Frame) -> Any:
        """Report progress. 100 or greater finishes the job. `step` is a titled
        status shown on the canvas."""
        return await self.command(Command.PROGRESS, CommandPayload(progress=progress_percent, frame=step))

    async def cmd_get_current_scope(self) -> Any:
        """Read the whole current context scope (raw bytes)."""
        sub = self._make_job_subject(Command.CONTEXT_CURRENT)
        msg, err = await self._send(sub, None)
        if err is not None:
            return err
        return msg.data

    async def cmd_next_filter(self, nexts_tags: list[str]) -> Any:
        """Fire only the outbound branch(es) whose tags are named — the runtime
        counterpart of Action.outbound. Edges carrying other tags are skipped."""
        sub = self._make_job_subject(Command.NEXT_TAGS)
        msg, err = await self._send(sub, ",".join(nexts_tags).encode())
        if err is not None:
            return err
        return msg.data

    async def cmd_svc_call(self, action: str, data: Any, op_data: Optional[dict[str, Any]] = None) -> Any:
        """Make a plugin-originated call to a downstream service. `action` names the
        service, `data` is the payload, `op_data` carries operation metadata."""
        if action.strip() == "":
            return ValueError("invalid subject")
        envelope = CallSvcBody(data=data, op=op_data)
        req_body = marshal(envelope)
        sub = self._make_call_svc_subject(action)
        msg, err = await self._send(sub, req_body)
        if err is not None:
            return err
        return msg.data

    async def cmd_get_scope(self, json_path: str) -> Any:
        """Read a slice of context addressed by JSON path (e.g. "$.OPA")."""
        sub = self._make_job_subject(Command.CONTEXT_PATH)
        msg, err = await self._send(sub, json_path.encode())
        if err is not None:
            return err
        return msg.data

    async def cmd_set_on_path(self, json_path: str, data: dict[str, Any]) -> Any:
        """Commit data into the flow context at a JSON path."""
        content = JobBodyContent(commit_on=json_path, details=data)
        sub = self._make_job_subject(Command.COMMIT)
        try:
            b_data = marshal(content)
        except Exception as err:
            return err
        msg, err = await self._send(sub, b_data)
        if err is not None:
            return err
        return msg.data

    async def command(self, cmd: Command, data: CommandPayload) -> Any:
        """Low-level: send a command payload to the runtime for this job."""
        sub = self._make_job_subject(cmd)
        try:
            data_byte = marshal(data)
        except Exception as err:
            print("progress command ", cmd, " error:", err)
            return err
        msg, err = await self._send(sub, data_byte)
        if err is not None:
            return err
        return msg.data

    async def _send(self, sub: str, data: Optional[bytes]):
        return await self.plugin.send(sub, data if data is not None else b"")

    def _make_job_subject(self, cmd: Command) -> str:
        # inflow.cpu.<PLUGIN_ID>.<JOB_ID>.<cmd>
        return f"inflow.cpu.{self.plugin.get_plugin_id()}.{self.job_id}.{cmd}"

    def _make_call_svc_subject(self, action: str) -> str:
        # inflow.cpu.<PLUGIN_ID>.<JOB_ID>.request/svc.<action>
        return f"inflow.cpu.{self.plugin.get_plugin_id()}.{self.job_id}.{Command.REQUEST}.{action}"
