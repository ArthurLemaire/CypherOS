"""Tidying long-term memory: merge what says the same thing, keep the newer fact, drop
what was never a fact about the user.

Memory grows one line at a time, in the middle of other work, so after a few weeks it
holds "prefers window seats" and "likes a window seat on flights", "lives in Shanghai"
next to "moved to Beijing in March", and "asked for the weather in Kyoto". A tidy-up
asks the model for a short list of changes, applies the ones that pass the checks
below, and logs each with the text it replaced so the user can undo it.

The model proposes; this module decides. It never invents a fact (a merged line may
only use words that were there), never drops a line the user wrote themselves, and
takes out at most a fifth of the store in one pass (four lines at least); when
more was proposed, the next pass follows at the next scheduler tick.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from openmuse.llm.base import BaseLLM
from openmuse.memory.store import MemoryChange, MemoryItem, MemoryStore, tokenize
from openmuse.schema import Message

TIDY_PROMPT = """You maintain the long-term memory of a personal agent: short facts about one user, saved over time. Below is everything it holds. Propose the changes that make it smaller and truer without losing anything the user would want kept.

Rules:
- merge: two or more lines that say the same thing, or where one is a more detailed version of another → one line that keeps every detail (names, numbers, dates). When lines contradict because the fact changed (a move, a new job), keep the newer fact and mention the change if it matters ("Lives in Beijing, moved from Shanghai in 2026").
- drop: a line that is not a durable fact about the user — a one-off request, a finished errand, something about today's weather, a duplicate of something kept.
- Do not invent, embellish, or generalise. Do not merge lines about different people or topics. Do not touch anything that is fine as it is. When nothing needs doing, answer [].
- Keep the user's wording and language.

Memory ({count} lines):
{lines}

Answer with a JSON array only, no prose. Items:
{{"op": "merge", "ids": ["m_1", "m_2"], "content": "<the one line>", "category": "<category of the most specific line>"}}
{{"op": "drop", "id": "m_3", "reason": "<a few words>"}}"""

MAX_LINES = 150  # newest first; a bigger store is tidied in passes
MAX_REMOVED_SHARE = 0.2  # lines a pass may take out (a merge of two takes out one)
MIN_REMOVED = 4
MAX_CONTENT = 300
BUDGET_NOTE = "enough for one pass"


_WORDS = {
    "en": {
        "merged": "Merged",
        "dropped": "Dropped",
        "would_merge": "Would merge",
        "would_drop": "Would drop",
    },
    "zh": {"merged": "合并", "dropped": "删除", "would_merge": "将合并", "would_drop": "将删除"},
}


@dataclass
class TidyReport:
    """What a tidy-up did (or would do, when planned only)."""

    merged: list[MemoryChange] = field(default_factory=list)
    dropped: list[MemoryChange] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # proposals that failed a check
    planned: list[dict[str, Any]] = field(default_factory=list)  # dry run
    considered: int = 0

    @property
    def changed(self) -> int:
        return len(self.merged) + len(self.dropped)

    @property
    def more(self) -> bool:
        """Sound proposals were left for the next pass because this one hit its budget."""
        return any(s.endswith(BUDGET_NOTE) for s in self.skipped)

    def lines(self, zh: bool = False) -> list[str]:
        """The report as the user reads it: one line per change (English or 中文)."""
        w = _WORDS["zh" if zh else "en"]
        out: list[str] = []
        for c in self.merged:
            olds = " + ".join(f"“{m.content}”" for m in c.before)
            out.append(f"{w['merged']} {olds} → “{c.after.content if c.after else ''}”")
        for c in self.dropped:
            why = f" ({c.reason})" if c.reason else ""
            out.append(f"{w['dropped']} “{c.before[0].content}”{why}")
        for p in self.planned:
            if p["op"] == "merge":
                olds = " + ".join(f"“{t}”" for t in p["before"])
                out.append(f"{w['would_merge']} {olds} → “{p['content']}”")
            else:
                why = f" ({p['reason']})" if p.get("reason") else ""
                out.append(f"{w['would_drop']} “{p['before'][0]}”{why}")
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "considered": self.considered,
            "changed": self.changed,
            "merged": [c.to_dict() for c in self.merged],
            "dropped": [c.to_dict() for c in self.dropped],
            "skipped": self.skipped,
            "more": self.more,
            "planned": self.planned,
            "lines": self.lines(),
        }


def _objects(text: str) -> list[dict[str, Any]]:
    """The JSON objects in the reply, whether or not the array around them parses."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    start, end = text.find("["), text.rfind("]")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1], strict=False)
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict)]
        except json.JSONDecodeError:
            pass
    decoder = json.JSONDecoder(strict=False)
    found: list[dict[str, Any]] = []
    pos = text.find("{")
    while pos >= 0:
        try:
            obj, stop = decoder.raw_decode(text, pos)
        except json.JSONDecodeError:
            pos = text.find("{", pos + 1)
            continue
        if isinstance(obj, dict):
            found.append(obj)
        pos = text.find("{", stop)
    return found


_CONNECTIVE_WORDS = frozenset(
    "and with from moved now since previously formerly also both prefers likes the for his her "
    "their is was has not no lives works uses".split()
)
_CONNECTIVE_CHARS = frozenset(
    "在从搬到现以前和与并且喜欢不的了是住工作用曾经后来已改为，、。；：（）"
)
_CJK_RE = re.compile(r"[\u3400-\u9fff]")


