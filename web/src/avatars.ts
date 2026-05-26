/**
 * The agent's face. Muse gives its agent a plush doll; so does OpenMuse — six knitted
 * characters shipped with the app (public/avatars/*.webp), or an emoji on a colour for
 * anyone who prefers it. `profile.avatar` names the doll; empty means the emoji.
 */
export interface Plush {
  id: string;
  /** shown in the picker; the agent's own name is separate */
  label: string;
}

export const PLUSH: readonly Plush[] = [
  { id: "sunny", label: "Sunny" },
  { id: "moss", label: "Moss" },
  { id: "sky", label: "Sky" },
  { id: "fox", label: "Fox" },
  { id: "bolt", label: "Bolt" },
  { id: "plum", label: "Plum" },
];

export function isPlush(id: string | undefined | null): id is string {
  return !!id && PLUSH.some((p) => p.id === id);
}

export function plushUrl(id: string): string {
  return `/avatars/${id}.webp`;
}
