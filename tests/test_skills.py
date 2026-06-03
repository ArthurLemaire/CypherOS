"""Skills: SKILL.md parsing, the library (built-in + yours), the tool, the slash
invocation, the API and the CLI."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from openmuse.cli import app as cli_app
from openmuse.config import SandboxSettings, Settings, SkillsSettings, load_app_settings
from openmuse.llm import MockLLM
from openmuse.sandbox import Sandbox
from openmuse.schema import Function, LLMResponse, RiskLevel, ToolCall
from openmuse.server import create_app
from openmuse.server.service import MuseService
from openmuse.skills import (
    BUILT_IN,
    BUILTIN_DIR,
    YOURS,
    SkillLibrary,
    load_skill,
    parse_front_matter,
    raw_skill_url,
    render_skill,
)
from openmuse.skills.library import fetch_skill_text
from openmuse.tools.skills_tool import Skills

APPLE_STYLE = """---
name: expense-report
description: "Turn receipts in the workspace into a monthly expense report: a CSV and a page. Use when the user asks for an expense report or to total receipts."
license: MIT
allowed-tools: files python_execute
metadata:
  author: Sam
  version: "2"
---

# Expense report

1. `files` list `receipts/`.
2. Total by category with `python_execute`.
3. Write `expenses/YYYY-MM.csv` and a page.
"""


def lib_for(tmp_path: Path, disabled: list[str] | None = None) -> SkillLibrary:
    own = tmp_path / "skills"
    own.mkdir(parents=True, exist_ok=True)
    return SkillLibrary(SkillsSettings(disabled=disabled or []), own_dir=own)


# ----------------------------------------------------------------------------- SKILL.md
def test_front_matter_variants():
    meta, body = parse_front_matter(APPLE_STYLE)
    assert meta["name"] == "expense-report" and meta["license"] == "MIT"
    assert meta["description"].startswith("Turn receipts") and ":" in meta["description"]
    assert meta["allowed-tools"] == "files python_execute"
    assert meta["metadata"] == {"author": "Sam", "version": "2"}
    assert body.strip().startswith("# Expense report")
    # lists in both spellings, block scalars, comments, CRLF, no front matter at all
    text = (
        "---\r\nname: x\r\n# a comment\r\ndescription: >\r\n  folded\r\n  lines\r\n"
        "allowed-tools: [shell, files]\r\ntags:\r\n  - a\r\n  - b\r\n---\r\nbody\r\n"
    )
    meta, body = parse_front_matter(text)
    assert meta["description"] == "folded lines" and meta["allowed-tools"] == ["shell", "files"]
    assert meta["tags"] == ["a", "b"] and body.strip() == "body"
    assert parse_front_matter("just text") == ({}, "just text")
    assert parse_front_matter("---\nname: open\nno end") == ({}, "---\nname: open\nno end")
    # the renderer quotes what YAML would misread, and reads its own output back
    out = render_skill(
        "n", 'A "quoted": thing #1', "body", metadata={"version": "1", "ok": "yes", "n": "Sam"}
    )
    meta, _ = parse_front_matter(out)
    assert meta["description"] == 'A "quoted": thing #1'
    assert meta["metadata"] == {"version": "1", "ok": "yes", "n": "Sam"}
    assert 'version: "1"' in out and 'ok: "yes"' in out and "n: Sam" in out


def test_load_skill_checks_the_folder(tmp_path: Path):
    folder = tmp_path / "expense-report"
    folder.mkdir()
    (folder / "SKILL.md").write_text(APPLE_STYLE)
    (folder / "scripts").mkdir()
    (folder / "scripts" / "total.py").write_text("print(1)")
    (folder / "scripts" / ".hidden").write_text("")
    s = load_skill(folder)
    assert s.name == "expense-report" and s.allowed_tools == ["files", "python_execute"]
    assert s.files == [Path("scripts/total.py")] and s.metadata["author"] == "Sam"
    assert str(folder / "scripts" / "total.py") in s.instructions()
    assert s.instructions().startswith("# Skill: expense-report\nTurn receipts")
    # name must match the folder; a description and a body are required
    bad = tmp_path / "other-name"
    bad.mkdir()
    (bad / "SKILL.md").write_text(APPLE_STYLE)
    with pytest.raises(ValueError, match="must match the folder"):
        load_skill(bad)
    (bad / "SKILL.md").write_text("---\nname: other-name\n---\n\nsteps\n")
    with pytest.raises(ValueError, match="needs a `description`"):
        load_skill(bad)
    (bad / "SKILL.md").write_text("---\nname: other-name\ndescription: d\n---\n\n")
    with pytest.raises(ValueError, match="no instructions"):
        load_skill(bad)
    upper = tmp_path / "Bad_Name"
    upper.mkdir()
    (upper / "SKILL.md").write_text("---\ndescription: d\n---\nsteps\n")
    with pytest.raises(ValueError, match="lowercase"):
        load_skill(upper)
    with pytest.raises(ValueError, match="no SKILL.md"):
        load_skill(tmp_path / "missing")


def test_builtin_skills_are_well_formed():
    lib = SkillLibrary(SkillsSettings(), own_dir=Path("/nonexistent/skills"))
    names = [s.name for s in lib.all()]
    assert names == sorted(names) and len(names) >= 5
    assert {"weekly-review", "trip-plan", "inbox-triage", "compare-options", "meeting-prep"} <= set(
        names
    )
    assert lib.errors == {} and all(s.source == BUILT_IN for s in lib.all())
    for s in lib.all():
        assert len(s.description) <= 300, f"{s.name}: the index line would be cut"
        assert "Use when" in s.description, f"{s.name}: says when to use it"
        assert (BUILTIN_DIR / s.name / "SKILL.md").exists()
    index = lib.index()
    assert index.count("\n") == len(names) - 1 and "…" not in index


def test_skills_dir_setting(tmp_path: Path):
    # an empty string (the documented "unset") must not become the current directory
    s = Settings.model_validate({"data_dir": str(tmp_path), "skills": {"dir": ""}})
    assert s.skills.dir is None and s.skills_dir == tmp_path / "skills"
    s = Settings.model_validate({"data_dir": str(tmp_path), "skills": {"dir": "~/my-skills"}})
    assert s.skills_dir == Path.home() / "my-skills"


# ----------------------------------------------------------------------------- library
def test_library_yours_override_disable_and_expand(tmp_path: Path):
    lib = lib_for(tmp_path)
    n_builtin = len(lib.all())
    # save one of yours
    s = lib.save(
        "Expense-Report", "Total receipts. Use when asked for an expense report.", "1. do it"
    )
    assert s.name == "expense-report" and s.source == YOURS and s.enabled
    assert (
        (tmp_path / "skills" / "expense-report" / "SKILL.md")
        .read_text()
        .startswith("---\nname: expense-report\n")
    )
    assert len(lib.all()) == n_builtin + 1 and "- expense-report: Total receipts" in lib.index()
    # yours with a built-in's name replaces it
    mine = lib.save("weekly-review", "My own review. Use when I say review.", "# Mine\nsteps")
    assert mine.source == YOURS and lib.get("weekly-review").body == "# Mine\nsteps"
    assert len(lib.all()) == n_builtin + 1
    assert (BUILTIN_DIR / "weekly-review" / "SKILL.md").exists(), "the built-in folder is untouched"
    # remove yours: the built-in is back
    assert lib.remove("weekly-review") and lib.get("weekly-review").source == BUILT_IN
    assert not lib.remove("trip-plan"), "built-ins are not removable"
    # disabled: out of the index and of expand, still listed
    assert lib.set_enabled("trip-plan", False).enabled is False
    assert lib.settings.disabled == ["trip-plan"] and "trip-plan" not in lib.index()
    assert len(lib) == n_builtin and lib.get("trip-plan") is not None
    assert lib.expand("/trip-plan Kyoto") == "/trip-plan Kyoto"
    lib.set_enabled("trip-plan", True)
    # /name rest → the message plus the instructions
    out = lib.expand("/trip-plan Kyoto, 4 days")
    assert out.startswith("Kyoto, 4 days\n\n[The user invoked the skill `trip-plan`. Follow it.]\n")
    assert "# Skill: trip-plan" in out and "## Itinerary" in out
    assert lib.expand("/expense-report").startswith("Do the `expense-report` job now.\n")
    assert lib.expand("/nope hi") == "/nope hi" and lib.expand("hello") == "hello"
    assert lib.expand("/trip-planner x") == "/trip-planner x", "a prefix is not the skill"
    # validation
    with pytest.raises(ValueError, match="lowercase"):
        lib.save("Bad Name!", "d", "b")
    with pytest.raises(ValueError, match="description"):
        lib.save("ok-name", "", "b")
    with pytest.raises(ValueError, match="instructions"):
        lib.save("ok-name", "d", "  ")
    # a folder edited by hand is picked up
    folder = tmp_path / "skills" / "handmade"
    folder.mkdir()
    (folder / "SKILL.md").write_text(
        "---\nname: handmade\ndescription: By hand. Use when.\n---\nsteps\n"
    )
    lib._loaded = 0  # the freshness check is rate-limited; pretend time passed
    assert lib.get("handmade") is not None and lib.get("handmade").source == YOURS
    # a broken folder is reported, not fatal
    broken = tmp_path / "skills" / "broken"
    broken.mkdir()
    (broken / "SKILL.md").write_text("no front matter")
    lib.reload()
    assert "broken" in lib.errors and lib.get("handmade") is not None
    assert lib.status()["yours"] == 2 and lib.status()["errors"]["broken"]


def test_save_text_and_raw_urls(tmp_path: Path):
    lib = lib_for(tmp_path)
    s = lib.save_text(APPLE_STYLE)
    assert s.name == "expense-report" and s.license == "MIT" and s.metadata["version"] == "2"
    assert s.allowed_tools == ["files", "python_execute"]
    with pytest.raises(ValueError, match="no `name`"):
        lib.save_text("---\ndescription: d\n---\nbody")
    assert lib.save_text("---\ndescription: d\n---\nbody", name="from-folder").name == "from-folder"
    assert (
        raw_skill_url("https://github.com/o/r/tree/main/skills/pdf")
        == "https://raw.githubusercontent.com/o/r/main/skills/pdf/SKILL.md"
    )
    assert (
        raw_skill_url("https://github.com/o/r/blob/v1/skills/pdf/SKILL.md")
        == "https://raw.githubusercontent.com/o/r/v1/skills/pdf/SKILL.md"
    )
    assert raw_skill_url("https://example.com/x/SKILL.md ") == "https://example.com/x/SKILL.md"


async def test_fetch_skill_text(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("good/SKILL.md"):
            return httpx.Response(200, text=APPLE_STYLE)
        if request.url.path.endswith("page/SKILL.md"):
            return httpx.Response(200, text="<html>not a skill</html>")
        return httpx.Response(404)

    real = httpx.AsyncClient

    def client(**kw):  # noqa: ANN003
        kw["transport"] = httpx.MockTransport(handler)
        return real(**kw)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    text = await fetch_skill_text("https://github.com/o/r/tree/main/good")
    assert text == APPLE_STYLE
    with pytest.raises(ValueError, match="not a SKILL.md"):
        await fetch_skill_text("https://x.example/page/SKILL.md")
    with pytest.raises(ValueError, match="HTTP 404"):
        await fetch_skill_text("https://x.example/missing/SKILL.md")
    with pytest.raises(ValueError, match="https://"):
        await fetch_skill_text("http://x.example/good/SKILL.md")


# ----------------------------------------------------------------------------- the tool
async def test_skills_tool(tmp_path: Path):
    lib = lib_for(tmp_path)
    tool = Skills(library=lib)
    assert tool.risk == RiskLevel.SAFE
    # reading is safe; writing a standing instruction is sensitive and names the skill
    assert tool.assess({"action": "use", "name": "trip-plan"}).risk == RiskLevel.SAFE
    a = tool.assess({"action": "save", "name": "Expense-Report", "description": "Totals.\nMore"})
    assert a.risk == RiskLevel.SENSITIVE and a.target == "expense-report"
    assert a.summary == "skills save 'expense-report': Totals. More" and not a.warnings
    b = tool.assess({"action": "save", "name": "trip-plan", "description": "x"})
    assert b.warnings == ["this replaces one of the built-in skills"]
    assert tool.assess({"action": "remove", "name": "x"}).risk == RiskLevel.SENSITIVE
    r = await tool.execute(action="list")
    assert r.ok and r.output.startswith("5 skills:\n- compare-options (built-in)")
    r = await tool.execute(action="use", name="trip-plan")
    assert r.ok and r.output.startswith("# Skill: trip-plan\n") and "## Research" in r.output
    r = await tool.execute(action="use", name="nope")
    assert not r.ok and "available: compare-options" in r.error
    assert not (await tool.execute(action="use")).ok
    r = await tool.execute(
        action="save",
        name="expense-report",
        description="Total receipts. Use when asked for an expense report.",
        instructions="1. list receipts\n2. total them",
    )
    assert (
        r.ok
        and r.output.startswith("Saved skill `expense-report` to")
        and "/expense-report" in r.output
    )
    assert lib.get("expense-report").body == "1. list receipts\n2. total them"
    r = await tool.execute(action="save", name="bad name", description="d", instructions="i")
    assert not r.ok and "lowercase" in r.error
    r = await tool.execute(action="remove", name="trip-plan")
    assert not r.ok and "built-in" in r.error
    r = await tool.execute(action="remove", name="expense-report")
    assert r.ok and lib.get("expense-report") is None
    assert not (await tool.execute(action="remove", name="expense-report")).ok
    assert not (await tool.execute(action="dance")).ok


# ----------------------------------------------------------------------------- sandbox
def test_skill_folders_are_readable_in_the_box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("openmuse.sandbox.shutil.which", lambda _name: "/usr/bin/bwrap")
    monkeypatch.setattr("openmuse.sandbox.platform.system", lambda: "Linux")
    ws = tmp_path / "ws"
    data = ws / ".openmuse"  # a data dir inside the workspace: masked …
    skills = data / "skills"  # … but the skills under it are bound back, read-only
    skills.mkdir(parents=True)
    box = Sandbox(
        SandboxSettings(),
        workspace=ws,
        data_dir=data,
        ro_roots=[skills, BUILTIN_DIR, tmp_path / "missing"],
        probe=False,
    )
    joined = " ".join(box.wrap(["/bin/true"], network=False, cwd=ws))
    assert f"--tmpfs {data}" in joined
    assert joined.index(f"--tmpfs {data}") < joined.index(f"--ro-bind-try {skills} {skills}")
    assert f"--ro-bind-try {BUILTIN_DIR.resolve()} {BUILTIN_DIR.resolve()}" in joined
    assert "missing" not in joined
    # a skills dir inside a writable root and not under the mask needs no binding of its own
    inside = ws / "skills"
    inside.mkdir()
    box2 = Sandbox(SandboxSettings(), workspace=ws, ro_roots=[inside], probe=False)
    assert f"--ro-bind-try {inside}" not in " ".join(
        box2.wrap(["/bin/true"], network=False, cwd=ws)
    )


# ----------------------------------------------------------------------------- the app
def tc(tool: str, **args: object) -> ToolCall:
    return ToolCall(function=Function(name=tool, arguments=json.dumps(args)))


def wait_for(pred, timeout: float = 5.0):  # noqa: ANN001
    deadline = time.time() + timeout
    while time.time() < deadline:
        if value := pred():
            return value
        time.sleep(0.05)
    raise AssertionError("timed out")


def test_skills_in_the_app(settings: Settings, tmp_path: Path):
    settings.server.token = "secret-token"
    llm = MockLLM([])
    service = MuseService(settings, llm=llm)
    app = create_app(settings, service)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer secret-token"
        assert "skills" in service.app.tools
        view = client.get("/api/skills").json()
        assert view["count"] >= 5 and view["yours"] == 0 and view["dir"] == str(settings.skills_dir)
        assert client.get("/api/settings").json()["skills"] == {
            "enabled": True,
            "count": view["count"],
            "yours": 0,
        }
        one = client.get("/api/skills/trip-plan").json()
        assert one["source"] == BUILT_IN and one["content"].startswith("---\nname: trip-plan")
        assert one["body"].startswith("# Trip plan") and one["files"] == []
        assert client.get("/api/skills/nope").status_code == 404
        # the system prompt carries the index, and a slash message the instructions
        prompt = service.threads["main"].agent.build_system_prompt("hi")
        assert "## Skills" in prompt and "- trip-plan: Plan a trip" in prompt
        assert "call `skills` action=use" in prompt
        # write one of yours from the app
        r = client.put("/api/skills/expense-report", json={"content": APPLE_STYLE})
        assert r.status_code == 200 and r.json()["source"] == YOURS
        assert (settings.skills_dir / "expense-report" / "SKILL.md").exists()
        assert client.get("/api/skills").json()["yours"] == 1
        r = client.put("/api/skills/expense-report", json={"content": "no front matter"})
        assert r.status_code == 400
        # switch a built-in off: persisted, out of the prompt, back on again
        r = client.post("/api/skills/trip-plan/enabled", json={"enabled": False})
        assert r.status_code == 200 and r.json()["enabled"] is False
        assert load_app_settings(settings.data_dir)["skills"]["disabled"] == ["trip-plan"]
        assert "- trip-plan:" not in service.threads["main"].agent.build_system_prompt("hi")
        assert client.post("/api/skills/trip-plan/enabled", json={"enabled": True}).json()[
            "enabled"
        ]
        assert client.post("/api/skills/nope/enabled", json={"enabled": True}).status_code == 404
        # /expense-report in chat: the model gets the instructions with the message
        llm.script.append(LLMResponse(content="On it."))
        client.post("/api/threads/main/send", json={"text": "/expense-report for March"})
        wait_for(lambda: llm.calls)
        sent = llm.calls[-1]["messages"][-1].content
        assert sent.startswith(
            "for March\n\n[The user invoked the skill `expense-report`. Follow it.]"
        )
        assert "# Expense report" in sent
        events = client.get("/api/threads/main/events").json()["events"]
        assert [e["text"] for e in events if e["type"] == "user"] == ["/expense-report for March"]
        # the agent saves a skill: an approval card, then the file
        wait_for(lambda: not service.threads["main"].busy)
        llm.script.extend(
            [
                LLMResponse(
                    content="Saving.",
                    tool_calls=[
                        tc(
                            "skills",
                            action="save",
                            name="rent-reminder",
                            description="Remind about rent. Use when the month ends.",
                            instructions="1. set a reminder\n2. draft the transfer note",
                        )
                    ],
                ),
                LLMResponse(content="Saved."),
            ]
        )
        client.post("/api/threads/main/send", json={"text": "save that as a skill"})
        card = wait_for(
            lambda: [
                e
                for e in client.get("/api/threads/main/events").json()["events"]
                if e["type"] == "approval" and e["status"] == "pending"
            ]
        )[0]
        assert card["tool"] == "skills" and card["risk"] == "sensitive"
        assert card["summary"].startswith("skills save 'rent-reminder': Remind about rent")
        client.post(f"/api/approvals/{card['id']}", json={"approved": True, "scope": "once"})
        wait_for(lambda: (settings.skills_dir / "rent-reminder" / "SKILL.md").exists())
        assert client.get("/api/skills/rent-reminder").json()["source"] == YOURS
        # remove yours; built-ins are not removable
        assert client.delete("/api/skills/rent-reminder").status_code == 200
        assert client.delete("/api/skills/trip-plan").status_code == 404
        assert client.get("/api/skills").json()["yours"] == 1
        # import from a link (mocked transport)
        import httpx

        real = httpx.AsyncClient

        def fake_client(**kw):  # noqa: ANN003
            kw["transport"] = httpx.MockTransport(
                lambda req: httpx.Response(
                    200, text=APPLE_STYLE.replace("expense-report", "receipts")
                )
            )
            return real(**kw)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx, "AsyncClient", fake_client)
            r = client.post(
                "/api/skills/import", json={"url": "https://github.com/o/r/tree/main/receipts"}
            )
        assert r.status_code == 200 and r.json()["name"] == "receipts"
        r = client.post("/api/skills/import", json={"url": "http://insecure.example/SKILL.md"})
        assert r.status_code == 400


def test_skills_off(settings: Settings):
    settings.skills.enabled = False
    service = MuseService(settings, llm=MockLLM([]))
    assert "skills" not in service.app.tools
    assert "## Skills" not in service.threads["main"].agent.build_system_prompt("hi")
    assert service.settings_view()["skills"]["enabled"] is False


# ----------------------------------------------------------------------------- CLI
def test_skills_cli(settings: Settings, tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'data_dir = "{settings.data_dir}"\n[agent]\nworkspace = "{settings.agent.workspace}"\n'
        '[llm]\napi_key = "test"\n'
    )
    runner = CliRunner()
    strip = lambda s: re.sub(r"\x1b\[[0-9;]*m", "", s)  # noqa: E731
    r = runner.invoke(cli_app, ["skills", "list", "-c", str(cfg)])
    assert r.exit_code == 0 and "weekly-review" in r.output and "built-in" in r.output
    r = runner.invoke(cli_app, ["skills", "show", "trip-plan", "-c", str(cfg)])
    assert r.exit_code == 0 and "name: trip-plan" in r.output and "## Itinerary" in r.output
    assert runner.invoke(cli_app, ["skills", "show", "nope", "-c", str(cfg)]).exit_code == 1
    # add from a folder with scripts
    src = tmp_path / "expense-report"
    (src / "scripts").mkdir(parents=True)
    (src / "SKILL.md").write_text(APPLE_STYLE)
    (src / "scripts" / "total.py").write_text("print(1)")
    r = runner.invoke(cli_app, ["skills", "add", str(src), "-c", str(cfg)])
    assert r.exit_code == 0 and "added expense-report" in strip(r.output)
    assert (settings.skills_dir / "expense-report" / "scripts" / "total.py").exists()
    r = runner.invoke(cli_app, ["skills", "add", str(tmp_path / "nothing.md"), "-c", str(cfg)])
    assert r.exit_code == 1
    # new: a scaffold to fill in
    r = runner.invoke(cli_app, ["skills", "new", "rent-check", "-c", str(cfg)])
    assert r.exit_code == 0 and (settings.skills_dir / "rent-check" / "SKILL.md").exists()
    assert runner.invoke(cli_app, ["skills", "new", "rent-check", "-c", str(cfg)]).exit_code == 1
    assert runner.invoke(cli_app, ["skills", "new", "Bad Name", "-c", str(cfg)]).exit_code == 1
    # disable / enable persist through app settings
    r = runner.invoke(cli_app, ["skills", "disable", "trip-plan", "-c", str(cfg)])
    assert r.exit_code == 0 and load_app_settings(settings.data_dir)["skills"]["disabled"] == [
        "trip-plan"
    ]
    r = runner.invoke(cli_app, ["skills", "list", "-c", str(cfg)])
    assert re.search(r"trip-plan\s+│\s+built-in\s+│\s+no", strip(r.output))
    r = runner.invoke(cli_app, ["skills", "enable", "trip-plan", "-c", str(cfg)])
    assert r.exit_code == 0 and load_app_settings(settings.data_dir)["skills"]["disabled"] == []
    assert runner.invoke(cli_app, ["skills", "enable", "nope", "-c", str(cfg)]).exit_code == 1
    # remove
    r = runner.invoke(cli_app, ["skills", "remove", "expense-report", "-c", str(cfg)])
    assert r.exit_code == 0 and not (settings.skills_dir / "expense-report").exists()
    assert runner.invoke(cli_app, ["skills", "remove", "trip-plan", "-c", str(cfg)]).exit_code == 1
    r = runner.invoke(cli_app, ["doctor", "--no-model", "-c", str(cfg)])
    assert re.search(r"skills: \d+ on · \d+ built-in, 1 yours", strip(r.output))
