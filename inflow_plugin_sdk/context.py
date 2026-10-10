# JobContext — the job's cancellation + value scope. Mirrors Go's context.Context
# as the SDK uses it (sdkv1/middleware.go, sdkv1/job.go).
#
# Go hands a context.Context down the pipeline; Python has no such type, so this
# is the equivalent built on asyncio:
#
#   Go                                     here
#   ───────────────────────────────────    ──────────────────────────────────────
#   ctx.Err() != nil                       ctx.canceled
#   context.Cause(ctx)                      ctx.cause
#   ctx.Value(k) / context.WithValue        ctx.value(k) / ctx.with_value(k, v)
#   context.WithCancelCause                 ctx.with_cancel()
#   context.WithTimeout                     ctx.with_timeout(seconds)
#   context.WithoutCancel                   ctx.without_cancel()
#   context.AfterFunc(ctx, fn)              ctx.on_done(fn)
#   select { <-ctx.Done(); <-time.After }   await ctx.sleep(seconds)
#   passing ctx to a library                await ctx.run(coro)
#
# The last line is the one that matters in practice. A Go library takes a context
# and abandons its own work; a Python library takes nothing, so `ctx.run(coro)`
# runs the awaitable in a task and cancels THAT when the context ends — which is
# how asyncio abandons work. For code that polls instead, `ctx.sleep` is the
# `select` on ctx.Done() and a timer.
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Mapping, Optional, TypeVar

T = TypeVar("T")


class Canceled(Exception):
    """The cause a context carries when it was cancelled without one — the
    counterpart of Go's `context.Canceled`. A deliberate cause (such as
    `jobstop.ErrStopped`) replaces it, so a handler can tell *why* its job ended.
    """


class DeadlineExceeded(Canceled):
    """The cause a context carries when its deadline passed. Mirrors Go's
    `context.DeadlineExceeded`."""


# The default cause of a cancellation, so `ctx.cause is ERR_CANCELED` works the
# way `errors.Is(err, context.Canceled)` does in Go.
ERR_CANCELED = Canceled("job context canceled")
ERR_DEADLINE_EXCEEDED = DeadlineExceeded("job context deadline exceeded")

# Cancels a derived context, optionally recording why. Mirrors Go's
# context.CancelCauseFunc.
CancelFunc = Callable[..., None]

_EMPTY: Mapping[Any, Any] = {}


