"""A goal is the standing instruction that gives a dot its purpose."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class Goal(BaseModel):
    """A declarative objective for a dot.

    Unlike a prompt, a goal persists across steps. The planner reads it every
    step to decide whether more work is warranted.
    """

    objective: str
    success_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    max_actions: int = 5

    def __init__(self, objective: str = "", /, **data: object) -> None:
        # Allow the ergonomic ``Goal("do the thing")`` positional form.
        if objective:
            data.setdefault("objective", objective)
        super().__init__(**data)

    @field_validator("objective")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("goal objective must not be empty")
        return v.strip()

    @field_validator("max_actions")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_actions must be >= 1")
        return v

    def describe(self) -> str:
        lines = [f"Objective: {self.objective}"]
        if self.success_criteria:
            lines.append("Done when: " + "; ".join(self.success_criteria))
        if self.constraints:
            lines.append("Constraints: " + "; ".join(self.constraints))
        return "\n".join(lines)
