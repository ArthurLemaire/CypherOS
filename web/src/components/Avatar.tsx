import { useEffect, useState } from "react";
import { isMascot, isPlush, plushUrl } from "../avatars";
import { useMood } from "../mood";
import type { Profile, Status } from "../types";
import { cx } from "../util";
import { RedPanda } from "./RedPanda";

/**
 * The agent's face: the red panda (drawn live, posed by what the agent is doing), a plush
 * doll (profile.avatar) or an emoji on a colour. The dolls and the emoji move as a whole —
 * breathe when idle, sway while working, hop when waiting — the panda moves on its own.
 * Tap it and it wiggles; the panda is pleased about it.
 */
export function Avatar({
  profile,
  status,
  size = 40,
  onClick,
  still = false,
  className,
}: {
  profile: Profile | null;
  status?: Status;
  size?: number;
  onClick?: () => void;
  /** no idle animation (lists, pickers) */
  still?: boolean;
  className?: string;
}) {
  const [wiggle, setWiggle] = useState(false);
  useEffect(() => {
    if (!wiggle) return;
    const id = window.setTimeout(() => setWiggle(false), 900);
    return () => window.clearTimeout(id);
  }, [wiggle]);

  const mood = useMood(status);
  const state = status?.state ?? "idle";
  const color = profile?.color ?? "#0064d4";
  const panda = !profile || isMascot(profile.avatar);
  const plush = !panda && isPlush(profile?.avatar) ? profile!.avatar : null;
  const motion = panda
    ? wiggle
      ? "avatar-wiggle"
      : ""
    : wiggle
      ? "avatar-wiggle"
      : still
        ? ""
        : state === "working"
          ? "avatar-working"
          : state === "waiting"
            ? "avatar-waiting"
            : "avatar-idle";

  const label = `${profile?.name ?? "nanoMuse"} avatar`;
  const box = cx("relative inline-block shrink-0 select-none rounded-full", className);
  const face = (
    <>
      <span
        className={cx("block h-full w-full overflow-hidden rounded-full will-change-transform", motion)}
        style={
          panda
            ? undefined
            : plush
              ? { background: "#eadfcd" }
              : { background: `linear-gradient(135deg, ${color}, color-mix(in srgb, ${color} 60%, #ffffff))` }
        }
      >
        {panda ? (
          <RedPanda mood={wiggle ? "happy" : mood} size={size} still={still && !wiggle} />
        ) : plush ? (
          <img src={plushUrl(plush)} alt="" draggable={false} className="h-full w-full object-cover" />
        ) : (
          <span className="flex h-full w-full items-center justify-center leading-none drop-shadow-sm" style={{ fontSize: size * 0.5 }}>
            {profile?.emoji ?? "✨"}
          </span>
        )}
      </span>
      {status && state !== "idle" && (
        <span
          className={cx(
            "absolute -bottom-0.5 -right-0.5 rounded-full border-2 border-bg",
            state === "working" ? "bg-amber-400" : "bg-rose-500",
          )}
          style={{ width: Math.max(10, size * 0.28), height: Math.max(10, size * 0.28) }}
        />
      )}
    </>
  );

  // A button of its own only when it does something; inside another button (the chat header)
  // it is plain markup that still wiggles when tapped.
  if (onClick) {
    return (
      <button
        type="button"
        onClick={() => {
          setWiggle(true);
          onClick();
        }}
        aria-label={label}
        className={cx(box, "transition active:scale-95")}
        style={{ width: size, height: size }}
      >
        {face}
      </button>
    );
  }
  return (
    <span role="img" aria-label={label} onClick={() => setWiggle(true)} className={box} style={{ width: size, height: size }}>
      {face}
    </span>
  );
}
