# Subject wiring: intro / settings / actions / forms / meta. Mirrors sdkv1/inflowV1.go.
from __future__ import annotations

import inspect
import uuid

from .models import Request, marshal
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
                    await with_job_handler(action.request_handler)(new_req, msg)
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
