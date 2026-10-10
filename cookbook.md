# Plugin developer cookbook (Python)

A hands-on cookbook for writing an Inflowenger **Plugin node** with
`inflow_plugin_sdk` (PyPI: `inflowenger-plugin-sdk`). Each section is a
self-contained *skill* — a concrete thing you'll need — with the minimal code that
does it. Everything here is grounded in the SDK's real API.

This mirrors the Go SDK's cookbook section for section: `go-plugin-sdk` is the main
stream, and this is its Python port. The wire protocol is identical, so a Python
plugin is interchangeable with a Go or Node one from the runtime's point of view.
Method names are the Go names in `snake_case` (`Job.Done` → `job.done`,
`CmdGetScope` → `job.cmd_get_scope`, `NewPlugin` → `new_plugin`).

If you want the concepts behind these recipes, read the docs first — they are
language-agnostic and live in the Go repo:
[architecture](https://github.com/Inflowenger/go-plugin-sdk/blob/main/docs/architecture.md) ·
[inflowv1 protocol](https://github.com/Inflowenger/go-plugin-sdk/blob/main/docs/protocol-inflowv1.md) ·
[jobs & commands](https://github.com/Inflowenger/go-plugin-sdk/blob/main/docs/jobs-and-commands.md) ·
[form builder](https://github.com/Inflowenger/go-plugin-sdk/blob/main/docs/form-builder.md) ·
[external job identity](https://github.com/Inflowenger/go-plugin-sdk/blob/main/docs/external-job-identity.md) ·
[detached work](https://github.com/Inflowenger/go-plugin-sdk/blob/main/docs/detached-work.md) ·
[examples](https://github.com/Inflowenger/go-plugin-sdk/blob/main/docs/examples.md).
Those docs are written in Go, but the protocol and the design are identical — Skills
12–14 below carry the Python form of everything in the last three.

Also worth keeping open: the **[plugin catalog](https://github.com/Inflowenger/plugin-catalog)** — the developer
knowledge base ([concepts](https://github.com/Inflowenger/plugin-catalog/blob/main/docs/concepts.md) ·
[build a plugin](https://github.com/Inflowenger/plugin-catalog/blob/main/docs/build-a-plugin.md) ·
[run a plugin](https://github.com/Inflowenger/plugin-catalog/blob/main/docs/run-a-plugin.md) ·
[dependent fields](https://github.com/Inflowenger/plugin-catalog/blob/main/docs/dependent-fields.md) ·
[SDK matrix](https://github.com/Inflowenger/plugin-catalog/blob/main/docs/sdks.md) ·
[publishing](https://github.com/Inflowenger/plugin-catalog/blob/main/docs/publishing.md)) and
[`plugins/`](https://github.com/Inflowenger/plugin-catalog/tree/main/plugins), an entry per shipped plugin pointing at its
real source — the best worked examples there are.

> **Using an AI coding agent?** This repo ships a companion **Agent Skill** at
> [`skills/inflow-plugin/SKILL.md`](skills/inflow-plugin/SKILL.md) — a `SKILL.md`
> (frontmatter + agent-directed rules) distilling this guide for a code agent.
> Since the SDK is installed as a **library**, drop it into *your* plugin project so
> an agent auto-loads it there: copy that folder to `.claude/skills/inflow-plugin/`
> in the repo where you're building the plugin.

---

## Skill 0 — Set up & provision

Before any code, the plugin must exist **in a space** (a NATS account managed by
Infra) so it has an identity and credentials. See
[go-plugin-sdk README → provisioning](https://github.com/Inflowenger/go-plugin-sdk#where-these-values-come-from--provisioning-a-plugin).
Put the three values Infra gives you in a dotenv file (`cp .env.inflow.example
.env.inflow`):

```env
# .env.inflow
PLUGIN_ID=aa-bbb-ccc-dddd
INFRA_CRED=LS0tLS1CRUdJTiBOQVRTIFVTRVIgSldULS0t...   # base64 of the .creds blob
INFRA_URL=localhost:4222
```

```bash
pip install inflowenger-plugin-sdk        # pulls nats-py and python-dotenv
```

Python **3.11+** is required (the SDK uses `StrEnum`).

> **Checklist:** plugin registered in a space · `PLUGIN_ID` · `INFRA_CRED` (base64) ·
> `INFRA_URL` · Infra + at least one Fractal running.

---

## Skill 1 — Scaffold a runnable plugin

A plugin is an ordinary long-running asyncio program. Construct → declare →
`start()` → **block**:

```python
import asyncio
from inflow_plugin_sdk import Action, Job, PluginIntro, new_plugin, with_dot_env


async def main() -> None:
    p = await new_plugin(with_dot_env(".env.inflow"))

    p.intro(PluginIntro(name="HTTP.CALL", author="you", version="v0.0.1"))

    async def handler(job: Job) -> None:
        await job.done({"ok": True})

    p.add_action(Action(method="http.call", title="HTTP Call", request_handler=handler))

    await p.start()                 # subscribes to all subjects, returns immediately
    await asyncio.Event().wait()    # keep the process alive to serve requests


if __name__ == "__main__":
    asyncio.run(main())
```

> **Gotcha:** `start()` returns as soon as it has wired up the subscriptions — it is
> the analogue of Go's `Start()` + `select {}`. Without the trailing
> `await asyncio.Event().wait()` the coroutine ends, `asyncio.run` tears down the
> loop, and the plugin dies.

Three ways to construct, pick one:

```python
# From dotenv (reads PLUGIN_ID / INFRA_CRED / INFRA_URL)
p = await new_plugin(with_dot_env(".env.inflow"))

# Explicit — you need BOTH the connection and the id
p = await new_plugin(
    with_infra_connection("localhost:4222", base64_cred),
    with_plugin_id("aa-bbb-ccc-dddd"),
)

# Either of the above, plus a custom reply timeout for Plugin.send
p = await new_plugin(with_dot_env(".env.inflow"), with_timeout(30))
```

`with_timeout(seconds)` overrides `DEFAULT_SEND_TIMEOUT`; the `REQ_TIMEOUT_ENV`
environment variable does the same without a code change.

---

## Skill 2 — Declare who you are (`intro`)

`intro` is the identity the platform shows for your plugin. Set it once before
`start()`:

```python
p.intro(PluginIntro(
    name="HTTP.CALL",
    author="inflow Dev. Team",
    version="v0.0.1",
))
```

Equivalently, assign the fields on `p.intro_data` (what the bundled examples do):

```python
p.intro_data.name = "HTTP.CALL"
p.intro_data.author = "inflow Dev. Team"
p.intro_data.version = "v0.0.1"
```

`PluginIntro` also carries an optional `manual` — a Markdown document the host
renders on the plugin's page. A fenced ` ```inflow-meta ` block whose body is a meta
method name becomes a **Run button** that calls it and shows the raw JSON reply:

````python
p.intro(PluginIntro(
    name="JIRA",
    author="you",
    version="v0.1.0",
    manual="## Jira\n\nTest the connection:\n\n```inflow-meta\njira.meta.ping\n```\n",
))
````

---

## Skill 3 — Add an action

An **action** is one method your node can perform. A plugin can expose many; call
`add_action` per action (it's variadic, so you can pass several at once):

```python
from inflow_plugin_sdk import Action, Icon

p.add_action(Action(
    method="http.call",                    # the method id used on the wire
    title="HTTP Call",                     # shown to users
    description="Perform an outbound HTTP request",
    icon=Icon(icon="mdi-web"),
    form=form,                             # Skill 8
    request_handler=my_handler,            # the work (Skill 4+)
))
```

Every action needs a unique `method` and a `request_handler` (an `async def` taking
a `Job`). `form` is optional but almost always wanted so users can configure the
node.

---

## Skill 4 — Read the request

Your handler receives a `Job`. The raw body is `job.req.data`; decode it with
`cast_request_to`, which unwraps the `{ "_registry", "body" }` envelope. It
**raises** on invalid JSON, so wrap it:

```python
from inflow_plugin_sdk import cast_request_to


async def my_handler(job: Job) -> None:
    try:
        req = cast_request_to(job.req.data)
    except Exception as e:
        await job.done_with_error(str(e))
        return

    body = req.body or {}       # the user's form input (a plain dict)
    reg = req.registry or {}    # runtime metadata; see Skill 5

    url = body.get("url")
    method = body.get("method", "GET")
```

> **Unlike Go, this is not generic.** Go's `CastRequestTo[Input]` decodes straight
> into your struct; the Python port takes no type parameter and `req.body` is a
> plain `dict`, so there is nothing to validate against — check the keys you depend
> on yourself (or hand the dict to `pydantic` / a `dataclass` if you want schema
> enforcement). Note also that the attribute is `req.registry`, while the wire field
> is `_registry`.

The keys you read must match your action's form (`jsonschema`) — the form defines
the shape that arrives in `body`.

---

## Skill 5 — Use previous-run metadata (`_registry`)

The `_registry` carries metadata the runtime attaches, including this node's
**previous** run — useful for idempotency, dedup, or resume:

```python
from datetime import datetime

if reg.get("jobId"):
    done_at = datetime.fromtimestamp(float(reg["doneAt"]))
    print(f"previous run {reg['jobId']} finished at {done_at}")
```

> **Gotcha:** timestamps are **seconds**, and JSON numbers arrive as `float`/`int`
> — coerce explicitly (`float(v)`) rather than trusting the type, and use `.get()`
> so a missing key is not a `KeyError`. (Python spares you Go's `float64` type
> assertions, but not the missing-key case.)

---

## Skill 6 — Report progress

Stream progress `0–100` with a titled status `Frame`. Progress is advisory feedback
shown on the canvas; it does **not** finish the job. Each command is a coroutine —
`await` it:

```python
from inflow_plugin_sdk import Frame

await job.progress(10, Frame(title="init step", content="starting"))
await job.progress(50, Frame(title="working", content="calling upstream"))
await job.progress(80, Frame(title="almost done"))
```

---

## Skill 7 — Finish (success or error)

Exactly one of these must run before your handler returns. All drive progress to
100 and terminate the job:

```python
# Success — `data` becomes this node's output
await job.done({"status": "ok", "result": result})

# Success, committing on an explicit key path (segments joined by ".")
await job.done(payload, "result", "http")

# Failure — completes as failed, reporting the reason
await job.done_with_error("upstream returned 500")

# Failure that still has data to report/commit
await job.done_with_error_data("upstream returned 500", {"messages": conversation})

# Failure carrying the plugin's own error number too
await job.done_with_error_code(429, "upstream rate limited", None)
```

The reason travels on the command's own `error` field (`{code, message}`), not as a
detail — so `details` are yours alone, and a bare `done_with_error` commits nothing.
`code` is the plugin's own numbering; the core carries it without interpreting it,
so pass `0` when the plugin has none.

> **Pattern:** on every error branch, `await job.done_with_error(...)` **and
> `return`**, so the job always terminates once and only once.

The SDK has a safety net Go does not need: if a handler raises instead of finishing,
the failure is reported to the runtime as `done_with_error` rather than swallowed —
otherwise the runtime would hang waiting for a result. Rely on it for bugs, not as
your error handling.

---

## Skill 8 — Give the action a UI form

Forms are **JSON Schema** (the data model + validation) plus a **UI Schema**
(layout), rendered by JSON Forms. What the user fills in becomes the `body` of the
request (Skill 4):

```python
import json
from inflow_plugin_sdk import FormBuilder

schema = json.dumps({
    "type": "object",
    "properties": {
        "url": {"type": "string", "title": "URL", "format": "uri"},
        "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"]},
    },
    "required": ["url", "method"],
})

ui = json.dumps({
    "type": "VerticalLayout",
    "elements": [
        {"type": "Control", "scope": "#/properties/url"},
        {"type": "Control", "scope": "#/properties/method"},
    ],
})

p.add_action(Action(
    method="http.call",
    form=FormBuilder(jsonschema=schema, jsonui=ui),
    request_handler=my_handler,
))
```

Or declare each field once and let `formkit` build both documents (the port of Go's
`formkit` package):

```python
from inflow_plugin_sdk import formkit

form = formkit.form("HTTP Call").add(
    formkit.text("url", "URL").required().format("uri"),
    formkit.enum_("method", "Method", "GET", "POST", "PUT", "DELETE").default("GET"),
    formkit.text_area("body", "JSON body"),
).build()
```

Field constructors: `text`, `text_area`, `secret`, `integer`, `number`, `boolean`,
`date`, `date_time`, `enum_`, `choice`, `list_`, `list_of`, `custom`. Modifiers
chain (`.required()`, `.describe()`, `.default()`, `.min()/.max()/.between()`,
`.show_when()/.hide_when()/.enable_when()`, `.lookup()`, `.inline()`).

`jsonschema` and `jsonui` are **JSON strings** either way — `.build()` returns a
`FormBuilder` with them already encoded. Keep the schema and the keys your handler
reads (Skill 4) in sync. More in
[form-builder.md](https://github.com/Inflowenger/go-plugin-sdk/blob/main/docs/form-builder.md).

---

## Skill 9 — Read the flow's context

A running flow has a shared **context** tree. Read all of it, or a slice by JSON
path. Both resolve to the reply `bytes` on success, **or to an `Exception`
instance** — the port of Go's `any` return that you type-assert to `[]byte`, because
`Plugin.send` returns its error rather than raising (a stopped workflow leaves no
NATS responder, and raising there would crash the plugin). So check before you
parse:

```python
import json

# whole current scope
cur = await job.cmd_get_current_scope()
if isinstance(cur, Exception):
    await job.done_with_error(f"cannot read scope: {cur}")
    return
print("current:", json.loads(cur))

# a slice addressed by JSON path
opa = await job.cmd_get_scope("$.OPA")
print("$.OPA:", opa if isinstance(opa, Exception) else json.loads(opa))

# `$this` is the location this run was handed — the slice the node's `scope`
# selected. With scope `$.tickets[*]` the node runs once per ticket and each
# run's `$this` is its own ticket, so the plugin never hardcodes an index.
who = await job.cmd_get_scope("$this.customer.id")
print("customer:", who if isinstance(who, Exception) else json.loads(who))
```

---

## Skill 10 — Write into the flow's context (inject results)

Commit data back into the context at a JSON path so **downstream nodes** can read
it:

```python
await job.cmd_set_on_path('$["doc appendix"]', {"itemXterm": [1, 3, 42, 2300]})
```

This is separate from `job.done(...)` output: `cmd_set_on_path` writes into shared
context mid-run; `done` emits the node's own result.

The path may start at `$this` to write relative to the node's own location —
`await job.cmd_set_on_path("$this.verdict", …)` lands inside whichever slice this
run was handed, so the same plugin works wherever the designer points its `scope`.

### Also on `Job` — routing, service calls

Two more commands round out the `Job` surface:

```python
# Fire only the outbound branch(es) whose tags are named (see Action.outbound).
await job.cmd_next_filter(["approved"])

# Call a downstream service mid-job; resolves to its reply bytes (or an Exception).
reply = await job.cmd_svc_call("some.service", {"q": "term"}, {"op": "search"})
```

Declare the branches at design time so the canvas can draw them, then name their
tags at runtime:

```python
from inflow_plugin_sdk import OutboundPort

p.add_action(Action(
    method="review",
    outbound=[
        OutboundPort(title="Approved", tags=["approved"]),
        OutboundPort(title="Rejected", tags=["rejected"], description="needs rework"),
    ],
    request_handler=review,
))
```

Note that failing does **not** stop the flow — downstream nodes still run. A
terminal command's details are what commit onto the node's scope, and a bare
`done_with_error` sends none, so reach for `done_with_error_data` (Skill 7) whenever
the node had persisted state it must not drop.

---

## Skill 11 — Require settings (onboarding form)

For config the plugin needs before any action runs (credentials, a base URL),
register a settings form plus a submit handler:

```python
from inflow_plugin_sdk import Response, Settings


def submit(r):
    # validate / persist r.data; return feedback (sync or async, both work)
    return Response(data={"ok": True})


p.required_params(Settings(
    jsonschema=settings_schema,
    jsonui=settings_ui,
    # submit_to defaults to "_settings.config.submit" if left blank
    submit_handler=submit,
))
```

`formkit` builds the same thing in one call —
`formkit.form("Setup").add(...).settings(submit)` returns the `Settings`.

> **Note:** the submit handler is a **validator, not a store** — the platform owns
> the values. For helpers a form calls while it is still being filled in
> (connection tests, lookups, fields that depend on another field), register **meta
> functions** with `p.add_meta(Meta(method=..., request_handler=...))` before
> `start()`; each is served on `inflow.v1.<PLUGIN_ID>.<method>` and its return value
> is marshalled verbatim (handlers may be sync or async).
>
> A meta call arrives **flat** — form fields, `settings` and `value` at the top
> level, *not* in the `{_registry, body}` action envelope — so `cast_request_to` is
> the wrong tool here; `json.loads(r.data)` and read what you need. Answer with the
> **patch object** (`{"issueKey": key}`), not a `Response`. There is no error
> channel in the transport, so say what happened under the reserved
> `x-inflow-notif` key, which `formkit` attaches for you:
>
> ```python
> return formkit.success("Issue: %s", key).patch({"issueKey": key})
> return formkit.failure("cannot reach %s: %s", site, err).patch(None)  # message only
> ```
>
> `formkit.info` / `success` / `warning` / `failure` / `help` are the five
> severities; `.about(field)` re-aims a message and `.patch(None)` is a valid answer
> on its own (a connection test writes nothing). Several candidates go back through
> `formkit.choose(...)` / `picker(...)`. Don't model this as a readonly status field
> — a message is not form data. See
> [form-builder.md](https://github.com/Inflowenger/go-plugin-sdk/blob/main/docs/form-builder.md).

---

## Skill 12 — Stop a job when its flow is stopped (signals + `jobstop`)

The runtime broadcasts on `inflow.plugin.<PLUGIN_ID>.proc` every time a plugin node
process ends — with the `job_id` and a conclusion (`done`, `flow_stop_by_user`,
`timeout`, …). `p.on_signal` subscribes to that port (`inflow.plugin.<PLUGIN_ID>.>`,
so future signal kinds reach the same handler); call it **before `start()`**.

```python
p.on_signal(lambda sig: print(f"job {sig.job_id} ended: {sig.conclusion}"))
```

**Skip this skill unless you need it.** A stopped or timed-out process does *not*
stop the job you accepted, by design: the next run of that node may build on the
progress this one made — the runtime hands the previous `jobId` back in `_registry`.
Only reach for it when the work itself must die with the process: an open stream, a
paid upstream call, a held lock.

The working pattern is to file the cancel under the `job_id` and let the signal find
it. `jobstop` is that, as a capability you add to the actions that need it — a
middleware on the action, a signal handler on the port:

```python
from inflow_plugin_sdk import Action, Job, jobstop

stops = jobstop.Registry()        # one per plugin
p.on_signal(stops.on_signal)      # before start()


async def long_export(job: Job) -> None:
    ctx = job.context()                       # ends when the flow is stopped
    try:
        rows = await ctx.run(fetch_everything())   # the awaited work is cancelled with it
    except jobstop.JobStopped:
        return                                # the runtime is gone: do NOT report
    except Exception as e:
        await job.done_with_error(str(e))
        return
    await job.done({"rows": rows})


p.add_action(Action(
    method="long.export",
    middleware=[stops.middleware],            # only on actions that stop with the flow
    request_handler=long_export,
))
```

Middleware runs before the runtime is told the jobId, so a stop can never arrive for
a job not yet filed. A middleware is a plain function —
`(ctx: JobContext, job: Job) -> JobContext | None` — so your own capabilities (a
long-running job kept in your own dict, a trace) are middleware too, listed in order:
`middleware=use(trace, stops.middleware)` on an action, `p.use(trace)` on every
action, `chain_signals(stops.on_signal, yours)` on the port. An exception from one
rejects the request.

`job.context()` is a `JobContext` — the Python stand-in for Go's `context.Context`:

| What you want | Call |
|---|---|
| Abandon an awaited call when the job is stopped | `await ctx.run(coro)` — raises the cause |
| Ask whether the job was cut short, and why | `ctx.canceled` · `ctx.cause` (e.g. `jobstop.ErrStopped`) |
| Poll without pinning a stopped job | `await ctx.sleep(2)` → `False` if it ended |
| Wait for the stop itself | `await ctx.wait_canceled()` |
| Clean up however the job ends | `ctx.on_done(lambda cause: …)` |
| Carry a value down the chain | `ctx.with_value(k, v)` / `ctx.value(k)` |
| Keep work alive past the handler | `ctx.without_cancel()` |
| Put a deadline on one step | `ctx, cancel = ctx.with_timeout(5)` |

`ctx.run` is the Python answer to Go's "pass ctx down": a Python library takes no
context, so `run` puts the awaitable in a task and cancels *that* when the job is
stopped. A polling loop uses `sleep` instead:

```python
async def observe(job: Job) -> None:
    ctx = job.context()
    while True:
        status = await poll()
        if status.done:
            break
        await job.progress(status.percent, Frame(title="Upstream", content=status.stage))
        if not await ctx.sleep(2):   # False ⇒ the flow was stopped
            return                   # wind down quietly; do not report
    await job.done({"result": status.result})
```

Gotchas:

- Cancellation is **per `job_id`**. One subject carries every signal of the plugin, so
  a process hears the endings of other flows' jobs (and other replicas'); those find
  nothing filed and do nothing.
- Signals arrive on **success too** — `stops.on_signal` filters on
  `canceled(sig.conclusion)`; a handler of your own should too.
- When a stop lands the runtime has already stopped listening to that job, so a
  stopped handler's `progress`/`done` will find no responder. Wind down quietly.
- **A cancellation raises.** `ctx.run` raises `jobstop.JobStopped` out of the handler.
  The SDK will not report a handler that raises while its context is already cancelled
  (it logs instead), but catch it yourself where you have cleanup to do.
- Handlers run in their own task (Go's "own goroutine"), so a slow one does not stall
  the port and an exception inside one is caught and logged; only the last one
  registered is kept — compose several with `chain_signals`.
- Registering your own handler replaces the logging `p.on_signal()` gives you. Chain
  `log_signals("<plugin>")` to keep a line per signal that arrives:
  `p.on_signal(chain_signals(log_signals("my-plugin"), stops.on_signal))`. `jobstop`
  logs the other half — the job it actually cancelled — so a signal with no cancel line
  beside it was not about work this process is running.
- `stops.cancel_all()` cancels every job the registry holds (cause
  `jobstop.ErrShutdown`), for a plugin about to exit. It sends nothing to the runtime.

Full treatment:
[jobs-and-commands.md § Signals](https://github.com/Inflowenger/go-plugin-sdk/blob/main/docs/jobs-and-commands.md#signals--when-the-runtime-ends-a-process).

---

## Skill 13 — Run the job under an external service's id (advanced)

When your plugin is a **middleman** for a service that names work itself — Joern's
HTTP server answering `POST /query` with `{"queryId":"q-8f21"}`, a render farm, a
scan — do not keep a `dict[plugin_job_id, upstream_id]`. Register the work in a
middleware function and bind what came back as the job's id: middleware runs **before**
the job is accepted, so the id you bind is the id the runtime is told.

Why the dict is the wrong answer, briefly: it has a window where the job is accepted
but not yet mapped (a stop then finds nothing); it dies with the process, so a
redeploy orphans every upstream query; and signals are broadcast to **every** replica,
so the process that hears the stop is usually not the one holding the entry. One
shared name removes all three.

```python
from inflow_plugin_sdk import Job, JobContext, cast_request_to, use, with_job_id_context


async def register_query(ctx: JobContext, job: Job) -> JobContext:
    body = cast_request_to(job.req.data)        # raises ⇒ the request is rejected
    # Re-running? The previous jobId IS the upstream id — reattach, don't duplicate.
    prev = (body.registry or {}).get("jobId")
    if prev and await joern.alive(prev):
        return with_job_id_context(ctx, prev)

    query_id = await joern.register(body.body["project"], body.body["query"])
    if len(query_id) < 10:                      # see the gotchas
        await joern.cancel(query_id)            # never accepted: undo it
        raise ValueError(f"jobId {query_id} from joern is shorter than 10 characters")
    return with_job_id_context(ctx, query_id)


p.on_signal(chain_signals(stops.on_signal, abort_upstream))
p.add_action(Action(
    method="cpg.query",
    middleware=use(register_query, stops.middleware),   # namer FIRST
    request_handler=query_handler,
))
```

From then on one name serves both systems: `job.job_id`, every command subject
(`inflow.cpu.<id>.q-8f21.progress`), the stop signal's `job_id`, and the next run's
`_registry["jobId"]`. Cancellation needs no local lookup at all —

```python
async def abort_upstream(sig: Signal) -> None:
    if sig.kind != PluginSignal.PROC or not canceled(sig.conclusion):
        return
    await joern.cancel(sig.job_id)   # sig.job_id IS the queryId
```

— so any replica that hears the stop can abort the query, which a process-local dict
could never do.

Gotchas:

- **Name the job first.** `stops.middleware` (and anything else keyed on the jobId)
  files under `job.job_id` *as of when it runs*; placed before the namer it files a
  uuid nothing will look up, and the stop is lost.
- **Validate the id you adopt.** It must be **at least 10 characters** —
  fractal-core refuses a shorter `jobId` with `init failed. invalid job ID` — a usable
  NATS subject token (no `.`, space, `*`, `>`, since the command subjects are built
  from it), and unique plugin-wide (prefix per-project counters).
- **Register fast.** The runtime is waiting for the jobId while middleware runs — one
  timeout-bounded call, never the work itself. 15 seconds is the whole budget.
- **Reject vs fail**: an exception from middleware means the node never ran (the
  runtime gets the error, not a failed job). When the flow should *see* a failed node,
  accept and use `job.done_with_error`.
- **Undo what you enlisted.** If a later function rejects, the job's context ends —
  register the compensation with
  `ctx.on_done(lambda _cause: asyncio.ensure_future(joern.cancel(query_id)))` (a
  coroutine function passed to `on_done` is scheduled for you) and it runs without any
  special casing.
- If the service accepts a **client-supplied** id instead, do the mirror image: keep
  the SDK's uuid and send `job.job_id` upstream — same single name, and the
  registration becomes idempotent by construction.

What it buys, stated as invariants: accepted ⇒ enlisted (the namer ran first);
enlisted ⇒ nameable (the id came from the service, so it survives a restart);
rejected ⇒ compensated or never enlisted; any stop is actionable by any replica; and
a crash is recoverable, because the id lives in the flow's own `_registry` rather than
in this process's memory.

Full treatment, with the distributed-transaction model and the failure modes:
[external-job-identity.md](https://github.com/Inflowenger/go-plugin-sdk/blob/main/docs/external-job-identity.md).

---

## Skill 14 — Report and observe instead of waiting (advanced)

Work that takes hours does not fit in a job. Three budgets say so: the runtime waits
**15s** for your `jobId`, gives up on a job that sends no command for the node's
`idle_min`, and ends the run at `ExecuteTimeOut`. So do not wait — **report where the
work has got to, route a "not yet" port, and end the job in seconds.** The flow's
process finishes; the external work doesn't; a later run of the same node picks it up
through `_registry`.

```python
# Accept stage. Only two inputs exist here: body, and _registry — the node's memory of
# its own previous run (job commands need a jobId, which this decides).
async def attach_or_start(ctx: JobContext, job: Job) -> JobContext:
    body = cast_request_to(job.req.data)
    prev = (body.registry or {}).get("jobId")
    if prev and await joern.has(prev):
        return with_job_id_context(ctx, prev)       # observe what the last run started
    query_id = await joern.register(body.body["project"], body.body["query"])
    return with_job_id_context(ctx, query_id)       # start new work


async def observe(job: Job) -> None:
    status = await joern.poll(job.job_id)           # job.job_id IS the upstream id
    if status.failed:
        await job.cmd_next_filter(["_exception"])   # fail AND route
        await job.done_with_error_data(status.error, {"queryId": job.job_id}, "joern")
    elif not status.done:
        await job.cmd_next_filter(["pending"])      # a SUCCESSFUL "not yet"
        await job.done({"state": "running", "percent": status.percent}, "joern")
    else:
        await joern.release(job.job_id)
        await job.cmd_next_filter(["ready"])
        await job.done({"state": "done", "result": status.result}, "joern")
```

Declare the ports so the canvas shows them before anything runs:

```python
Action(
    method="cpg.query.observe",
    middleware=[attach_or_start],   # deliberately no stops.middleware — see below
    request_handler=observe,
    outbound=[
        OutboundPort(title="Still running", tags=["pending"]),
        OutboundPort(title="Result ready", tags=["ready"]),
        OutboundPort(title="Query failed", tags=["_exception"]),
    ],
)
```

Then the flow closes the loop: the `pending` branch ends in a delay/Continue After
node, a schedule re-runs it, or a loop edge returns to the node — all of which must
re-enter **over the same context document**, because `_registry` is the node's entry
in that document.

Gotchas:

- **"Still running" is `done`, not an error.** The job did look; the answer is "not
  yet". `done_with_error` there would route the flow's error branch for a perfectly
  healthy query.
- **Commit, don't just report.** `job.done(data, "joern")` commits at that key — a
  bare `done` with no key commits nothing, so the next run (and the next node) sees an
  empty scope.
- **`_registry` is per call site and lives in the context document.** Two `GoTo`s onto
  the same sub-flow keep separate memories; a run over a *new* context starts fresh
  and will correctly start new upstream work.
- **`doneAt` / `conclusion` describe the run, not the work.** A "pending" run ends
  `done`. Only the service knows the work's state. `reqAt` is the useful one — it
  dates the handle, so you can give up on a stale one.
- **No `stops.middleware` on an observer action.** Outliving the flow is the point; a
  stop should not abort the upstream work unless an abandoned job genuinely costs you
  (then abort it from the signal handler by `sig.job_id`).
- **Handle the stale handle.** If the service has forgotten the id, start fresh rather
  than reporting `pending` forever against a query that no longer exists.
- **Give the loop a floor** — an attempt counter in a contract, or a `reqAt` age limit
  in the plugin. An observer with no stopping rule is an infinite flow.
- **Polling costs one job per re-entry.** A one-minute loop over a six-hour build is
  360 runs. Match the cadence to the work; sub-minute observation belongs inside a
  single streaming job.

Full treatment, with the three budgets, the registry fields and the limits:
[detached-work.md](https://github.com/Inflowenger/go-plugin-sdk/blob/main/docs/detached-work.md).

---

## Recipe A — An adapter action (external I/O)

The canonical shape: input → progress → external work → shaped output. (This is the
`HTTP.CALL` sample, condensed — see `examples/http_call.py`.)

```python
import json
import urllib.request


async def http_call(job: Job) -> None:
    try:
        req = cast_request_to(job.req.data)
    except Exception as e:
        await job.done_with_error(str(e))
        return

    body = req.body or {}
    await job.progress(20, Frame(title="working", content=body.get("url", "")))

    try:
        data = json.dumps(body["body"]).encode() if body.get("body") else None
        request = urllib.request.Request(
            body["url"],
            data=data,
            method=body.get("method", "GET"),
            headers={"Content-Type": "application/json", **(body.get("headers") or {})},
        )
        with urllib.request.urlopen(request) as resp:
            raw = resp.read().decode()
        try:
            out = json.loads(raw)
        except Exception:
            out = {"rawBody": raw}      # fall back to raw if not JSON
        await job.done(out)
    except Exception as e:
        await job.done_with_error(str(e))


p.add_action(Action(method="http.call", request_handler=http_call))
```

> Blocking calls belong in a thread, not on the loop: wrap them in
> `await asyncio.to_thread(...)` (or use `aiohttp` / `httpx`) so one slow request
> cannot stall the whole plugin. This is the Python counterpart of Go's
> "keep shared state concurrency-safe".

## Recipe B — A pure context/transform action (no I/O)

The minimal functional node — read context, compute, write, done. (This is the `RPC`
sample — see `examples/rpc.py`.)

```python
async def fn(job: Job) -> None:
    opa = await job.cmd_get_scope("$.OPA")
    print("$.OPA:", opa if isinstance(opa, Exception) else json.loads(opa))
    await job.cmd_set_on_path('$["result"]', {"computed": 42})
    await job.done({"action": "done"})


p.add_action(Action(method="fn", request_handler=fn))
```

## Recipe C — A long-running / event plugin

Because the plugin is a persistent process, an action can kick off background work,
or the plugin can hold connections and run loops between requests. Keep any shared
state on your own objects and guard it; each `request_handler` runs per invocation.
This is the plugin shape most likely to want
[Skill 12](#skill-12--stop-a-job-when-its-flow-is-stopped-signals--jobstop): background
work that should be torn down when the process that started it is stopped. If the work
is measured in hours rather than minutes, it wants
[Skill 14](#skill-14--report-and-observe-instead-of-waiting-advanced) instead — report
and end, rather than hold a job open.

```python
async def main() -> None:
    p = await new_plugin(with_dot_env(".env.inflow"))
    p.intro(PluginIntro(name="QUEUE.WATCH", author="you", version="v0.0.1"))

    # e.g. open a DB/queue connection once, reuse across handlers
    # conn = await connect_to_queue()

    async def enqueue(job: Job) -> None:
        # use conn ...
        await job.done({"queued": True})

    p.add_action(Action(method="enqueue", request_handler=enqueue))

    await p.start()
    await asyncio.Event().wait()
```

> Handlers run in **detached asyncio tasks** — the SDK acks the `jobId` on the
> dispatch coroutine and runs your handler separately, because `nats-py` delivers a
> subscription's messages serially and every call to one action shares the subject
> `inflow.cpu.<PLUGIN_ID>.<method>`. Awaiting a long handler inline would
> head-of-line-block concurrent calls to the same action (parallel flow branches are
> exactly this) until the runtime abandoned them with "timeout exceeded". So, as in
> Go, do not assume handlers are serialized: guard shared mutable state yourself.

---

## Run & iterate locally

1. Point `.env.inflow` at your running Infra (`PLUGIN_ID` / `INFRA_CRED` / `INFRA_URL`).
2. `python your_plugin.py` — or try the bundled samples, `python examples/rpc.py`
   and `python examples/http_call.py`.
3. On startup the SDK logs each subscribed subject (form/action/job/meta) — that
   confirms the plugin registered.
4. Add your node to a flow in the inspector panel, run the flow, watch progress
   frames and output appear.

Working *on* the SDK itself? `pip install -e ".[dev]"` and run `pytest`.

---

## Ship checklist

- [ ] Plugin is defined in a space; `PLUGIN_ID` / `INFRA_CRED` / `INFRA_URL` set.
- [ ] The entry point blocks after `start()` (`await asyncio.Event().wait()`).
- [ ] Every action has a unique `method` and a `request_handler`.
- [ ] Every handler ends in exactly one `done` / `done_with_error` on all paths.
- [ ] Each action's `jsonschema` matches the keys the handler reads.
- [ ] Every context/finish call is `await`ed.
- [ ] Context reads are checked with `isinstance(res, Exception)` before parsing.
- [ ] Blocking I/O is off the event loop (`asyncio.to_thread` or an async client).
- [ ] Long-running/shared state is concurrency-safe.
- [ ] Errors are surfaced via `done_with_error`, not just logged.
- [ ] If any action must stop with its flow: `middleware=[stops.middleware]` on it,
      `p.on_signal(stops.on_signal)` before `start()`, and the handler returns on
      `ctx.canceled` (or catches `jobstop.JobStopped`) without reporting.
- [ ] If a middleware function names the job from an upstream service, it comes
      **first** in the list and validates the id (≥ 10 chars, subject-safe).
