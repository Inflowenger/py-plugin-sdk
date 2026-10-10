# Subject wiring: intro / settings / actions / forms / meta. Mirrors sdkv1/inflowV1.go.
from __future__ import annotations

import asyncio
import inspect
import json

from .context import JobContext, background
from .job import Job
from .middleware import job_id_from_context
from .models import Action, Request, Signal, marshal
from .req import ActionRequest


# ---- subject makers -------------------------------------------------------


def make_action_subject(plugin_id: str, action: str) -> str:
    # inflow.v1.<PLUGIN_ID>.<action> — meta functions & settings submit.
    return f"inflow.v1.{plugin_id}.{action}"


def make_settings_subject(plugin_id: str) -> str:
    return f"inflow.v1.{plugin_id}.@settings"


def make_actions_list_subject(plugin_id: str) -> str:
    return f"inflow.v1.{plugin_id}.@actions"


def make_intro_subject(plugin_id: str) -> str:
    return f"inflow.v1.{plugin_id}.@intro"


def make_action_cpu(plugin_id: str, action: str) -> str:
    # inflow.cpu.<PLUGIN_ID>.<ACTION> — the runtime's execution call.
    return f"inflow.cpu.{plugin_id}.{action}"


def make_form_subject(plugin_id: str, action: str) -> str:
    return f"inflow.v1.{plugin_id}.{action}.@form"


def make_signal_subject(plugin_id: str) -> str:
    # inflow.plugin.<PLUGIN_ID>.> — the wildcard signal port (every signal kind).
    return f"inflow.plugin.{plugin_id}.>"


# ---- handlers -------------------------------------------------------------


def _req_from(p, msg) -> Request:
    return Request(data=msg.data, header=msg.headers, plugin=p)


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def intro_handler(p) -> None:
    conn = p.infra_conn.get_connection()
    if conn is None:
        raise RuntimeError("connection error occurred")

    async def cb(msg):
        try:
            intro_byte = p.intro_payload()
        except Exception as e:
            print(f"intro: marshal failed: {e}")
            return
        await msg.respond(intro_byte)

    await conn.subscribe(make_intro_subject(p.plugin_id), cb=cb)
    print(f"Intro Subscribed on : {make_intro_subject(p.plugin_id)}")


async def settings_handler(p) -> None:
    conn = p.infra_conn.get_connection()
    if conn is None:
        raise RuntimeError("connection error occurred")

    async def cb(msg):
        print("Settings Called")
        try:
            settings_byte = p.settings_payload()
        except Exception as e:
            print(f"settings: marshal failed: {e}")
            return
        await msg.respond(settings_byte)

    await conn.subscribe(make_settings_subject(p.plugin_id), cb=cb)
    print(f"Settings Subscribed on : {make_settings_subject(p.plugin_id)}")

    # settings submit handler
    if p.settings_data is not None:
        if p.settings_data.submit_to.strip() == "":
            p.settings_data.submit_to = "_settings.config.submit"

        async def submit_cb(msg):
            if p.settings_data.submit_handler is None:
                await msg.respond(b'{"status":"not implemented"}')
                return
            try:
                res = await _maybe_await(p.settings_data.submit_handler(_req_from(p, msg)))
                await msg.respond(marshal(res))
            except Exception as e:
                print(e)
                await msg.respond(b'{"error":"error occurred in marshal response"}')

        await conn.subscribe(make_action_subject(p.plugin_id, p.settings_data.submit_to), cb=submit_cb)


async def actions_handler(p) -> None:
    conn = p.infra_conn.get_connection()
    if conn is None:
        print("connection error occurred")
        return

    async def list_cb(msg):
        try:
            list_bytes = marshal(p.actions)
        except Exception as e:
            print(f"Failed to marshal actions: {e}")
            return
        await msg.respond(list_bytes)

    await conn.subscribe(make_actions_list_subject(p.plugin_id), cb=list_cb)

    for action in p.actions:

        def make_form_cb(action):
            async def form_cb(msg):
                try:
                    form_body = marshal(action.form)
                except Exception as e:
                    print("action form ", action.title, " error:", e)
                    return
                await msg.respond(form_body)

            return form_cb

        await conn.subscribe(make_form_subject(p.plugin_id, action.method), cb=make_form_cb(action))
        print(f"Form Builder Service : {make_form_subject(p.plugin_id, action.method)}")

        def make_cpu_cb(action):
            async def cpu_cb(msg):
                await dispatch_action(p, action, msg)

            return cpu_cb

        await conn.subscribe(make_action_cpu(p.plugin_id, action.method), cb=make_cpu_cb(action))
        print(f"Subscribed Action : {make_action_cpu(p.plugin_id, action.method)}")


