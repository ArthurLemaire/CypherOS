"""Goal management tool (create / list / get / update / update_step / add_step / propose / note)."""

from __future__ import annotations

from typing import Any

from openmuse.goals import CATEGORIES, GOAL_STATUSES, STEP_STATUSES, GoalStore
from openmuse.schema import RiskLevel, ToolResult
from openmuse.tools.base import BaseTool, CallAssessment


class Goals(BaseTool):
    name: str = "goals"
    description: str = (
        "Manage the user's long-term goals and their step-by-step plans (persisted across sessions). "
        "Actions: `create` (title, description, steps[], category, due, check_in), "
        "`list` (status, category optional), `get` (goal_id), "
        "`update` (goal_id + any of title, description, category, due, check_in — '' clears), "
        "`update_step` (goal_id, step_index, status, note), `add_step` (goal_id, title), "
        "`propose` (goal_id, note=why, steps=revised remaining steps — the user accepts or dismisses "
        "in the app; never silently rewrite a plan), "
        "`set_status` (goal_id, status: active|paused|done|cancelled), `note` (goal_id, note). "
        "Create a goal whenever the user gives you a multi-step or long-running objective, then "
        "keep steps up to date as you work. Pick the category and, if the user gave one, the "
        "target date; offer a check-in cadence when a goal is a habit or needs regular nudges."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "create",
                    "list",
                    "get",
                    "update",
                    "update_step",
                    "add_step",
                    "propose",
                    "set_status",
                    "note",
                ],
            },
            "goal_id": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "steps": {"type": "array", "items": {"type": "string"}},
            "category": {
                "type": "string",
                "description": "One of: " + ", ".join(CATEGORIES) + ".",
            },
            "due": {"type": "string", "description": "Target date, YYYY-MM-DD."},
            "check_in": {
                "type": "string",
                "description": (
                    "Reminder cadence: 'daily 08:00', 'weekdays 07:30', 'weekly mon 09:00', "
                    "'monthly 1 09:00' (local time), or '' for none."
                ),
            },
            "step_index": {"type": "integer", "description": "1-based step number."},
            "status": {
                "type": "string",
                "description": f"goal: {'|'.join(GOAL_STATUSES)}; step: {'|'.join(STEP_STATUSES)}",
            },
            "note": {"type": "string"},
        },
        "required": ["action"],
    }
    risk: RiskLevel = RiskLevel.SAFE
    store: GoalStore

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        a = super().assess(args)
        action = str(args.get("action") or "?")
        gid = args.get("goal_id") or ""
        if action == "create":
            detail = str(args.get("title") or "")[:80]
        elif action == "update_step":
            detail = f"{gid} step {args.get('step_index')} → {args.get('status') or 'note'}"
        elif action in ("add_step", "note"):
            detail = f"{gid}: {str(args.get('title') or args.get('note') or '')[:60]}"
        elif action == "propose":
            detail = f"{gid}: {str(args.get('note') or '')[:60]}"
        elif action == "update":
            changed = [
                k for k in ("title", "description", "category", "due", "check_in") if k in args
            ]
            detail = f"{gid}: {', '.join(changed)}"
        elif action == "set_status":
            detail = f"{gid} → {args.get('status')}"
        else:
            detail = gid or str(args.get("status") or args.get("category") or "")
        a.summary = f"goals {action}" + (f": {detail}" if detail else "")
        return a

    async def execute(
        self,
        action: str = "",
        goal_id: str | None = None,
        title: str | None = None,
        description: str | None = None,
        steps: list[str] | None = None,
        category: str | None = None,
        due: str | None = None,
        check_in: str | None = None,
        step_index: int | None = None,
        status: str | None = None,
        note: str | None = None,
        **_: Any,
    ) -> ToolResult:
        def show(goal) -> ToolResult:  # noqa: ANN001
            return (
                ToolResult(output=goal.render()) if goal else ToolResult.fail(f"no goal {goal_id}")
            )

        try:
            if action == "create":
                if not title:
                    return ToolResult.fail("`title` is required")
                goal = self.store.create(
                    title,
                    description or "",
                    steps or [],
                    category=category or "",
                    due=due or "",
                    check_in=check_in or "",
                )
                return ToolResult(output=f"Created goal.\n{goal.render()}")
            if action == "list":
                goals = self.store.list(status, category)
                if not goals:
                    what = " ".join(x for x in (category, status) if x)
                    return ToolResult(output=f"No {what + ' ' if what else ''}goals.")
                return ToolResult(output="\n\n".join(g.render(with_notes=False) for g in goals))
            if not goal_id:
                return ToolResult.fail("`goal_id` is required")
            if action == "get":
                return show(self.store.get(goal_id))
            if action == "update":
                return show(
                    self.store.update(
                        goal_id,
                        title=title,
                        description=description,
                        category=category,
                        due=due,
                        check_in=check_in,
                    )
                )
            if action == "update_step":
                if step_index is None:
                    return ToolResult.fail("`step_index` is required")
                return show(
                    self.store.update_step(goal_id, int(step_index), status=status, note=note)
                )
            if action == "add_step":
                if not title:
                    return ToolResult.fail("`title` is required")
                return show(self.store.add_step(goal_id, title))
            if action == "propose":
                if not note or not steps:
                    return ToolResult.fail(
                        "`note` (why the plan should change) and `steps` (the revised remaining "
                        "steps) are required"
                    )
                proposed = self.store.propose(goal_id, note, steps)
                if proposed is None:
                    return ToolResult.fail(f"no goal {goal_id}")
                return ToolResult(
                    output="Proposal recorded; the user will accept or dismiss it in the app. "
                    "Keep working on the current plan where you can.\n" + proposed.render()
                )
            if action == "set_status":
                if not status:
                    return ToolResult.fail("`status` is required")
                return show(self.store.set_status(goal_id, status))
            if action == "note":
                if not note:
                    return ToolResult.fail("`note` is required")
                return show(self.store.append_note(goal_id, note))
            return ToolResult.fail(f"unknown action '{action}'")
        except ValueError as exc:
            return ToolResult.fail(str(exc))


__all__ = ["Goals"]
