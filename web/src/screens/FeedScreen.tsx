import {
  ArrowRight,
  Bell,
  CalendarClock,
  CalendarDays,
  ChevronDown,
  FileText,
  Loader2,
  Mail,
  MapPin,
  MessageCircleQuestion,
  Moon,
  PenLine,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  Trash2,
  Webhook,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Markdown } from "../components/Markdown";
import { intlLocale, localLabel, t, useLocale, useT } from "../i18n";
import { useStore } from "../store";
import type { CalendarData, CalendarEvent, FeedItem, FeedPost, FeedPostsData, UpcomingData } from "../types";
import { cx, relativeTime, timeShort } from "../util";

/**
 * The Feed, the way Muse does it: posts written for you from what it knows, steered by
 * your "feed instructions" — and, below them, what happened while you were away: replies
 * from background passes, files it made, cards still waiting for you.
 */
export function FeedScreen() {
  const { state, send, openThread, openFile, markFeedSeen, setTab, toast } = useStore();
  const [items, setItems] = useState<FeedItem[] | null>(null);
  const [posts, setPosts] = useState<FeedPostsData | null>(null);
  const [upcoming, setUpcoming] = useState<UpcomingData | null>(null);
  const [calendar, setCalendar] = useState<CalendarData | null>(null);
  const name = state.profile?.name ?? "OpenMuse";
  const t = useT();
  const locale = useLocale();

  useEffect(() => {
    let alive = true;
    api.feed(80)
      .then((d) => alive && setItems(d))
      .catch((e: Error) => toast(e.message));
    api.upcoming()
      .then((d) => alive && setUpcoming(d))
      .catch(() => undefined);
    api.feedPosts()
      .then((d) => alive && setPosts(d))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.feedVersion, state.remindersVersion]);

  // the day's events, when a calendar is connected (a feed refresh pushes a new version)
  useEffect(() => {
    let alive = true;
    api.calendar()
      .then((d) => alive && setCalendar(d))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [state.calendarVersion, state.connectionsVersion]);

  // Looking at the feed marks it read — the newest item's time is the watermark.
  useEffect(() => {
    if (items && items.length && items[0].ts > state.feedSeenAt) markFeedSeen(items[0].ts);
  }, [items, state.feedSeenAt, markFeedSeen]);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const groups = useMemo(() => groupByDay(items ?? []), [items, locale]);

  return (
    <div className="flex h-full flex-col">
      <header className="safe-top shrink-0 px-5 pt-4 pb-3">
        <h1 className="text-[24px] font-bold tracking-tight">{t("Feed")}</h1>
        <p className="text-[13px] text-muted">{t("Written for you by {name}, from what it knows — plus what it did while you were away.", { name })}</p>
      </header>

      <div className="flex-1 overflow-y-auto px-4 pb-6 space-y-4">
        <FeedInstructions data={posts} name={name} onChange={setPosts} />
        {posts && posts.posts.length > 0 && (
          <section className="space-y-3">
            {posts.posts.map((p) => (
              <PostCard
                key={p.id}
                post={p}
                name={name}
                onAsk={() => {
                  void send("main", p.prompt);
                  openThread("main");
                }}
                onDelete={async () => {
                  try {
                    await api.deleteFeedPost(p.id);
                    setPosts((d) => (d ? { ...d, posts: d.posts.filter((x) => x.id !== p.id) } : d));
                  } catch (e) {
                    toast((e as Error).message);
                  }
                }}
              />
            ))}
          </section>
        )}

        {upcoming && <NextUp data={upcoming} name={name} onSettings={() => setTab("you")} onGoals={() => setTab("goals")} />}
        {calendar?.configured && <TodayBlock data={calendar} onAsk={() => openThread("main")} />}

        {items && items.length === 0 && (!posts || posts.posts.length === 0) && (
          <div className="py-10 text-center text-muted text-[14px] px-6">
            <Moon size={28} className="mx-auto mb-2 opacity-60" />
            {t("Nothing yet. Once {name} works on a goal in the background or needs your approval, it shows up here.", { name })}
          </div>
        )}

        {items && items.length > 0 && (
          <div className="px-1 pt-1 text-[12px] font-semibold uppercase tracking-wide text-muted">{t("While you were away")}</div>
        )}
        {groups.map(([day, list]) => (
          <section key={day}>
            <div className="px-1 mb-1.5 text-[12px] uppercase tracking-wide text-muted font-semibold">{day}</div>
            <ul className="space-y-2">
              {list.map((it) => (
                <li key={it.id}>
                  <FeedRow
                    item={it}
                    unseen={it.ts > state.feedSeenAt}
                    onOpen={() => {
                      if (it.kind === "artifact" && it.path) openFile(it.path);
                      else openThread(it.thread);
                    }}
                  />
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}

/** "Feed instructions": one prompt that steers what gets written here, and a way to ask for a batch now. */
function FeedInstructions({ data, name, onChange }: { data: FeedPostsData | null; name: string; onChange: (d: FeedPostsData) => void }) {
  const { toast } = useStore();
  const t = useT();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<"save" | "write" | null>(null);
  useEffect(() => {
    if (data && !editing) setText(data.instructions);
  }, [data, editing]);
  const save = async () => {
    setBusy("save");
    try {
      onChange(await api.setFeedInstructions(text));
      setEditing(false);
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const write = async () => {
    setBusy("write");
    try {
      const d = await api.refreshFeedPosts();
      onChange(d);
      if (d.error) toast(t("Could not write posts: {error}", { error: d.error }));
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const empty = !data?.instructions;
  return (
    <section className="rounded-[22px] border border-border/70 bg-surface px-4 py-3">
      <div className="flex items-center gap-2">
        <PenLine size={16} className="text-accent" />
        <div className="flex-1 text-[14.5px] font-semibold">{t("Feed instructions")}</div>
        <button
          type="button"
          onClick={() => void write()}
          disabled={busy !== null || !data}
          className="flex items-center gap-1.5 rounded-full bg-surface-2 px-3 py-1.5 text-[12.5px] font-medium text-fg disabled:opacity-60"
        >
          {busy === "write" ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
          {busy === "write" ? t("Writing…") : data?.posts.length ? t("New posts") : t("Write my feed")}
        </button>
      </div>
      {editing ? (
        <div className="mt-2.5">
          <textarea
            autoFocus
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={4}
            maxLength={2000}
            placeholder={t("e.g. Keep me up to date on cycling and Rust. A nudge on my goals every morning. Short posts, no fluff.")}
            className="w-full resize-none rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[14px] leading-snug outline-none focus:ring-2 focus:ring-accent/40"
          />
          <div className="mt-2 flex justify-end gap-2">
            <button type="button" onClick={() => setEditing(false)} className="rounded-full px-3.5 py-1.5 text-[13px] text-muted">
              {t("Cancel")}
            </button>
            <button
              type="button"
              onClick={() => void save()}
              disabled={busy !== null}
              className="rounded-full bg-accent px-4 py-1.5 text-[13px] font-semibold text-accent-fg disabled:opacity-60"
            >
              {t("Save")}
            </button>
          </div>
        </div>
      ) : (
        <button type="button" onClick={() => setEditing(true)} className="mt-1.5 block w-full text-left">
          <div className={cx("text-[13.5px] leading-snug", empty ? "text-muted" : "text-fg/90 line-clamp-3")}>
            {empty ? t("Tell {name} what you would like to read here — topics to follow, nudges on your goals, a morning plan, the tone. It writes a few posts a day from that and what it knows about you.", { name }) : data?.instructions}
          </div>
          <div className="mt-1 text-[12.5px] font-medium text-accent">{empty ? t("Write instructions") : t("Edit")}</div>
        </button>
      )}
    </section>
  );
}

function PostCard({ post, name, onAsk, onDelete }: { post: FeedPost; name: string; onAsk: () => void; onDelete: () => void }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const long = post.body.length > 320;
  return (
    <article className="rounded-[22px] border border-border/70 bg-surface px-4 pt-3.5 pb-3 shadow-[0_4px_20px_-12px_rgba(0,0,0,0.18)]">
      <div className="flex items-start gap-2">
        <h3 className="flex-1 text-[16px] font-semibold leading-snug">{post.title}</h3>
        <button type="button" onClick={onDelete} aria-label={t("Remove")} className="-mr-1.5 -mt-1 rounded-full p-1.5 text-muted/70 hover:bg-surface-2 hover:text-fg">
          <Trash2 size={15} />
        </button>
      </div>
      <div className={cx("md mt-1.5 text-[14.5px] leading-[1.5]", !open && long && "line-clamp-6")}>
        <Markdown text={post.body} />
      </div>
      {long && !open && (
        <button type="button" onClick={() => setOpen(true)} className="mt-1 flex items-center gap-0.5 text-[13px] font-medium text-accent">
          {t("Read more")} <ChevronDown size={14} />
        </button>
      )}
      <div className="mt-2.5 flex items-center gap-2 text-[12px] text-muted">
        <span>{relativeTime(post.ts)}</span>
        {post.prompt && (
          <button type="button" onClick={onAsk} className="ml-auto flex items-center gap-1 font-medium text-accent">
            {t("Ask {name}", { name })} <ArrowRight size={13} />
          </button>
        )}
      </div>
    </article>
  );
}

function NextUp({
  data,
  name,
  onSettings,
  onGoals,
}: {
  data: UpcomingData;
  name: string;
  onSettings: () => void;
  onGoals: () => void;
}) {
  const t = useT();
  const next = data.queue[0];
  const active = data.reminders.filter((r) => r.status === "active" && r.next_at);
  const nextReminder = active[0];
  const activeReminders = active.length;
  return (
    <div className="rounded-3xl border border-border/70 bg-surface shadow-sm px-4 py-3.5">
      <div className="flex items-center gap-2 text-[12px] uppercase tracking-wide text-muted font-semibold">
        <Bell size={13} /> {t("Next up")}
      </div>
      {!data.proactive ? (
        <div className="mt-1.5 text-[14px] leading-snug">
          {t("Background work is off. {name} only acts when you ask.", { name })}{" "}
          <button type="button" onClick={onSettings} className="text-accent font-medium">
            {t("Turn it on")}
          </button>
        </div>
      ) : !next ? (
        <div className="mt-1.5 text-[14px] leading-snug">
          {t("No goal has a next step to work on.")}{" "}
          <button type="button" onClick={onGoals} className="text-accent font-medium">
            {t("Add one")}
          </button>
        </div>
      ) : (
        <div className="mt-1.5 text-[14px] leading-snug">
          {data.busy
            ? t("Working now")
            : data.quiet_until
              ? t("Quiet hours — after {time}", { time: timeShort(data.quiet_until) })
              : data.next_pass_at
                ? t("Around {time}", { time: timeShort(data.next_pass_at) })
                : t("Soon")}
          : <span className="font-medium">{next.title}</span>
          {next.next_step && <span className="text-muted"> — {next.next_step}</span>}
          {next.overdue && <span className="text-rose-500 font-medium"> · {t("overdue")}</span>}
          {data.queue.length > 1 && <span className="text-muted"> · {t("{n} more in line", { n: data.queue.length - 1 })}</span>}
        </div>
      )}
      {data.check_ins[0] && (
        <div className="mt-1.5 text-[12.5px] text-muted">
          {t("Check-in on")} <span className="font-medium text-fg">{data.check_ins[0].title}</span> {relativeTime(data.check_ins[0].at)}
          {data.check_ins.length > 1 && ` · ${t("{n} more", { n: data.check_ins.length - 1 })}`}
        </div>
      )}
      {nextReminder && (
        <div className="mt-1.5 text-[12.5px] text-muted">
          {nextReminder.kind === "task" ? t("Routine") : t("Reminder")} <span className="font-medium text-fg">{nextReminder.text}</span>{" "}
          {relativeTime(nextReminder.next_at!)}
          {activeReminders > 1 && ` · ${t("{n} more", { n: activeReminders - 1 })}`}
        </div>
      )}
    </div>
  );
}

/** Today's events (and tomorrow's, when today is done) from the connected calendars. */
function TodayBlock({ data, onAsk }: { data: CalendarData; onAsk: () => void }) {
  const t = useT();
  // the server sends what overlaps today and tomorrow; what began by today is today's
  const isToday = (e: CalendarEvent) => e.start.slice(0, 10) <= data.today;
  const todays = data.events.filter(isToday);
  const later = data.events.filter((e) => !isToday(e));
  const now = new Date();
  const over = (e: CalendarEvent) => !e.all_day && new Date(e.end) < now;
  const broken = data.feeds.filter((f) => f.error);
  const showTomorrow = todays.every(over) && later.length > 0;
  const list = showTomorrow ? later : todays;
  return (
    <div className="rounded-3xl border border-border/70 bg-surface shadow-sm px-4 py-3.5">
      <div className="flex items-center gap-2 text-[12px] uppercase tracking-wide text-muted font-semibold">
        <CalendarDays size={13} /> {showTomorrow ? t("Tomorrow") : t("Today")}
        {list.length > 0 && <span className="ml-auto normal-case tracking-normal font-normal">{t("{n} scheduled", { n: list.length })}</span>}
      </div>
      {list.length === 0 ? (
        <div className="mt-1.5 text-[14px] leading-snug text-muted">{t("Nothing on the calendar today.")}</div>
      ) : (
        <ul className="mt-1.5 space-y-1">
          {list.map((e) => (
            <li key={`${e.uid}-${e.start}`} className={cx("flex items-baseline gap-2.5 text-[14px] leading-snug", !showTomorrow && over(e) && "opacity-50")}>
              <span className="w-[86px] shrink-0 tabular-nums text-[12.5px] text-muted">
                {e.all_day ? t("all day") : `${e.start.slice(11, 16)}–${e.end.slice(11, 16)}`}
              </span>
              <span className="min-w-0 flex-1">
                <span className="font-medium">{e.summary}</span>
                {e.location && (
                  <span className="text-muted text-[12.5px]">
                    {" "}
                    <MapPin size={11} className="inline -mt-0.5" /> {e.location}
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      {broken.length > 0 && <div className="mt-1.5 text-[12px] text-rose-500">{t("{name} could not be read", { name: broken.map((f) => f.name).join(", ") })}</div>}
      <button type="button" onClick={onAsk} className="mt-2 text-[12.5px] text-accent font-medium">
        {t("Ask about your week")}
      </button>
    </div>
  );
}

/** Markdown down to its words for a three-line preview. */
function plain(md: string): string {
  return md
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/(\*\*|__|`)/g, "")
    .replace(/^\s*[-*+]\s+/gm, "• ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .trim();
}

function FeedRow({ item, unseen, onOpen }: { item: FeedItem; unseen: boolean; onOpen: () => void }) {
  const t = useT();
  const icon =
    item.kind === "approval" ? (
      <ShieldAlert size={18} />
    ) : item.kind === "question" ? (
      <MessageCircleQuestion size={18} />
    ) : item.kind === "artifact" ? (
      <FileText size={18} />
    ) : item.quiet ? (
      <Moon size={18} />
    ) : item.title.startsWith("New mail: ") ? (
      <Mail size={18} />
    ) : item.title.startsWith("Coming up: ") ? (
      <CalendarClock size={18} />
    ) : item.title.startsWith("Webhook: ") ? (
      <Webhook size={18} />
    ) : (
      <Sparkles size={18} />
    );
  const tone =
    item.kind === "approval"
      ? "bg-amber-500/12 text-amber-600 dark:text-amber-300"
      : item.kind === "question"
        ? "bg-accent/12 text-accent"
        : "bg-surface-2 text-muted";
  if (item.quiet) {
    // a pass that found nothing worth interrupting you for: one line, no card
    return (
      <button type="button" onClick={onOpen} className="w-full text-left px-2 py-1.5 flex items-center gap-2 text-[12.5px] text-muted">
        <Moon size={13} className="shrink-0" />
        <span className="truncate">
          {t("{label} — nothing new", { label: localLabel(item.title.replace(/^Working on your goal: /, "")) })}{item.text ? `: ${item.text}` : ""}
        </span>
        <span className="ml-auto shrink-0">{relativeTime(item.ts)}</span>
      </button>
    );
  }
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cx(
        "w-full text-left rounded-3xl border bg-surface shadow-sm px-4 py-3 active:scale-[0.99] transition",
        unseen ? "border-accent/40" : "border-border/70",
      )}
    >
      <div className="flex items-start gap-3">
        <div className={cx("rounded-2xl p-2 mt-0.5", tone)}>{icon}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <div className="font-semibold text-[14.5px] leading-snug truncate">{localLabel(item.title)}</div>
            {unseen && <span className="h-2 w-2 rounded-full bg-accent shrink-0" />}
          </div>
          {item.text && <div className="mt-0.5 text-[13.5px] text-muted leading-snug line-clamp-3 whitespace-pre-wrap">{plain(item.text)}</div>}
          <div className="mt-1.5 flex items-center gap-2 text-[12px] text-muted">
            <span>{relativeTime(item.ts)}</span>
            <span>·</span>
            <span className="truncate">{item.thread === "main" ? t(item.thread_title) : item.thread_title}</span>
            <span className="ml-auto flex items-center gap-1 text-accent font-medium">
              {item.kind === "artifact" ? t("Open") : item.kind === "approval" || item.kind === "question" ? t("Answer") : t("Open chat")}
              <ArrowRight size={13} />
            </span>
          </div>
        </div>
      </div>
    </button>
  );
}

function groupByDay(items: FeedItem[]): Array<[string, FeedItem[]]> {
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const label = (iso: string) => {
    const d = new Date(iso);
    if (d.toDateString() === today.toDateString()) return t("Today");
    if (d.toDateString() === yesterday.toDateString()) return t("Yesterday");
    return d.toLocaleDateString(intlLocale(), { weekday: "long", month: "short", day: "numeric" });
  };
  const map = new Map<string, FeedItem[]>();
  for (const it of items) {
    const k = label(it.ts);
    map.set(k, [...(map.get(k) ?? []), it]);
  }
  return [...map.entries()];
}
