import type { Profile, Status } from "../types";
import { cx } from "../util";

export function Avatar({
  profile,
  status,
  size = 40,
  onClick,
}: {
  profile: Profile | null;
  status?: Status;
  size?: number;
  onClick?: () => void;
}) {
  const busy = status && status.state !== "idle";
  const color = profile?.color ?? "#7c3aed";
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`${profile?.name ?? "Muse"} avatar`}
      className={cx(
        "relative shrink-0 rounded-full flex items-center justify-center select-none",
        busy && "pulse",
        onClick ? "active:scale-95 transition" : "cursor-default",
      )}
      style={{
        width: size,
        height: size,
        background: `linear-gradient(135deg, ${color}, color-mix(in srgb, ${color} 55%, #ec4899))`,
        fontSize: size * 0.5,
        ["--om-accent" as string]: color,
      }}
    >
      <span className="leading-none drop-shadow-sm">{profile?.emoji ?? "✨"}</span>
      {status && (
        <span
          className={cx(
            "absolute -bottom-0.5 -right-0.5 rounded-full border-2 border-bg",
            status.state === "idle" && "bg-emerald-500",
            status.state === "working" && "bg-amber-400",
            status.state === "waiting" && "bg-rose-500",
          )}
          style={{ width: size * 0.3, height: size * 0.3 }}
        />
      )}
    </button>
  );
}
