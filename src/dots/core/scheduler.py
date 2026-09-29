"""Drive a dot on a fixed interval without clock drift."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from dots.core.agent import Dot
from dots.core.event import Event
from dots.core.runtime import StepResult


class Scheduler:
    """Ticks a dot every ``interval`` seconds using a monotonic clock.

    Uses absolute wake targets rather than ``sleep(interval)`` so a slow step
    doesn't accumulate drift — if a step overruns, the next tick fires
    immediately rather than compounding the delay.
    """

    def __init__(self, dot: Dot, *, interval: float) -> None:
        if interval <= 0:
            raise ValueError("interval must be positive")
        self._dot = dot
        self._interval = interval
        self._stop = asyncio.Event()

    async def run(self, *, max_ticks: int | None = None) -> AsyncIterator[StepResult]:
        """Yield a :class:`StepResult` per tick until stopped or capped."""
        loop = asyncio.get_running_loop()
        next_at = loop.time()
        ticks = 0
        while not self._stop.is_set():
            if max_ticks is not None and ticks >= max_ticks:
                return
            result = await self._dot.step(Event.tick())
            ticks += 1
            yield result

            next_at += self._interval
            delay = max(0.0, next_at - loop.time())
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=delay)

    def stop(self) -> None:
        self._stop.set()
