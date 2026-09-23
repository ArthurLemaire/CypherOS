"""Command-line interface: ``openmuse chat | run | serve | goals | reminders | memory | vault | audit | config | daemon``."""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

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
triggers_app = typer.Typer(
    help="Triggers: work that starts from new mail, a calendar event or a webhook.",
    no_args_is_help=True,
)
memory_app = typer.Typer(help="Inspect or edit long-term memory.", no_args_is_help=True)
calendar_app = typer.Typer(
    help="The calendar feeds: agenda, free time, links.", no_args_is_help=True
)
contacts_app = typer.Typer(
    help="The address book: look people up, connect .vcf exports.", no_args_is_help=True
)
skills_app = typer.Typer(
    help="Skills: how a job is done, written down (SKILL.md folders).", no_args_is_help=True
)
vault_app = typer.Typer(help="Store credentials the model never sees.", no_args_is_help=True)
config_app = typer.Typer(help="Configuration helpers.", no_args_is_help=True)
app.add_typer(goals_app, name="goals")
app.add_typer(reminders_app, name="reminders")
app.add_typer(triggers_app, name="triggers")
app.add_typer(memory_app, name="memory")
app.add_typer(calendar_app, name="calendar")
app.add_typer(contacts_app, name="contacts")
app.add_typer(skills_app, name="skills")
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

    ui = ConsoleUI(console, show_thinking=show_thinking, name=settings.agent.name)
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

        ui = ConsoleUI(
            console,
            show_thinking=show_thinking or settings.agent.show_thinking,
            name=settings.agent.name,
        )
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
    """Run the always-on OpenMuse with the mobile-first web app (chat, goals, ideas, memory, approvals)."""
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

        ui = ConsoleUI(console, show_thinking=show_thinking, name=settings.agent.name)
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


# ============================================================================ calendar
def _calendar(config: Path | None):  # noqa: ANN202
    from openmuse.calendar import CalendarFeeds
    from openmuse.vault import CredentialVault

    s = _settings(config)
    vault = CredentialVault(s.vault_file, s.vault_key_file)
    return s, CalendarFeeds(s.connectors.calendar, vault=vault, cache_file=s.calendar_cache)


@calendar_app.command("agenda")
def calendar_agenda(
    config: ConfigOpt = None,
    day: Annotated[str, typer.Option(help="'today', 'tomorrow' or YYYY-MM-DD")] = "today",
    days: Annotated[int, typer.Option(min=1, max=31)] = 1,
    refresh: Annotated[
        bool, typer.Option("--refresh", help="Fetch the feeds even if fresh")
    ] = False,
) -> None:
    """What is on the calendar, grouped by day."""
    from openmuse.tools.calendar_tool import _parse_day

    s, feeds = _calendar(config)
    if not feeds.configured:
        console.print("[yellow]no calendar feeds — `openmuse calendar add NAME URL`[/yellow]")
        raise typer.Exit(1)
    _run_async(feeds.refresh(force=refresh))
    today = datetime.now(feeds.tz).date()
    try:
        start = _parse_day(day, today)
    except ValueError:
        console.print(f"[red]not a day: {day}[/red]")
        raise typer.Exit(1) from None
    console.print(feeds.render(feeds.agenda(start, days), today), markup=False)
    for state in feeds.states.values():
        if state.error:
            console.print(f"[yellow]{state.name}: {state.error}[/yellow]")


