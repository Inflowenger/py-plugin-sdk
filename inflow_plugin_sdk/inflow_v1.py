# Subject wiring: intro / settings / actions / forms / meta. Mirrors sdkv1/inflowV1.go.
from __future__ import annotations

import asyncio
import inspect
import uuid

import json

from .models import Request, Signal, marshal
from .req import ActionRequest, with_job_handler


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
                if action.request_handler is None:
                    print(f"recv new request message on action {action.method}")
                    return
                job_id = str(uuid.uuid4())
                new_req = ActionRequest(job_id, action.method, _req_from(p, msg))
                try:
                    await with_job_handler(action.request_handler, p.jobs)(new_req, msg)
                except Exception as e:
                    # Handler errors are already reported to the runtime as
                    # DoneWithError inside with_job_handler. Reaching here means the
                    # accept/ack itself failed (no jobId assigned, nothing to report)
                    # — just log so the plugin keeps serving other requests.
                    print(f"action {action.method} accept error: {e}")

            return cpu_cb

        await conn.subscribe(make_action_cpu(p.plugin_id, action.method), cb=make_cpu_cb(action))
        print(f"Subscribed Action : {make_action_cpu(p.plugin_id, action.method)}")


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
