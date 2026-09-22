"""The ``skills`` tool: the recipes for jobs — read one before doing the job, write one
down after a job the user wants done the same way again."""

from __future__ import annotations

from typing import Any

from openmuse.schema import RiskLevel, ToolResult
from openmuse.skills import YOURS, SkillLibrary
from openmuse.tools.base import BaseTool, CallAssessment


class Skills(BaseTool):
    name: str = "skills"
    description: str = (
        "Skills are written-down ways of doing a job (a weekly review, a trip plan, an inbox "
        "triage …); the system prompt lists the ones available. Actions: `use` — the full "
        "instructions of skill `name`; call it as the first step whenever a request matches a "
        "skill, then follow them. `list` — every skill with its description. `save` — write a "
        "skill of your own: `name` (lowercase-with-hyphens), `description` (one line: what it "
        "does and when to use it, ≤ 1024 characters) and `instructions` (Markdown: the steps, "
        "what to produce, what to ask and what never to do; include the user's preferences that "
        "came up). Save one when the user asks you to remember how a job is done, or after a "
        "multi-step job they say they will want again — it asks the user first, so tell them "
        "what you are about to save. `remove` — delete a skill you saved (`name`)."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["use", "list", "save", "remove"]},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "instructions": {"type": "string"},
        },
        "required": ["action"],
    }
    risk: RiskLevel = RiskLevel.SAFE
    library: SkillLibrary

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        action = str(args.get("action", ""))
        name = str(args.get("name") or "").strip().lower()
        if action in ("save", "remove"):
            # a skill is a standing instruction for every later session: writing one is
            # as sensitive as changing the configuration, and always shown to the user
            desc = str(args.get("description") or "").strip().replace("\n", " ")
            return CallAssessment(
                risk=RiskLevel.SENSITIVE,
                target=name or None,
                summary=f"skills {action} {name!r}" + (f": {desc[:100]}" if desc else ""),
                warnings=(
                    ["this replaces one of the built-in skills"]
                    if action == "save"
                    and (s := self.library.get(name)) is not None
                    and s.source != YOURS
                    else []
                ),
            )
        return CallAssessment(
            risk=RiskLevel.SAFE, summary=f"skills {action}" + (f" {name!r}" if name else "")
        )

    async def execute(
        self,
        action: str = "",
        name: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        **_: Any,
    ) -> ToolResult:
        lib = self.library
        name = (name or "").strip().lower()
        try:
            if action == "list":
                skills = lib.enabled()
                if not skills:
                    return ToolResult(
                        output="No skills yet. `save` one after a job worth repeating."
                    )
                lines = [f"- {s.name} ({s.source}): {s.description}" for s in skills]
                return ToolResult(output=f"{len(skills)} skills:\n" + "\n".join(lines))
            if action == "use":
                if not name:
                    return ToolResult.fail("`name` is required")
                skill = lib.get(name)
                if skill is None or not skill.enabled:
                    names = ", ".join(s.name for s in lib.enabled()) or "none"
                    return ToolResult.fail(f"no skill named {name!r}; available: {names}")
                return ToolResult(output=skill.instructions())
            if action == "save":
                if not name:
                    return ToolResult.fail("`name` is required")
                skill = lib.save(name, description or "", instructions or "")
                return ToolResult(
                    output=f"Saved skill `{skill.name}` to {skill.path}. It is in the list from "
                    "now on; the user can also start it with /" + skill.name + "."
                )
            if action == "remove":
                if not name:
                    return ToolResult.fail("`name` is required")
                skill = lib.get(name)
                if skill is None:
                    return ToolResult.fail(f"no skill named {name!r}")
                if skill.source != YOURS:
                    return ToolResult.fail(
                        f"`{name}` is a built-in skill; it cannot be removed here (the user can "
                        "switch it off in the app)"
                    )
                lib.remove(name)
                return ToolResult(output=f"Removed skill `{name}`.")
            return ToolResult.fail(f"unknown action {action!r}")
        except ValueError as exc:
            return ToolResult.fail(str(exc))
        except OSError as exc:
            return ToolResult.fail(f"could not write the skill: {exc}")


__all__ = ["Skills"]