class JobContext:
    """A job's context: what its middleware passed down, and what ends when the
    job ends. Handlers get one from `job.context()`; middleware functions get one
    as their first argument and return it — derived or as-is — for the next
    function.

    Instances are immutable: `with_value` / `with_cancel` / `without_cancel`
    return a new context and leave the one they were called on alone, exactly as
    Go's do."""

    __slots__ = ("_state", "_values")

    def __init__(self, state: Optional["_CancelState"], values: Mapping[Any, Any]):
        # None ⇒ this context is never cancelled (the background context).
        self._state = state
        self._values = values

    # ---- construction -----------------------------------------------------

    @staticmethod
    def background() -> "JobContext":
        """The root context: never cancelled, carrying nothing. Mirrors Go's
        `context.Background()`. A `Job` built by hand answers with this."""
        return JobContext(None, _EMPTY)

    # ---- state ------------------------------------------------------------

    @property
    def canceled(self) -> bool:
        """Whether this context has ended. Mirrors `ctx.Err() != nil`."""
        return self._state is not None and self._state.cause is not None

    @property
    def cause(self) -> Optional[BaseException]:
        """Why this context ended, or None while it is live — the exception a
        canceller passed, e.g. `jobstop.ErrStopped`. Mirrors
        `context.Cause(ctx)`."""
        return self._state.cause if self._state is not None else None

    def value(self, key: Any, default: Any = None) -> Any:
        """The value bound to `key`, or `default`. Mirrors `ctx.Value(key)`."""
        return self._values.get(key, default)

    # ---- derivation -------------------------------------------------------

    def with_value(self, key: Any, value: Any) -> "JobContext":
        """A context carrying `value` under `key`, sharing this one's
        cancellation. Mirrors `context.WithValue`. Use a module-private key, so
        two packages cannot collide (that is what `_JOB_ID_KEY` in middleware.py
        does)."""
        values = dict(self._values)
        values[key] = value
        return JobContext(self._state, values)

    def with_cancel(self) -> tuple["JobContext", CancelFunc]:
        """A cancellable child of this context, and the function that cancels it
        with a cause. Mirrors `context.WithCancelCause`. The child also ends when
        this context does, carrying this context's cause."""
        state = _CancelState()
        child = JobContext(state, self._values)

        def cancel(cause: Optional[BaseException] = None) -> None:
            state.cancel(cause or ERR_CANCELED)

        if self._state is not None:
            if self._state.cause is not None:
                state.cancel(self._state.cause)
            else:
                # Unhook from the parent as soon as the child ends: a plugin-wide
                # parent outlives thousands of jobs, and a callback per finished
                # job is a leak.
                off = self._state.on_done(state.cancel)
                state.on_done(lambda _cause: off())
        return child, cancel

    def with_timeout(self, seconds: float) -> tuple["JobContext", CancelFunc]:
        """A child of this context that cancels itself after `seconds` with
        DeadlineExceeded. Mirrors `context.WithTimeout`. Call the returned cancel
        when done so the timer is dropped."""
        ctx, cancel = self.with_cancel()
        timer = asyncio.get_running_loop().call_later(
            seconds, lambda: cancel(ERR_DEADLINE_EXCEEDED)
        )
        ctx.on_done(lambda _cause: timer.cancel())
        return ctx, cancel

    def without_cancel(self) -> "JobContext":
        """A context with this one's values but no cancellation — for work that
        must outlive the job that started it (a compensating call, a last log
        write). Mirrors `context.WithoutCancel`."""
        return JobContext(None, self._values)

    # ---- reacting ---------------------------------------------------------

    def on_done(self, fn: Callable[[BaseException], Any]) -> Callable[[], None]:
        """Run `fn(cause)` once when this context ends, and return a function
        that unregisters it. Mirrors `context.AfterFunc`. On a context already
        ended `fn` is scheduled on the loop (never called synchronously, like
        Go's); on one that can never be cancelled it never runs.

        A coroutine function is accepted too: it is scheduled as a task."""
        if self._state is None:
            return lambda: None
        return self._state.on_done(fn)

    async def wait_canceled(self) -> BaseException:
        """Wait until this context ends and answer its cause — the counterpart of
        `<-ctx.Done()`. On a context that can never be cancelled it waits
        forever, so only use it where that cannot happen (inside a handler, the
        job's context is always cancellable)."""
        if self._state is None:
            await asyncio.Event().wait()  # never set: mirrors a nil channel
            raise AssertionError("unreachable")
        return await self._state.wait()

    async def sleep(self, seconds: float) -> bool:
        """Wait `seconds`, or until this context ends — whichever comes first.
        Answers True if the wait completed, False if the context ended, so a
        polling loop reads `if not await ctx.sleep(2): return`. The counterpart
        of Go's `select { case <-ctx.Done(): case <-time.After(d): }`."""
        if self.canceled:
            return False
        if self._state is None:
            await asyncio.sleep(seconds)
            return True
        waiter = asyncio.ensure_future(self._state.wait())
        try:
            await asyncio.wait({waiter}, timeout=seconds)
        finally:
            waiter.cancel()
        return not self.canceled

    async def run(self, aw: Awaitable[T]) -> T:
        """Await `aw`, cancelling it if this context ends first — then raising the
        context's cause.

        This is how a Python handler does what a Go handler does by passing ctx
        down: `rows = await ctx.run(db.fetch(...))` abandons the query when the
        flow is stopped. Note that the raised cause propagates out of the
        handler, which the SDK reports as a failed job — for a job *stopped by
        the runtime* that is wrong (nobody is listening), so either catch it or
        check `ctx.canceled` and return instead:

            try:
                result = await ctx.run(slow_call())
            except jobstop.JobStopped:
                return  # the runtime is gone: do not report
        """
        task = asyncio.ensure_future(aw)
        if self._state is None:
            return await task
        waiter = asyncio.ensure_future(self._state.wait())
        try:
            done, _ = await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                return task.result()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            raise self.cause or ERR_CANCELED
        finally:
            waiter.cancel()

    def raise_if_canceled(self) -> None:
        """Raise this context's cause if it has ended; otherwise do nothing. For
        a handler that would rather unwind than check a boolean — but note that
        an exception escaping a handler reports the job as failed
        (`with_job_handler` → `done_with_error`), which a *stopped* job must not
        do: the runtime has stopped listening. Prefer `if ctx.canceled: return`
        there."""
        if self.canceled:
            raise self.cause or ERR_CANCELED


class _CancelState:
    """The shared cancellation behind one `with_cancel` — the cause, the
    callbacks, and an Event for the waiters. Private: contexts are the API."""

    __slots__ = ("cause", "_callbacks", "_event")

    def __init__(self) -> None:
        self.cause: Optional[BaseException] = None
        self._callbacks: list[Callable[[BaseException], Any]] = []
        self._event: Optional[asyncio.Event] = None

    def cancel(self, cause: BaseException) -> None:
        if self.cause is not None:
            return  # the first cause wins, as in Go
        self.cause = cause
        if self._event is not None:
            self._event.set()
        callbacks, self._callbacks = self._callbacks, []
        for fn in callbacks:
            _invoke(fn, cause)

    def on_done(self, fn: Callable[[BaseException], Any]) -> Callable[[], None]:
        if self.cause is not None:
            cause = self.cause
            # Never synchronously, so a canceller is not surprised by a callback
            # running inside its own call — Go's AfterFunc has the same promise.
            _soon(lambda: _invoke(fn, cause))
            return lambda: None
        self._callbacks.append(fn)

        def off() -> None:
            try:
                self._callbacks.remove(fn)
            except ValueError:
                pass

        return off

    async def wait(self) -> BaseException:
        if self.cause is not None:
            return self.cause
        if self._event is None:
            self._event = asyncio.Event()
        await self._event.wait()
        assert self.cause is not None
        return self.cause


def _invoke(fn: Callable[[BaseException], Any], cause: BaseException) -> None:
    try:
        result = fn(cause)
        if asyncio.iscoroutine(result):
            asyncio.ensure_future(result)
    except Exception as e:  # a cleanup that fails must not break the canceller
        print(f"context on_done callback failed: {e}")


def _soon(fn: Callable[[], None]) -> None:
    try:
        asyncio.get_running_loop().call_soon(fn)
    except RuntimeError:
        fn()  # no loop (a synchronous test): the best we can do is run it now


def background() -> JobContext:
    """The root context: never cancelled, carrying nothing. Mirrors
    `context.Background()`."""
    return JobContext.background()
