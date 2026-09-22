"""Goal management tool (create / list / get / update / add_step / note)."""

from __future__ import annotations

from typing import Any

from openmuse.goals import GOAL_STATUSES, STEP_STATUSES, GoalStore
from openmuse.schema import RiskLevel, ToolResult
from openmuse.tools.base import BaseTool, CallAssessment


class Goals(BaseTool):
    name: str = "goals"
    description: str = (
        "Manage the user's long-term goals and their step-by-step plans (persisted across sessions). "
        "Actions: `create` (title, description, steps[]), `list` (status optional), `get` (goal_id), "
        "`update_step` (goal_id, step_index, status, note), `add_step` (goal_id, title), "
        "`set_status` (goal_id, status: active|paused|done|cancelled), `note` (goal_id, note). "
        "Create a goal whenever the user gives you a multi-step or long-running objective, then "
        "keep steps up to date as you work."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "list", "get", "update_step", "add_step", "set_status", "note"],
            },
            "goal_id": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "steps": {"type": "array", "items": {"type": "string"}},
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
        elif action == "set_status":
            detail = f"{gid} → {args.get('status')}"
        else:
            detail = gid or str(args.get("status") or "")
        a.summary = f"goals {action}" + (f": {detail}" if detail else "")
        return a

    async def execute(
        self,
        action: str = "",
        goal_id: str | None = None,
        title: str | None = None,
        description: str = "",
        steps: list[str] | None = None,
        step_index: int | None = None,
        status: str | None = None,
        note: str | None = None,
        **_: Any,
    ) -> ToolResult:
        try:
            if action == "create":
                if not title:
                    return ToolResult.fail("`title` is required")
                goal = self.store.create(title, description or "", steps or [])
                return ToolResult(output=f"Created goal.\n{goal.render()}")
            if action == "list":
                goals = self.store.list(status)
                if not goals:
                    return ToolResult(
                        output="No goals" + (f" with status {status}" if status else "") + "."
                    )
                return ToolResult(output="\n\n".join(g.render(with_notes=False) for g in goals))
            if not goal_id:
                return ToolResult.fail("`goal_id` is required")
            if action == "get":
                goal = self.store.get(goal_id)
                return (
                    ToolResult(output=goal.render())
                    if goal
                    else ToolResult.fail(f"no goal {goal_id}")
                )
            if action == "update_step":
                if step_index is None:
                    return ToolResult.fail("`step_index` is required")
                goal = self.store.update_step(goal_id, int(step_index), status=status, note=note)
                return (
                    ToolResult(output=goal.render())
                    if goal
                    else ToolResult.fail(f"no goal {goal_id}")
                )
            if action == "add_step":
                if not title:
                    return ToolResult.fail("`title` is required")
                goal = self.store.add_step(goal_id, title)
                return (
                    ToolResult(output=goal.render())
                    if goal
                    else ToolResult.fail(f"no goal {goal_id}")
                )
            if action == "set_status":
                if not status:
                    return ToolResult.fail("`status` is required")
                goal = self.store.set_status(goal_id, status)
                return (
                    ToolResult(output=goal.render())
                    if goal
                    else ToolResult.fail(f"no goal {goal_id}")
                )
            if action == "note":
                if not note:
                    return ToolResult.fail("`note` is required")
                goal = self.store.append_note(goal_id, note)
                return (
                    ToolResult(output=goal.render())
                    if goal
                    else ToolResult.fail(f"no goal {goal_id}")
                )
            return ToolResult.fail(f"unknown action '{action}'")
        except ValueError as exc:
            return ToolResult.fail(str(exc))


__all__ = ["Goals"]