async def dispatch_action(p, action: Action, msg) -> None:
    """Start one execution request's pipeline on a task of its own, so neither
    its middleware nor its handler holds up the requests behind it on the
    subscription.

    nats-py delivers one subscription's messages serially — it awaits each
    callback before pulling the next — and every call to an action shares the
    subject inflow.cpu.<PLUGIN_ID>.<method>. Running the pipeline inline would
    therefore head-of-line-block every concurrent call to the same action (a
    parallel flow branch is exactly this). Mirrors Go's dispatchAction, where the
    same job is done by `go`."""
    if action.request_handler is None:
        # Say so, rather than leave the runtime waiting out its 15s accept budget
        # for a jobId that is never coming. Mirrors Go.
        await ActionRequest("", action.method, _req_from(p, msg)).reject(
            msg, '{"error":"action not implemented"}'
        )
        print(f"recv new request message on action {action.method}: no request_handler")
        return
    task = asyncio.create_task(run_pipeline(p, action, _req_from(p, msg), msg))
    # asyncio only keeps a weak reference to a bare task; hold a strong one on
    # the plugin so the loop cannot collect it mid-flight.
    p.jobs.add(task)
    task.add_done_callback(p.jobs.discard)


async def run_pipeline(p, action: Action, req: Request, msg) -> None:
    """Run a request's middleware functions in order (Plugin.pipeline), then
    accept the job — reply the jobId — and run the handler. The job's context
    begins here and ends when this returns: once the handler has, or as soon as
    the request is rejected. Mirrors Go's runPipeline."""
    ctx, end = background().with_cancel()
    try:
        try:
            accepted, job = await run_middleware(p, action, ctx, Job(p, action.method, "", req))
        except Exception as e:
            await reject_request(p, action, msg, e)
            return

        live = (await ActionRequest(job.job_id, job.action, job.req).accept(msg)).with_context(
            accepted
        )
        try:
            result = action.request_handler(live)
            if inspect.isawaitable(result):
                await result
        except Exception as e:
            if accepted.canceled:
                # The job was stopped: ctx.run / an aborted client raised its way
                # out of the handler. The runtime has already concluded this job
                # and stopped listening, so reporting would only retry against a
                # subject with no responder. (In Go a cancellation is a returned
                # error the handler inspects, so this path cannot arise there.)
                print(f"job {live.job_id} ended by cancellation: {e}")
                return
            # Accepted: the runtime is waiting on the job, so an exception is its
            # failure — never swallowed, or the runtime hangs waiting for a
            # result that never comes. (done_with_error goes through Plugin.send,
            # which reports rather than raises, so this cannot itself crash the
            # plugin.)
            await live.done_with_error(str(e))
    finally:
        end()


async def run_middleware(
    p, action: Action, ctx: JobContext, job: Job
) -> tuple[JobContext, Job]:
    """Run the request's middleware functions in order, each on the context the
    one before returned, keeping Job.job_id in step with the jobId bound to the
    context. The first exception stops it, and so does a job no function named.
    Mirrors Go's runMiddleware."""
    for fn in p.pipeline(action):
        nxt = fn(ctx, job)
        if inspect.isawaitable(nxt):
            nxt = await nxt
        if nxt is not None:
            ctx = nxt
        bound = job_id_from_context(ctx)
        if bound != "" and bound != job.job_id:
            job = job.with_job_id(bound)
    if job.job_id == "":
        raise ValueError(
            "no jobId: the first middleware function (job_id, or with_job_id's) bound none"
        )
    return ctx, job


