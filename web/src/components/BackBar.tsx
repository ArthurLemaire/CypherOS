import { ChevronLeft } from "lucide-react";
import { useStore } from "../store";

/** "Back to chat" for screens reached through the avatar menu rather than the tab bar. */
export function BackBar({ label = "Chat" }: { label?: string }) {
  const { setTab } = useStore();
  return (
    <button
      type="button"
      onClick={() => setTab("chat")}
      className="-ml-2 mb-1 flex items-center gap-0.5 rounded-full py-1 pl-1 pr-3 text-[14px] font-medium text-accent hover:bg-surface-2"
    >
      <ChevronLeft size={19} /> {label}
    </button>
  );
}
