---
name: inflow-plugin-python
description: Build an Inflowenger Plugin node with the Python SDK (inflowenger-plugin-sdk / inflow_plugin_sdk). Use when the user asks to create, scaffold, or extend an inflow/Inflowenger plugin in Python — adding an action, parsing request input, reporting progress, reading/writing flow context, building the action's UI form, wiring settings, or reacting to a stopped/timed-out process. Not for extrinsic nodes (those belong to inflow-fusion), and not for the Go or Node SDKs (use inflow-plugin / inflow-plugin-node for those).
---

# Building an Inflowenger Plugin node (Python)

Instructions for writing a plugin with `inflow_plugin_sdk` (PyPI:
`inflowenger-plugin-sdk`), the Python port of the Go SDK. A plugin is a
long-running asyncio process that appears as a node on the Inflowenger workflow
canvas and is called by the Fractal runtime over NATS. The wire format is
identical across the three SDKs, so a Python plugin is interchangeable with a Go
or Node one from the runtime's point of view.

Fuller reference lives in the SDK repos (this skill is meant to be copied into a
consuming plugin project, so links point there rather than at local paths): this
repo's [`README.md`](https://github.com/Inflowenger/py-plugin-sdk/blob/main/README.md)
and the language-agnostic concept docs shared with the Go SDK under
[`docs/`](https://github.com/Inflowenger/go-plugin-sdk/tree/main/docs) —
notably
[`protocol-inflowv1.md`](https://github.com/Inflowenger/go-plugin-sdk/blob/main/docs/protocol-inflowv1.md),
[`jobs-and-commands.md`](https://github.com/Inflowenger/go-plugin-sdk/blob/main/docs/jobs-and-commands.md)
and
[`form-builder.md`](https://github.com/Inflowenger/go-plugin-sdk/blob/main/docs/form-builder.md).
Verify the current API against the installed `inflow_plugin_sdk` package before
relying on any signature; do not invent methods. Method names are the Go names in
`snake_case` (`Job.Done` → `job.done`, `CmdGetScope` → `job.cmd_get_scope`,
`NewPlugin` → `new_plugin`).

The **[plugin catalog](https://github.com/Inflowenger/plugin-catalog)** is the other live resource worth reading: it
carries the current developer knowledge base —
[`concepts.md`](https://github.com/Inflowenger/plugin-catalog/blob/main/docs/concepts.md) (the mental model),
[`build-a-plugin.md`](https://github.com/Inflowenger/plugin-catalog/blob/main/docs/build-a-plugin.md) (build from zero),
[`run-a-plugin.md`](https://github.com/Inflowenger/plugin-catalog/blob/main/docs/run-a-plugin.md),
[`dependent-fields.md`](https://github.com/Inflowenger/plugin-catalog/blob/main/docs/dependent-fields.md),
[`sdks.md`](https://github.com/Inflowenger/plugin-catalog/blob/main/docs/sdks.md) (the SDK matrix) and
[`publishing.md`](https://github.com/Inflowenger/plugin-catalog/blob/main/docs/publishing.md) — plus
[`plugins/`](https://github.com/Inflowenger/plugin-catalog/tree/main/plugins), an entry per shipped plugin pointing at its
real source. Those are the best worked examples available: in Python, [github-oc](https://github.com/FloMorphic/github-oc) (13 actions)
and [scrapli-plugin](https://github.com/Inflowenger/scrapli-plugin); the Go
plugins listed there are the fullest reference, since Go is the main stream. Prefer their
patterns over inventing your own, and check
[`plugins/index.json`](https://github.com/Inflowenger/plugin-catalog/blob/main/plugins/index.json) for the machine-readable
list.

## When to use

Use this when building or modifying an inflow **plugin** node in **Python**:
scaffolding a plugin, adding/editing an action, decoding request bodies, progress
reporting, flow-context read/write, routing outbound branches, calling downstream
services, meta functions, or action/settings forms.

Do **not** use this for **extrinsic** nodes (internal service calls via
inflow-fusion, a different repo), nor for the Go or Node SDKs.

## The non-negotiable rules (get these right)

1. **The entry point must stay alive after `start()`.** `await p.start()` only
   wires NATS subscriptions and returns. End `main` with
   `await asyncio.Event().wait()` or the process exits and the plugin dies. Run it
   under `asyncio.run(main())`.
2. **Every handler ends in exactly one `await job.done(...)` or
   `await job.done_with_error(...)` on every path.** On each error branch call
   `await job.done_with_error(str(e))` **and `return`**. Never finish twice or zero
   times. (The SDK's safety net reports an escaping exception as
   `done_with_error` so the runtime does not hang — rely on it for bugs, not as
   your error handling.)
3. **`await` every Job call.** `progress`, `done`, `done_with_error`, and all
   `cmd_*` methods are coroutines. Forgetting `await` drops the command.
4. **Decode input with `cast_request_to(job.req.data)`.** It unwraps the
   `{ _registry, body }` envelope into a `RequestBody` → `.body` (the user's form
   input) + `.registry` (runtime metadata, notably this node's previous run).
   Unlike Go it is **not generic**: `.body` is a plain `dict`/`Any`, so validate
   the keys you need yourself. It **raises** on invalid JSON — wrap it in
   `try/except` and call `done_with_error` on failure. Timestamps are seconds
   (`datetime.fromtimestamp(float(v))`).
5. **Keep each action's `jsonschema` in sync with the input you read.** The form
   defines the shape delivered as `body`. `jsonschema`/`jsonui` on `FormBuilder`
   are **JSON strings** (`json.dumps({...})`); `formkit` produces them for you.
6. **Provisioning is a prerequisite, not code.** The plugin must be defined in a
   space (a NATS account in Infra) to get `PLUGIN_ID`, `INFRA_CRED` (base64), and
   `INFRA_URL`. If missing, tell the user to provision; don't fabricate
   credentials.

## Procedure

1. **Confirm prerequisites**: `PLUGIN_ID`, `INFRA_CRED`, `INFRA_URL` (usually a
   `.env.inflow` — see `.env.inflow.example`), Python 3.11+ (the SDK uses
   `StrEnum`), and Infra + a Fractal running. Install with
   `pip install inflowenger-plugin-sdk` (pulls `nats-py` and `python-dotenv`).
2. **Scaffold `main`**:
   ```python
   import asyncio
   from inflow_plugin_sdk import Action, Frame, Job, PluginIntro, new_plugin, with_dot_env

   async def main() -> None:
       p = await new_plugin(with_dot_env(".env.inflow"))  # or with_infra_connection + with_plugin_id
       p.intro(PluginIntro(name="MY.PLUGIN", author="…", version="v0.0.1"))
       p.add_action(Action(method="do.thing", title="…", form=form, request_handler=handler))
       await p.start()
       await asyncio.Event().wait()   # keep the process alive to serve requests

   if __name__ == "__main__":
       asyncio.run(main())
   ```
3. **Write each `request_handler(job: Job)`** (an `async def`) using only these
   verified `Job` ops (all coroutines):
   - `cast_request_to(job.req.data)` — the input envelope (rule 4).
   - `job.progress(pct, Frame(title=…, content=…))` — advisory, 0–100; does not
     finish.
   - `job.done(data: dict, *key)` — success + output (finishes).
   - `job.done_with_error(error: str)` — failure (finishes); the reason goes on the
     command's own `error` field, never into `details`.
   - `job.done_with_error_code(code: int, error: str, data, *key)` — same, plus the
     plugin's own error number (pass `0` when it has none).
   - `job.done_with_error_data(error: str, data, *key)` — failure that keeps a
     payload/state alongside the reason (finishes).
   - `job.cmd_get_current_scope()` / `job.cmd_get_scope("$.path")` — read context;
     both resolve to raw reply `bytes` (`json.loads(res)` to use them).
   - `job.cmd_set_on_path("$.path", data: dict)` — write into flow context.
   - `job.cmd_next_filter(tags: list[str])` — fire only the outbound branch(es)
     with these tags (the runtime counterpart of the action's declared
     `outbound=[OutboundPort(...)]`).
   - `job.cmd_svc_call(action, data, op_data=None)` — ask the extrinsics service to
     run `action` (e.g. `add.db.record`) through the runtime (feeder pattern);
     `action` is required and is not a registered extrinsics subject. The call is
     origin-tagged `plugin:<node title>`; the service may refuse it if plugin calls
     aren't granted.
   - Any path above may start at `$this`, inflow's non-standard root for the
     location this run was handed (the slice the node's `scope` selected), e.g.
     `job.cmd_get_scope("$this.customer.id")`. Prefer it over a hardcoded index
     when the node's scope can select more than one location.
   - `Plugin.send` and the Job methods **return** their error rather than raising
     (Go's `(msg, err)` contract) — a stopped workflow leaves no NATS responder,
     and raising there would crash the plugin. So every op above resolves to
     either the reply `bytes` or an `Exception` **instance**: check with
     `isinstance(res, Exception)` before using a result you depend on; never
     `json.loads` it blind.
4. **Add forms** when the node needs configuration. Either hand-write JSON Forms —
   `FormBuilder(jsonschema=json.dumps(schema), jsonui=json.dumps(ui))` — or build
   both documents from one declaration with `formkit`:
   ```python
   from inflow_plugin_sdk import formkit

   form = formkit.form("Create issue").add(
       formkit.text("projectKey", "Project key").required()
           .lookup("jira.meta.project.resolve", "Find").picks("jira.issue.create"),
       formkit.text("summary", "Summary").required(),
       formkit.text_area("description", "Description"),
   ).build()
   ```
   Field constructors: `text`, `text_area`, `secret`, `integer`, `number`,
   `boolean`, `date`, `date_time`, `enum_`, `choice`, `list_`, `list_of`,
   `custom`. Plugin-level onboarding/config:
   `p.required_params(Settings(..., submit_handler=handler))` (or
   `formkit.form(...).settings(handler)`). An optional Markdown manual for the
   plugin's page goes on `PluginIntro(manual=…)`; a fenced ` ```inflow-meta `
   block naming a meta method becomes a Run button.
5. **Make dependent fields work.** Any field a user cannot type from memory (an
   `accountId`, a project key, an id valid only inside another selection) must not
   ship as a bare text input. Register a **meta function** and put a button on the
   control that calls it:
   ```python
   from inflow_plugin_sdk import Meta, Request

   p.add_meta(Meta(method="my.meta.users.resolve",
                   request_handler=resolve_user))   # before start(); sync or async
   ```
   Each is served on `inflow.v1.<PLUGIN_ID>.<method>`; the handler returns any
   JSON-able value, marshalled **verbatim** (a `Response`, a bare list, or a
   `formkit` patch/envelope). A form button — `formkit`'s `.lookup(fn, label)`, or
   a hand-written `x-inflow-ui` control — calls it and patches the answer back into
   the open form.

   Four rules, each of which fails **silently** if broken:
   - `action.name` in a hand-written control is always the literal `pluginFn`. It
     is the host's only action.
   - The request arrives **flat** (form fields + `settings` + `value` at the top
     level), *not* in the `{_registry, body}` action envelope — so
     `cast_request_to` yields nothing useful here. Decode `job.req.data` /
     `request.data` tolerantly with `json.loads`, trying `body` first and then the
     raw object.
   - Return the **patch object** (`{"assignee": "5b10…"}`), not a `Response` — the
     latter's `{data, error}` envelope gets patched in as fields called `data` and
     `error`. Patch keys are absolute leaf paths; patching a nested object replaces
     it wholesale.
   - **There is no error channel in the transport.** Say what happened under the
     reserved `x-inflow-notif` key (`formkit.NotifKey`), which the host lifts out
     of the answer and shows — or the button appears to do nothing. `formkit`
     builds it:
     ```python
     return formkit.success("Issue: %s", key).patch({"issueKey": key})
     return formkit.failure("cannot reach %s: %s", site, err).patch(None)  # message only
     ```
     `formkit.info` / `success` / `warning` / `failure` / `help` are the five
     severities; `.about(field)` re-aims a message, `.patch(None)` is a valid
     answer on its own (a connection test writes nothing). The message defaults to
     the field the button targets; a field some *other* control fills needs
     `.inline()` on it so the host has somewhere to put it. Several candidates go
     back through `formkit.choose(...)` / `picker(...)`. Do **not** add a readonly
     `lookupStatus`-style property for this — a message is not form data, and one
     declared as a field is sent to the service and stored with the rest.

   Full contract: the Go repo's `docs/form-builder.md` and the catalog's
   `dependent-fields.md` (that doc still describes the pre-`x-inflow-notif`
   status-field workaround; the notification channel above supersedes it).
6. **Only if in-flight work must stop with the process**, register a signal
   handler before `start()`:
   ```python
   from inflow_plugin_sdk import Signal, canceled

   inflight: dict[str, asyncio.Task] = {}

   def on_signal(sig: Signal) -> None:        # inflow.plugin.<PLUGIN_ID>.>
       if not canceled(sig.conclusion):       # done / next / failed: nothing to abort
           return
       task = inflight.pop(sig.job_id, None)  # sig.job_id == the job.job_id you were given
       if task is not None:
           task.cancel()

   p.on_signal(on_signal)                     # p.on_signal() alone just logs the port
   ```
   This is **optional and not the default**: a stopped process deliberately does
   not stop the job, because a later run of the node may build on its progress (the
   previous `jobId` comes back in `_registry`). Add it only for a stream to close,
   an upstream call to abort, a lock to release. Signals also arrive on success, so
   always filter on `sig.conclusion` (`canceled()` / `succeeded()` or the
   `Conclusion` enum); and once one lands, the runtime no longer answers that job's
   commands — wind the work down, do not try to `done` an abandoned job.
7. **Run**: `python your_plugin.py`. The SDK prints each subscribed subject on
   startup. Verify by adding the node to a flow and running it. The repo's own
   tests run with `pytest`; see `examples/rpc.py` and `examples/http_call.py`.

## Known limitations to respect

- A form action **cannot mutate the schema** from a patch — answers are patched
  into form *data* only, so you cannot populate a `<select>`'s `enum` at runtime
  from a lookup's answer. Model a picker as free text + a resolve button (scalar
  fields) or as an array field filled with a returned list (multi-value).
  `formkit.choices(...)` rewrites a schema property into a drop-down, but that is a
  *form* answer (`picker` / `choose`), not a data patch. Do not invent an
  options-loading API.
- Nothing fires automatically: no on-change, no debounce, no type-ahead. The user
  clicks. Label the button with what it does.
- Handlers run in detached asyncio tasks so one slow call cannot head-of-line-block
  concurrent calls to the same action; do not assume handlers are serialized.
- If asked about **extrinsic** nodes, redirect to inflow-fusion; not part of this
  SDK.

## Verify before finishing

- The code imports and runs: `python -c "import inflow_plugin_sdk"`, then the
  plugin starts and logs its subjects.
- `main` blocks after `start()`, under `asyncio.run`.
- Each action: unique `method`, a `request_handler`, exactly one finish per path,
  all Job calls `await`ed.
- Each `jsonschema` matches the input the handler reads.
- Every meta function is registered before `start()`, decodes a flat body, and
  returns a patch (not a `Response`) if a form button calls it.
- No fabricated SDK methods — every `Job`/`Plugin` call exists in the installed
  `inflow_plugin_sdk`.
