import { FolderOpen, Lightbulb, MessageCircle, Newspaper, Target, WifiOff } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { setToken } from "./api";
import { FileViewer } from "./components/FileViewer";
import { ChatScreen } from "./screens/ChatScreen";
import { ConnectionsScreen } from "./screens/ConnectionsScreen";
import { FeedScreen } from "./screens/FeedScreen";
import { GoalsScreen } from "./screens/GoalsScreen";
import { IdeasScreen } from "./screens/IdeasScreen";
import { LibraryScreen } from "./screens/LibraryScreen";
import { MemoryScreen } from "./screens/MemoryScreen";
import { Onboarding } from "./screens/Onboarding";
import { SettingsScreen } from "./screens/SettingsScreen";
import { SkillsScreen } from "./screens/SkillsScreen";
import { useStore, type Tab } from "./store";
import { useT } from "./i18n";
import { cx } from "./util";

/** The tab bar. Memory and Settings are reached through the avatar menu, like in Muse. */
const TABS: Array<{ id: Tab; label: string; icon: (active: boolean) => ReactNode }> = [
  { id: "chat", label: "Chat", icon: (a) => <MessageCircle size={23} strokeWidth={a ? 2.4 : 1.9} /> },
  { id: "feed", label: "Feed", icon: (a) => <Newspaper size={23} strokeWidth={a ? 2.4 : 1.9} /> },
  { id: "ideas", label: "Ideas", icon: (a) => <Lightbulb size={23} strokeWidth={a ? 2.4 : 1.9} /> },
  { id: "goals", label: "Goals", icon: (a) => <Target size={23} strokeWidth={a ? 2.4 : 1.9} /> },
  { id: "library", label: "Library", icon: (a) => <FolderOpen size={23} strokeWidth={a ? 2.4 : 1.9} /> },
];

export default function App() {
  const { state, setTab, openFile } = useStore();
  const t = useT();

  // Accent colour follows the avatar colour; document title follows the name.
  useEffect(() => {
    if (state.profile?.color) document.documentElement.style.setProperty("--om-accent", state.profile.color);
    document.title = state.profile?.name ? `${state.profile.name} · OpenMuse` : "OpenMuse";
  }, [state.profile?.color, state.profile?.name]);

  if (state.authError) return <TokenGate />;
  // First run: the server has not seen setup finish and nothing has been said yet.
  if (state.loaded && state.settings && !state.settings.onboarded && !state.onboardingDismissed && !state.threads.some((t) => t.events > 0)) {
    return <Onboarding />;
  }

  const pendingApprovals = state.pendingApprovals.length;
  const activeGoals = state.goals.filter((g) => g.status === "active").length;
  // a plan change waiting for your answer is worth a red badge; the count of goals is not
  const proposals = state.goals.filter((g) => g.proposal && g.status !== "cancelled").length;
  const feedUnseen = state.pendingApprovals.filter((a) => a.ts > state.feedSeenAt).length;

  return (
    <div className="mx-auto flex h-[100dvh] max-w-[760px] flex-col bg-bg sm:border-x sm:border-border">
      {!state.connected && state.loaded && (
        <div className="flex items-center justify-center gap-2 bg-amber-500/15 text-amber-700 dark:text-amber-300 text-[12.5px] py-1">
          <WifiOff size={14} /> {t("Reconnecting to your Muse…")}
        </div>
      )}
      {state.error && !state.loaded && (
        <div className="m-4 rounded-2xl bg-rose-500/12 text-rose-700 dark:text-rose-300 p-3 text-[13.5px]">
          {t("Could not reach the server: {error}", { error: state.error })}
        </div>
      )}
      <main className="min-h-0 flex-1">
        {state.tab === "chat" && <ChatScreen />}
        {state.tab === "feed" && <FeedScreen />}
        {state.tab === "ideas" && <IdeasScreen />}
        {state.tab === "goals" && <GoalsScreen />}
        {state.tab === "library" && <LibraryScreen />}
        {state.tab === "memory" && <MemoryScreen />}
        {state.tab === "skills" && <SkillsScreen />}
        {state.tab === "connections" && <ConnectionsScreen />}
        {state.tab === "you" && <SettingsScreen />}
      </main>
      <nav className="safe-bottom shrink-0 border-t border-border bg-surface/90 backdrop-blur">
        <ul className="grid grid-cols-5">
          {TABS.map((tab) => {
            const active = state.tab === tab.id;
            const badge = tab.id === "chat" ? pendingApprovals : tab.id === "feed" ? feedUnseen : tab.id === "goals" ? proposals || activeGoals : 0;
            return (
              <li key={tab.id}>
                <button
                  type="button"
                  onClick={() => setTab(tab.id)}
                  className={cx(
                    "relative w-full flex flex-col items-center gap-0.5 pt-2 pb-1.5 text-[10.5px] font-medium transition",
                    active ? "text-accent" : "text-muted",
                  )}
                >
                  {tab.icon(active)}
                  <span>{t(tab.label)}</span>
                  {badge > 0 && (
                    <span
                      className={cx(
                        "absolute top-1 left-1/2 ml-2 min-w-[17px] h-[17px] px-1 rounded-full text-[10px] font-bold flex items-center justify-center",
                        tab.id === "goals" && !proposals ? "bg-surface-2 text-muted" : "bg-rose-500 text-white",
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
      <FileViewer path={state.viewer} onClose={() => openFile(null)} />
      {state.toast && (
        <div className="pointer-events-none fixed inset-x-0 bottom-24 z-[70] flex justify-center px-4">
          <div className="rise rounded-2xl bg-fg text-bg px-4 py-2 text-[13.5px] shadow-lg max-w-sm text-center">{state.toast}</div>
        </div>
      )}
    </div>
  );
}

function TokenGate() {
  const [value, setValue] = useState("");
  const t = useT();
  return (
    <div className="mx-auto flex h-[100dvh] max-w-md flex-col items-center justify-center px-6 text-center">
      <div className="text-5xl">✨</div>
      <h1 className="mt-3 text-[22px] font-bold">{t("Connect to your Muse")}</h1>
      <p className="mt-2 text-[14px] text-muted">
        {t("This app talks to the OpenMuse server you run yourself. Scan the QR code printed by")}{" "}
        <code className="rounded bg-surface-2 px-1">openmuse serve</code>{t(", or paste the access token below.")}
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
          placeholder={t("Access token")}
          className="flex-1 rounded-2xl bg-surface-2 px-4 py-2.5 text-[15px] outline-none focus:ring-2 focus:ring-accent/40"
        />
        <button type="submit" className="rounded-2xl bg-accent text-accent-fg px-4 font-medium">
          {t("Connect")}
        </button>
      </form>
    </div>
  );
}
