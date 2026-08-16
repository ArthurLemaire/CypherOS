import { X } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect } from "react";

/** Bottom sheet on phones, centered dialog on wide screens. */
export function Sheet({
  open,
  onClose,
  title,
  children,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center sm:justify-center">
      <div className="absolute inset-0 bg-black/45 backdrop-blur-[2px]" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        className="sheet-in relative w-full sm:max-w-lg max-h-[92dvh] flex flex-col bg-surface rounded-t-3xl sm:rounded-3xl shadow-2xl border border-border"
      >
        <div className="flex items-center gap-3 px-5 pt-4 pb-2">
          <div className="sm:hidden absolute left-1/2 -translate-x-1/2 top-2 h-1 w-10 rounded-full bg-border" />
          <div className="flex-1 font-semibold text-[17px] mt-1">{title}</div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="p-2 -mr-2 rounded-full text-muted hover:bg-surface-2"
          >
            <X size={20} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 pb-4">{children}</div>
        {footer && <div className="px-5 pt-2 pb-4 safe-bottom border-t border-border">{footer}</div>}
      </div>
    </div>
  );
}
