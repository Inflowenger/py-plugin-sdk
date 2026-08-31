"""RPC sample plugin — the Python equivalent of TestCommands in sdkv1_test.go.

A pure context function: read context and return. Run: python -m examples.rpc
"""
import asyncio

from inflow_plugin_sdk import Job, new_plugin, with_dot_env


async def main() -> None:
    p = await new_plugin(with_dot_env(".env.inflow"))

    p.intro_data.name = "RPC"
    p.intro_data.author = "inflow Dev. Team"
    p.intro_data.version = "v0.0.1"

    async def fn(job: Job) -> None:
        cur = await job.cmd_get_current_scope()
        print("GetCurrent", cur if isinstance(cur, Exception) else cur.decode())

        scope = await job.cmd_get_scope("$.OPA")
        print("Scope : ", scope if isinstance(scope, Exception) else scope.decode())

        await job.done({"action": "done"})

    from inflow_plugin_sdk import Action

    p.add_action(Action(method="fn", request_handler=fn))

    await p.start()
    await asyncio.Event().wait()  # keep the process alive to serve requests


if __name__ == "__main__":
    asyncio.run(main())
