# The Plugin type, construction, options, and NATS send. Mirrors sdkv1/plugin.go.
from __future__ import annotations

import asyncio
import inspect
import os
from typing import Optional

from nats.aio.msg import Msg
from nats.errors import NoRespondersError

from .env import get_env_var, load_env
from .inflow_v1 import actions_handler, intro_handler, meta_func_handler, settings_handler
from .models import Action, Meta, PluginIntro, Settings, marshal
from .nats_box import NatsBox

# DefaultSendTimeout is the NATS request/reply deadline for send when the plugin
# author doesn't set one. A conservative 5s: fine for the fast RPCs (account
# list, settings test, a single email send). A plugin whose actions proxy slower
# upstream calls — a multi-message search, a large fetch — should raise it in
# code with with_timeout(), since the deadline must sit above whatever the
# backend needs to answer or the reply is abandoned mid-flight.
DEFAULT_SEND_TIMEOUT = 5.0  # seconds

# ReqTimeoutEnv is an env var, in SECONDS, that overrides the send timeout at
# deploy time — so an operator can widen it for a slow network (REQ_TIMEOUT=50)
# or tighten it, without touching code. Read in new_plugin AFTER the options run,
# so it wins over the developer's with_timeout.
REQ_TIMEOUT_ENV = "REQ_TIMEOUT"


class Plugin:
    def __init__(self):
        self.plugin_id: str = ""
        self.infra_conn: Optional[NatsBox] = None
        self.intro_data: PluginIntro = PluginIntro()
        self.settings_data: Optional[Settings] = None
        self.actions: list[Action] = []
        self.meta_fn: list[Meta] = []
        self.send_timeout: float = DEFAULT_SEND_TIMEOUT

    # ---- registration (call before start) ---------------------------------

    def intro(self, i: PluginIntro) -> None:
        self.intro_data = i

    def required_params(self, requirements: Settings) -> None:
        self.settings_data = requirements

    def add_action(self, *act: Action) -> None:
        self.actions.extend(act)

    def add_meta(self, *meta: Meta) -> None:
        """Register one or more meta methods (see the Meta type). Each is served as
        a synchronous RPC on inflow.v1.<PLUGIN_ID>.<Method>; call it before start."""
        self.meta_fn.extend(meta)

    # ---- payloads ---------------------------------------------------------

    def intro_payload(self) -> bytes:
        return marshal(self.intro_data)

    def settings_payload(self) -> bytes:
        # A plugin that requires nothing still answers, with an empty object: an
        # empty body is not JSON, so a caller could not tell "asks for nothing"
        # from "not running".
        if self.settings_data is None:
            return b"{}"
        return marshal(self.settings_data)

    # ---- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        """Wire up all subscriptions. Returns once subscribed — keep the process
        alive after (e.g. `await asyncio.Event().wait()`)."""
        await intro_handler(self)
        await settings_handler(self)
        await actions_handler(self)
        await meta_func_handler(self)

    def get_plugin_id(self) -> str:
        return self.plugin_id

    async def send(self, subject: str, data: bytes) -> tuple[Optional[Msg], Optional[Exception]]:
        """NATS request/reply with retry: send_timeout deadline (default 5s, set in
        code with with_timeout()), up to 5 attempts, backing off on "no responders".

        Mirrors Go's Send: it returns (msg, err) and never raises — a workflow the
        user has stopped leaves no responders, and raising here would surface as an
        unhandled exception that crashes the whole plugin."""
        conn = self.infra_conn.get_connection() if self.infra_conn else None
        if conn is None:
            print("connection error occurred")
            return None, Exception("connection error")
        timeout = self.send_timeout
        if timeout <= 0:
            timeout = DEFAULT_SEND_TIMEOUT
        for retry in range(5):
            try:
                msg = await conn.request(subject, data, timeout=timeout)
            except NoRespondersError:
                if retry > 2:
                    print(f"No responders - retry :{retry}")
                    print(f"No responders - body : {data.decode(errors='replace')}")
                await asyncio.sleep(retry + 1)
                continue
            except Exception as err:
                print("subs : ", subject)
                print("body : ", data.decode(errors="replace"))
                return None, err
            print(f"result of {subject}  :  {msg.data} ")
            return msg, None
        return None, Exception("exception occurred")


async def new_plugin(*opts) -> Plugin:
    """Construct a plugin from functional options. Mirrors Go's NewPlugin."""
    p = Plugin()
    for o in opts:
        result = o(p)
        if inspect.isawaitable(result):
            await result
    # Operator override, applied last so REQ_TIMEOUT beats the developer's
    # with_timeout. with_dot_env (if used) has already loaded the .env file.
    d = _req_timeout_env()
    if d is not None:
        p.send_timeout = d
    return p


def _req_timeout_env() -> Optional[float]:
    """Read REQ_TIMEOUT (seconds) into a duration, returning None when unset,
    blank, non-numeric, or non-positive (leaving the code/default)."""
    raw = os.environ.get(REQ_TIMEOUT_ENV)
    if raw is None or raw.strip() == "":
        return None
    try:
        seconds = int(raw)
    except ValueError:
        print(f"Invalid {REQ_TIMEOUT_ENV}={raw}, ignoring")
        return None
    if seconds <= 0:
        print(f"Invalid {REQ_TIMEOUT_ENV}={raw}, ignoring")
        return None
    return float(seconds)


def with_dot_env(env_file: str):
    """Load PLUGIN_ID / INFRA_CRED / INFRA_URL from a dotenv file and connect."""

    async def opt(p: Plugin) -> None:
        load_env(env_file)
        p.plugin_id = get_env_var("PLUGIN_ID")
        credential = get_env_var("INFRA_CRED")
        infra_url = get_env_var("INFRA_URL")
        p.infra_conn = await NatsBox.create(credential, infra_url)

    return opt


def with_plugin_id(plugin_id: str):
    """Set the plugin id explicitly."""

    def opt(p: Plugin) -> None:
        p.plugin_id = plugin_id

    return opt


def with_infra_connection(infra_url: str, credential: str):
    """Open the infra connection explicitly (url + base64 credential)."""

    async def opt(p: Plugin) -> None:
        p.infra_conn = await NatsBox.create(credential, infra_url)

    return opt


def with_timeout(seconds: int):
    """Set the NATS request/reply deadline for send, in SECONDS. Declare it where
    the plugin is constructed, e.g. new_plugin(with_dot_env(f), with_timeout(65)).
    Omit it to keep the default (5s). A non-positive value is ignored. The
    REQ_TIMEOUT env var, when set, overrides this at deploy time."""

    def opt(p: Plugin) -> None:
        if seconds > 0:
            p.send_timeout = float(seconds)

    return opt
