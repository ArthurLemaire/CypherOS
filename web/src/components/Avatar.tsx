import { useEffect, useState } from "react";
import { isPlush, plushUrl } from "../avatars";
import type { Profile, Status } from "../types";
import { cx } from "../util";

/**
 * The agent's face: a plush doll (profile.avatar) or an emoji on a colour. It moves with the
 * agent's state — breathes when idle, sways while working, hops when it waits for you — and
 * wiggles when tapped.
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
    const id = window.setTimeout(() => setWiggle(false), 650);
    return () => window.clearTimeout(id);
  }, [wiggle]);

  const state = status?.state ?? "idle";
  const motion = wiggle
    ? "avatar-wiggle"
    : still
      ? ""
      : state === "working"
        ? "avatar-working"
        : state === "waiting"
          ? "avatar-waiting"
          : "avatar-idle";
  const color = profile?.color ?? "#0064d4";
  const plush = isPlush(profile?.avatar) ? profile!.avatar : null;

  return (
    <button
      type="button"
      onClick={() => {
        setWiggle(true);
        onClick?.();
      }}
      aria-label={`${profile?.name ?? "OpenMuse"} avatar`}
      className={cx("relative shrink-0 select-none rounded-full", onClick ? "transition active:scale-95" : "cursor-default", className)}
      style={{ width: size, height: size }}
    >
      <span
        className={cx("block h-full w-full overflow-hidden rounded-full will-change-transform", motion)}
        style={
          plush
            ? { background: "#eadfcd" }
            : { background: `linear-gradient(135deg, ${color}, color-mix(in srgb, ${color} 60%, #ffffff))` }
        }
      >
        {plush ? (
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
    </button>
  );
}
