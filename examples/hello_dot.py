"""The smallest useful dot: observe a tick, jot a note, print the diary.

    python examples/hello_dot.py
"""

from __future__ import annotations

import asyncio

from dots import Dot, Event, Goal


async def main() -> None:
    dot = Dot(name="hello", goal=Goal("Say hello whenever woken"))

    # Feed it two ticks.
    await dot.step(Event.tick())
    await dot.step(Event.tick())

    print("diary:")
    for line in dot.diary():
        print(" ", line)

    print("\nremembered:")
    for record in await dot.memory.all():
        print(" ", record.text)


if __name__ == "__main__":
    asyncio.run(main())
