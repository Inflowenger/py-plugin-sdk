"""JobContext — the cancellation/value scope middleware passes down."""
from __future__ import annotations

import asyncio

import pytest

from inflow_plugin_sdk import ERR_CANCELED, ERR_DEADLINE_EXCEEDED, background


async def test_the_background_context_is_never_cancelled_and_carries_nothing():
    ctx = background()
    assert ctx.canceled is False
    assert ctx.cause is None
    assert ctx.value("anything") is None
    assert ctx.value("anything", "fallback") == "fallback"
    ctx.on_done(lambda cause: pytest.fail("must not run"))()
    assert await ctx.sleep(0) is True


async def test_with_value_keeps_the_parent_intact_and_shares_its_cancellation():
    parent, cancel = background().with_cancel()
    child = parent.with_value("k", 1)
    assert parent.value("k") is None
    assert child.value("k") == 1
    cancel()
    assert child.canceled is True, "values derive, cancellation is shared"


async def test_cancel_records_the_cause():
    ctx, cancel = background().with_cancel()
    reasons = []
    ctx.on_done(reasons.append)
    sentinel = RuntimeError("mine")
    cancel(sentinel)
    cancel(RuntimeError("later"))  # the first cause wins, like Go's
    assert ctx.cause is sentinel
    assert reasons == [sentinel]


async def test_a_cancel_with_no_cause_reads_as_err_canceled():
    ctx, cancel = background().with_cancel()
    cancel()
    assert ctx.cause is ERR_CANCELED


async def test_a_child_ends_when_its_parent_does_with_the_parents_cause():
    parent, cancel_parent = background().with_cancel()
    child, _ = parent.with_cancel()
    boom = RuntimeError("parent's reason")
    cancel_parent(boom)
    assert child.canceled is True
    assert child.cause is boom


async def test_deriving_from_an_already_ended_context_ends_immediately():
    parent, cancel = background().with_cancel()
    cancel()
    child, _ = parent.with_cancel()
    assert child.canceled is True
    ran = []
    child.on_done(ran.append)
    assert ran == [], "never synchronously"
    await asyncio.sleep(0)
    assert ran == [ERR_CANCELED]


async def test_without_cancel_keeps_the_values_and_drops_the_cancellation():
    ctx, cancel = background().with_cancel()
    detached = ctx.with_value("trace", "abc").without_cancel()
    cancel()
    assert ctx.canceled is True
    assert detached.canceled is False
    assert detached.value("trace") == "abc"


async def test_with_timeout_ends_with_deadline_exceeded():
    ctx, _ = background().with_timeout(0.01)
    assert await ctx.sleep(5) is False
    assert ctx.cause is ERR_DEADLINE_EXCEEDED


async def test_sleep_answers_true_when_it_completes_false_when_the_context_ends():
    ctx, cancel = background().with_cancel()
    assert await ctx.sleep(0.001) is True
    waiting = asyncio.create_task(ctx.sleep(5))
    await asyncio.sleep(0)
    cancel()
    assert await waiting is False
    assert await ctx.sleep(5) is False, "an ended context never waits"


async def test_wait_canceled_answers_the_cause():
    ctx, cancel = background().with_cancel()
    waiter = asyncio.create_task(ctx.wait_canceled())
    await asyncio.sleep(0)
    boom = RuntimeError("stopped")
    cancel(boom)
    assert await waiter is boom


async def test_run_returns_the_result_when_the_work_wins():
    ctx, _ = background().with_cancel()

    async def work():
        return 42

    assert await ctx.run(work()) == 42


async def test_run_cancels_the_work_and_raises_the_cause_when_the_context_ends():
    ctx, cancel = background().with_cancel()
    cancelled = []

    async def slow():
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    running = asyncio.create_task(ctx.run(slow()))
    await asyncio.sleep(0.01)
    boom = RuntimeError("stopped")
    cancel(boom)
    with pytest.raises(RuntimeError, match="stopped"):
        await running
    assert cancelled == [True]


async def test_run_propagates_the_works_own_exception():
    ctx, _ = background().with_cancel()

    async def failing():
        raise ValueError("upstream said no")

    with pytest.raises(ValueError, match="upstream said no"):
        await ctx.run(failing())


async def test_raise_if_canceled_raises_the_cause():
    ctx, cancel = background().with_cancel()
    ctx.raise_if_canceled()
    boom = RuntimeError("stopped")
    cancel(boom)
    with pytest.raises(RuntimeError, match="stopped"):
        ctx.raise_if_canceled()


async def test_a_long_lived_parent_does_not_accumulate_callbacks_per_job():
    parent, _ = background().with_cancel()
    for _ in range(50):
        _, cancel = parent.with_cancel()
        cancel()
    # The child unhooks itself from the parent when it ends.
    assert len(parent._state._callbacks) == 0


async def test_on_done_accepts_a_coroutine_function():
    ctx, cancel = background().with_cancel()
    ran = asyncio.Event()

    async def cleanup(_cause):
        ran.set()

    ctx.on_done(cleanup)
    cancel()
    await asyncio.wait_for(ran.wait(), 1)
