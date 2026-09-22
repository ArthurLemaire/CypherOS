"""Command-line interface: ``openmuse chat | run | serve | goals | reminders | memory | vault | audit | config | daemon``."""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from openmuse import __version__
from openmuse.config import DEFAULT_DATA_DIR, Settings, find_config_file, load_settings

app = typer.Typer(
    name="openmuse",
    help="OpenMuse — an open-source personal AI agent with a Sentinel gatekeeper.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)
goals_app = typer.Typer(help="Manage long-term goals.", no_args_is_help=True)
reminders_app = typer.Typer(help="Reminders and routines.", no_args_is_help=True)
memory_app = typer.Typer(help="Inspect or edit long-term memory.", no_args_is_help=True)
vault_app = typer.Typer(help="Store credentials the model never sees.", no_args_is_help=True)
config_app = typer.Typer(help="Configuration helpers.", no_args_is_help=True)
app.add_typer(goals_app, name="goals")
app.add_typer(reminders_app, name="reminders")
app.add_typer(memory_app, name="memory")
app.add_typer(vault_app, name="vault")
app.add_typer(config_app, name="config")

console = Console()


def _version_flag(value: bool) -> None:
    if value:
        console.print(f"openmuse {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(  # noqa: B008
        False,
        "--version",
        "-V",
        help="Print the version and exit.",
        callback=_version_flag,
        is_eager=True,
    ),
) -> None:
    """OpenMuse — an open-source personal AI agent with a Sentinel gatekeeper."""


ConfigOpt = Annotated[Path | None, typer.Option("--config", "-c", help="Path to config.toml")]
AutoOpt = Annotated[
    bool, typer.Option("--auto", help="Sentinel auto mode: approve everything (unattended)")
]
ThinkOpt = Annotated[bool, typer.Option("--show-thinking", help="Show the model's reasoning")]


def _settings(config: Path | None, auto: bool = False) -> Settings:
    try:
        settings = load_settings(config)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    if auto:
        settings.sentinel.mode = "auto"
    if not settings.llm.api_key and "localhost" not in (settings.llm.base_url or ""):
        console.print(
            "[yellow]No API key configured.[/yellow] Set [bold]llm.api_key[/bold] in config.toml "
            "(run `openmuse config init`) or export DEEPSEEK_API_KEY / OPENAI_API_KEY."
        )
    settings.ensure_dirs()  # the store commands open SQLite files under data_dir directly
    return settings


def _run_async(coro) -> None:  # noqa: ANN001
    """Run a coroutine, turning failures into a short message instead of a traceback."""
    try:
        asyncio.run(coro)
    except KeyboardInterrupt:
        console.print("\n[yellow]interrupted[/yellow]")
        raise typer.Exit(130) from None
    except Exception as exc:  # noqa: BLE001
        console.print(f"[bold red]error:[/bold red] {type(exc).__name__}: {exc}")
        raise typer.Exit(1) from None


def _banner(settings: Settings) -> None:
    console.print(
        f"[bold magenta]OpenMuse[/bold magenta] v{__version__}  ·  model [cyan]{settings.llm.model}[/cyan] "
        f"via {settings.llm.provider}  ·  sentinel [yellow]{settings.sentinel.mode}[/yellow]  ·  "
        f"config [dim]{settings.source}[/dim]"
    )
    if settings.sentinel.mode == "auto":
        console.print(
            "[bold red]⚠ auto mode: the Sentinel will approve every action without asking.[/bold red]"
        )


# ============================================================================ chat / run
@app.command()
def chat(
    config: ConfigOpt = None,
    auto: AutoOpt = False,
    show_thinking: ThinkOpt = False,
    resume: Annotated[
        bool, typer.Option("--resume", help="Continue the most recent session")
    ] = False,
) -> None:
    """Interactive chat with your agent."""
    settings = _settings(config, auto)
    _run_async(_chat(settings, show_thinking or settings.agent.show_thinking, resume))


