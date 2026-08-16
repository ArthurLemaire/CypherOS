import { Brain, Lightbulb, MessageCircle, Target, UserRound, WifiOff } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { setToken } from "./api";
import { ChatScreen } from "./screens/ChatScreen";
import { GoalsScreen } from "./screens/GoalsScreen";
import { IdeasScreen } from "./screens/IdeasScreen";
import { MemoryScreen } from "./screens/MemoryScreen";
import { SettingsScreen } from "./screens/SettingsScreen";
import { useStore, type Tab } from "./store";
import { cx } from "./util";

const TABS: Array<{ id: Tab; label: string; icon: (active: boolean) => ReactNode }> = [
  { id: "chat", label: "Chat", icon: (a) => <MessageCircle size={23} strokeWidth={a ? 2.4 : 1.9} /> },
  { id: "goals", label: "Goals", icon: (a) => <Target size={23} strokeWidth={a ? 2.4 : 1.9} /> },
  { id: "ideas", label: "Ideas", icon: (a) => <Lightbulb size={23} strokeWidth={a ? 2.4 : 1.9} /> },
  { id: "memory", label: "Memory", icon: (a) => <Brain size={23} strokeWidth={a ? 2.4 : 1.9} /> },
  { id: "you", label: "You", icon: (a) => <UserRound size={23} strokeWidth={a ? 2.4 : 1.9} /> },
];

export default function App() {
  const { state, setTab } = useStore();

  // Accent colour follows the avatar colour; document title follows the name.
  useEffect(() => {
    if (state.profile?.color) document.documentElement.style.setProperty("--om-accent", state.profile.color);
    document.title = state.profile?.name ? `${state.profile.name} · OpenMuse` : "OpenMuse";
  }, [state.profile?.color, state.profile?.name]);

  if (state.authError) return <TokenGate />;

  const pendingApprovals = Object.values(state.events)
    .flat()
    .filter((e) => e.type === "approval" && e.status === "pending").length;
  const activeGoals = state.goals.filter((g) => g.status === "active").length;

  return (
    <div className="mx-auto flex h-[100dvh] max-w-[760px] flex-col bg-bg sm:border-x sm:border-border">
      {!state.connected && state.loaded && (
        <div className="flex items-center justify-center gap-2 bg-amber-500/15 text-amber-700 dark:text-amber-300 text-[12.5px] py-1">
          <WifiOff size={14} /> Reconnecting to your Muse…
        </div>
      )}
      {state.error && !state.loaded && (
        <div className="m-4 rounded-2xl bg-rose-500/12 text-rose-700 dark:text-rose-300 p-3 text-[13.5px]">
          Could not reach the server: {state.error}
        </div>
      )}
      <main className="min-h-0 flex-1">
        {state.tab === "chat" && <ChatScreen />}
        {state.tab === "goals" && <GoalsScreen />}
        {state.tab === "ideas" && <IdeasScreen />}
        {state.tab === "memory" && <MemoryScreen />}
        {state.tab === "you" && <SettingsScreen />}
      </main>
      <nav className="safe-bottom shrink-0 border-t border-border bg-surface/90 backdrop-blur">
        <ul className="grid grid-cols-5">
          {TABS.map((t) => {
            const active = state.tab === t.id;
            const badge = t.id === "chat" ? pendingApprovals : t.id === "goals" ? activeGoals : 0;
            return (
              <li key={t.id}>
                <button
                  type="button"
                  onClick={() => setTab(t.id)}
                  className={cx(
                    "relative w-full flex flex-col items-center gap-0.5 pt-2 pb-1.5 text-[10.5px] font-medium transition",
                    active ? "text-accent" : "text-muted",
                  )}
                >
                  {t.icon(active)}
                  <span>{t.label}</span>
                  {badge > 0 && (
                    <span
                      className={cx(
                        "absolute top-1 left-1/2 ml-2 min-w-[17px] h-[17px] px-1 rounded-full text-[10px] font-bold flex items-center justify-center",
                        t.id === "chat" ? "bg-rose-500 text-white" : "bg-surface-2 text-muted",
                      )}
                    >
                      {badge}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      </nav>
      {state.toast && (
        <div className="pointer-events-none fixed inset-x-0 bottom-24 flex justify-center px-4">
          <div className="rise rounded-2xl bg-fg text-bg px-4 py-2 text-[13.5px] shadow-lg max-w-sm text-center">{state.toast}</div>
        </div>
      )}
    </div>
  );
}

function TokenGate() {
  const [value, setValue] = useState("");
  return (
    <div className="mx-auto flex h-[100dvh] max-w-md flex-col items-center justify-center px-6 text-center">
      <div className="text-5xl">✨</div>
      <h1 className="mt-3 text-[22px] font-bold">Connect to your Muse</h1>
      <p className="mt-2 text-[14px] text-muted">
        This app talks to the OpenMuse server you run yourself. Scan the QR code printed by{" "}
        <code className="rounded bg-surface-2 px-1">openmuse serve</code>, or paste the access token below.
      </p>
      <form
        className="mt-5 w-full flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (!value.trim()) return;
          setToken(value.trim());
          window.location.reload();
        }}
      >
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Access token"
          className="flex-1 rounded-2xl bg-surface-2 px-4 py-2.5 text-[15px] outline-none focus:ring-2 focus:ring-accent/40"
        />
        <button type="submit" className="rounded-2xl bg-accent text-accent-fg px-4 font-medium">
          Connect
        </button>
      </form>
    </div>
  );
}
