"""Skills: how a job is done, written down once.

A skill is a folder with a ``SKILL.md`` in it — the `Agent Skills
<https://agentskills.io>`_ format, so recipes written for other agents work here and the
ones written here work there. The file starts with a short front matter (``name``,
``description``, optionally ``license``, ``allowed-tools``, ``metadata``) and continues
with the instructions in Markdown; ``scripts/``, ``references/`` and ``assets/`` next to
it hold what the instructions point at.

The model sees only the index (name and description of each skill) in its system prompt
and loads the instructions of the one it needs with the ``skills`` tool, or the user
invokes one directly by starting a message with ``/name``. Skills come from two places:
the ones shipped with OpenMuse (``openmuse/skills/builtin``) and your own, in
``<data_dir>/skills`` — a folder of yours with a built-in's name replaces it. The agent
can write a skill of its own after a job went well, which asks first: a skill is a
standing instruction, and planting one is the obvious thing for a hostile web page to try.
"""

from __future__ import annotations

import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from openmuse.logger import logger

if TYPE_CHECKING:
    from openmuse.config import SkillsSettings

BUILTIN_DIR = Path(__file__).parent / "builtin"
BUILT_IN = "built-in"
YOURS = "yours"
NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
MAX_SKILL_BYTES = 64 * 1024
RESOURCE_DIRS = ("scripts", "references", "assets")
SLASH = re.compile(r"^/([a-z0-9][a-z0-9-]*)(?:\s+|$)")


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path  # the skill's folder
    source: str = YOURS  # BUILT_IN or YOURS
    license: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    updated_at: float = 0.0

    @property
    def files(self) -> list[Path]:
        """What comes with the instructions, relative to the folder: scripts, references,
        assets — sorted, without the SKILL.md itself or hidden files."""
        out: list[Path] = []
        for sub in RESOURCE_DIRS:
            root = self.path / sub
            if not root.is_dir():
                continue
            for p in sorted(root.rglob("*")):
                if p.is_file() and not any(part.startswith(".") for part in p.parts):
                    out.append(p.relative_to(self.path))
        return out

    def to_dict(self, body: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "enabled": self.enabled,
            "path": str(self.path),
            "files": [str(f) for f in self.files],
            "allowed_tools": self.allowed_tools,
            "metadata": self.metadata,
            "updated_at": datetime.fromtimestamp(self.updated_at)
            .astimezone()
            .isoformat(timespec="seconds")
            if self.updated_at
            else None,
        }
        if body:
            d["body"] = self.body
            d["content"] = self.render()
        return d

    def render(self) -> str:
        """The SKILL.md text, as it would be written."""
        return render_skill(
            self.name,
            self.description,
            self.body,
            license=self.license,
            allowed_tools=self.allowed_tools,
            metadata=self.metadata,
        )

    def instructions(self) -> str:
        """What the model gets when it uses the skill: the body, and where the files are
        (absolute paths — the folder is readable from the sandbox)."""
        text = f"# Skill: {self.name}\n{self.description}\n\n{self.body.strip()}"
        files = self.files
        if files:
            listed = "\n".join(f"- {self.path / f}" for f in files)
            text += f"\n\nFiles that come with this skill (read-only):\n{listed}"
        return text


