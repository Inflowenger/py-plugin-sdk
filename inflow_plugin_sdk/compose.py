# Composing signal handlers, and the one that just logs. Mirrors sdkv1/compose.go.
from __future__ import annotations

import inspect
from typing import Optional

from .models import Signal, SignalHandler
from .types import PluginSignal, canceled, succeeded


def chain_signals(*handlers: Optional[SignalHandler]) -> SignalHandler:
    """Compose signal handlers into one, so the plugin's single signal port
    (Plugin.on_signal) serves any number of them. Each handler sees every signal,
    in order, and an async one is awaited before the next runs. An exception in
    one is caught and logged, so it cannot keep the handlers after it — a
    cancellation, say — from seeing the signal. None entries are skipped.

        p.on_signal(chain_signals(stops.on_signal, audit))
    """
    chain = [h for h in handlers if h is not None]

    async def handler(sig: Signal) -> None:
        for fn in chain:
            try:
                result = fn(sig)
                if inspect.isawaitable(result):
                    await result
            except Exception as e:
                print(f"signal handler failed on {sig.subject}: {e}")

    return handler


def log_signals(prefix: str) -> SignalHandler:
    """A SignalHandler that prints one line per signal that lands on the plugin's
    signal port, so what the runtime published is visible in the plugin's log the
    moment it arrives. `prefix` names the plugin in the line (pass "" for none):

        ai-decision: signal proc job=<uuid> conclusion=flow_stop_by_user canceled=True succeeded=False

    It is read-only — acting on a conclusion is another handler's job — so it
    belongs beside the one that does, which is why Plugin.on_signal takes a
    single handler and this composes:

        p.on_signal(chain_signals(log_signals("ai-decision"), stops.on_signal))

    Registering a cancellation handler alone replaces the default handler
    on_signal() installs, and with it the only sight of the port; chain this to
    keep it.

    This is the signal ARRIVING, which is not the same event as a job being cut
    short: jobstop.Registry.on_signal logs that separately, for the jobs it
    holds. The two lines together read as the whole story — what the runtime
    said, and what this process did about it — and a signal with no cancel line
    was for a job this process is not running, or concluded a job that was
    already done.

    Note what a logged jobId does NOT mean. The runtime publishes process signals
    on ONE subject per plugin, so every process of a plugin sees every one of
    that plugin's signals: jobs of other flows running at the same time, and,
    when the plugin runs as several replicas, jobs this process never accepted.
    Lines for jobs this process knows nothing about are the ordinary case.

    A kind this SDK does not model carries no typed fields, so its line gives the
    subject and the raw payload instead."""
    tag = "" if prefix == "" else f"{prefix}: "

    def handler(sig: Signal) -> None:
        if sig.kind != PluginSignal.PROC:
            print(f"{tag}signal {sig.kind} subject={sig.subject} data={sig.data.decode(errors='replace')}")
            return
        print(
            f"{tag}signal {sig.kind} job={sig.job_id} conclusion={sig.conclusion} "
            f"canceled={canceled(sig.conclusion)} succeeded={succeeded(sig.conclusion)}"
        )

    return handler
