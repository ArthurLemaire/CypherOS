import { LayoutGrid, Lightbulb, MessageCircle, Newspaper, SquareCheckBig, WifiOff } from "lucide-react";
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

/** The tab bar: five icons in a floating pill, as in Muse. Memory and Settings are behind the avatar. */
const TABS: Array<{ id: Tab; label: string; icon: (active: boolean) => ReactNode }> = [
  { id: "chat", label: "Chat", icon: (a) => <MessageCircle size={22} strokeWidth={a ? 2.2 : 1.8} /> },
  { id: "feed", label: "Feed", icon: (a) => <Newspaper size={22} strokeWidth={a ? 2.2 : 1.8} /> },
  { id: "ideas", label: "Ideas", icon: (a) => <Lightbulb size={22} strokeWidth={a ? 2.2 : 1.8} /> },
  { id: "goals", label: "Goals", icon: (a) => <SquareCheckBig size={22} strokeWidth={a ? 2.2 : 1.8} /> },
  { id: "library", label: "Library", icon: (a) => <LayoutGrid size={22} strokeWidth={a ? 2.2 : 1.8} /> },
];

export default function App() {
  const { state, setTab, openFile } = useStore();
  const t = useT();

  // The document title follows the agent's name.
  useEffect(() => {
    document.title = state.profile?.name ? `${state.profile.name} · OpenMuse` : "OpenMuse";
  }, [state.profile?.name]);

  if (state.authError) return <TokenGate />;
  // First run: the server has not seen setup finish and nothing has been said yet.
  if (state.loaded && state.settings && !state.settings.onboarded && !state.onboardingDismissed && !state.threads.some((t) => t.events > 0)) {
    return <Onboarding />;
  }

  const pendingApprovals = state.pendingApprovals.length;
  // a plan change waiting for your answer is worth a red badge; the count of goals is not
  const proposals = state.goals.filter((g) => g.proposal && g.status !== "cancelled").length;
  const feedUnseen = state.pendingApprovals.filter((a) => a.ts > state.feedSeenAt).length;

  return (
    <div className="mx-auto flex h-[100dvh] max-w-[760px] flex-col bg-bg sm:border-x sm:border-border">
      {!state.connected && state.loaded && (
        <div className="flex items-center justify-center gap-2 bg-amber-500/15 text-amber-700 dark:text-amber-300 text-[12.5px] py-1">
          <WifiOff size={14} /> {t("Reconnecting to your OpenMuse…")}
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
      <nav className="safe-bottom shrink-0 bg-bg px-4 pb-2.5 pt-1.5">
        <ul className="mx-auto flex w-fit items-center gap-1 rounded-full border border-border/70 bg-surface p-1.5 shadow-[0_6px_24px_-8px_rgba(0,0,0,0.18)]">
          {TABS.map((tab) => {
            const active = state.tab === tab.id;
            const badge = tab.id === "chat" ? pendingApprovals : tab.id === "feed" ? feedUnseen : tab.id === "goals" ? proposals : 0;
            return (
              <li key={tab.id}>
                <button
                  type="button"
                  onClick={() => setTab(tab.id)}
                  aria-label={t(tab.label)}
                  aria-current={active ? "page" : undefined}
                  className={cx(
                    "relative flex h-11 w-[52px] items-center justify-center rounded-full transition",
                    active ? "bg-surface-2 text-fg" : "text-fg/65 hover:text-fg",
                  )}
                >
                  {tab.icon(active)}
                  {badge > 0 && (
                    <span className="absolute right-2 top-1 flex h-[17px] min-w-[17px] items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-bold text-white">
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
      <img src="/avatars/sunny.webp" alt="" className="avatar-idle h-24 w-24 rounded-full object-cover" />
      <h1 className="mt-4 text-[22px] font-bold">{t("Connect to your OpenMuse")}</h1>
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