def _no_new_words(merged: str, sources: list[MemoryItem]) -> bool:
    """A merged line may rephrase, not add: every word must come from one of the sources.

    Short words and digits are let through (articles, "in", "a 10k"), and so is a
    handful of connective words the model needs to join two lines. CJK is checked by
    character, since a bigram across a junction is new by construction.
    """
    allowed: set[str] = set()
    allowed_chars: set[str] = set()
    for m in sources:
        allowed |= tokenize(m.content)
        allowed_chars.update(_CJK_RE.findall(m.content))
    new_words = {
        t
        for t in tokenize(merged) - allowed
        if len(t) > 2 and not t.isdigit() and t not in _CONNECTIVE_WORDS and not _CJK_RE.search(t)
    }
    new_chars = set(_CJK_RE.findall(merged)) - allowed_chars - _CONNECTIVE_CHARS
    return not new_words and not new_chars


def plan(items: list[MemoryItem], reply: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Turn the model's reply into checked operations.

    Returns ``(ops, skipped)``: ops are ``{"op": "merge", "items": [...], "content", "category"}``
    or ``{"op": "drop", "item", "reason"}``; skipped says why a proposal was refused.
    """
    by_id = {m.id: m for m in items}
    ops: list[dict[str, Any]] = []
    skipped: list[str] = []
    touched: set[str] = set()
    removed = 0
    budget = max(MIN_REMOVED, int(len(items) * MAX_REMOVED_SHARE))
    for raw in _objects(reply):
        op = str(raw.get("op", "")).lower()
        if op == "merge":
            ids = [str(i) for i in (raw.get("ids") or []) if str(i) in by_id]
            ids = list(dict.fromkeys(ids))
            content = str(raw.get("content") or "").strip()[:MAX_CONTENT]
            if len(ids) < 2 or not content:
                skipped.append(f"merge of {raw.get('ids')}: needs two known ids and a line")
                continue
            if any(i in touched for i in ids):
                skipped.append(f"merge of {ids}: a line is already in another change")
                continue
            sources = [by_id[i] for i in ids]
            if not _no_new_words(content, sources):
                skipped.append(f"merge of {ids}: “{content}” adds words that were not there")
                continue
            if removed + len(ids) - 1 > budget:
                skipped.append(f"merge of {ids}: {BUDGET_NOTE}")
                continue
            touched.update(ids)
            removed += len(ids) - 1
            ops.append(
                {
                    "op": "merge",
                    "items": sources,
                    "content": content,
                    "category": str(raw.get("category") or "").strip() or sources[0].category,
                }
            )
        elif op == "drop":
            mid = str(raw.get("id") or "")
            item = by_id.get(mid)
            if item is None:
                skipped.append(f"drop {mid}: unknown id")
                continue
            if mid in touched:
                skipped.append(f"drop {mid}: already in another change")
                continue
            if item.source == "user":
                skipped.append(f"drop {mid}: the user wrote it")
                continue
            if removed + 1 > budget:
                skipped.append(f"drop {mid}: {BUDGET_NOTE}")
                continue
            touched.add(mid)
            removed += 1
            ops.append({"op": "drop", "item": item, "reason": str(raw.get("reason") or "")[:120]})
        else:
            skipped.append(f"unknown op {op!r}")
    return ops, skipped


def apply(store: MemoryStore, ops: list[dict[str, Any]], report: TidyReport) -> None:
    for op in ops:
        if op["op"] == "merge":
            change = store.replace(
                [m.id for m in op["items"]], op["content"], category=op["category"], action="merge"
            )
            if change is not None:
                report.merged.append(change)
        else:
            change = store.drop(op["item"].id, reason=op["reason"])
            if change is not None:
                report.dropped.append(change)


async def tidy(store: MemoryStore, llm: BaseLLM, dry_run: bool = False) -> TidyReport:
    """One tidy-up pass over the store. ``dry_run`` plans and reports without changing."""
    items = store.all(limit=MAX_LINES)
    report = TidyReport(considered=len(items))
    if len(items) < 2:
        return report
    lines = "\n".join(
        f"{m.id} ({m.category}, {m.created_at[:10]}{', by the user' if m.source == 'user' else ''}): {m.content}"
        for m in items
    )
    reply = await llm.ask_complete(
        [Message.user(TIDY_PROMPT.format(count=len(items), lines=lines))], tools=None
    )
    ops, report.skipped = plan(items, reply.content or "")
    if dry_run:
        for op in ops:
            if op["op"] == "merge":
                report.planned.append(
                    {
                        "op": "merge",
                        "ids": [m.id for m in op["items"]],
                        "before": [m.content for m in op["items"]],
                        "content": op["content"],
                        "category": op["category"],
                    }
                )
            else:
                report.planned.append(
                    {
                        "op": "drop",
                        "ids": [op["item"].id],
                        "before": [op["item"].content],
                        "reason": op["reason"],
                    }
                )
        return report
    apply(store, ops, report)
    return report


__all__ = ["MAX_LINES", "TIDY_PROMPT", "TidyReport", "plan", "tidy"]
