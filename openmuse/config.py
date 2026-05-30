"""Configuration loading.

Search order for the TOML config file:

1. explicit path (``--config`` / :func:`load_settings(path)`)
2. ``$OPENMUSE_CONFIG``
3. ``./config/config.toml``
4. ``~/.openmuse/config.toml``

String values may reference environment variables with ``${VAR}`` or
``${VAR:-default}`` so that secrets never have to live in the file itself.
A handful of ``OPENMUSE_*`` environment variables override the most common
settings (see :func:`_apply_env_overrides`). Whatever was changed from the app
(``<data_dir>/app-settings.json``: model, connectors, MCP servers) is layered on
top; secrets it refers to live in the vault as ``{{vault:NAME}}``.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from openmuse.schema import RiskLevel

DEFAULT_DATA_DIR = Path.home() / ".openmuse"
_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


# ----------------------------------------------------------------------------- models
class LLMSettings(BaseModel):
    provider: Literal["openai", "openai_responses"] = "openai"
    model: str = "deepseek-flash"
    base_url: str | None = "https://api.deepseek.com"
    api_key: str = ""
    max_tokens: int = 4096
    temperature: float = 0.3
    timeout: float = 180.0
    max_retries: int = 5
    stream: bool = True
    # "auto":   the provider's function-calling API; if the endpoint rejects the `tools`
    #           field (Ollama for a model without a tool template, vLLM without a tool
    #           parser) switch to prompt mode for the rest of the run.
    # "native": always the function-calling API.
    # "prompt": describe tools in the prompt and parse <tool_call> blocks — works with
    #           any chat model, including endpoints that silently ignore `tools`.
    tool_mode: Literal["auto", "native", "prompt"] = "auto"
    # Pictures the user attaches in chat go to the model as images.
    # "auto": send them; if the endpoint rejects image content (DeepSeek, most text-only
    #         models) send the text only from then on and tell the user once.
    # "on":   always send them (the call fails when the model cannot take images).
    # "off":  never — the model gets the file names and can read text files with `files`.
    vision: Literal["auto", "on", "off"] = "auto"
    # Send `reasoning_content` back with assistant messages (DeepSeek thinking-mode
    # tool calling wants this on some endpoints).
    pass_reasoning: bool = False
    extra_headers: dict[str, str] = Field(default_factory=dict)
    extra_body: dict[str, Any] = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def _strip_slash(cls, v: str | None) -> str | None:
        return v.rstrip("/") if v else v


class AgentSettings(BaseModel):
    name: str = "Muse"
    max_steps: int = 30
    workspace: Path = Path("./workspace")
    # Directories outside the workspace the files tool may read and write (e.g. "~/Documents").
    extra_roots: list[Path] = Field(default_factory=list)
    # "auto" → answer in the user's language; or force e.g. "zh" / "en".
    language: str = "auto"
    max_context_messages: int = 80
    show_thinking: bool = False
    # Optional free-text profile injected into the system prompt.
    user_profile: str = ""
    # Extra instructions appended to the system prompt.
    instructions: str = ""


class SentinelRule(BaseModel):
    tool: str = "*"
    # argument name -> glob pattern matched against str(value)
    match: dict[str, str] = Field(default_factory=dict)
    action: Literal["allow", "ask", "deny"] = "ask"
    reason: str = ""


class SentinelSettings(BaseModel):
    # ask    : safe/moderate run freely, sensitive actions need approval (default)
    # strict : moderate *and* sensitive actions need approval
    # auto   : approve everything except explicit deny rules (unattended runs / CI)
    mode: Literal["ask", "strict", "auto"] = "ask"
    always_ask_tools: list[str] = Field(default_factory=lambda: ["send_email", "shell"])
    always_allow_tools: list[str] = Field(default_factory=list)
    deny_tools: list[str] = Field(default_factory=list)
    # Domains the agent may reach *without* approval even after it has read private
    # data (mirrors Muse's "short list of pre-approved destinations").
    egress_allowlist: list[str] = Field(
        default_factory=lambda: [
            "duckduckgo.com",
            "*.duckduckgo.com",
            "wikipedia.org",
            "*.wikipedia.org",
            "github.com",
            "*.github.com",
            "*.githubusercontent.com",
            "pypi.org",
            "*.pypi.org",
        ]
    )
    rules: list[SentinelRule] = Field(default_factory=list)
    audit_file: Path | None = None
    # Enable taint tracking: once the agent has read private data, network egress to
    # non-allowlisted destinations requires approval.
    taint_tracking: bool = True


class MemorySettings(BaseModel):
    enabled: bool = True
    max_inject: int = 20
    # Recall by meaning. Memories are embedded once and a message finds the ones that mean
    # the same thing, in any language ("写邮件给房东" finds "the landlord is Bob Li"); the
    # keyword recall stays and the two rankings are fused.
    #   auto: use the endpoint's /embeddings when it has one (OpenAI, Ollama, most gateways;
    #         DeepSeek has none) and fall back to keyword recall when it does not
    #   on:   insist — recall stays by keyword when the call fails, and `doctor` says so
    #   off:  keyword recall only
    embeddings: Literal["auto", "on", "off"] = "auto"
    # Empty → a default for the endpoint: text-embedding-3-small on OpenAI and most
    # gateways, qwen3-embedding:0.6b on Ollama.
    embedding_model: str = ""
    # Empty → the model's endpoint and key (llm.base_url / llm.api_key). Set these to use a
    # different service for embeddings than for chat — Ollama next to DeepSeek, say.
    embedding_base_url: str = ""
    embedding_api_key: str = ""

    @field_validator("embedding_base_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")


class EmailSettings(BaseModel):
    enabled: bool = False
    imap_host: str = ""
    imap_port: int = 993
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_starttls: bool = True
    # Values may be vault placeholders such as "{{vault:EMAIL_PASSWORD}}" — the model
    # never sees them; the Sentinel resolves them right before the connector runs.
    address: str = "{{vault:EMAIL_ADDRESS}}"
    password: str = "{{vault:EMAIL_PASSWORD}}"
    # Strip one-time passcodes / password-reset links before the model reads a mail.
    scrub_secrets: bool = True


class CalendarFeedSettings(BaseModel):
    name: str
    # A private .ics link (Google, Outlook, iCloud, Fastmail, Nextcloud all have one) or a
    # local file. The link is usually the secret, so "{{vault:CALENDAR_WORK}}" works here.
    url: str


class CalendarSettings(BaseModel):
    enabled: bool = False
    feeds: list[CalendarFeedSettings] = Field(default_factory=list)
    refresh_minutes: int = 30
    # Working hours, for "when am I free" — local time.
    day_start: str = "09:00"
    day_end: str = "18:00"


class ContactSourceSettings(BaseModel):
    """A ``.vcf`` export or link: Google Contacts, iCloud, Outlook, Nextcloud … all export one."""

    name: str
    # a path, or a URL — a "{{vault:NAME}}" placeholder when the link is a secret
    url: str


class ContactsSettings(BaseModel):
    # On by default: even without a source the agent keeps its own book of the people
    # you tell it about ("Alice's address is …"), in <data_dir>/contacts.vcf.
    enabled: bool = True
    sources: list[ContactSourceSettings] = Field(default_factory=list)


class SearchSettings(BaseModel):
    """Who answers ``web_search``. DuckDuckGo needs nothing and is the default; Brave and
    Tavily want a key, SearXNG wants the URL of an instance. A failed search falls back
    to DuckDuckGo once, with a note, so a lapsed key does not stop a task."""

    provider: Literal["duckduckgo", "brave", "tavily", "searxng"] = "duckduckgo"
    # Brave / Tavily. May be a vault placeholder — the app stores it as {{vault:SEARCH_API_KEY}}.
    api_key: str = ""
    # SearXNG: your instance, e.g. "http://127.0.0.1:8080".
    base_url: str = ""


class ConnectorSettings(BaseModel):
    email: EmailSettings = Field(default_factory=EmailSettings)
    calendar: CalendarSettings = Field(default_factory=CalendarSettings)
    contacts: ContactsSettings = Field(default_factory=ContactsSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)


class SkillsSettings(BaseModel):
    """Skills: recipes for jobs, as ``SKILL.md`` folders (the Agent Skills format)."""

    enabled: bool = True
    # Where your own skills live; one folder per skill with a SKILL.md inside. Empty →
    # <data_dir>/skills. A skill here with the same name as a built-in one replaces it.
    dir: Path | None = None
    # Built-in skills to leave out (by name).
    disabled: list[str] = Field(default_factory=list)

    @field_validator("dir", mode="before")
    @classmethod
    def _empty_is_unset(cls, v: Any) -> Any:
        return None if isinstance(v, str) and not v.strip() else v


class SandboxSettings(BaseModel):
    """Each ``shell`` / ``python_execute`` call in its own bubblewrap namespace (Linux)."""

    # "auto": bubblewrap when it is installed and works here; "bwrap": insist (a startup
    # error otherwise); "off": commands run unboxed, with the scrubbed environment only.
    mode: str = "auto"


class TriggerSettings(BaseModel):
    """Triggers start work from the world: new mail, an event about to start, a webhook."""

    # How often the inbox is looked at while a mail trigger is active.
    mail_poll_minutes: int = 5
    # Deliveries to one webhook closer together than this are refused (HTTP 429).
    hook_min_seconds: int = 10


class BrowserSettings(BaseModel):
    enabled: bool = False
    headless: bool = True
    timeout_ms: int = 30_000


class MCPServerSettings(BaseModel):
    name: str
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None  # Streamable-HTTP / SSE endpoint
    risk: RiskLevel = RiskLevel.MODERATE
    egress: bool = False
    reads_private_data: bool = False


class MCPSettings(BaseModel):
    servers: list[MCPServerSettings] = Field(default_factory=list)


class ServerSettings(BaseModel):
    """``openmuse serve`` — the always-on agent behind the mobile-first web app."""

    host: str = "127.0.0.1"  # use 0.0.0.0 to reach it from your phone on the same network
    port: int = 8787
    # Require an access token (printed with a QR code on start). Never disable on a shared network.
    auth: bool = True
    token: str = ""  # empty → generated once and stored in <data_dir>/server_token
    # How long an approval card / question may wait for you before it is treated as "deny".
    approval_timeout: float = 3600.0
    # Extra origins allowed to call the API (only needed for the Vite dev server).
    cors_origins: list[str] = Field(default_factory=list)
    # Largest file the app may attach to a message (photos from a phone run 3–12 MB).
    max_upload_mb: int = 25


class Settings(BaseModel):
    data_dir: Path = DEFAULT_DATA_DIR
    log_level: str = "INFO"
    llm: LLMSettings = Field(default_factory=LLMSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    sentinel: SentinelSettings = Field(default_factory=SentinelSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    connectors: ConnectorSettings = Field(default_factory=ConnectorSettings)
    triggers: TriggerSettings = Field(default_factory=TriggerSettings)
    skills: SkillsSettings = Field(default_factory=SkillsSettings)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    mcp: MCPSettings = Field(default_factory=MCPSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    # Where the settings came from (informational).
    source: str | None = None

    @property
    def audit_file(self) -> Path:
        return self.sentinel.audit_file or (self.data_dir / "audit.jsonl")

    @property
    def memory_db(self) -> Path:
        return self.data_dir / "memory.db"

    @property
    def goals_db(self) -> Path:
        return self.data_dir / "goals.db"

    @property
    def reminders_db(self) -> Path:
        return self.data_dir / "reminders.db"

    @property
    def triggers_db(self) -> Path:
        return self.data_dir / "triggers.db"

    @property
    def calendar_cache(self) -> Path:
        return self.data_dir / "calendar-cache.json"

    @property
    def contacts_file(self) -> Path:
        """The agent's own address book (the only contacts source it writes to)."""
        return self.data_dir / "contacts.vcf"

    @property
    def contacts_cache(self) -> Path:
        return self.data_dir / "contacts-cache.json"

    @property
    def contacts_dir(self) -> Path:
        """Where ``.vcf`` files uploaded in the app are kept."""
        return self.data_dir / "contacts"

    @property
    def skills_dir(self) -> Path:
        """Your own skills, one folder each."""
        return (self.skills.dir or (self.data_dir / "skills")).expanduser()

    @property
    def vault_file(self) -> Path:
        return self.data_dir / "vault.enc"

    @property
    def vault_key_file(self) -> Path:
        return self.data_dir / "vault.key"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.agent.workspace.mkdir(parents=True, exist_ok=True)