# ------------------------------------------------------------------ SKILL.md
def _yaml_scalar(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        inner = raw[1:-1]
        return inner.replace('\\"', '"').replace("\\n", "\n") if raw[0] == '"' else inner
    return raw


def _yaml_list(raw: str) -> list[str]:
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        return [_yaml_scalar(x) for x in raw[1:-1].split(",") if x.strip()]
    return [x for x in re.split(r"[,\s]+", raw) if x]


def parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """The ``---`` block at the top of a SKILL.md and the Markdown after it.

    Enough YAML for skills in the wild: ``key: value`` (quoted or not), ``key: [a, b]``
    and ``- item`` lists, one level of nesting for ``metadata``, ``|`` / ``>`` block
    scalars, comments. No YAML library needed — and none of its surprises."""
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() in ("---", "..."))
    except StopIteration:
        return {}, text
    meta: dict[str, Any] = {}
    i = 1
    while i < end:
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        m = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key, rest = m.group(1), m.group(2).strip()
        if rest in ("|", ">", "|-", ">-"):
            block: list[str] = []
            i += 1
            while i < end and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                block.append(lines[i].strip())
                i += 1
            joiner = "\n" if rest.startswith("|") else " "
            meta[key] = joiner.join(block).strip()
            continue
        if rest == "":
            # a nested mapping or a "- item" list on the following indented lines
            nested: dict[str, str] = {}
            items: list[str] = []
            i += 1
            while i < end and lines[i].startswith((" ", "\t")):
                sub = lines[i].strip()
                if sub.startswith("- "):
                    items.append(_yaml_scalar(sub[2:]))
                elif (sm := re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", sub)) is not None:
                    nested[sm.group(1)] = _yaml_scalar(sm.group(2))
                i += 1
            meta[key] = items if items else nested
            continue
        if rest.startswith("["):
            meta[key] = _yaml_list(rest)
        else:
            meta[key] = _yaml_scalar(
                rest.split(" #", 1)[0] if not rest.startswith(('"', "'")) else rest
            )
        i += 1
    return meta, "\n".join(lines[end + 1 :])


def _yaml_quote(value: str) -> str:
    # quoted when YAML would read it as something other than this string
    if (
        value == ""
        or re.search(r"[:#\[\]{}\"'\n]|^\s|\s$|^[-?&*!|>%@`]", value)
        or re.fullmatch(r"[-+]?(\d[\d_]*\.?\d*|\.\d+)([eE][-+]?\d+)?|0x[0-9a-fA-F]+", value)
        or value.lower() in ("true", "false", "yes", "no", "on", "off", "null", "~")
    ):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'
    return value


def render_skill(
    name: str,
    description: str,
    body: str,
    *,
    license: str = "",
    allowed_tools: list[str] | None = None,
    metadata: dict[str, str] | None = None,
) -> str:
    lines = ["---", f"name: {name}", f"description: {_yaml_quote(description.strip())}"]
    if license:
        lines.append(f"license: {_yaml_quote(license)}")
    if allowed_tools:
        lines.append("allowed-tools: " + " ".join(allowed_tools))
    if metadata:
        lines.append("metadata:")
        lines += [f"  {k}: {_yaml_quote(str(v))}" for k, v in metadata.items()]
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body.strip() + "\n"


def load_skill(folder: Path, source: str = YOURS) -> Skill:
    """The skill in ``folder`` (its ``SKILL.md``); raises ``ValueError`` when it is not one."""
    file = folder / "SKILL.md"
    if not file.is_file():
        raise ValueError(f"{folder.name}: no SKILL.md")
    if file.stat().st_size > MAX_SKILL_BYTES:
        raise ValueError(f"{folder.name}: SKILL.md is larger than {MAX_SKILL_BYTES // 1024} KB")
    meta, body = parse_front_matter(file.read_text("utf-8", errors="replace"))
    name = str(meta.get("name") or folder.name).strip()
    if name != folder.name:
        raise ValueError(f"{folder.name}: `name` in SKILL.md is {name!r}; it must match the folder")
    if not NAME_RE.match(name):
        raise ValueError(
            f"{name!r}: a skill name is lowercase letters, digits and hyphens (up to 64 characters)"
        )
    description = str(meta.get("description") or "").strip()
    if not description:
        raise ValueError(f"{name}: SKILL.md needs a `description` in its front matter")
    if not body.strip():
        raise ValueError(f"{name}: SKILL.md has no instructions after the front matter")
    tools = meta.get("allowed-tools") or meta.get("allowed_tools") or []
    if isinstance(tools, str):
        tools = _yaml_list(tools)
    raw_meta = meta.get("metadata")
    metadata = {str(k): str(v) for k, v in raw_meta.items()} if isinstance(raw_meta, dict) else {}
    return Skill(
        name=name,
        description=description[:1024],
        body=body.strip(),
        path=folder,
        source=source,
        license=str(meta.get("license") or ""),
        allowed_tools=[str(t) for t in tools],
        metadata=metadata,
        updated_at=file.stat().st_mtime,
    )


# ------------------------------------------------------------------ the library
class SkillLibrary:
    """Every skill available: the built-in ones and yours, yours winning on a name clash."""

    def __init__(self, settings: SkillsSettings, own_dir: Path, builtin_dir: Path = BUILTIN_DIR):
        self.settings = settings
        self.own_dir = own_dir
        self.builtin_dir = builtin_dir
        self._skills: dict[str, Skill] = {}
        self.errors: dict[str, str] = {}
        self._loaded = 0.0
        self.reload()

    # ---------------------------------------------------------------- loading
    def reload(self) -> None:
        skills: dict[str, Skill] = {}
        errors: dict[str, str] = {}
        for source, root in ((BUILT_IN, self.builtin_dir), (YOURS, self.own_dir)):
            if not root.is_dir():
                continue
            for folder in sorted(root.iterdir()):
                if not folder.is_dir() or folder.name.startswith((".", "_")):
                    continue
                try:
                    skill = load_skill(folder, source)
                except (ValueError, OSError) as exc:
                    errors[folder.name] = str(exc)
                    logger.warning("skill {} skipped: {}", folder.name, exc)
                    continue
                skill.enabled = skill.name not in self.settings.disabled
                skills[skill.name] = skill  # yours come second and replace a built-in
        self._skills = skills
        self.errors = errors
        self._loaded = time.time()

    def _fresh(self) -> None:
        """Pick up folders edited by hand (cheap: one stat per skill folder, at most every
        two seconds)."""
        if time.time() - self._loaded < 2:
            return
        seen: set[str] = set()
        for root in (self.builtin_dir, self.own_dir):
            if root.is_dir():
                seen.update(p.name for p in root.iterdir() if p.is_dir())
        changed = seen != set(self._skills) | set(self.errors) or any(
            (s.path / "SKILL.md").exists() and (s.path / "SKILL.md").stat().st_mtime != s.updated_at
            for s in self._skills.values()
        )
        if changed:
            self.reload()
        else:
            self._loaded = time.time()

    # ---------------------------------------------------------------- reading
    def __len__(self) -> int:
        return len(self.enabled())

    def all(self) -> list[Skill]:
        self._fresh()
        return sorted(self._skills.values(), key=lambda s: s.name)

    def enabled(self) -> list[Skill]:
        return [s for s in self.all() if s.enabled]

    def get(self, name: str) -> Skill | None:
        self._fresh()
        return self._skills.get(name.strip().lower())

    def index(self) -> str:
        """The lines the system prompt carries: one per enabled skill."""
        lines = []
        for s in self.enabled():
            desc = s.description.replace("\n", " ")
            lines.append(f"- {s.name}: {desc[:280]}{'…' if len(desc) > 280 else ''}")
        return "\n".join(lines)

    def expand(self, text: str) -> str:
        """``/name rest`` → the message with the skill's instructions attached, when
        ``name`` is an enabled skill; anything else unchanged."""
        m = SLASH.match(text)
        if not m:
            return text
        skill = self.get(m.group(1))
        if skill is None or not skill.enabled:
            return text
        rest = text[m.end() :].strip()
        head = rest or f"Do the `{skill.name}` job now."
        return f"{head}\n\n[The user invoked the skill `{skill.name}`. Follow it.]\n{skill.instructions()}"

    # ---------------------------------------------------------------- writing
    def save(
        self,
        name: str,
        description: str,
        body: str,
        *,
        license: str = "",
        allowed_tools: list[str] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> Skill:
        """Write (or rewrite) one of your skills. A built-in of the same name is replaced
        by it from then on; its folder is left alone."""
        name = name.strip().lower()
        if not NAME_RE.match(name):
            raise ValueError(
                "a skill name is lowercase letters, digits and hyphens, up to 64 characters "
                "(e.g. weekly-review)"
            )
        if not description.strip():
            raise ValueError("a skill needs a one-line description: when to use it")
        if not body.strip():
            raise ValueError("a skill needs instructions")
        text = render_skill(
            name,
            description,
            body,
            license=license,
            allowed_tools=allowed_tools or [],
            metadata=metadata or {},
        )
        if len(text.encode()) > MAX_SKILL_BYTES:
            raise ValueError(f"a SKILL.md is at most {MAX_SKILL_BYTES // 1024} KB")
        folder = self.own_dir / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(text, "utf-8")
        self.reload()
        skill = self._skills[name]
        return skill

    def save_text(self, text: str, name: str = "") -> Skill:
        """Write a skill from the text of a SKILL.md (pasted, uploaded, fetched)."""
        meta, body = parse_front_matter(text)
        skill_name = str(meta.get("name") or name).strip().lower()
        if not skill_name:
            raise ValueError("the SKILL.md has no `name` in its front matter")
        tools = meta.get("allowed-tools") or meta.get("allowed_tools") or []
        if isinstance(tools, str):
            tools = _yaml_list(tools)
        raw_meta = meta.get("metadata")
        return self.save(
            skill_name,
            str(meta.get("description") or ""),
            body,
            license=str(meta.get("license") or ""),
            allowed_tools=[str(t) for t in tools],
            metadata={str(k): str(v) for k, v in raw_meta.items()}
            if isinstance(raw_meta, dict)
            else {},
        )

    def remove(self, name: str) -> bool:
        """Delete one of your skills (folder and all). Built-ins cannot be removed —
        ``set_enabled(name, False)`` hides one."""
        skill = self.get(name)
        if skill is None or skill.source != YOURS:
            return False
        shutil.rmtree(skill.path, ignore_errors=True)
        self.reload()
        return True

    def set_enabled(self, name: str, enabled: bool) -> Skill | None:
        skill = self.get(name)
        if skill is None:
            return None
        disabled = set(self.settings.disabled)
        (disabled.discard if enabled else disabled.add)(skill.name)
        self.settings.disabled = sorted(disabled)
        skill.enabled = enabled
        return skill

    def status(self) -> dict[str, Any]:
        skills = self.all()
        return {
            "count": len([s for s in skills if s.enabled]),
            "built_in": len([s for s in skills if s.source == BUILT_IN]),
            "yours": len([s for s in skills if s.source == YOURS]),
            "dir": str(self.own_dir),
            "errors": self.errors,
        }


_GITHUB_PAGE = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/(?:tree|blob)/([^/]+)/(.+)$")


def raw_skill_url(url: str) -> str:
    """A GitHub folder or file page → the raw SKILL.md behind it; anything else as is."""
    m = _GITHUB_PAGE.match(url.strip())
    if not m:
        return url.strip()
    owner, repo, ref, path = m.groups()
    path = path.rstrip("/")
    if not path.endswith("SKILL.md"):
        path += "/SKILL.md"
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"


async def fetch_skill_text(url: str) -> str:
    """The text of a SKILL.md at an https link (a raw file, or a GitHub page turned into one).
    ``ValueError`` when it is not one."""
    import httpx

    url = raw_skill_url(url)
    if not url.startswith("https://"):
        raise ValueError("the link must start with https://")
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        r = await client.get(url, headers={"User-Agent": "OpenMuse"})
    if r.status_code >= 400:
        raise ValueError(f"HTTP {r.status_code} for {url}")
    if len(r.content) > MAX_SKILL_BYTES:
        raise ValueError(
            f"that file is larger than a SKILL.md can be ({MAX_SKILL_BYTES // 1024} KB)"
        )
    text = r.content.decode("utf-8", errors="replace")
    if not text.lstrip().startswith("---"):
        raise ValueError("that is not a SKILL.md (it does not start with front matter)")
    return text


__all__ = [
    "BUILTIN_DIR",
    "BUILT_IN",
    "NAME_RE",
    "SLASH",
    "YOURS",
    "Skill",
    "SkillLibrary",
    "fetch_skill_text",
    "load_skill",
    "parse_front_matter",
    "raw_skill_url",
    "render_skill",
]
