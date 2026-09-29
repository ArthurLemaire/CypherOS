"""Run a dot on an interval with the Scheduler, bounded to a few ticks.

    python examples/scheduler_dot.py
"""

from __future__ import annotations

import asyncio

from dots import Dot, Goal
from dots.core.scheduler import Scheduler


async def main() -> None:
    dot = Dot(name="heartbeat", goal=Goal("Record a heartbeat every tick"))
    scheduler = Scheduler(dot, interval=0.05)

    async for result in scheduler.run(max_ticks=5):
        print(f"tick {result.step}: acted={result.acted} learned={result.learned}")

    print("\nfinal diary:")
    for line in dot.diary():
        print(" ", line)


if __name__ == "__main__":
    asyncio.run(main())