# ----------------------------------------------------------------------------- loading
def _expand_env(value: Any) -> Any:
    if isinstance(value, str):

        def repl(m: re.Match[str]) -> str:
            var, default = m.group(1), m.group(2)
            return os.environ.get(var, default if default is not None else "")

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def find_config_file(explicit: str | Path | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"config file not found: {explicit}")
        return path
    if env_path := os.environ.get("OPENMUSE_CONFIG"):
        candidates.append(Path(env_path).expanduser())
    candidates.append(Path("config/config.toml"))
    candidates.append(DEFAULT_DATA_DIR / "config.toml")
    for path in candidates:
        if path.is_file():
            return path
    return None


def _apply_env_overrides(raw: dict[str, Any]) -> None:
    llm = raw.setdefault("llm", {})
    mapping = {
        "OPENMUSE_LLM_PROVIDER": "provider",
        "OPENMUSE_LLM_MODEL": "model",
        "OPENMUSE_LLM_BASE_URL": "base_url",
        "OPENMUSE_LLM_API_KEY": "api_key",
        "OPENMUSE_LLM_TOOL_MODE": "tool_mode",
        "OPENMUSE_LLM_VISION": "vision",
    }
    for env, key in mapping.items():
        if (val := os.environ.get(env)) not in (None, ""):
            llm[key] = val
    if not llm.get("api_key"):
        for env in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
            if val := os.environ.get(env):
                llm["api_key"] = val
                break
    if val := os.environ.get("OPENMUSE_DATA_DIR"):
        raw["data_dir"] = val
    if val := os.environ.get("OPENMUSE_WORKSPACE"):
        raw.setdefault("agent", {})["workspace"] = val
    if val := os.environ.get("OPENMUSE_SENTINEL_MODE"):
        raw.setdefault("sentinel", {})["mode"] = val
    if val := os.environ.get("OPENMUSE_LOG_LEVEL"):
        raw["log_level"] = val
    for env, key in (
        ("OPENMUSE_SEARCH_PROVIDER", "provider"),
        ("OPENMUSE_SEARCH_API_KEY", "api_key"),
        ("OPENMUSE_SEARCH_BASE_URL", "base_url"),
    ):
        if val := os.environ.get(env):
            raw.setdefault("connectors", {}).setdefault("search", {})[key] = val
    server = raw.setdefault("server", {})
    if val := os.environ.get("OPENMUSE_SERVER_HOST"):
        server["host"] = val
    if val := os.environ.get("OPENMUSE_SERVER_PORT"):
        server["port"] = int(val)
    if val := os.environ.get("OPENMUSE_SERVER_TOKEN"):
        server["token"] = val
    # turns the browser tool on (the browser Docker image sets it); it never turns it off, so a
    # mounted config.toml keeps the last word otherwise
    if os.environ.get("OPENMUSE_BROWSER_ENABLED", "").strip().lower() in ("1", "true", "yes", "on"):
        raw.setdefault("browser", {})["enabled"] = True