async def _chat(settings: Settings, show_thinking: bool, resume: bool) -> None:
    from openmuse.app import OpenMuseApp
    from openmuse.console import ConsoleUI

    ui = ConsoleUI(console, show_thinking=show_thinking)
    _banner(settings)
    async with OpenMuseApp(settings, ui) as muse:
        if resume:
            sessions = sorted((settings.data_dir / "sessions").glob("*.json"))
            if sessions:
                n = muse.agent.load_session(sessions[-1])
                console.print(f"[dim]resumed {sessions[-1].name} ({n} messages)[/dim]")
        console.print("[dim]Type your request. /help for commands, /exit to quit.[/dim]\n")
        while True:
            try:
                user = await asyncio.to_thread(
                    Prompt.ask, "[bold green]You[/bold green] ›", console=console
                )
            except (EOFError, KeyboardInterrupt):
                console.print()
                break
            user = user.strip()
            if not user:
                continue
            if user.startswith("/"):
                if await _slash(user, muse):
                    break
                continue
            try:
                await muse.run(user)
            except KeyboardInterrupt:
                console.print("[yellow]interrupted[/yellow]")
                muse.agent.state = muse.agent.state.IDLE
            except Exception as exc:  # noqa: BLE001
                console.print(f"[red]error:[/red] {exc}")
                muse.agent.state = muse.agent.state.IDLE
            console.print()


async def _slash(cmd: str, muse) -> bool:  # noqa: ANN001
    name, _, arg = cmd[1:].partition(" ")
    if name in ("exit", "quit", "q"):
        return True
    if name == "help":
        console.print(
            "/reset – clear conversation   /memory – list memories   /goals – list goals\n"
            "/audit [n] – recent audit entries   /tools – list tools   /tainted – taint status\n"
            "/permissions – what you allowed   /revoke <key> – take one back\n"
            "/forget-approvals – clear every granted permission   /exit – quit"
        )
    elif name == "reset":
        muse.agent.reset()
        console.print("[dim]conversation cleared[/dim]")
    elif name == "memory":
        _print_memories(muse.memory.all() if muse.memory else [])
    elif name == "goals":
        _print_goals(muse.goals.list())
    elif name == "audit":
        _print_audit(muse.audit.tail(int(arg) if arg.isdigit() else 10))
    elif name == "tools":
        for t in muse.tools:
            console.print(f"  [cyan]{t.name}[/cyan] [{t.risk.value}] {t.description[:90]}")
    elif name == "tainted":
        console.print(f"session tainted: {muse.sentinel.tainted}")
    elif name == "permissions":
        grants = muse.sentinel.active_grants()
        if not grants:
            console.print("[dim]no standing permissions[/dim]")
        for g in grants:
            until = {"task": "this task", "session": "until restart", "always": "always"}.get(
                g.scope, f"until {_local_time(g.to_dict()['expires_at'] or '')}"
            )
            console.print(f"  [cyan]{g.key}[/cyan]  {until}")
    elif name == "revoke":
        if muse.sentinel.revoke(arg.strip()):
            console.print(f"[dim]revoked {arg.strip()}[/dim]")
        else:
            console.print(f"[red]no permission '{arg.strip()}' (see /permissions)[/red]")
    elif name == "forget-approvals":
        muse.sentinel.forget_approvals()
        console.print("[dim]approvals cleared[/dim]")
    else:
        console.print(f"[red]unknown command /{name}[/red]")
    return False


@app.command()
def run(
    task: Annotated[str, typer.Argument(help="What should the agent do?")],
    config: ConfigOpt = None,
    auto: AutoOpt = False,
    show_thinking: ThinkOpt = False,
) -> None:
    """Run a single task and exit."""
    settings = _settings(config, auto)

    async def _run() -> None:
        from openmuse.app import OpenMuseApp
        from openmuse.console import ConsoleUI

        ui = ConsoleUI(console, show_thinking=show_thinking or settings.agent.show_thinking)
        _banner(settings)
        async with OpenMuseApp(settings, ui) as muse:
            await muse.run(task)

    _run_async(_run())


