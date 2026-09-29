"""A research dot: fetch a page, remember it, recall against the goal.

    python examples/research_dot.py https://example.com
"""

from __future__ import annotations

import asyncio
import sys

from dots import Dot, Goal
from dots.planner.planner import Action, Plan
from dots.tools import BrowserTool


class FetchOnce:
    """A one-shot planner that fetches a single URL, then declares success."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._done = False

    async def plan(self, goal: Goal, events: list[object], recall: list[str]) -> Plan:
        if self._done:
            return Plan(reasoning="already fetched", goal_satisfied=True)
        self._done = True
        return Plan(
            actions=[Action(tool="browser", args={"url": self._url}, rationale="gather source")],
            reasoning="fetch the target once",
        )


async def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    dot = Dot(
        name="research",
        goal=Goal(f"Summarize {url}"),
        tools=[BrowserTool()],
        planner=FetchOnce(url),
    )

    await dot.step()  # fetch
    hits = await dot.memory.recall(url, k=3)
    print(f"recall for {url!r}:")
    for record in hits:
        print(f"  · {record.text}")


if __name__ == "__main__":
    asyncio.run(main())