APP_SETTINGS_FILE = "app-settings.json"


def load_app_settings(data_dir: Path) -> dict[str, Any]:
    """Settings changed from the app (model, connectors, MCP servers, onboarding state).

    They live in ``<data_dir>/app-settings.json`` and are layered over ``config.toml`` so a
    phone-only setup works without ever editing a file. Secrets are not in here: the app
    stores them in the vault and this file only holds ``{{vault:NAME}}`` references.
    """
    path = data_dir / APP_SETTINGS_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_app_settings(data_dir: Path, data: dict[str, Any]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / APP_SETTINGS_FILE
    path.write_text(json.dumps({"version": 1, **data}, ensure_ascii=False, indent=1), "utf-8")
    try:
        path.chmod(0o600)
    except OSError:  # pragma: no cover
        pass


def apply_app_settings(settings: Settings, data: dict[str, Any]) -> None:
    """Layer app-managed settings over ``settings`` in place."""
    if llm := data.get("llm"):
        for key in ("provider", "model", "base_url", "api_key", "tool_mode", "vision"):
            if key in llm and llm[key] not in (None, ""):
                setattr(settings.llm, key, llm[key])
        if settings.llm.base_url:
            settings.llm.base_url = settings.llm.base_url.rstrip("/")
    if emb := data.get("embeddings"):
        m = settings.memory
        if emb.get("mode") in ("auto", "on", "off"):
            m.embeddings = emb["mode"]
        for key in ("model", "base_url", "api_key"):
            # "" is meaningful here: back to the default (the model's endpoint and key)
            if key in emb and emb[key] is not None:
                setattr(m, f"embedding_{key}", str(emb[key]).strip().rstrip("/"))
    if search := data.get("search"):
        web = settings.connectors.search
        if search.get("provider") in ("duckduckgo", "brave", "tavily", "searxng"):
            web.provider = search["provider"]
        for key in ("api_key", "base_url"):
            if key in search and search[key] is not None:
                setattr(web, key, str(search[key]).strip().rstrip("/"))
    if email := data.get("email"):
        for key in ("enabled", "imap_host", "imap_port", "smtp_host", "smtp_port", "smtp_starttls"):
            if key in email and email[key] is not None:
                setattr(settings.connectors.email, key, email[key])
    if calendar := data.get("calendar"):
        cal = settings.connectors.calendar
        if "enabled" in calendar and calendar["enabled"] is not None:
            cal.enabled = bool(calendar["enabled"])
        for key in ("refresh_minutes", "day_start", "day_end"):
            if calendar.get(key) not in (None, ""):
                setattr(cal, key, calendar[key])
        if isinstance(calendar.get("feeds"), list):
            feeds = []
            for raw_feed in calendar["feeds"]:
                try:
                    feeds.append(CalendarFeedSettings.model_validate(raw_feed))
                except ValueError:
                    continue
            # feeds added in the app come after the ones in config.toml; same name → app wins
            names = {f.name for f in feeds}
            cal.feeds = [f for f in cal.feeds if f.name not in names] + feeds
    if contacts := data.get("contacts"):
        book = settings.connectors.contacts
        if "enabled" in contacts and contacts["enabled"] is not None:
            book.enabled = bool(contacts["enabled"])
        if isinstance(contacts.get("sources"), list):
            sources = []
            for raw_source in contacts["sources"]:
                try:
                    sources.append(ContactSourceSettings.model_validate(raw_source))
                except ValueError:
                    continue
            names = {c.name for c in sources}
            book.sources = [c for c in book.sources if c.name not in names] + sources
    if skills := data.get("skills"):
        if isinstance(skills.get("disabled"), list):
            off = {str(n) for n in skills["disabled"]}
            settings.skills.disabled = sorted(set(settings.skills.disabled) | off)
    if browser := data.get("browser"):
        if "enabled" in browser:
            settings.browser.enabled = bool(browser["enabled"])
    for raw_server in (data.get("mcp") or {}).get("servers") or []:
        try:
            server = MCPServerSettings.model_validate(raw_server)
        except ValueError:
            continue
        settings.mcp.servers = [s for s in settings.mcp.servers if s.name != server.name]
        settings.mcp.servers.append(server)


def load_settings(path: str | Path | None = None) -> Settings:
    """Load settings from TOML (if found) + environment + what was changed in the app."""
    config_file = find_config_file(path)
    raw: dict[str, Any] = {}
    if config_file is not None:
        with config_file.open("rb") as fh:
            raw = tomllib.load(fh)
    raw = _expand_env(raw)
    _apply_env_overrides(raw)
    settings = Settings.model_validate(raw)
    settings.source = str(config_file) if config_file else "defaults+env"
    settings.data_dir = settings.data_dir.expanduser()
    settings.agent.workspace = settings.agent.workspace.expanduser()
    settings.agent.extra_roots = [p.expanduser() for p in settings.agent.extra_roots]
    apply_app_settings(settings, load_app_settings(settings.data_dir))
    return settings


__all__ = [
    "APP_SETTINGS_FILE",
    "AgentSettings",
    "BrowserSettings",
    "CalendarFeedSettings",
    "CalendarSettings",
    "ContactSourceSettings",
    "ContactsSettings",
    "ConnectorSettings",
    "DEFAULT_DATA_DIR",
    "EmailSettings",
    "LLMSettings",
    "MCPServerSettings",
    "MCPSettings",
    "MemorySettings",
    "SandboxSettings",
    "SentinelRule",
    "SentinelSettings",
    "ServerSettings",
    "Settings",
    "SkillsSettings",
    "TriggerSettings",
    "apply_app_settings",
    "find_config_file",
    "load_app_settings",
    "load_settings",
    "save_app_settings",
]
