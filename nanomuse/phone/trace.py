"""The trace of one ``phone_task``: what the operator saw, thought and did, step by step.

One JSON Lines file per task under ``<data_dir>/phone-traces/<id>.jsonl``::

    {"kind": "task", "id": "pt-20260923-101500-3f2a", "goal": "...", "app": "12306", ...}
    {"kind": "step", "step": 1, "screen": {"app": "...", "image": ".../phone-....png", ...},
     "thought": "...", "action": "Tap the search box", "tool_call": {"action": "click", ...},
     "params": {"action": "tap", "x": 180, "y": 209, "label": "Tap the search box"},
     "latency_ms": 1830, "error": null}
    {"kind": "end", "status": "done", "message": "...", "steps": 7, "t": 1758600000.0}

A failed run is then a thing to read rather than a thing to guess about: was it the
model's reasoning, its grounding (the tap landed next to the button), the device (an action
that did nothing), or the Sentinel (a refused step)? ``nanomuse phone trace <id>`` renders a
trace as one HTML page with the screenshots and the taps drawn on them.
"""

from __future__ import annotations

import base64
import html
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nanomuse.logger import logger

if TYPE_CHECKING:
    from nanomuse.phone.operator import Outcome, Step
    from nanomuse.phone.screen import Screen

KEEP_TRACES = 200