async def reject_request(p, action: Action, msg, err: BaseException) -> None:
    """Answer a request with an error instead of a jobId. Mirrors Go's
    rejectRequest."""
    reason = str(err) or err.__class__.__name__
    print(f"action {action.method} rejected: {reason}")
    await ActionRequest("", action.method, _req_from(p, msg)).reject(
        msg, json.dumps({"error": reason}, separators=(",", ":"))
    )


async def meta_func_handler(p) -> None:
    conn = p.infra_conn.get_connection()
    if conn is None:
        print("connection error occurred")
        return

    for meta in p.meta_fn:

        def make_cb(meta):
            async def cb(msg):
                try:
                    res = await _maybe_await(meta.request_handler(_req_from(p, msg)))
                    await msg.respond(marshal(res))
                except Exception as e:
                    print(e)
                    await msg.respond(b'{"error":"error occurred in marshal response"}')

            return cb

        await conn.subscribe(make_action_subject(p.plugin_id, meta.method), cb=make_cb(meta))
        print(f"Meta Function Service : {make_action_subject(p.plugin_id, meta.method)}")


def signal_port_note(p) -> str:
    """What start() logs when no on_signal handler is registered. The port then
    has no subscription, so no signal reaches the plugin — harmless for most
    plugins, but a stop capability added as middleware (jobstop's) then silently
    never fires. Naming where middleware is added points at the likely victims.
    Mirrors Go's signalPortNote."""
    note = (
        f"Signals not subscribed on : {make_signal_subject(p.plugin_id)} "
        "(no on_signal handler registered: no stop will reach any job)"
    )
    if p.middlewares:
        note += "; plugin middleware is set"
    with_middleware = [a.method for a in p.actions if a.middleware]
    if with_middleware:
        note += "; actions with middleware: " + ", ".join(with_middleware)
    return note


def parse_signal(plugin_id: str, msg) -> Signal:
    """Turn a raw signal message into a Signal: `kind` is whatever the subject
    carries past the plugin's prefix, and a payload that parses as the runtime's
    `{conclusion, jobId}` body fills the typed fields. A payload that does not parse
    is not an error — an unmodelled future kind still reaches the handler with its
    bytes intact. Mirrors Go's parseSignal."""
    prefix = f"inflow.plugin.{plugin_id}."
    sig = Signal(
        kind=msg.subject[len(prefix):] if msg.subject.startswith(prefix) else msg.subject,
        subject=msg.subject,
        data=msg.data,
        msg=msg,
    )
    try:
        body = json.loads(msg.data.decode())
    except Exception:
        return sig  # an unmodelled kind: leave the typed fields empty, keep data
    if isinstance(body, dict):
        sig.job_id = body.get("jobId") or ""
        sig.conclusion = body.get("conclusion") or ""
    return sig


async def signals_handler(p) -> None:
    """Subscribe the registered signal handler (Plugin.on_signal) to the whole signal
    port, `inflow.plugin.<PLUGIN_ID>.>`. A plugin that never called on_signal
    subscribes to nothing — the port is opt-in. Mirrors Go's signalsHandler."""
    handler = p.signal_fn
    if handler is None:
        print(signal_port_note(p))
        return
    conn = p.infra_conn.get_connection()
    if conn is None:
        raise RuntimeError("connection error occurred")

    async def cb(msg):
        sig = parse_signal(p.plugin_id, msg)

        async def body():
            try:
                await _maybe_await(handler(sig))
            except Exception as e:
                # nats-py delivers one subscription's messages serially, so a slow
                # handler (closing a stream, aborting an upstream call) would stall
                # the signals behind it — hence the detached task — and an escaping
                # exception must not kill the subscription.
                print(f"signal handler failed on {sig.subject}: {e}")

        task = asyncio.create_task(body())
        # asyncio only keeps a weak reference to a bare task; hold a strong one on
        # the plugin so the loop cannot collect it mid-flight.
        p.jobs.add(task)
        task.add_done_callback(p.jobs.discard)

    await conn.subscribe(make_signal_subject(p.plugin_id), cb=cb)
    print(f"Signals Subscribed on : {make_signal_subject(p.plugin_id)}")
