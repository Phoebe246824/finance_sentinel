"""Reusable async stage timer with Rich live display and decorator support.

Direct usage:      timer = StageTimer(); with timer: timer.stage("...")
Decorator usage:   @timed_stages(); async def f(): with stage("..."): ...
"""

import contextvars
import functools
import time
from collections.abc import Callable
from typing import Any

from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.live import Live
from rich.text import Text

__all__ = ["StageTimer", "stage", "timed_stages"]

_DEFAULT_CONSOLE = Console()
_DEFAULT_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_DEFAULT_SPINNER_FPS = 10

_current_timer: contextvars.ContextVar["StageTimer | None"] = contextvars.ContextVar(
    "stage_timer", default=None
)


class StageTimer:
    """Async-safe stage timer with Rich live display.

    Direct usage (timer created & managed manually)::

        timer = StageTimer()
        with timer:
            with timer.stage("step 1"):
                ...
            with timer.stage("step 2"):
                ...

    Decorator usage (prefer this — see ``timed_stages``)::

        @timed_stages()
        async def my_func():
            with stage("step 1"):
                ...
    """

    def __init__(
        self,
        *,
        live_enabled: bool | None = None,
        console: Console | None = _DEFAULT_CONSOLE,
        spinner_frames: tuple[str, ...] = _DEFAULT_SPINNER_FRAMES,
        spinner_fps: int = _DEFAULT_SPINNER_FPS,
    ) -> None:
        self._console = console
        self._live_enabled = (
            live_enabled
            if live_enabled is not None
            else console is not None and console.is_terminal
        )
        self._spinner_frames = spinner_frames
        self._spinner_fps = spinner_fps
        self._live: Live | None = None
        self._total_start = 0.0
        self._total_elapsed = 0.0
        self._current_label: str | None = None
        self._current_started_at = 0.0
        self._timings: list[tuple[str, float]] = []
        self._ctx_token: contextvars.Token | None = None

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------

    @property
    def timings(self) -> list[tuple[str, float]]:
        """Completed stage (label, elapsed_seconds) pairs in order."""
        return list(self._timings)

    @property
    def total_elapsed(self) -> float:
        """Total elapsed seconds since ``__enter__``."""
        return self._total_elapsed or time.perf_counter() - self._total_start

    def stage(self, label: str) -> "_Stage":
        """Return a context manager that times a single stage."""
        return _Stage(self, label)

    # ------------------------------------------------------------------
    # context manager (direct use)
    # ------------------------------------------------------------------

    def __enter__(self) -> "StageTimer":
        self._total_start = time.perf_counter()
        self._ctx_token = _current_timer.set(self)
        if self._live_enabled:
            self._live = Live(
                self,
                console=self._console,
                refresh_per_second=4,
                transient=False,
            ).__enter__()
        return self

    def __exit__(self, *args: object) -> None:
        self._current_label = None
        self._total_elapsed = time.perf_counter() - self._total_start
        self._refresh()
        if self._live is not None:
            self._live.__exit__(*args)
            self._live = None
        if self._ctx_token is not None:
            _current_timer.reset(self._ctx_token)
            self._ctx_token = None

    # ------------------------------------------------------------------
    # Rich protocol
    # ------------------------------------------------------------------

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        del console, options
        rows = self._render_rows()
        if not rows:
            yield Text("...", style="cyan")
        else:
            yield Group(*rows)

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _start_stage(self, label: str, started_at: float) -> None:
        self._current_label = label
        self._current_started_at = started_at
        self._refresh()

    def _finish_stage(self, label: str, started_at: float) -> None:
        elapsed = time.perf_counter() - started_at
        self._timings.append((label, elapsed))
        self._current_label = None
        self._refresh()

    def _refresh(self) -> None:
        if self._live is not None:
            self._live.update(self)

    def _render_rows(self) -> list[Text]:
        rows: list[Text] = []
        for label, elapsed in self._timings:
            rows.append(Text(f"  ✓ {label:<30} {elapsed:>8.3f}s", style="green"))

        if self._current_label is not None:
            elapsed = time.perf_counter() - self._current_started_at
            frame = self._spinner_frame(elapsed)
            rows.append(
                Text(
                    f"  {frame} {self._current_label:<30} {elapsed:>8.3f}s",
                    style="cyan",
                )
            )
        return rows

    def _spinner_frame(self, elapsed: float) -> str:
        frame_index = int(elapsed * self._spinner_fps)
        return self._spinner_frames[frame_index % len(self._spinner_frames)]


class _Stage:
    """Context manager for a single timed stage — yielded by ``StageTimer.stage()``."""

    def __init__(self, timer: StageTimer, label: str) -> None:
        self._timer = timer
        self._label = label
        self._started_at = 0.0

    def __enter__(self) -> "_Stage":
        self._started_at = time.perf_counter()
        self._timer._start_stage(self._label, self._started_at)
        return self

    def __exit__(self, *args: object) -> None:
        self._timer._finish_stage(self._label, self._started_at)


# ------------------------------------------------------------------
# public convenience API
# ------------------------------------------------------------------


def stage(label: str) -> _Stage:
    """Context manager for use *inside* a ``@timed_stages`` decorated function.

    Raises ``RuntimeError`` if no ``StageTimer`` is active on the current context.
    """
    timer = _current_timer.get()
    if timer is None:
        raise RuntimeError(
            "stage() must be called inside a @timed_stages decorated function "
            "or within an active StageTimer context manager"
        )
    return timer.stage(label)


def timed_stages(
    *,
    live_enabled: bool | None = None,
    console: Console | None = _DEFAULT_CONSOLE,
) -> Callable:
    """Decorator: wrap an async function with a ``StageTimer`` live display.

    Inside the decorated function, use ``stage("label")`` as a context manager::

        @timed_stages()
        async def setup():
            with stage("load config"):
                ...
            with stage("init db"):
                ...

    The timer's live terminal display starts on entry and stops on exit.
    No textual breakdown is emitted — the live view is the output.
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            timer = StageTimer(live_enabled=live_enabled, console=console)
            with timer:
                return await func(*args, **kwargs)

        return wrapper

    return decorator
