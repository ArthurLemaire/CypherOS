import { ArrowRight, CornerDownLeft, Globe, Hand, Loader2, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, frameUrl } from "../api";
import { useT } from "../i18n";
import { useStore } from "../store";
import type { BrowserEvent } from "../types";
import { cx } from "../util";
import { Sheet } from "./Sheet";

/**
 * Watch the agent's browser, or take over. The frame is the latest one the server has
 * for this card; it refreshes as the card is updated over the WebSocket. In take-over
 * mode a tap on the picture clicks the page there, the field types, Enter presses Enter —
 * that is how you sign in when the agent stops at a login form.
 */
export function BrowserViewer({ thread, eventId, onClose }: { thread: string; eventId: string; onClose: () => void }) {
  const { state, toast } = useStore();
  const t = useT();
  const event = (state.events[thread] ?? []).find((e) => e.id === eventId) as BrowserEvent | undefined;
  const [control, setControl] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [gone, setGone] = useState(false);
  const imgRef = useRef<HTMLImageElement>(null);

  useEffect(() => setGone(false), [event?.frame]);

  const act = async (body: Parameters<typeof api.browserControl>[1]) => {
    setBusy(body.action);
    try {
      await api.browserControl(thread, body);
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const onTap = (e: React.MouseEvent<HTMLImageElement>) => {
    if (!control || busy) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    void act({ action: "click", x: Math.min(Math.max(x, 0), 1), y: Math.min(Math.max(y, 0), 1) });
  };

  if (!event) return null;
  let host = event.url;
  try {
    host = new URL(event.url).host;
  } catch {
    /* raw */
  }
  const live = event.status === "live";

  return (
    <Sheet
      open
      onClose={onClose}
      title={
        <div className="flex items-center gap-2 min-w-0">
          <Globe size={17} className="text-accent shrink-0" />
          <span className="truncate">{event.title || host}</span>
          {live && (
            <span className="ml-1 flex items-center gap-1 rounded-full bg-rose-500/12 px-2 py-0.5 text-[10.5px] font-semibold text-rose-500">
              <span className="h-1.5 w-1.5 rounded-full bg-rose-500 animate-pulse" /> {t("LIVE")}
            </span>
          )}
        </div>
      }
      footer={
        control ? (
          <div className="space-y-2">
            <form
              className="flex items-center gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (!text) return;
                void act({ action: "type", text }).then(() => setText(""));
              }}
            >
              <input
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={t("Type into the focused field…")}
                className="flex-1 rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[14px] outline-none"
                autoComplete="off"
                autoCapitalize="off"
              />
              <button type="submit" disabled={!text || !!busy} aria-label={t("Type")} className="rounded-full bg-accent p-2.5 text-white disabled:opacity-40">
                {busy === "type" ? <Loader2 size={16} className="animate-spin" /> : <ArrowRight size={16} />}
              </button>
              <button
                type="button"
                onClick={() => void act({ action: "key", key: "Enter" })}
                disabled={!!busy}
                aria-label={t("Press Enter")}
                className="rounded-full bg-surface-2 p-2.5 text-fg disabled:opacity-40"
              >
                <CornerDownLeft size={16} />
              </button>
            </form>
            <form
              className="flex items-center gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (!url) return;
                void act({ action: "navigate", url }).then(() => setUrl(""));
              }}
            >
              <input
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder={t("Open a URL…")}
                inputMode="url"
                autoCapitalize="off"
                className="flex-1 rounded-2xl bg-surface-2 px-3.5 py-2 text-[13px] outline-none"
              />
              <button type="submit" disabled={!url || !!busy} className="rounded-2xl bg-surface-2 px-3 py-2 text-[13px] font-medium disabled:opacity-40">
                {t("Go")}
              </button>
            </form>
            <div className="flex items-center justify-between gap-2">
              <span className="text-[12px] text-muted">{t("Tap the page to click. If the browser was closed, open a URL first.")}</span>
              <button
                type="button"
                onClick={() => setControl(false)}
                className="shrink-0 whitespace-nowrap rounded-full bg-accent/12 px-3 py-1.5 text-[13px] font-medium text-accent"
              >
                {t("Hand back")}
              </button>
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0 text-[12.5px] text-muted truncate">
              {event.action} · {host}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                type="button"
                onClick={() => void act({ action: "look" })}
                disabled={!!busy}
                aria-label={t("Refresh")}
                className="rounded-full bg-surface-2 p-2 text-muted disabled:opacity-40"
              >
                {busy === "look" ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
              </button>
              <button
                type="button"
                onClick={() => setControl(true)}
                className="flex items-center gap-1.5 rounded-full bg-accent px-3.5 py-2 text-[13px] font-semibold text-white"
              >
                <Hand size={14} /> {t("Take over")}
              </button>
            </div>
          </div>
        )
      }
    >
      <div className={cx("relative overflow-hidden rounded-2xl border border-border bg-surface-2", control && "ring-2 ring-accent")}>
        {gone ? (
          <div className="flex aspect-[16/10] flex-col items-center justify-center gap-1 text-muted">
            <Globe size={24} />
            <span className="text-[12.5px]">{t("This frame is no longer available.")}</span>
            <button type="button" onClick={() => void act({ action: "look" })} className="text-accent text-[13px] font-medium">
              {t("Look again")}
            </button>
          </div>
        ) : (
          <img
            ref={imgRef}
            key={event.frame}
            src={frameUrl(thread, event.frame)}
            alt={event.title || host}
            onError={() => setGone(true)}
            onClick={onTap}
            draggable={false}
            className={cx("block w-full select-none", control ? "cursor-crosshair" : "")}
          />
        )}
        {busy && busy !== "look" && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/20">
            <Loader2 size={26} className="animate-spin text-white" />
          </div>
        )}
      </div>
      <div className="mt-2 flex items-center justify-between text-[12px] text-muted">
        <span className="truncate">{event.url}</span>
        <span className="shrink-0 ml-2">{event.frames === 1 ? t("1 frame") : t("{n} frames", { n: event.frames })}</span>
      </div>
      {control && (
        <div className="mt-3 rounded-2xl bg-accent/8 px-3.5 py-2.5 text-[13px] leading-snug">
          {t("You are driving. Sign in or fix what needs a person, then")} <span className="font-medium">{t("Hand back")}</span> {t("— the agent continues from the page as you left it. Passwords you type here go to the website, never to the model.")}
        </div>
      )}
    </Sheet>
  );
}
