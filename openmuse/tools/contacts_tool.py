"""The ``contacts`` tool: who is who, from the user's address book."""

from __future__ import annotations

from typing import Any

from openmuse.contacts import OWN, ContactBook
from openmuse.schema import RiskLevel, ToolResult
from openmuse.tools.base import BaseTool, CallAssessment


class Contacts(BaseTool):
    name: str = "contacts"
    description: str = (
        "The user's address book. Use it whenever the user names a person you need to write "
        "to, call, or know something about — do not guess an address. Actions: `search` — "
        "people matching `query` (a name, nickname, company, email or phone; every word must "
        "match, prefixes count) with their emails and phones; `get` — one person by "
        "`contact_id`; `add` — a person the user tells you how to reach (`name` plus `email`, "
        "`phone`, `org`, `note`, `birthday`), kept in the agent's own book and updated if the "
        "name is already there; `remove` — a person from that own book by `contact_id` "
        "(people from the user's imported address books cannot be removed here); `list` — the "
        "first people alphabetically (`limit`). No match: say so and ask, rather than guess."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["search", "get", "add", "remove", "list"]},
            "query": {"type": "string"},
            "contact_id": {"type": "string"},
            "name": {"type": "string"},
            "email": {"type": "string", "description": "one or more, comma-separated"},
            "phone": {"type": "string"},
            "org": {"type": "string"},
            "note": {"type": "string"},
            "birthday": {"type": "string", "description": "YYYY-MM-DD or --MM-DD"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        "required": ["action"],
    }
    risk: RiskLevel = RiskLevel.SAFE
    # the address book is the user's private data: after a look-up, sending to a new host asks
    reads_private_data: bool = True
    book: ContactBook

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        action = args.get("action", "")
        what = args.get("query") or args.get("name") or args.get("contact_id") or ""
        return CallAssessment(
            risk=RiskLevel.SAFE,
            reads_private_data=action in ("search", "get", "list"),
            summary=f"contacts {action}" + (f" {str(what)[:60]!r}" if what else ""),
        )

    async def execute(
        self,
        action: str = "",
        query: str | None = None,
        contact_id: str | None = None,
        name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        org: str | None = None,
        note: str | None = None,
        birthday: str | None = None,
        limit: int | None = None,
        **_: Any,
    ) -> ToolResult:
        book = self.book
        try:
            if action == "search":
                if not (query or "").strip():
                    return ToolResult.fail("`query` is required")
                hits = book.search(query or "", limit=limit or 8)
                if not hits:
                    return ToolResult(
                        output=f"No one matching {query!r} in the address book "
                        f"({len(book)} people). Ask the user for the address rather than guess; "
                        "`add` it once they tell you."
                    )
                return ToolResult(output=book.render(hits))
            if action == "get":
                if not contact_id:
                    return ToolResult.fail("`contact_id` is required")
                hit = book.get(contact_id)
                if hit is None:
                    return ToolResult.fail(f"no contact {contact_id}")
                return ToolResult(output=hit.render())
            if action == "list":
                people = sorted(book.contacts, key=lambda c: c.name.lower())[: limit or 20]
                if not people:
                    return ToolResult(output="The address book is empty.")
                return ToolResult(
                    output=f"{len(book)} people; the first {len(people)}:\n" + book.render(people)
                )
            if action == "add":
                if not name:
                    return ToolResult.fail("`name` is required")
                contact = book.add(
                    name,
                    email=email or "",
                    phone=phone or "",
                    org=org or "",
                    note=note or "",
                    birthday=birthday or "",
                )
                return ToolResult(output=f"Saved to {OWN}.\n{contact.render()}")
            if action == "remove":
                if not contact_id:
                    return ToolResult.fail("`contact_id` is required")
                gone = book.remove(contact_id)
                if gone is None:
                    hit = book.get(contact_id)
                    if hit is not None:
                        return ToolResult.fail(
                            f"{hit.name} comes from the user's {hit.source!r} address book; "
                            "only people in the agent's own book can be removed here"
                        )
                    return ToolResult.fail(f"no contact {contact_id}")
                return ToolResult(output=f"Removed {gone.name} from {OWN}.")
            return ToolResult.fail(f"unknown action {action!r}")
        except (ValueError, RuntimeError) as exc:
            return ToolResult.fail(str(exc))


__all__ = ["Contacts"]
