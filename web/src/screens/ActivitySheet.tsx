import { Ban, Check, ShieldCheck, ShieldOff } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { RiskBadge, toolIcon } from "../components/Cards";
import { Sheet } from "../components/Sheet";
import { useStore } from "../store";
import type { ActivityData, AuditEntry, RiskLevel } from "../types";
import { cx, timeShort } from "../util";

/** Tap the avatar: what your Muse has been doing, and what it is allowed to do. */
export function ActivitySheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { state, toast } = useStore();
  const [data, setData] = useState<ActivityData | null>(null);
  const [view, setView] = useState<"activity" | "permissions">("activity");

  useEffect(() => {
    if (!open) return;
    let alive = true;
    const load = () => api.activity(150).then((d) => alive && setData(d)).catch(() => undefined);
    load();
    const t = window.setInterval(load, 4000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [open]);

  const reset = async () => {
    if (!window.confirm("Forget every “allow for session / always” permission you granted?")) return;
    try {
      await api.resetApprovals();
      setData(await api.activity(150));
      toast("Permissions reset");
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const name = state.profile?.name ?? "Muse";
  const entries = (data?.audit ?? []).filter((e) => e.event === "tool_call").reverse();

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={
        <div className="flex items-center gap-2">
          <span>{name}</span>
          <span className="text-[12px] font-normal text-muted">
            {state.status.state === "idle" ? "idle" : state.status.detail || state.status.state}
          </span>
        </div>
      }
    >
      <div className="mb-3 grid grid-cols-2 rounded-2xl bg-surface-2 p-1 text-[13.5px] font-medium">
        {(["activity", "permissions"] as const).map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => setView(v)}
            className={cx("rounded-xl py-1.5 capitalize", view === v && "bg-surface shadow-sm")}
          >
            {v}
          </button>
        ))}
      </div>

      {view === "activity" ? (
        <div>
          <p className="text-[12.5px] text-muted mb-2">
            Every tool call goes through the Sentinel and is written to the audit log — including the ones it refused.
          </p>
          {entries.length === 0 && <div className="py-8 text-center text-muted text-[14px]">Nothing yet.</div>}
          <ul className="space-y-1.5">
            {entries.map((e, i) => (
              <AuditRow key={`${e.ts}-${i}`} entry={e} />
            ))}
          </ul>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="rounded-2xl border border-border p-3.5">
            <div className="flex items-center gap-2 font-medium">
              <ShieldCheck size={18} className="text-accent" /> Sentinel mode:{" "}
              <span className="capitalize">{state.settings?.sentinel.mode}</span>
            </div>
            <p className="mt-1 text-[12.5px] text-muted">
              {state.settings?.sentinel.mode === "ask" && "Safe and moderate actions run freely; anything sensitive (email, shell, purchases) waits for you."}
              {state.settings?.sentinel.mode === "strict" && "Moderate and sensitive actions both wait for your approval."}
              {state.settings?.sentinel.mode === "auto" && "Everything is approved automatically except explicit deny rules. Use with care."}
            </p>
            {data?.tainted && (
              <p className="mt-2 text-[12.5px] text-amber-600 dark:text-amber-300 flex items-center gap-1.5">
                <ShieldOff size={14} /> Private data was read this session: network calls to new destinations need approval.
              </p>
            )}
          </div>
          <PermissionList title="Allowed until restart" tools={data?.approvals.session ?? []} />
          <PermissionList title="Always allowed" tools={data?.approvals.persistent ?? []} />
          <PermissionList title="Always ask (from config)" tools={state.settings?.sentinel.always_ask_tools ?? []} muted />
          {((data?.approvals.session.length ?? 0) > 0 || (data?.approvals.persistent.length ?? 0) > 0) && (
            <button type="button" onClick={() => void reset()} className="w-full rounded-2xl border border-border py-2.5 text-[14px] font-medium">
              Reset granted permissions
            </button>
          )}
        </div>
      )}
    </Sheet>
  );
}

function PermissionList({ title, tools, muted }: { title: string; tools: string[]; muted?: boolean }) {
  return (
    <div>
      <div className="text-[12px] uppercase tracking-wide text-muted font-semibold mb-1.5">{title}</div>
      {tools.length === 0 ? (
        <div className="text-[13px] text-muted">None</div>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {tools.map((t) => (
            <span key={t} className={cx("rounded-full px-2.5 py-1 text-[12.5px] flex items-center gap-1", muted ? "bg-surface-2 text-muted" : "bg-accent/12 text-accent")}>
              {toolIcon(t, 12)} {t}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function AuditRow({ entry }: { entry: AuditEntry }) {
  const denied = entry.decision === "deny";
  const failed = entry.ok === false && !denied;
  return (
    <li className="flex items-start gap-2.5 rounded-2xl bg-surface-2/60 px-3 py-2">
      <div className={cx("mt-0.5", denied ? "text-rose-500" : failed ? "text-amber-500" : "text-muted")}>
        {denied ? <Ban size={15} /> : failed ? <Ban size={15} /> : <Check size={15} />}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-[13.5px]">
          <span className="text-muted">{toolIcon(entry.tool ?? "", 13)}</span>
          <span className="font-medium truncate">{entry.summary || entry.tool}</span>
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11.5px] text-muted">
          <span>{timeShort(entry.ts)}</span>
          {entry.risk && <RiskBadge risk={entry.risk as RiskLevel} />}
          {entry.approved === true && <span className="text-emerald-600 dark:text-emerald-300">approved by you{entry.approval_scope && entry.approval_scope !== "once" ? ` (${entry.approval_scope})` : ""}</span>}
          {denied && <span className="text-rose-500">blocked</span>}
          {failed && <span className="text-amber-600">failed</span>}
          {typeof entry.duration_ms === "number" && <span>{(entry.duration_ms / 1000).toFixed(1)}s</span>}
        </div>
        {denied && entry.reasons && entry.reasons.length > 0 && (
          <div className="mt-0.5 text-[12px] text-muted">{entry.reasons.join(" · ")}</div>
        )}
      </div>
    </li>
  );
}