@calendar_app.command("free")
def calendar_free(
    config: ConfigOpt = None,
    day: Annotated[str, typer.Option(help="'today', 'tomorrow' or YYYY-MM-DD")] = "today",
    minutes: Annotated[int, typer.Option(min=5, help="Shortest gap worth listing")] = 30,
) -> None:
    """Free gaps in the working hours of a day."""
    from openmuse.tools.calendar_tool import _parse_day

    s, feeds = _calendar(config)
    if not feeds.configured:
        console.print("[yellow]no calendar feeds — `openmuse calendar add NAME URL`[/yellow]")
        raise typer.Exit(1)
    _run_async(feeds.refresh())
    today = datetime.now(feeds.tz).date()
    d = _parse_day(day, today)
    cal = s.connectors.calendar
    slots = feeds.free_slots(d, minutes, cal.day_start, cal.day_end)
    if not slots:
        console.print(
            f"[dim]no gap of {minutes}+ min on {d:%a %Y-%m-%d} ({cal.day_start}–{cal.day_end})[/dim]"
        )
        return
    for sl in slots:
        console.print(f"{sl.start:%H:%M}–{sl.end:%H:%M}  ({sl.minutes} min)")


@calendar_app.command("feeds")
def calendar_feeds(config: ConfigOpt = None) -> None:
    """The connected calendars and when they were last read."""
    s, feeds = _calendar(config)
    if not s.connectors.calendar.feeds:
        console.print("[dim]no calendar feeds[/dim]")
        return
    table = Table(title="Calendar feeds" + ("" if s.connectors.calendar.enabled else " (off)"))
    table.add_column("name", style="cyan")
    table.add_column("link")
    table.add_column("events")
    table.add_column("read")
    table.add_column("error")
    status = {f["name"]: f for f in feeds.status()["feeds"]}
    for f in s.connectors.calendar.feeds:
        st = status.get(f.name, {})
        link = f.url if "{{vault:" in f.url else (f.url[:40] + "…" if len(f.url) > 40 else f.url)
        table.add_row(
            f.name,
            link,
            str(st.get("events", 0)),
            st.get("fetched_at") or "-",
            st.get("error") or "",
        )
    console.print(table)


