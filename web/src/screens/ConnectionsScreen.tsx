import {
  Bot,
  Check,
  ChevronDown,
  ChevronUp,
  Globe,
  KeyRound,
  Loader2,
  Mail,
  Plug,
  Plus,
  Trash2,
  Unplug,
} from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import { BackBar } from "../components/BackBar";
import { useStore } from "../store";
import type { ConnectionsData, TestResult } from "../types";
import { cx } from "../util";

/**
 * Connections: the model, your mailbox, a browser, MCP servers — plugged in and out from the
 * phone. Anything secret is typed here and lands in the vault on the server; the model only
 * ever gets the tools that result, never the key or the password.
 */
export function ConnectionsScreen() {
  const { state } = useStore();
  const [data, setData] = useState<ConnectionsData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const name = state.profile?.name ?? "Muse";

  const load = useCallback(async () => {
    try {
      setData(await api.connections());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, state.connectionsVersion]);

  return (
    <div className="flex h-full flex-col">
      <header className="safe-top shrink-0 px-5 pt-2 pb-3">
        <BackBar />
        <h1 className="text-[24px] font-bold tracking-tight">Connections</h1>
        <p className="text-[13px] text-muted">
          What {name} can reach. Keys and passwords go into the vault on your machine — the model never sees them.
        </p>
      </header>
      <div className="flex-1 overflow-y-auto px-4 pb-8 space-y-4">
        {error && <div className="rounded-2xl bg-rose-500/12 text-rose-700 dark:text-rose-300 p-3 text-[13.5px]">{error}</div>}
        {!data && !error && (
          <div className="flex justify-center py-10 text-muted">
            <Loader2 className="animate-spin" size={20} />
          </div>
        )}
        {data && (
          <>
            <ModelCard data={data} onChange={load} />
            <EmailCard data={data} onChange={load} />
            <BrowserCard data={data} onChange={load} />
            <MCPCard data={data} onChange={load} />
            <VaultCard data={data} onChange={load} />
          </>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ model
export function ModelCard({ data, onChange, compact }: { data: ConnectionsData; onChange: () => void; compact?: boolean }) {
  const { toast } = useStore();
  const [open, setOpen] = useState(!!compact);
  const presets = data.providers;
  const currentPreset =
    Object.entries(presets).find(([id, p]) => id !== "custom" && p.base_url && data.llm.base_url.startsWith(p.base_url))?.[0] ??
    (data.llm.base_url ? "custom" : "deepseek");
  const [preset, setPreset] = useState(currentPreset);
  const [model, setModel] = useState(data.llm.model);
  const [baseUrl, setBaseUrl] = useState(data.llm.base_url);
  const [key, setKey] = useState("");
  const [toolMode, setToolMode] = useState(data.llm.tool_mode || "native");
  const [saving, setSaving] = useState(false);
  const [test, setTest] = useState<TestResult | null>(null);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    setModel(data.llm.model);
    setBaseUrl(data.llm.base_url);
    setToolMode(data.llm.tool_mode || "native");
    setPreset(currentPreset);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.llm]);

  const pick = (id: string) => {
    setPreset(id);
    const p = presets[id];
    if (!p) return;
    if (p.base_url) setBaseUrl(p.base_url);
    if (p.models?.length && !p.models.includes(model)) setModel(p.models[0]);
  };

  const status =
    data.llm.key_source === "none" && !presets[preset]?.no_key
      ? { text: "No key yet", tone: "warn" }
      : data.llm.key_source === "missing"
        ? { text: "Key missing from vault", tone: "warn" }
        : { text: data.llm.key_source === "vault" ? "Key in vault" : data.llm.key_source === "config" ? "Key from config" : "No key needed", tone: "ok" };

  const save = async () => {
    setSaving(true);
    setTest(null);
    try {
      await api.setLLM({
        provider: presets[preset]?.provider ?? "openai",
        model: model.trim(),
        base_url: baseUrl.trim(),
        tool_mode: toolMode,
        api_key: key ? key : presets[preset]?.no_key ? "" : null,
      });
      setKey("");
      toast("Model saved");
      onChange();
      if (!compact) setOpen(false);
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const runTest = async () => {
    setTesting(true);
    try {
      setTest(await api.testLLM());
    } catch (e) {
      setTest({ ok: false, error: (e as Error).message });
    } finally {
      setTesting(false);
    }
  };

  return (
    <Card
      icon={<Bot size={19} />}
      title="Model"
      summary={`${data.llm.model || "—"}${data.llm.base_url ? ` · ${hostOf(data.llm.base_url)}` : ""}`}
      status={status}
      open={open}
      onToggle={compact ? undefined : () => setOpen(!open)}
    >
      <Field label="Provider">
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(presets).map(([id, p]) => (
            <button
              key={id}
              type="button"
              onClick={() => pick(id)}
              className={cx("rounded-full px-3 py-1.5 text-[13px] border", preset === id ? "border-accent bg-accent/10 text-accent font-medium" : "border-border text-muted")}
            >
              {p.label}
            </button>
          ))}
        </div>
      </Field>
      <Field label="Model">
        <input list="om-models" value={model} onChange={(e) => setModel(e.target.value)} className={inputCls} placeholder="model name" />
        <datalist id="om-models">
          {(presets[preset]?.models ?? []).map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
      </Field>
      {(preset === "custom" || !presets[preset]?.base_url) && (
        <Field label="Base URL">
          <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} className={inputCls} placeholder="https://host/v1" inputMode="url" />
        </Field>
      )}
      {!presets[preset]?.no_key && (
        <Field label="API key" hint={data.llm.key_source === "vault" ? "A key is in the vault. Leave blank to keep it." : "Stored encrypted in the vault as LLM_API_KEY."}>
          <input type="password" value={key} onChange={(e) => setKey(e.target.value)} className={inputCls} placeholder={data.llm.key_source === "vault" ? "••••••••" : "sk-…"} autoComplete="off" />
        </Field>
      )}
      <Field label="Tool calling" hint="Native for most APIs; prompt for small local models that lack function calling.">
        <div className="flex gap-1.5">
          {["native", "prompt"].map((m) => (
            <button key={m} type="button" onClick={() => setToolMode(m)} className={cx("rounded-full px-3 py-1.5 text-[13px] border", toolMode === m ? "border-accent bg-accent/10 text-accent font-medium" : "border-border text-muted")}>
              {m}
            </button>
          ))}
        </div>
      </Field>
      <div className="flex gap-2 pt-1">
        <button type="button" disabled={saving || !model.trim()} onClick={() => void save()} className={primaryBtn}>
          {saving ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />} Save
        </button>
        <button type="button" disabled={testing} onClick={() => void runTest()} className={secondaryBtn}>
          {testing ? <Loader2 size={16} className="animate-spin" /> : <Plug size={16} />} Test
        </button>
      </div>
      {test && <TestLine result={test} okText={`Replied "${test.reply}" in ${test.ms} ms`} />}
    </Card>
  );
}

// ------------------------------------------------------------------ email
const MAIL_PRESETS: Array<{ id: string; label: string; imap: string; smtp: string; port: number; starttls: boolean }> = [
  { id: "gmail", label: "Gmail", imap: "imap.gmail.com", smtp: "smtp.gmail.com", port: 587, starttls: true },
  { id: "outlook", label: "Outlook", imap: "outlook.office365.com", smtp: "smtp.office365.com", port: 587, starttls: true },
  { id: "icloud", label: "iCloud", imap: "imap.mail.me.com", smtp: "smtp.mail.me.com", port: 587, starttls: true },
  { id: "qq", label: "QQ", imap: "imap.qq.com", smtp: "smtp.qq.com", port: 587, starttls: true },
  { id: "163", label: "163", imap: "imap.163.com", smtp: "smtp.163.com", port: 465, starttls: false },
  { id: "fastmail", label: "Fastmail", imap: "imap.fastmail.com", smtp: "smtp.fastmail.com", port: 587, starttls: true },
];

export function EmailCard({ data, onChange, compact }: { data: ConnectionsData; onChange: () => void; compact?: boolean }) {
  const { toast } = useStore();
  const e = data.email;
  const [open, setOpen] = useState(!!compact);
  const [address, setAddress] = useState(e.address);
  const [password, setPassword] = useState("");
  const [imap, setImap] = useState(e.imap_host);
  const [imapPort, setImapPort] = useState(e.imap_port);
  const [smtp, setSmtp] = useState(e.smtp_host);
  const [smtpPort, setSmtpPort] = useState(e.smtp_port);
  const [starttls, setStarttls] = useState(e.smtp_starttls);
  const [busy, setBusy] = useState<"save" | "test" | "off" | null>(null);
  const [test, setTest] = useState<TestResult | null>(null);

  useEffect(() => {
    setAddress(e.address);
    setImap(e.imap_host);
    setImapPort(e.imap_port);
    setSmtp(e.smtp_host);
    setSmtpPort(e.smtp_port);
    setStarttls(e.smtp_starttls);
  }, [e]);

  const applyPreset = (p: (typeof MAIL_PRESETS)[number]) => {
    setImap(p.imap);
    setImapPort(993);
    setSmtp(p.smtp);
    setSmtpPort(p.port);
    setStarttls(p.starttls);
  };

  const connect = async () => {
    setBusy("save");
    setTest(null);
    try {
      await api.setEmail({
        enabled: true,
        address: address.trim(),
        password: password || undefined,
        imap_host: imap.trim(),
        imap_port: imapPort,
        smtp_host: smtp.trim(),
        smtp_port: smtpPort,
        smtp_starttls: starttls,
      });
      setPassword("");
      const result = await api.testEmail();
      setTest(result);
      toast(result.ok ? "Email connected" : "Saved, but the test failed");
      onChange();
    } catch (err) {
      toast((err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const disconnect = async () => {
    setBusy("off");
    try {
      await api.disconnectEmail();
      setTest(null);
      toast("Email disconnected");
      onChange();
    } catch (err) {
      toast((err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const status = e.enabled && e.configured ? { text: "Connected", tone: "ok" } : e.enabled ? { text: "Incomplete", tone: "warn" } : { text: "Not connected", tone: "off" };

  return (
    <Card
      icon={<Mail size={19} />}
      title="Email"
      summary={e.configured && e.enabled ? `${e.address} · reads and sends` : "Read your inbox, draft and send mail"}
      status={status}
      open={open}
      onToggle={compact ? undefined : () => setOpen(!open)}
    >
      <p className="text-[12.5px] text-muted -mt-1">
        Reading is a moderate action; sending always asks you first. Use an app password where your provider offers one.
      </p>
      <Field label="Provider">
        <div className="flex flex-wrap gap-1.5">
          {MAIL_PRESETS.map((p) => (
            <button key={p.id} type="button" onClick={() => applyPreset(p)} className={cx("rounded-full px-3 py-1.5 text-[13px] border", imap === p.imap ? "border-accent bg-accent/10 text-accent font-medium" : "border-border text-muted")}>
              {p.label}
            </button>
          ))}
        </div>
      </Field>
      <Field label="Address">
        <input value={address} onChange={(ev) => setAddress(ev.target.value)} className={inputCls} placeholder="you@example.com" inputMode="email" autoComplete="off" />
      </Field>
      <Field label="Password" hint={e.password_set ? "A password is in the vault. Leave blank to keep it." : "Stored encrypted in the vault as EMAIL_PASSWORD."}>
        <input type="password" value={password} onChange={(ev) => setPassword(ev.target.value)} className={inputCls} placeholder={e.password_set ? "••••••••" : "app password"} autoComplete="off" />
      </Field>
      <div className="grid grid-cols-[1fr_84px] gap-2">
        <Field label="IMAP server">
          <input value={imap} onChange={(ev) => setImap(ev.target.value)} className={inputCls} placeholder="imap.example.com" />
        </Field>
        <Field label="Port">
          <input type="number" value={imapPort} onChange={(ev) => setImapPort(Number(ev.target.value))} className={inputCls} />
        </Field>
        <Field label="SMTP server">
          <input value={smtp} onChange={(ev) => setSmtp(ev.target.value)} className={inputCls} placeholder="smtp.example.com" />
        </Field>
        <Field label="Port">
          <input type="number" value={smtpPort} onChange={(ev) => setSmtpPort(Number(ev.target.value))} className={inputCls} />
        </Field>
      </div>
      <label className="flex items-center gap-2 text-[13.5px]">
        <input type="checkbox" checked={starttls} onChange={(ev) => setStarttls(ev.target.checked)} className="accent-[var(--om-accent)]" /> STARTTLS for SMTP (off for port 465)
      </label>
      <div className="flex gap-2 pt-1">
        <button type="button" disabled={busy !== null || !address.trim() || !imap.trim() || !smtp.trim() || (!password && !e.password_set)} onClick={() => void connect()} className={primaryBtn}>
          {busy === "save" ? <Loader2 size={16} className="animate-spin" /> : <Plug size={16} />} {e.configured ? "Save & test" : "Connect"}
        </button>
        {e.enabled && (
          <button type="button" disabled={busy !== null} onClick={() => void disconnect()} className={secondaryBtn}>
            {busy === "off" ? <Loader2 size={16} className="animate-spin" /> : <Unplug size={16} />} Disconnect
          </button>
        )}
      </div>
      {test && <TestLine result={test} okText={`Signed in · ${test.inbox ?? "?"} messages in the inbox`} />}
    </Card>
  );
}

// ------------------------------------------------------------------ browser
function BrowserCard({ data, onChange }: { data: ConnectionsData; onChange: () => void }) {
  const { toast } = useStore();
  const b = data.browser;
  const [busy, setBusy] = useState(false);
  const flip = async () => {
    setBusy(true);
    try {
      await api.setBrowser(!b.enabled);
      onChange();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card
      icon={<Globe size={19} />}
      title="Browser"
      summary={b.available ? "Open pages, click, fill forms, screenshot" : "Playwright is not installed on the server"}
      status={b.enabled && b.available ? { text: "On", tone: "ok" } : b.enabled ? { text: "Unavailable", tone: "warn" } : { text: "Off", tone: "off" }}
      open={false}
      trailing={
        <button type="button" role="switch" aria-checked={b.enabled} disabled={busy} onClick={() => void flip()} className={cx("relative h-7 w-12 shrink-0 rounded-full transition", b.enabled ? "bg-accent" : "bg-surface-2 border border-border")}>
          <span className={cx("absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition", b.enabled ? "left-[22px]" : "left-0.5")} />
        </button>
      }
    >
      {!b.available && (
        <p className="text-[12.5px] text-muted">
          Install it where the server runs: <code className="rounded bg-surface-2 px-1">pip install &quot;openmuse[browser]&quot; &amp;&amp; playwright install chromium</code>
        </p>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ mcp
function MCPCard({ data, onChange }: { data: ConnectionsData; onChange: () => void }) {
  const { toast } = useStore();
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [command, setCommand] = useState("");
  const [url, setUrl] = useState("");
  const [risk, setRisk] = useState("moderate");
  const [busy, setBusy] = useState<string | null>(null);

  const add = async () => {
    setBusy("add");
    try {
      const parts = command.trim().split(/\s+/).filter(Boolean);
      await api.addMCP({
        name: name.trim(),
        command: parts[0] ?? null,
        args: parts.slice(1),
        url: url.trim() || null,
        risk,
      });
      setName("");
      setCommand("");
      setUrl("");
      setAdding(false);
      toast("Server connected");
      onChange();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const remove = async (n: string) => {
    setBusy(n);
    try {
      await api.removeMCP(n);
      onChange();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const connected = data.mcp.filter((m) => m.connected).length;
  return (
    <Card
      icon={<Plug size={19} />}
      title="MCP servers"
      summary={data.mcp.length ? `${connected} of ${data.mcp.length} connected · ${data.mcp.reduce((n, m) => n + m.tools, 0)} tools` : "Add tools from any Model Context Protocol server"}
      status={data.mcp.length ? { text: `${connected} on`, tone: connected ? "ok" : "warn" } : { text: "None", tone: "off" }}
      open={open}
      onToggle={() => setOpen(!open)}
    >
      {data.mcp.length > 0 && (
        <ul className="space-y-1.5">
          {data.mcp.map((m) => (
            <li key={m.name} className="flex items-center gap-2.5 rounded-2xl bg-surface-2/60 px-3 py-2">
              <span className={cx("h-2 w-2 rounded-full", m.connected ? "bg-emerald-500" : "bg-rose-500")} />
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium truncate">{m.name}</div>
                <div className="text-[11.5px] text-muted truncate">
                  {m.url ?? [m.command, ...m.args].join(" ")} · {m.tools} tools · {m.risk}
                  {!m.from_app && " · from config.toml"}
                </div>
              </div>
              {m.from_app && (
                <button type="button" aria-label="Remove" disabled={busy === m.name} onClick={() => void remove(m.name)} className="p-1.5 rounded-full text-muted hover:bg-surface-2">
                  {busy === m.name ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {adding ? (
        <div className="space-y-2.5 rounded-2xl border border-border/70 p-3">
          <Field label="Name">
            <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} placeholder="filesystem" />
          </Field>
          <Field label="Command" hint="Run locally over stdio, for example: npx -y @modelcontextprotocol/server-filesystem ./workspace">
            <input value={command} onChange={(e) => setCommand(e.target.value)} className={inputCls} placeholder="npx -y @modelcontextprotocol/server-…" />
          </Field>
          <Field label="or URL" hint="A remote server over Streamable HTTP.">
            <input value={url} onChange={(e) => setUrl(e.target.value)} className={inputCls} placeholder="https://host/mcp" inputMode="url" />
          </Field>
          <Field label="Risk of its tools" hint="Decides when the Sentinel asks you before a call.">
            <div className="flex gap-1.5">
              {["safe", "moderate", "high"].map((r) => (
                <button key={r} type="button" onClick={() => setRisk(r)} className={cx("rounded-full px-3 py-1.5 text-[13px] border", risk === r ? "border-accent bg-accent/10 text-accent font-medium" : "border-border text-muted")}>
                  {r}
                </button>
              ))}
            </div>
          </Field>
          <div className="flex gap-2">
            <button type="button" disabled={busy === "add" || !name.trim() || !(command.trim() || url.trim())} onClick={() => void add()} className={primaryBtn}>
              {busy === "add" ? <Loader2 size={16} className="animate-spin" /> : <Plug size={16} />} Connect
            </button>
            <button type="button" onClick={() => setAdding(false)} className={secondaryBtn}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button type="button" onClick={() => setAdding(true)} className={secondaryBtn}>
          <Plus size={16} /> Add a server
        </button>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ vault
function VaultCard({ data, onChange }: { data: ConnectionsData; onChange: () => void }) {
  const { toast } = useStore();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const add = async () => {
    setBusy("add");
    try {
      await api.vaultSet(name.trim(), value);
      setName("");
      setValue("");
      toast("Stored in the vault");
      onChange();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const remove = async (n: string) => {
    setBusy(n);
    try {
      await api.vaultDelete(n);
      onChange();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card
      icon={<KeyRound size={19} />}
      title="Vault"
      summary={data.vault.length ? `${data.vault.length} secrets · encrypted on your machine` : "Encrypted secrets the model never sees"}
      status={{ text: `${data.vault.length}`, tone: "off" }}
      open={open}
      onToggle={() => setOpen(!open)}
    >
      <p className="text-[12.5px] text-muted -mt-1">
        Refer to a secret as <code className="rounded bg-surface-2 px-1">{"{{vault:NAME}}"}</code> in a tool call or config: the value is filled in after the Sentinel approves and is redacted from everything the model reads.
      </p>
      {data.vault.length > 0 && (
        <ul className="flex flex-wrap gap-1.5">
          {data.vault.map((n) => (
            <li key={n} className="flex items-center gap-1 rounded-full bg-surface-2 pl-3 pr-1 py-1 text-[12.5px] font-mono">
              {n}
              <button type="button" aria-label={`Delete ${n}`} disabled={busy === n} onClick={() => void remove(n)} className="p-1 rounded-full text-muted hover:text-rose-500">
                {busy === n ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="grid grid-cols-[1fr_1fr_auto] gap-2 items-end">
        <Field label="Name">
          <input value={name} onChange={(e) => setName(e.target.value.toUpperCase().replace(/[^A-Z0-9_.-]/g, "_"))} className={cx(inputCls, "font-mono")} placeholder="GITHUB_TOKEN" />
        </Field>
        <Field label="Value">
          <input type="password" value={value} onChange={(e) => setValue(e.target.value)} className={inputCls} placeholder="secret" autoComplete="off" />
        </Field>
        <button type="button" disabled={busy === "add" || !name || !value} onClick={() => void add()} className={cx(primaryBtn, "px-3")} aria-label="Store">
          {busy === "add" ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
        </button>
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------ bits
function Card({
  icon,
  title,
  summary,
  status,
  open,
  onToggle,
  trailing,
  children,
}: {
  icon: ReactNode;
  title: string;
  summary: string;
  status: { text: string; tone: string };
  open: boolean;
  onToggle?: () => void;
  trailing?: ReactNode;
  children?: ReactNode;
}) {
  const head = (
    <>
      <span className="text-accent mt-0.5">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="text-[15px] font-semibold">{title}</span>
          <span
            className={cx(
              "rounded-full px-2 py-0.5 text-[11px] font-medium",
              status.tone === "ok" && "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300",
              status.tone === "warn" && "bg-amber-500/15 text-amber-700 dark:text-amber-300",
              status.tone === "off" && "bg-surface-2 text-muted",
            )}
          >
            {status.text}
          </span>
        </span>
        <span className="block text-[12.5px] text-muted truncate">{summary}</span>
      </span>
      {trailing ?? (onToggle ? (open ? <ChevronUp size={18} className="text-muted" /> : <ChevronDown size={18} className="text-muted" />) : null)}
    </>
  );
  return (
    <section className="rounded-3xl bg-surface border border-border/70 shadow-sm">
      {onToggle ? (
        <button type="button" onClick={onToggle} className="flex w-full items-start gap-3 px-4 py-3.5 text-left">
          {head}
        </button>
      ) : (
        <div className="flex w-full items-start gap-3 px-4 py-3.5">{head}</div>
      )}
      {(open || (!onToggle && children)) && children ? <div className="px-4 pb-4 space-y-3">{children}</div> : null}
    </section>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div>
      <label className="text-[12px] text-muted">{label}</label>
      <div className="mt-1">{children}</div>
      {hint && <div className="mt-1 text-[11.5px] text-muted leading-snug">{hint}</div>}
    </div>
  );
}

function TestLine({ result, okText }: { result: TestResult; okText: string }) {
  return (
    <div className={cx("rounded-2xl px-3 py-2 text-[12.5px]", result.ok ? "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300" : "bg-rose-500/12 text-rose-700 dark:text-rose-300")}>
      {result.ok ? okText : result.error}
    </div>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

export const inputCls =
  "w-full rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[14.5px] outline-none focus:ring-2 focus:ring-accent/40";
export const primaryBtn =
  "flex items-center justify-center gap-1.5 rounded-2xl bg-accent text-accent-fg px-4 py-2.5 text-[14px] font-medium disabled:opacity-40";
export const secondaryBtn =
  "flex items-center justify-center gap-1.5 rounded-2xl border border-border px-4 py-2.5 text-[14px] font-medium text-muted disabled:opacity-40";