@dataclass
class Trace:
    id: str
    path: Path | None
    started: float = field(default_factory=time.time)

    @classmethod
    def start(cls, traces_dir: Path | None, goal: str, app: str = "", context: str = "") -> Trace:
        trace_id = f"pt-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
        path = None
        if traces_dir is not None:
            try:
                traces_dir.mkdir(parents=True, exist_ok=True)
                path = traces_dir / f"{trace_id}.jsonl"
                _prune(traces_dir)
            except OSError as exc:
                logger.warning("phone trace directory unusable: {}", exc)
                path = None
        trace = cls(id=trace_id, path=path)
        trace._write(
            {
                "kind": "task",
                "id": trace_id,
                "t": trace.started,
                "goal": goal,
                "app": app,
                "context": context[:2000],
            }
        )
        return trace

    def step(
        self,
        step_no: int,
        screen: Screen,
        step: Step | None = None,
        raw: str = "",
        latency_ms: int = 0,
        params: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self._write(
            {
                "kind": "step",
                "step": step_no,
                "t": time.time(),
                "screen": screen.to_dict(),
                "thought": step.thought if step else None,
                "action": step.action if step else None,
                "tool_call": {"name": step.name, "arguments": step.arguments} if step else None,
                "params": params,
                "raw": None if step else raw[:2000],
                "latency_ms": latency_ms,
                "error": error,
            }
        )

    def end(self, outcome: Outcome) -> None:
        self._write(
            {
                "kind": "end",
                "t": time.time(),
                "status": outcome.status,
                "message": outcome.message,
                "steps": outcome.steps,
                "seconds": round(time.time() - self.started, 1),
            }
        )

    def _write(self, record: dict[str, Any]) -> None:
        if self.path is None:
            return
        try:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("could not write phone trace: {}", exc)
            self.path = None


def _prune(traces_dir: Path) -> None:
    old = sorted(traces_dir.glob("pt-*.jsonl"), key=lambda p: p.stat().st_mtime)
    for stale in old[: max(0, len(old) - KEEP_TRACES + 1)]:
        stale.unlink(missing_ok=True)


# ------------------------------------------------------------------ reading


def list_traces(traces_dir: Path) -> list[dict[str, Any]]:
    """The tasks on disk, newest first: id, goal, status, steps."""
    items = []
    for path in sorted(traces_dir.glob("pt-*.jsonl"), reverse=True):
        records = read_trace(path)
        if not records:
            continue
        task = records[0] if records[0].get("kind") == "task" else {}
        end = records[-1] if records[-1].get("kind") == "end" else {}
        items.append(
            {
                "id": task.get("id") or path.stem,
                "goal": task.get("goal", ""),
                "app": task.get("app", ""),
                "status": end.get("status", "running"),
                "steps": end.get("steps") or sum(1 for r in records if r.get("kind") == "step"),
                "started": task.get("t"),
            }
        )
    return items


def read_trace(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return records


def render_html(records: list[dict[str, Any]]) -> str:
    """One self-contained page: every step's screenshot with the action drawn on it."""
    task = records[0] if records and records[0].get("kind") == "task" else {}
    end = records[-1] if records and records[-1].get("kind") == "end" else {}
    parts = [
        "<!doctype html><meta charset='utf-8'><title>phone trace</title>",
        "<style>body{font:14px/1.45 system-ui,sans-serif;margin:24px;color:#1b1b1f;background:#f6f6f8}"
        "h1{font-size:18px;margin:0 0 4px}.meta{color:#5c5c66;margin-bottom:20px}"
        ".step{display:flex;gap:18px;align-items:flex-start;background:#fff;border-radius:12px;"
        "padding:14px;margin-bottom:14px;box-shadow:0 1px 2px rgba(0,0,0,.06)}"
        ".shot{position:relative;flex:none;width:270px}.shot img{width:100%;display:block;border-radius:8px}"
        ".shot svg{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}"
        ".n{font-weight:600}.t{color:#5c5c66}.a{margin:6px 0}.err{color:#b3261e}"
        "code{background:#eeeef2;padding:1px 5px;border-radius:4px;font-size:12px}</style>",
        f"<h1>{html.escape(str(task.get('goal') or 'phone task'))}</h1>",
        "<div class='meta'>"
        + html.escape(
            " · ".join(
                s
                for s in (
                    str(task.get("id") or ""),
                    f"app {task['app']}" if task.get("app") else "",
                    f"{end.get('status', 'running')}",
                    f"{end.get('steps', '?')} steps",
                    f"{end.get('seconds')} s" if end.get("seconds") is not None else "",
                )
                if s
            )
        )
        + "</div>",
    ]
    for rec in records:
        if rec.get("kind") != "step":
            continue
        screen = rec.get("screen") or {}
        w, h = int(screen.get("width") or 0), int(screen.get("height") or 0)
        img = _inline_image(screen.get("image"))
        overlay = _overlay(rec.get("params") or {}, w, h)
        parts.append("<div class='step'>")
        parts.append("<div class='shot'>")
        if img:
            parts.append(f"<img src='{img}' alt=''>")
            if overlay:
                parts.append(overlay)
        else:
            parts.append("<div class='t'>(no screenshot)</div>")
        parts.append("</div><div>")
        parts.append(
            f"<div><span class='n'>Step {rec.get('step')}</span> "
            f"<span class='t'>{html.escape(str(screen.get('app_name') or screen.get('app') or ''))}"
            f" · {rec.get('latency_ms', 0)} ms</span></div>"
        )
        if rec.get("thought"):
            parts.append(f"<div class='t'>{html.escape(str(rec['thought']))}</div>")
        if rec.get("action"):
            parts.append(f"<div class='a'><b>{html.escape(str(rec['action']))}</b></div>")
        shown = rec.get("params") or (rec.get("tool_call") or {}).get("arguments")
        if shown:
            parts.append(
                f"<div><code>{html.escape(json.dumps(shown, ensure_ascii=False))}</code></div>"
            )
        if rec.get("raw"):
            parts.append(
                f"<div class='err'>unparsed reply: {html.escape(str(rec['raw'])[:600])}</div>"
            )
        if rec.get("error"):
            parts.append(f"<div class='err'>{html.escape(str(rec['error']))}</div>")
        parts.append("</div></div>")
    if end.get("message"):
        parts.append(
            f"<p><b>{html.escape(str(end.get('status')))}</b> — {html.escape(str(end['message']))}</p>"
        )
    return "\n".join(parts)


def _inline_image(path: str | None) -> str:
    if not path:
        return ""
    p = Path(path)
    try:
        data = p.read_bytes()
    except OSError:
        return ""
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _overlay(params: dict[str, Any], w: int, h: int) -> str:
    """A ring where the finger went, an arrow for a swipe — in the screen's own coordinates."""
    if not (w and h):
        return ""
    action = params.get("action")
    x, y = params.get("x"), params.get("y")
    if action in ("tap", "double_tap", "long_press") and x is not None and y is not None:
        r = max(w, h) * 0.035
        return (
            f"<svg viewBox='0 0 {w} {h}'><circle cx='{x}' cy='{y}' r='{r}' fill='rgba(255,64,64,.25)' "
            f"stroke='#ff4040' stroke-width='{r / 5}'/></svg>"
        )
    if action == "swipe" and x is not None and y is not None:
        x2, y2 = params.get("x2", x), params.get("y2", y)
        return (
            f"<svg viewBox='0 0 {w} {h}'><line x1='{x}' y1='{y}' x2='{x2}' y2='{y2}' stroke='#ff4040' "
            f"stroke-width='{max(w, h) * 0.006}' stroke-linecap='round'/>"
            f"<circle cx='{x2}' cy='{y2}' r='{max(w, h) * 0.015}' fill='#ff4040'/></svg>"
        )
    return ""


__all__ = ["Trace", "list_traces", "read_trace", "render_html"]