@app.command()
def daemon(
    config: ConfigOpt = None,
    interval: Annotated[int, typer.Option(help="Seconds between passes")] = 3600,
    once: Annotated[bool, typer.Option("--once", help="Run one pass and exit")] = False,
) -> None:
    """Keep advancing active goals in the background (Sentinel auto mode)."""
    settings = _settings(config, auto=True)

    async def _loop() -> None:
        from openmuse.app import OpenMuseApp
        from openmuse.console import ConsoleUI

        ui = ConsoleUI(console, quiet=True)
        _banner(settings)
        while True:
            async with OpenMuseApp(settings, ui) as muse:
                active = muse.goals.list("active")
                console.print(f"[dim]{len(active)} active goal(s)[/dim]")
                for goal in active:
                    console.print(f"[bold]▶ {goal.id}: {goal.title}[/bold]")
                    try:
                        summary = await muse.advance_goal(goal.id)
                        console.print(summary)
                    except Exception as exc:  # noqa: BLE001
                        console.print(f"[red]{goal.id} failed: {exc}[/red]")
            if once:
                return
            await asyncio.sleep(interval)

    _run_async(_loop())


@app.command()
def serve(
    config: ConfigOpt = None,
    host: Annotated[
        str | None,
        typer.Option("--host", help="Bind address (0.0.0.0 to reach it from your phone)"),
    ] = None,
    port: Annotated[int | None, typer.Option("--port", "-p", help="Port (default 8787)")] = None,
    no_auth: Annotated[
        bool, typer.Option("--no-auth", help="Disable the access token (local development only)")
    ] = False,
    no_qr: Annotated[bool, typer.Option("--no-qr", help="Do not print the QR code")] = False,
    auto: AutoOpt = False,
) -> None:
    """Run the always-on Muse with the mobile-first web app (chat, goals, ideas, memory, approvals)."""
    settings = _settings(config, auto=auto)
    if no_auth:
        settings.server.auth = False
    _banner(settings)
    try:
        from openmuse.server import serve as _serve
    except ImportError as exc:  # pragma: no cover
        console.print(
            f"[red]server dependencies missing: {exc}[/red]  →  pip install 'openmuse[server]'"
        )
        raise typer.Exit(1) from exc
    try:
        _serve(settings, host=host, port=port, print_qr=not no_qr)
    except KeyboardInterrupt:  # pragma: no cover
        console.print("\n[yellow]stopped[/yellow]")


# ============================================================================ goals
def _print_goals(goals) -> None:  # noqa: ANN001
    if not goals:
        console.print("[dim]no goals[/dim]")
        return
    table = Table(title="Goals")
    table.add_column("id", style="cyan")
    table.add_column("title")
    table.add_column("category")
    table.add_column("status")
    table.add_column("progress")
    table.add_column("due")
    table.add_column("next step")
    for g in goals:
        nxt = g.next_step
        table.add_row(
            g.id,
            g.title,
            g.category or "-",
            g.status,
            g.progress,
            (g.due + (" [red]overdue[/red]" if g.overdue else "")) if g.due else "-",
            f"{nxt.idx}. {nxt.title}" if nxt else "-",
        )
    console.print(table)


@goals_app.command("list")
def goals_list(
    config: ConfigOpt = None, status: str | None = None, category: str | None = None
) -> None:
    """List goals."""
    from openmuse.goals import GoalStore

    s = _settings(config)
    _print_goals(GoalStore(s.goals_db).list(status, category))


@goals_app.command("show")
def goals_show(goal_id: str, config: ConfigOpt = None) -> None:
    """Show one goal with its steps and notes."""
    from openmuse.goals import GoalStore

    s = _settings(config)
    goal = GoalStore(s.goals_db).get(goal_id)
    if not goal:
        console.print(f"[red]no goal {goal_id}[/red]")
        raise typer.Exit(1)
    console.print(goal.render())


