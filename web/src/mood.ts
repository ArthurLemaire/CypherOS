import { useEffect, useState } from "react";
import type { Mood } from "./components/RedPanda";
import { useStore } from "./store";
import type { Status } from "./types";

/** How long the face stays pleased after a run ends, or worried after something failed. */
export const HAPPY_MS = 3000;
export const ERROR_MS = 4000;

/**
 * What the red panda should look like right now. The agent's status gives the pose it holds
 * (working, waiting for you); two moments from the store colour it briefly: the end of a run
 * (a pleased bounce) and a failed or refused tool call (a worried shake). No server: asleep.
 * Without a status to follow — pickers, previews — it just idles.
 */
export function useMood(status?: Status): Mood {
  const { state } = useStore();
  const now = useNow(status ? [state.mishapAt + ERROR_MS, state.finishedAt + HAPPY_MS] : []);
  if (!status) return "idle";
  if (state.loaded && !state.connected) return "sleepy";
  if (status.state === "waiting") return "waiting";
  if (status.state === "working") return "working";
  if (state.mishapAt && now - state.mishapAt < ERROR_MS) return "error";
  if (state.finishedAt && now - state.finishedAt < HAPPY_MS) return "happy";
  return "idle";
}

/** The clock, read again whenever a window opens and once more when the nearest one closes. */
function useNow(ends: number[]): number {
  const [now, setNow] = useState(() => Date.now());
  const key = ends.join(",");
  useEffect(() => setNow(Date.now()), [key]);
  const next = Math.min(...ends.filter((t) => t > now), Infinity);
  useEffect(() => {
    if (!Number.isFinite(next)) return;
    const id = window.setTimeout(() => setNow(Date.now()), Math.max(0, next - Date.now()) + 20);
    return () => window.clearTimeout(id);
  }, [next]);
  return now;
}
