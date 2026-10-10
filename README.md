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
| `sdkv1/middleware.go` | `inflow_plugin_sdk/middleware.py` |
| `sdkv1/compose.go` | `inflow_plugin_sdk/compose.py` |
| `jobstop/jobstop.go` | `inflow_plugin_sdk/jobstop.py` |
| `context.Context` (stdlib) | `inflow_plugin_sdk/context.py` (`JobContext`) |

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
from inflow_plugin_sdk import Signal

p.on_signal(lambda sig: print(f"job {sig.job_id} ended: {sig.conclusion}"))
# p.on_signal() with no argument installs that same logging handler
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

### Stopping a job with its flow — `jobstop`

Rather than hand-rolling a `dict[job_id, asyncio.Task]`, add the stop capability to
the actions that need it: a middleware function on the action, a signal handler on the
port.

```python
from inflow_plugin_sdk import Action, Job, jobstop

stops = jobstop.Registry()

p.on_signal(stops.on_signal)            # before start() — or no stop ever arrives
p.add_action(Action(
    method="long.export",
    middleware=[stops.middleware],      # opt in, per action
    request_handler=long_export,
))

async def long_export(job: Job) -> None:
    ctx = job.context()                              # ends with the flow
    try:
        rows = await ctx.run(fetch_everything())     # the task is cancelled with it
    except jobstop.JobStopped:
        return                                       # the runtime has stopped listening
    await job.done({"rows": rows})
```

Middleware functions run **before the job is accepted**, so nothing can happen to a
job before what a function set up under its jobId is in place. They are plain
functions — `(ctx, job) -> ctx` — and raising from one rejects the request, so the same
mechanism carries per-job registration, tracing, and naming a job from an upstream
service's id.

`job.context()` is a `JobContext`, the Python stand-in for Go's `context.Context`:
`ctx.canceled` / `ctx.cause`, `await ctx.run(coro)` (abandon an awaited call),
`await ctx.sleep(s)` (`False` ⇒ stopped — the polling-loop idiom),
`ctx.on_done(cb)`, `ctx.with_value(k, v)`, `ctx.without_cancel()`,
`ctx.with_timeout(s)`. An action with no middleware gets a background context, never
cancelled, so a handler may read `ctx.canceled` unconditionally.

Two patterns build on this: **one id across two systems** (adopt the upstream
service's job id as the `jobId`) and **the flow as observer** (report state and end,
for work that outlives the run). Cookbook Skills 13 and 14 carry both in Python.

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
(subjects, payloads, the signal port),
[jobs-and-commands.md](https://github.com/Inflowenger/go-plugin-sdk/blob/main/docs/jobs-and-commands.md)
(the `Job` API, middleware, `jobstop` and `OnSignal`/`on_signal` in depth),
[external-job-identity.md](https://github.com/Inflowenger/go-plugin-sdk/blob/main/docs/external-job-identity.md)
and
[detached-work.md](https://github.com/Inflowenger/go-plugin-sdk/blob/main/docs/detached-work.md)
(the two advanced patterns). Their code is Go; [`cookbook.md`](cookbook.md) Skills
12–14 are the Python form of the same material.

One place where this port genuinely differs from Go, and it is worth knowing: in Go a
cancellation is an `error` the handler inspects, so a stopped job simply returns. In
Python it **raises** — out of `ctx.run`, out of an aborted client — and would unwind
straight out of the handler, which the SDK would otherwise report as a failed job. So
the SDK adds one guard Go has no need for: a handler that raises while its context is
already cancelled reports nothing and logs instead. Catch `jobstop.JobStopped`
yourself wherever the handler has cleanup to do.