@goals_app.command("add")
def goals_add(
    title: str,
    config: ConfigOpt = None,
    description: str = "",
    step: Annotated[
        list[str] | None, typer.Option("--step", "-s", help="Plan step (repeatable)")
    ] = None,
    category: Annotated[
        str, typer.Option(help="health, finance, career, learning, relationships, family, …")
    ] = "",
    due: Annotated[str, typer.Option(help="Target date, YYYY-MM-DD")] = "",
    check_in: Annotated[
        str, typer.Option(help="Reminder cadence, e.g. 'daily 08:00' or 'weekly mon 09:00'")
    ] = "",
) -> None:
    """Create a goal manually."""
    from openmuse.goals import GoalStore

    s = _settings(config)
    try:
        goal = GoalStore(s.goals_db).create(
            title, description, step or [], category=category, due=due, check_in=check_in
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None
    console.print(goal.render())


@goals_app.command("run")
def goals_run(
    goal_id: str, config: ConfigOpt = None, auto: AutoOpt = False, show_thinking: ThinkOpt = False
) -> None:
    """Let the agent advance a goal now."""
    settings = _settings(config, auto)

    async def _run() -> None:
        from openmuse.app import OpenMuseApp
        from openmuse.console import ConsoleUI

        ui = ConsoleUI(console, show_thinking=show_thinking)
        _banner(settings)
        async with OpenMuseApp(settings, ui) as muse:
            await muse.advance_goal(goal_id)

    _run_async(_run())


@goals_app.command("status")
def goals_status(goal_id: str, status: str, config: ConfigOpt = None) -> None:
    """Set goal status: active | paused | done | cancelled."""
    from openmuse.goals import GoalStore

    s = _settings(config)
    goal = GoalStore(s.goals_db).set_status(goal_id, status)
    console.print(goal.render() if goal else f"[red]no goal {goal_id}[/red]")


@goals_app.command("delete")
def goals_delete(goal_id: str, config: ConfigOpt = None) -> None:
    """Delete a goal."""
    from openmuse.goals import GoalStore

    s = _settings(config)
    ok = GoalStore(s.goals_db).delete(goal_id)
    console.print("deleted" if ok else f"[red]no goal {goal_id}[/red]")


# ============================================================================ reminders
@reminders_app.command("list")
def reminders_list(
    config: ConfigOpt = None,
    all: Annotated[bool, typer.Option("--all", help="Include recently finished ones")] = False,  # noqa: A002
) -> None:
    """List reminders and routines, soonest first."""
    from openmuse.reminders import ReminderStore

    s = _settings(config)
    items = ReminderStore(s.reminders_db).list(None if all else "active")
    if not items:
        console.print("[dim]nothing scheduled[/dim]")
        return
    table = Table(title="Reminders")
    table.add_column("id", style="cyan")
    table.add_column("when")
    table.add_column("kind")
    table.add_column("text")
    table.add_column("status")
    for r in items:
        when = r.repeat or (
            datetime.fromisoformat(r.next_at).astimezone().strftime("%Y-%m-%d %H:%M")
            if r.next_at
            else "-"
        )
        table.add_row(r.id, when, r.kind, r.text, r.status)
    console.print(table)


@reminders_app.command("add")
def reminders_add(
    text: str,
    config: ConfigOpt = None,
    at: Annotated[str, typer.Option(help="One-off, local time: 'YYYY-MM-DD HH:MM'")] = "",
    repeat: Annotated[
        str, typer.Option(help="Routine: 'daily 08:00', 'weekdays 07:30', 'weekly mon 09:00'…")
    ] = "",
    task: Annotated[bool, typer.Option("--task", help="Do the work then, not just say it")] = False,
) -> None:
    """Schedule a reminder (or, with --task, a routine the agent carries out)."""
    from openmuse.reminders import ReminderStore

    s = _settings(config)
    try:
        item = ReminderStore(s.reminders_db).create(
            text, at=at, repeat=repeat, kind="task" if task else "remind"
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None
    console.print(item.render(), markup=False)


@reminders_app.command("cancel")
def reminders_cancel(reminder_id: str, config: ConfigOpt = None) -> None:
    """Cancel a reminder or routine."""
    from openmuse.reminders import ReminderStore

    s = _settings(config)
    item = ReminderStore(s.reminders_db).cancel(reminder_id)
    if item is None:
        console.print(f"[red]no active reminder {reminder_id}[/red]")
        raise typer.Exit(1)
    console.print(item.render(), markup=False)


# ============================================================================ memory
def _print_memories(items) -> None:  # noqa: ANN001
    if not items:
        console.print("[dim]no memories[/dim]")
        return
    table = Table(title="Memories")
    table.add_column("id", style="cyan")
    table.add_column("category")
    table.add_column("content")
    table.add_column("created", style="dim")
    for m in items:
        table.add_row(m.id, m.category, m.content, m.created_at[:10])
    console.print(table)


@memory_app.command("list")
def memory_list(config: ConfigOpt = None) -> None:
    """List everything the agent remembers."""
    from openmuse.memory import MemoryStore

    s = _settings(config)
    _print_memories(MemoryStore(s.memory_db).all())


@memory_app.command("add")
def memory_add(content: str, config: ConfigOpt = None, category: str = "profile") -> None:
    """Add a memory manually."""
    from openmuse.memory import MemoryStore

    s = _settings(config)
    item = MemoryStore(s.memory_db).add(content, category, source="user")
    console.print(item.render())


@memory_app.command("forget")
def memory_forget(target: str, config: ConfigOpt = None) -> None:
    """Forget by id (m_xxx) or by matching text."""
    from openmuse.memory import MemoryStore

    s = _settings(config)
    store = MemoryStore(s.memory_db)
    if target.startswith("m_"):
        console.print("forgotten" if store.forget(target) else "not found")
    else:
        console.print(f"forgot {store.forget_matching(target)} memories")


@memory_app.command("tidy")
def memory_tidy(
    config: ConfigOpt = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would change without changing it")
    ] = False,
) -> None:
    """Merge lines that say the same thing, keep the newer fact, drop what was never a fact.

    The model proposes, OpenMuse checks (nothing invented, nothing you wrote dropped),
    and every change is logged so `memory restore` can undo it.
    """
    from openmuse.app import OpenMuseApp
    from openmuse.console import ConsoleUI
    from openmuse.memory import tidy

    s = _settings(config)
    muse = OpenMuseApp(s, ConsoleUI(console))  # resolves a key kept in the vault
    if muse.memory is None:
        console.print("[red]memory is disabled in the config[/red]")
        raise typer.Exit(1)
    store = muse.memory

    async def go() -> None:
        try:
            report = await tidy(store, muse.llm, dry_run=dry_run)
        finally:
            await muse.close()
        lines = report.lines()
        if not lines:
            console.print(f"[dim]{report.considered} memories, nothing to tidy.[/dim]")
        for line in lines:
            console.print(f" - {line}")
        for why in report.skipped:
            console.print(f"[dim] · not applied — {why}[/dim]")
        if report.more:
            console.print("[dim]more was proposed; the next pass continues.[/dim]")
        if not dry_run and report.changed:
            console.print(
                f"[green]{report.changed} change(s); undo with `openmuse memory changes` / `memory restore <id>`.[/green]"
            )

    _run_async(go())


@memory_app.command("changes")
def memory_changes(config: ConfigOpt = None, limit: int = 20) -> None:
    """What tidy-ups and updates changed, newest first."""
    from openmuse.memory import MemoryStore

    s = _settings(config)
    changes = MemoryStore(s.memory_db).history(limit)
    if not changes:
        console.print("[dim]no changes logged[/dim]")
        return
    table = Table(title="Memory changes")
    table.add_column("id", style="cyan")
    table.add_column("when", style="dim")
    table.add_column("change")
    for c in changes:
        before = " + ".join(m.content for m in c.before)
        after = c.after.content if c.after else "—"
        state = " [dim](restored)[/dim]" if c.restored else ""
        table.add_row(c.id, c.at[:16].replace("T", " "), f"{c.action}: {before} → {after}{state}")
    console.print(table)


@memory_app.command("restore")
def memory_restore(change_id: str, config: ConfigOpt = None) -> None:
    """Undo one change by its id (c_xxx): the old lines come back, the new one goes."""
    from openmuse.memory import MemoryStore

    s = _settings(config)
    change = MemoryStore(s.memory_db).restore(change_id)
    if change is None:
        console.print("[red]no such change[/red]")
        raise typer.Exit(1)
    console.print(f"restored: {' + '.join(m.content for m in change.before)}")


@memory_app.command("clear")
def memory_clear(config: ConfigOpt = None, yes: bool = typer.Option(False, "--yes", "-y")) -> None:
    """Delete all memories."""
    from openmuse.memory import MemoryStore

    s = _settings(config)
    if not yes and not typer.confirm("Delete ALL memories?"):
        raise typer.Exit()
    console.print(f"deleted {MemoryStore(s.memory_db).clear()} memories")


# ============================================================================ vault
@vault_app.command("set")
def vault_set(
    name: str,
    config: ConfigOpt = None,
    value: Annotated[
        str | None, typer.Option("--value", help="Secret value (prompted if omitted)")
    ] = None,
) -> None:
    """Store a secret. Reference it as {{vault:NAME}} in config; the model never sees it."""
    from openmuse.vault import CredentialVault

    s = _settings(config)
    s.ensure_dirs()
    secret = (
        value
        if value is not None
        else Prompt.ask(f"Value for {name}", password=True, console=console)
    )
    CredentialVault(s.vault_file, s.vault_key_file).set(name, secret)
    console.print(f"stored [cyan]{name}[/cyan] → use it as [bold]{{{{vault:{name}}}}}[/bold]")


@vault_app.command("list")
def vault_list(config: ConfigOpt = None) -> None:
    """List secret names (never values)."""
    from openmuse.vault import CredentialVault

    s = _settings(config)
    names = CredentialVault(s.vault_file, s.vault_key_file).names()
    console.print("\n".join(names) if names else "[dim]vault is empty[/dim]")


@vault_app.command("delete")
def vault_delete(name: str, config: ConfigOpt = None) -> None:
    """Delete a secret."""
    from openmuse.vault import CredentialVault

    s = _settings(config)
    ok = CredentialVault(s.vault_file, s.vault_key_file).delete(name)
    console.print("deleted" if ok else "not found")


# ============================================================================ audit
def _print_audit(entries) -> None:  # noqa: ANN001
    if not entries:
        console.print("[dim]audit log is empty[/dim]")
        return
    table = Table(title="Audit trail")
    table.add_column("time", style="dim")
    table.add_column("event")
    table.add_column("detail")
    table.add_column("decision")
    for e in entries:
        detail = e.get("summary") or (e.get("content") or "")[:80]
        decision = e.get("decision", "")
        if decision == "deny":
            decision = f"[red]{decision}[/red]"
        elif e.get("approved"):
            decision = f"[green]{decision} (approved)[/green]"
        table.add_row(_local_time(e.get("ts", "")), e.get("event", ""), str(detail)[:100], decision)
    console.print(table)


def _local_time(ts: str) -> str:
    from datetime import datetime

    try:
        return datetime.fromisoformat(ts).astimezone().strftime("%m-%d %H:%M:%S")
    except ValueError:
        return ts[11:19]


@app.command()
def audit(
    config: ConfigOpt = None,
    n: Annotated[int, typer.Option("-n", help="Entries to show")] = 20,
    as_json: Annotated[bool, typer.Option("--json", help="Raw JSON lines")] = False,
) -> None:
    """Show the most recent audit entries."""
    from openmuse.sentinel import AuditLog

    s = _settings(config)
    entries = AuditLog(s.audit_file).tail(n)
    if as_json:
        for e in entries:
            console.print_json(json.dumps(e, ensure_ascii=False))
    else:
        _print_audit(entries)


# ============================================================================ config
@config_app.command("init")
def config_init(
    path: Annotated[Path, typer.Option(help="Where to write config.toml")] = Path(
        "config/config.toml"
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite existing file"),
) -> None:
    """Create a config.toml from the bundled example."""
    here = Path(__file__).resolve().parent
    candidates = [here / "config.example.toml", here.parent / "config" / "config.example.toml"]
    example = next((p for p in candidates if p.exists()), None)
    if path.exists() and not force:
        console.print(f"[yellow]{path} already exists (use --force to overwrite)[/yellow]")
        raise typer.Exit(1)
    path.parent.mkdir(parents=True, exist_ok=True)
    if example is not None:
        shutil.copy(example, path)
    else:  # no example shipped: write a minimal file
        path.write_text(
            '[llm]\nprovider = "openai"\nmodel = "deepseek-flash"\nbase_url = "https://api.deepseek.com"\n'
            'api_key = "${DEEPSEEK_API_KEY}"\n\n[sentinel]\nmode = "ask"\n',
            "utf-8",
        )
    console.print(f"wrote [cyan]{path}[/cyan] – edit llm.api_key / model, then run `openmuse chat`")


@config_app.command("show")
def config_show(config: ConfigOpt = None) -> None:
    """Print the effective configuration (secrets masked)."""
    s = _settings(config)
    data = s.model_dump(mode="json")
    if data["llm"].get("api_key"):
        key = data["llm"]["api_key"]
        data["llm"]["api_key"] = key[:4] + "…" + key[-2:] if len(key) > 8 else "***"
    console.print_json(json.dumps(data, ensure_ascii=False, default=str))


@config_app.command("path")
def config_path() -> None:
    """Show which config file would be used."""
    found = find_config_file()
    console.print(
        str(found)
        if found
        else f"[dim]none found (defaults + env). Data dir: {DEFAULT_DATA_DIR}[/dim]"
    )


@app.command()
def version() -> None:
    """Print the version."""
    console.print(f"openmuse {__version__}")


# ============================================================================ doctor
@app.command()
def doctor(
    config: ConfigOpt = None,
    no_model: Annotated[
        bool, typer.Option("--no-model", help="Do not call the model (offline check)")
    ] = False,
) -> None:
    """Check the installation: config, data, model, connectors. Paste the output into a bug report."""
    settings = _settings(config)
    _run_async(_doctor(settings, check_model=not no_model))


def _mark(ok: bool | None) -> str:
    return "[green]✓[/green]" if ok else ("[yellow]·[/yellow]" if ok is None else "[red]✗[/red]")


async def _doctor(settings: Settings, check_model: bool) -> None:
    import os
    import platform
    import sys

    from openmuse.app import OpenMuseApp
    from openmuse.console import ConsoleUI
    from openmuse.schema import Message
    from openmuse.tools.browser import playwright_available

    problems: list[str] = []

    def line(ok: bool | None, text: str, problem: str | None = None) -> None:
        console.print(f" {_mark(ok)} {text}")
        if ok is False and problem:
            problems.append(problem)

    console.print(
        f"[bold magenta]openmuse {__version__}[/bold magenta] · Python {platform.python_version()} · "
        f"{platform.system()} {platform.release()} · {sys.executable}"
    )
    line(settings.source != "defaults+env" or None, f"config: {settings.source}")
    data_ok = os.access(settings.data_dir, os.W_OK)
    line(data_ok, f"data dir: {settings.data_dir}", "data dir is not writable")
    ws = settings.agent.workspace
    line(ws.is_dir(), f"workspace: {ws}", f"workspace {ws} does not exist")

    llm = settings.llm
    key = llm.api_key or ""
    key_state = "no key"
    app_: OpenMuseApp | None = None
    try:
        app_ = OpenMuseApp(settings, ConsoleUI(console))
    except Exception as exc:  # noqa: BLE001
        line(False, f"could not start: {type(exc).__name__}: {exc}", "the app does not start")
    if app_ is not None and key:
        if app_.vault.has_placeholders(key):
            resolved = app_.vault.resolve(key, strict=False)
            key_state = (
                "key in the vault"
                if not app_.vault.has_placeholders(resolved)
                else "key MISSING from the vault"
            )
        else:
            key_state = "key set"
    local = "localhost" in (llm.base_url or "") or "127.0.0.1" in (llm.base_url or "")
    line(
        ("MISSING" not in key_state) and (bool(key) or local),
        f"model: {llm.model} · {llm.provider} · {llm.base_url or 'provider default'} · "
        f"tools {llm.tool_mode} · {key_state}",
        "no usable API key (set llm.api_key, or enter it under Connections in the app)",
    )
    line(
        None,
        f"sentinel: {settings.sentinel.mode} mode · taint tracking {'on' if settings.sentinel.taint_tracking else 'off'}",
    )

    if app_ is None:
        _doctor_summary(problems)
        return
    try:
        try:
            await app_.start()
            mcp_ok: bool | None = True if settings.mcp.servers else None
        except Exception as exc:  # noqa: BLE001
            mcp_ok = False
            console.print(f"   [red]MCP: {type(exc).__name__}: {exc}[/red]")
        names = sorted(t.name for t in app_.tools if t.name not in {"terminate", "ask_user"})
        line(True, f"tools ({len(names)}): {', '.join(names)}")
        email = settings.connectors.email
        line(
            None,
            f"email: {'on' if email.enabled else 'off'}"
            + (f" · {email.imap_host} / {email.smtp_host}" if email.enabled else ""),
        )
        if settings.browser.enabled:
            line(
                playwright_available(),
                "browser: on"
                + ("" if playwright_available() else " · Playwright is not installed"),
                "browser.enabled but Playwright is missing: pip install 'openmuse[browser]' && playwright install chromium",
            )
        else:
            line(None, "browser: off")
        line(
            mcp_ok,
            f"MCP servers: {len(settings.mcp.servers)}"
            + (
                f" ({', '.join(s.name for s in settings.mcp.servers)})"
                if settings.mcp.servers
                else ""
            ),
            "an MCP server did not connect",
        )
        line(
            None,
            "push notifications: "
            + (
                "keys ready · needs https:// or localhost"
                if (settings.data_dir / "push-vapid.json").exists()
                else "not set up yet (turned on from Settings in the app)"
            ),
        )
        if check_model:
            loop = asyncio.get_running_loop()
            started = loop.time()
            try:
                reply = await asyncio.wait_for(
                    app_.llm.ask([Message.user("Reply with the single word OK.")], tools=None),
                    timeout=45,
                )
                text = (reply.content or "").strip().replace("\n", " ")[:60]
                line(True, f"model call: {int((loop.time() - started) * 1000)} ms · {text!r}")
            except TimeoutError:
                line(False, "model call: no answer within 45 s", "the model did not answer")
            except Exception as exc:  # noqa: BLE001
                line(
                    False,
                    f"model call: {type(exc).__name__}: {str(exc)[:200]}",
                    "the model call failed",
                )
        else:
            line(None, "model call: skipped (--no-model)")
    finally:
        await app_.close()
    _doctor_summary(problems)


def _doctor_summary(problems: list[str]) -> None:
    if problems:
        console.print("\n[bold red]problems:[/bold red]")
        for p in problems:
            console.print(f" - {p}")
        raise typer.Exit(1)
    console.print("\n[green]all good.[/green]")


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
