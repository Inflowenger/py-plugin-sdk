# inflowenger-plugin-sdk

Python SDK for building Inflowenger Plugin nodes (the `inflowv1` protocol) — the
Python port of [go-plugin-sdk](https://github.com/Inflowenger/go-plugin-sdk)
(`sdkv1`). It mirrors the Go SDK file-for-file and keeps the same wire format, so
a Python plugin is interchangeable with a Go (or Node) plugin from the runtime's
point of view.

## Async, but faithful to Go

Go's `nats.go` is synchronous; Python's maintained NATS client (`nats-py`) is
asyncio-only, so — like the Node port — this SDK is `async`. Method names are the
Go names in `snake_case` (`Job.Done` → `job.done`, `CmdGetScope` → `cmd_get_scope`,
`NewPlugin` → `new_plugin`).

One deliberate fidelity point: **`Plugin.send` returns `(msg, err)` and never
raises** — exactly Go's `(*nats.Msg, error)` contract. A workflow the user has
stopped leaves no NATS responders, and raising there would crash the whole
plugin. Job methods return the error object (not raise) or the reply bytes, just
like the Go handlers return `err` or `msg.Data`.

## File map (Go → Python)

| Go | Python |
| --- | --- |
| `sdkv1/plugin.go` | `inflow_plugin_sdk/plugin.py` |
| `sdkv1/inflowV1.go` | `inflow_plugin_sdk/inflow_v1.py` |
| `sdkv1/job.go` | `inflow_plugin_sdk/job.py` |
| `sdkv1/req.go` | `inflow_plugin_sdk/req.py` |
| `sdkv1/models.go` + `types.go` | `inflow_plugin_sdk/models.py` + `types.py` |
| `sdkv1/dotenv.go` | `inflow_plugin_sdk/env.py` |
| `nats/natsBox.go` | `inflow_plugin_sdk/nats_box.py` |
| `formkit/*.go` | `inflow_plugin_sdk/formkit/` |

## Install

```bash
pip install inflowenger-plugin-sdk        # pulls nats-py and python-dotenv
```

Working *on* the SDK itself? Clone the repo and install it editable, so your
source edits are picked up without reinstalling:

```bash
pip install -e ".[dev]"                   # editable, plus pytest / build / twine
```

## Quick start

```python
import asyncio
from inflow_plugin_sdk import Action, Frame, Job, new_plugin, with_dot_env


async def main() -> None:
    p = await new_plugin(with_dot_env(".env.inflow"))
    p.intro_data.name = "HTTP.CALL"
    p.intro_data.author = "inflow Dev. Team"
    p.intro_data.version = "v0.0.1"

    async def handler(job: Job) -> None:
        await job.progress(10, Frame(title="init", content="working"))
        await job.done({"action": "done"})

    p.add_action(Action(method="fn", request_handler=handler))

    await p.start()
    await asyncio.Event().wait()  # keep the process alive to serve requests


if __name__ == "__main__":
    asyncio.run(main())
```

See `examples/rpc.py` and `examples/http_call.py` (the ports of `TestCommands` /
`TestInit` in `sdkv1_test.go`). Copy `.env.inflow.example` to `.env.inflow` and
fill in the values Infra minted for your plugin.

## Signals — knowing a process ended (`on_signal`)

The runtime broadcasts on `inflow.plugin.<PLUGIN_ID>.proc` whenever a plugin node
process ends, saying which job it was and how it ended: `done`, `flow_stop_by_user`,
`timeout`, and so on. `p.on_signal(handler)` — registered **before `start()`** —
subscribes to that port (`inflow.plugin.<PLUGIN_ID>.>`, so future signal kinds reach
the same handler).

```python
from inflow_plugin_sdk import Signal, canceled

inflight: dict[str, asyncio.Task] = {}

def on_signal(sig: Signal) -> None:
    if not canceled(sig.conclusion):      # done / next / failed: nothing to abort
        return
    task = inflight.pop(sig.job_id, None) # sig.job_id == the job.job_id you were given
    if task is not None:
        task.cancel()

p.on_signal(on_signal)                    # p.on_signal() alone just logs the port
```

**This is optional, and ignoring it is a valid choice.** A stopped process does not
stop the job: that is on purpose, because the next process on the same node may build
on the progress this one made — the runtime hands the previous `jobId` back in
`_registry`. Register a handler only where the work itself must not outlive the
process: a stream to close, an upstream call to abort, a reservation to release.

Two things to keep in mind: a signal also arrives on **success** (filter on
`sig.conclusion`, with `canceled()` / `succeeded()` or the `Conclusion` enum), and by
the time it lands the runtime no longer answers that job's commands — wind the work
down, do not try to report it. Handlers run in their own task, so a slow one does not
stall the port, and an exception inside one is caught and logged.

## Forms

`formkit` builds an action's JSON Schema + JSON Forms UI Schema from one
declaration per field — the port of the Go `formkit` package:

```python
from inflow_plugin_sdk import formkit

form = formkit.form("Create issue").add(
    formkit.text("projectKey", "Project key").required()
        .lookup("jira.meta.project.resolve", "Find").picks("jira.issue.create"),
    formkit.text("summary", "Summary").required(),
    formkit.text_area("description", "Description"),
).build()

p.add_action(Action(method="jira.issue.create", form=form, request_handler=...))
```

The protocol docs are language-agnostic and shared with the Go and Node SDKs — see
[protocol-inflowv1.md](https://github.com/Inflowenger/go-plugin-sdk/blob/main/docs/protocol-inflowv1.md)
(subjects, payloads, the signal port) and
[jobs-and-commands.md](https://github.com/Inflowenger/go-plugin-sdk/blob/main/docs/jobs-and-commands.md)
(the `Job` API and `OnSignal`/`on_signal` in depth).
