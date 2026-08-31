"""HTTP.CALL sample plugin — the Python equivalent of TestInit in sdkv1_test.go.

Setup (uses the SDK published on PyPI):
    pip install inflowenger-plugin-sdk
    cp .env.inflow.example .env.inflow   # then fill in your values
Run:
    python examples/http_call.py
"""
import asyncio
import json
import urllib.request

from inflow_plugin_sdk import Action, Frame, Job, cast_request_to, new_plugin, with_dot_env


async def main() -> None:
    p = await new_plugin(with_dot_env(".env.inflow"))

    p.intro_data.name = "HTTP.CALL"
    p.intro_data.author = "inflow Dev. Team"
    p.intro_data.version = "v0.0.1"

    # Action 1: perform a real outbound HTTP request driven by the node's form.
    async def http_call(job: Job) -> None:
        try:
            req = cast_request_to(job.req.data)
        except Exception as e:
            await job.done_with_error(str(e))
            return

        # _registry carries this node's previous run (idempotency / resume).
        if req.registry and req.registry.get("jobId"):
            print(f"This node's previous run had jobId {req.registry['jobId']}")

        body = req.body or {}
        print(f"REQUEST URL: {body.get('url')}")

        await job.progress(10, Frame(title="init step", content="given task is in progress"))
        await job.progress(20, Frame(title="working", content="task is being processed"))

        try:
            data = json.dumps(body.get("body")).encode() if body.get("body") else None
            request = urllib.request.Request(
                body["url"],
                data=data,
                method=body.get("method", "GET"),
                headers={"Content-Type": "application/json", **(body.get("headers") or {})},
            )
            with urllib.request.urlopen(request) as resp:
                raw = resp.read().decode()
            try:
                done_body = json.loads(raw)
            except Exception:
                done_body = {"rawBody": raw}
            await job.progress(80, Frame(title="almost done", content=""))
            await job.done(done_body)
        except Exception as e:
            await job.done_with_error(str(e))

    p.add_action(
        Action(
            method="http.call",
            title="HTTP Call",
            description="Perform an outbound HTTP request",
            request_handler=http_call,
        )
    )

    # Action 2: read + write flow context.
    async def fn(job: Job) -> None:
        cur = await job.cmd_get_current_scope()
        print("GetCurrent", cur if isinstance(cur, Exception) else cur.decode())

        scope = await job.cmd_get_scope("$.OPA")
        print("Scope : ", scope if isinstance(scope, Exception) else scope.decode())

        await job.cmd_set_on_path('$["doc appendix"]', {"itemXterm": [1, 3, 42, 2300]})
        await job.done({"action": "done finally...."})

    p.add_action(Action(method="fn", request_handler=fn))

    await p.start()
    await asyncio.Event().wait()  # keep the process alive to serve requests


if __name__ == "__main__":
    asyncio.run(main())
