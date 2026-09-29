from __future__ import annotations

import pytest

from dots import Dot, Goal
from dots.core.scheduler import Scheduler


async def test_scheduler_runs_capped_ticks() -> None:
    dot = Dot(name="s", goal=Goal("beat"))
    sched = Scheduler(dot, interval=0.001)
    results = [r async for r in sched.run(max_ticks=4)]
    assert len(results) == 4
    assert [r.step for r in results] == [1, 2, 3, 4]


async def test_scheduler_rejects_bad_interval() -> None:
    dot = Dot(name="s", goal=Goal("beat"))
    with pytest.raises(ValueError):
        Scheduler(dot, interval=0)


async def test_scheduler_stop_halts_iteration() -> None:
    dot = Dot(name="s", goal=Goal("beat"))
    sched = Scheduler(dot, interval=0.001)
    seen = 0
    async for _ in sched.run(max_ticks=100):
        seen += 1
        if seen == 2:
            sched.stop()
    assert seen == 2
