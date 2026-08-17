"""Command-line interface: ``openmuse chat | run | serve | goals | memory | vault | audit | config | daemon``."""

from __future__ import annotations

import asyncio
import json
import shutil
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
memory_app = typer.Typer(help="Inspect or edit long-term memory.", no_args_is_help=True)
vault_app = typer.Typer(help="Store credentials the model never sees.", no_args_is_help=True)
config_app = typer.Typer(help="Configuration helpers.", no_args_is_help=True)
app.add_typer(goals_app, name="goals")
app.add_typer(memory_app, name="memory")
app.add_typer(vault_app, name="vault")
app.add_typer(config_app, name="config")

console = Console()

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
            "/forget-approvals – clear session/persistent approvals   /exit – quit"
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
    table.add_column("status")
    table.add_column("progress")
    table.add_column("next step")
    for g in goals:
        nxt = g.next_step
        table.add_row(
            g.id, g.title, g.status, g.progress, f"{nxt.idx}. {nxt.title}" if nxt else "-"
        )
    console.print(table)


@goals_app.command("list")
def goals_list(config: ConfigOpt = None, status: str | None = None) -> None:
    """List goals."""
    from openmuse.goals import GoalStore

    s = _settings(config)
    _print_goals(GoalStore(s.goals_db).list(status))


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
) -> None:
    """Create a goal manually."""
    from openmuse.goals import GoalStore

    s = _settings(config)
    goal = GoalStore(s.goals_db).create(title, description, step or [])
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
    example = Path(__file__).resolve().parent.parent / "config" / "config.example.toml"
    if path.exists() and not force:
        console.print(f"[yellow]{path} already exists (use --force to overwrite)[/yellow]")
        raise typer.Exit(1)
    path.parent.mkdir(parents=True, exist_ok=True)
    if example.exists():
        shutil.copy(example, path)
    else:  # installed as a wheel without the example: write a minimal file
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


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