@calendar_app.command("add")
def calendar_add(name: str, url: str, config: ConfigOpt = None) -> None:
    """Connect a calendar by its private .ics link (or a path to an .ics file).

    The link is kept in the vault; app-settings.json refers to it as {{vault:CALENDAR_NAME}}.
    """
    import re

    from openmuse.config import apply_app_settings, load_app_settings, save_app_settings
    from openmuse.vault import CredentialVault

    s = _settings(config)
    secret = "CALENDAR_" + (re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_") or "FEED")
    CredentialVault(s.vault_file, s.vault_key_file).set(secret, url.strip())
    data = load_app_settings(s.data_dir)
    cal = dict(data.get("calendar") or {})
    feeds = [f for f in cal.get("feeds") or [] if f.get("name") != name]
    feeds.append({"name": name, "url": f"{{{{vault:{secret}}}}}"})
    cal["feeds"], cal["enabled"] = feeds, True
    data["calendar"] = cal
    save_app_settings(s.data_dir, data)
    apply_app_settings(s, {"calendar": cal})
    _, reader = _calendar(config)
    status = asyncio.run(reader.refresh(force=True))
    st: dict[str, Any] = next((f for f in status["feeds"] if f["name"] == name), {})
    if st.get("error"):
        console.print(f"[yellow]added, but reading it failed: {st['error']}[/yellow]")
        raise typer.Exit(1)
    console.print(f"[green]added {name}: {st.get('events', 0)} events[/green]")


@calendar_app.command("remove")
def calendar_remove(name: str, config: ConfigOpt = None) -> None:
    """Disconnect a calendar added with `calendar add` (feeds in config.toml are removed there)."""
    import re

    from openmuse.config import load_app_settings, save_app_settings
    from openmuse.vault import CredentialVault

    s = _settings(config)
    data = load_app_settings(s.data_dir)
    cal = dict(data.get("calendar") or {})
    feeds = cal.get("feeds") or []
    if not any(f.get("name") == name for f in feeds):
        console.print(f"[red]no calendar '{name}' was added from the app or the CLI[/red]")
        raise typer.Exit(1)
    cal["feeds"] = [f for f in feeds if f.get("name") != name]
    data["calendar"] = cal
    save_app_settings(s.data_dir, data)
    secret = "CALENDAR_" + (re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_") or "FEED")
    CredentialVault(s.vault_file, s.vault_key_file).delete(secret)
    console.print(f"removed {name}")


# ============================================================================ contacts
def _contacts(config: Path | None):  # noqa: ANN202
    from openmuse.contacts import ContactBook
    from openmuse.vault import CredentialVault

    s = _settings(config)
    vault = CredentialVault(s.vault_file, s.vault_key_file)
    return s, ContactBook(
        s.connectors.contacts,
        vault=vault,
        own_file=s.contacts_file,
        cache_file=s.contacts_cache,
    )


@contacts_app.command("search")
def contacts_search(
    query: str,
    config: ConfigOpt = None,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 8,
) -> None:
    """Find people by name, nickname, company, email or phone — as the agent does."""
    _, book = _contacts(config)
    hits = book.search(query, limit=limit)
    if not hits:
        console.print(f"[dim]no one matching '{query}' ({len(book)} people)[/dim]")
        raise typer.Exit(1)
    console.print(book.render(hits), markup=False)  # ids in [brackets] are not styles


@contacts_app.command("list")
def contacts_list(
    config: ConfigOpt = None, limit: Annotated[int, typer.Option("--limit", "-n")] = 20
) -> None:
    """The first people alphabetically."""
    _, book = _contacts(config)
    people = sorted(book.contacts, key=lambda c: c.name.lower())[:limit]
    if not people:
        console.print("[dim]the address book is empty[/dim]")
        return
    console.print(f"[dim]{len(book)} people; the first {len(people)}[/dim]")
    console.print(book.render(people), markup=False)


@contacts_app.command("add")
def contacts_add(
    name: str,
    config: ConfigOpt = None,
    email: Annotated[str, typer.Option("--email", "-e")] = "",
    phone: Annotated[str, typer.Option("--phone", "-p")] = "",
    org: Annotated[str, typer.Option("--org")] = "",
    note: Annotated[str, typer.Option("--note")] = "",
    birthday: Annotated[str, typer.Option("--birthday")] = "",
) -> None:
    """Put a person in the agent's own book (<data_dir>/contacts.vcf), or update them."""
    _, book = _contacts(config)
    try:
        contact = book.add(name, email=email, phone=phone, org=org, note=note, birthday=birthday)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(contact.render(), markup=False)


@contacts_app.command("sources")
def contacts_sources(config: ConfigOpt = None) -> None:
    """The connected address books and how many people each has."""
    from openmuse.contacts import OWN

    s, book = _contacts(config)
    asyncio.run(book.refresh())
    status = {c["name"]: c for c in book.status()["sources"]}
    table = Table(
        title=f"Address books · {len(book)} people"
        + ("" if s.connectors.contacts.enabled else " (off)")
    )
    table.add_column("name", style="cyan")
    table.add_column("where")
    table.add_column("people")
    table.add_column("read")
    table.add_column("error")
    own = status.get(OWN, {})
    table.add_row(OWN, str(s.contacts_file), str(len(book.own)), own.get("fetched_at") or "-", "")
    for c in s.connectors.contacts.sources:
        st = status.get(c.name, {})
        where = c.url if "{{vault:" in c.url else (c.url[:40] + "…" if len(c.url) > 40 else c.url)
        table.add_row(
            c.name,
            where,
            str(st.get("contacts", 0)),
            st.get("fetched_at") or "-",
            st.get("error") or "",
        )
    console.print(table)


@contacts_app.command("add-source")
def contacts_add_source(name: str, url: str, config: ConfigOpt = None) -> None:
    """Connect a .vcf export: a path, or a link (kept in the vault as CONTACTS_NAME)."""
    import re

    from openmuse.config import apply_app_settings, load_app_settings, save_app_settings
    from openmuse.vault import CredentialVault

    s = _settings(config)
    url = url.strip()
    if url.startswith(("http://", "https://")):
        secret = "CONTACTS_" + (re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_") or "FEED")
        CredentialVault(s.vault_file, s.vault_key_file).set(secret, url)
        url = f"{{{{vault:{secret}}}}}"
    data = load_app_settings(s.data_dir)
    contacts = dict(data.get("contacts") or {})
    sources = [c for c in contacts.get("sources") or [] if c.get("name") != name]
    sources.append({"name": name, "url": url})
    contacts["sources"], contacts["enabled"] = sources, True
    data["contacts"] = contacts
    save_app_settings(s.data_dir, data)
    apply_app_settings(s, {"contacts": contacts})
    _, book = _contacts(config)
    status = asyncio.run(book.refresh(only=name))
    st: dict[str, Any] = next((c for c in status["sources"] if c["name"] == name), {})
    if st.get("error"):
        console.print(f"[yellow]added, but reading it failed: {st['error']}[/yellow]")
        raise typer.Exit(1)
    console.print(f"[green]added {name}: {st.get('contacts', 0)} people[/green]")


@contacts_app.command("remove-source")
def contacts_remove_source(name: str, config: ConfigOpt = None) -> None:
    """Disconnect an address book added with `add-source` or in the app."""
    import re

    from openmuse.config import load_app_settings, save_app_settings
    from openmuse.vault import CredentialVault

    s = _settings(config)
    data = load_app_settings(s.data_dir)
    contacts = dict(data.get("contacts") or {})
    sources = contacts.get("sources") or []
    if not any(c.get("name") == name for c in sources):
        console.print(f"[red]no address book '{name}' was added from the app or the CLI[/red]")
        raise typer.Exit(1)
    contacts["sources"] = [c for c in sources if c.get("name") != name]
    data["contacts"] = contacts
    save_app_settings(s.data_dir, data)
    secret = "CONTACTS_" + (re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_") or "FEED")
    CredentialVault(s.vault_file, s.vault_key_file).delete(secret)
    console.print(f"removed {name}")


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


# ============================================================================ triggers
def _hook_url(s: Settings, tr: Any) -> str:
    """The webhook address as the running server would give it (the app shows the same)."""
    from openmuse.server import lan_ip

    host = (
        s.server.host if s.server.host not in ("", "0.0.0.0", "::") else (lan_ip() or "127.0.0.1")
    )
    return f"http://{host}:{s.server.port}/api/hooks/{tr.id}?key={tr.secret}"


@triggers_app.command("list")
def triggers_list(
    config: ConfigOpt = None,
    all: Annotated[bool, typer.Option("--all", help="Include cancelled ones")] = False,  # noqa: A002
) -> None:
    """List triggers."""
    from openmuse.triggers import TriggerStore

    s = _settings(config)
    items = TriggerStore(s.triggers_db).list(None if all else "active")
    if not items:
        console.print("[dim]no triggers[/dim]")
        return
    table = Table(title="Triggers")
    table.add_column("id", style="cyan")
    table.add_column("when")
    table.add_column("do")
    table.add_column("fired", justify="right")
    table.add_column("status")
    for tr in items:
        table.add_row(tr.id, tr.describe(), tr.text, str(tr.fired), tr.status)
    console.print(table)
    for tr in items:
        if tr.kind == "hook" and tr.status == "active":
            console.print(f"{tr.id}  POST {_hook_url(s, tr)}", markup=False, highlight=False)


@triggers_app.command("add")
def triggers_add(
    kind: Annotated[str, typer.Argument(help="mail | event | hook")],
    text: Annotated[str, typer.Argument(help="What to do each time it fires")],
    config: ConfigOpt = None,
    match: Annotated[
        str,
        typer.Option(
            help="Words that must all appear in the sender/subject (mail) or title/place "
            "(event); a name for a hook. Empty: anything."
        ),
    ] = "",
    lead: Annotated[int, typer.Option(help="event: minutes before the start")] = 30,
) -> None:
    """Add a trigger. Mail triggers need the email connector, event triggers a calendar."""
    from openmuse.triggers import TriggerStore

    s = _settings(config)
    if kind == "mail" and not (s.connectors.email.enabled and s.connectors.email.imap_host):
        console.print("[red]the email connector is not set up (connectors.email)[/red]")
        raise typer.Exit(1)
    if kind == "event" and not (s.connectors.calendar.enabled and s.connectors.calendar.feeds):
        console.print("[red]no calendar feed is set up (connectors.calendar)[/red]")
        raise typer.Exit(1)
    try:
        item = TriggerStore(s.triggers_db).create(kind, text, match=match, lead_minutes=lead)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None
    console.print(item.render(), markup=False)
    if item.kind == "hook":
        console.print(f"POST {_hook_url(s, item)}", markup=False, highlight=False)


@triggers_app.command("cancel")
def triggers_cancel(trigger_id: str, config: ConfigOpt = None) -> None:
    """Cancel a trigger."""
    from openmuse.triggers import TriggerStore

    s = _settings(config)
    item = TriggerStore(s.triggers_db).cancel(trigger_id)
    if item is None:
        console.print(f"[red]no active trigger {trigger_id}[/red]")
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


@memory_app.command("recall")
def memory_recall(query: str, config: ConfigOpt = None, limit: int = 10) -> None:
    """What the agent would recall for a message: keyword hits and, when an embedding
    endpoint is set up, hits by meaning, fused — with each memory's closeness shown."""
    from openmuse.app import OpenMuseApp
    from openmuse.console import ConsoleUI

    s = _settings(config)
    app_ = OpenMuseApp(s, ConsoleUI(console))

    async def go() -> None:
        try:
            store = app_.memory
            if store is None:
                console.print("[dim]memory is off[/dim]")
                return
            hits = await store.search_async(query, limit=limit)
            closeness: dict[str, float] = {}
            if store.index is not None:
                closeness = {
                    m.id: score for score, m in await store.index.closest(query, limit=1000)
                }
                console.print(
                    f"[dim]by meaning: {app_.embedder.status if app_.embedder else 'off'}[/dim]"
                )
            else:
                console.print("[dim]by keyword only (memory.embeddings = off)[/dim]")
            if not hits:
                console.print("[dim]nothing recalled[/dim]")
                return
            table = Table(title=f"Recalled for {query!r}")
            table.add_column("id", style="cyan")
            table.add_column("category")
            table.add_column("content")
            if closeness:
                table.add_column("closeness", justify="right", style="dim")
            for m in hits:
                row = [m.id, m.category, m.content]
                if closeness:
                    row.append(f"{closeness.get(m.id, 0.0):.2f}")
                table.add_row(*row)
            console.print(table)
        finally:
            await app_.close()

    asyncio.run(go())


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


# ============================================================================ skills
def _skills(config: Path | None):  # noqa: ANN202
    from openmuse.skills import SkillLibrary

    s = _settings(config)
    return s, SkillLibrary(s.skills, own_dir=s.skills_dir)


@skills_app.command("list")
def skills_list(config: ConfigOpt = None) -> None:
    """Every skill: the built-in ones and yours (<data_dir>/skills)."""
    s, lib = _skills(config)
    table = Table(title=f"Skills · {len(lib)} on" + ("" if s.skills.enabled else " (skills off)"))
    table.add_column("name", style="cyan")
    table.add_column("from")
    table.add_column("on")
    table.add_column("description")
    for skill in lib.all():
        table.add_row(
            skill.name,
            skill.source,
            "yes" if skill.enabled else "no",
            skill.description[:100] + ("…" if len(skill.description) > 100 else ""),
        )
    console.print(table)
    for name, err in lib.errors.items():
        console.print(f"[yellow]{name}: {err}[/yellow]")
    console.print(f"[dim]yours live in {lib.own_dir}; start one in chat with /name[/dim]")


@skills_app.command("show")
def skills_show(name: str, config: ConfigOpt = None) -> None:
    """A skill's SKILL.md, as the model reads it."""
    _, lib = _skills(config)
    skill = lib.get(name)
    if skill is None:
        console.print(f"[red]no skill named '{name}'[/red]")
        raise typer.Exit(1)
    console.print(f"[dim]{skill.path / 'SKILL.md'} ({skill.source})[/dim]")
    console.print(skill.render(), markup=False)
    if skill.files:
        console.print("[dim]files:[/dim] " + ", ".join(str(f) for f in skill.files))


@skills_app.command("add")
def skills_add(source: str, config: ConfigOpt = None) -> None:
    """Add a skill from a SKILL.md file, a skill folder, or an https link (a raw file, or a
    GitHub folder/file page)."""
    _, lib = _skills(config)
    try:
        if source.startswith("https://"):
            from openmuse.skills import fetch_skill_text

            name = lib.save_text(asyncio.run(fetch_skill_text(source))).name
        else:
            path = Path(source).expanduser()
            file = path / "SKILL.md" if path.is_dir() else path
            if not file.is_file():
                console.print(f"[red]{file} is not a file[/red]")
                raise typer.Exit(1)
            skill = lib.save_text(file.read_text("utf-8"), name=file.parent.name)
            # scripts/, references/, assets/ next to the file come along
            for sub in ("scripts", "references", "assets"):
                src = file.parent / sub
                if src.is_dir() and src.resolve() != (skill.path / sub).resolve():
                    import shutil

                    shutil.copytree(src, skill.path / sub, dirs_exist_ok=True)
            name = skill.name
    except (ValueError, OSError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(f"[green]added {name}[/green] → {lib.own_dir / name}")


@skills_app.command("new")
def skills_new(name: str, config: ConfigOpt = None) -> None:
    """Start a skill of your own: a SKILL.md to fill in, printed with its path."""
    from openmuse.skills import NAME_RE, render_skill

    _, lib = _skills(config)
    name = name.strip().lower()
    if not NAME_RE.match(name):
        console.print("[red]a skill name is lowercase letters, digits and hyphens[/red]")
        raise typer.Exit(1)
    folder = lib.own_dir / name
    if (folder / "SKILL.md").exists():
        console.print(f"[red]{folder / 'SKILL.md'} exists[/red]")
        raise typer.Exit(1)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(
        render_skill(
            name,
            "What this does, and when to use it — the model picks the skill from this line.",
            "# " + name.replace("-", " ").capitalize() + "\n\n"
            "## Gather\n\n- What to read first, with which tools.\n\n"
            "## Do\n\n1. The steps, in order.\n2. What to produce (a file in the workspace?).\n\n"
            "## Finish\n\n- What to say in chat; what to ask; what never to do.\n",
        ),
        "utf-8",
    )
    console.print(
        f"[green]{folder / 'SKILL.md'}[/green] — edit it; the agent sees it on its next turn"
    )


@skills_app.command("remove")
def skills_remove(name: str, config: ConfigOpt = None) -> None:
    """Delete one of your skills (built-in ones are switched off with `disable`)."""
    _, lib = _skills(config)
    if not lib.remove(name):
        console.print(f"[red]no skill of yours named '{name}'[/red]")
        raise typer.Exit(1)
    console.print(f"[green]removed {name}[/green]")


def _set_skill(name: str, enabled: bool, config: Path | None) -> None:
    from openmuse.config import load_app_settings, save_app_settings

    s, lib = _skills(config)
    if lib.set_enabled(name, enabled) is None:
        console.print(f"[red]no skill named '{name}'[/red]")
        raise typer.Exit(1)
    data = load_app_settings(s.data_dir)
    data["skills"] = {"disabled": list(s.skills.disabled)}
    save_app_settings(s.data_dir, data)
    console.print(f"[green]{name} is {'on' if enabled else 'off'}[/green]")


@skills_app.command("enable")
def skills_enable(name: str, config: ConfigOpt = None) -> None:
    """Switch a skill on."""
    _set_skill(name, True, config)


@skills_app.command("disable")
def skills_disable(name: str, config: ConfigOpt = None) -> None:
    """Switch a skill off (it leaves the model's list; the folder stays)."""
    _set_skill(name, False, config)


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
    if app_ is not None and app_.memory is not None:
        emb = app_.embedder
        if emb is None or not emb.enabled:
            line(None, "recall by meaning: off (memory.embeddings = off) · keyword recall only")
        else:
            emb.reset()
            if emb.usable:
                await emb.embed(["probe"])
            st = app_.memory.index.status() if app_.memory.index else {}
            line(
                True if emb.available else (False if settings.memory.embeddings == "on" else None),
                f"recall by meaning: {emb.status}"
                + (
                    f" · {st.get('indexed', 0)}/{st.get('total', 0)} memories indexed"
                    if emb.available
                    else ""
                ),
                "memory.embeddings = on, but the embeddings endpoint cannot be used",
            )
    if app_ is not None:
        from openmuse.search import WebSearchProvider

        web = WebSearchProvider(settings.connectors.search, vault=app_.vault)
        line(
            None if web.configured else False,
            f"web search: {web.describe()}"
            + ("" if web.configured else " · searches fall back to DuckDuckGo"),
            f"connectors.search.provider = {web.name}, but it is not configured",
        )
    if app_ is not None:
        box = app_.sandbox
        line(
            True if box.active else (False if settings.sandbox.mode == "bwrap" else None),
            f"sandbox: {box.status}",
            (
                "sandbox.mode = bwrap, but bubblewrap does not work here"
                if settings.sandbox.mode == "bwrap"
                else "commands run unboxed — on Linux, `apt install bubblewrap` gives each one its own namespace"
            ),
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
        cal = settings.connectors.calendar
        if cal.enabled and cal.feeds:
            status = await app_.calendar.refresh()
            broken = [f for f in status["feeds"] if f["error"]]
            line(
                not broken,
                f"calendar: {len(cal.feeds)} feed(s), "
                f"{sum(f['events'] for f in status['feeds'])} events"
                + (
                    " · " + "; ".join(f"{f['name']}: {f['error']}" for f in broken)
                    if broken
                    else ""
                ),
                "a calendar feed could not be read",
            )
        else:
            line(None, "calendar: off")
        contacts = settings.connectors.contacts
        if contacts.enabled:
            status = await app_.contacts.refresh()
            broken = [c for c in status["sources"] if c["error"]]
            line(
                not broken,
                f"contacts: {status['count']} people"
                + (f" · {len(contacts.sources)} source(s)" if contacts.sources else "")
                + (f" · {len(app_.contacts.own)} added by the agent" if app_.contacts.own else "")
                + (
                    " · " + "; ".join(f"{c['name']}: {c['error']}" for c in broken)
                    if broken
                    else ""
                ),
                "an address book could not be read",
            )
        else:
            line(None, "contacts: off")
        if settings.skills.enabled:
            sk = app_.skills.status()
            line(
                not sk["errors"],
                f"skills: {sk['count']} on · {sk['built_in']} built-in, {sk['yours']} yours"
                + (
                    " · " + "; ".join(f"{n}: {e}" for n, e in sk["errors"].items())
                    if sk["errors"]
                    else ""
                ),
                "a skill folder could not be read",
            )
        else:
            line(None, "skills: off")
        triggers = app_.triggers.list("active")
        kinds = app_.trigger_kinds()
        orphans = [tr for tr in triggers if not kinds.get(tr.kind, True)]
        line(
            not orphans,
            f"triggers: {len(triggers)} active"
            + (
                " · "
                + ", ".join(
                    f"{k}: {sum(1 for t in triggers if t.kind == k)}"
                    for k in ("mail", "event", "hook")
                    if any(t.kind == k for t in triggers)
                )
                if triggers
                else ""
            )
            + (f" · {len(orphans)} without their connector" if orphans else ""),
            "a mail/event trigger needs its connector (email / calendar) to fire",
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
