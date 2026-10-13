"use client";

import { Check, Info, X } from "lucide-react";
import { useSyncExternalStore } from "react";

type Kind = "success" | "error" | "info";
interface Toast { id: number; kind: Kind; message: string }

let toasts: Toast[] = [];
let nextId = 1;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

function push(kind: Kind, message: string) {
  const id = nextId++;
  toasts = [...toasts, { id, kind, message }].slice(-4);
  emit();
  setTimeout(() => {
    toasts = toasts.filter((t) => t.id !== id);
    emit();
  }, kind === "error" ? 6000 : 3500);
}

export const toast = {
  success: (message: string) => push("success", message),
  error: (message: string) => push("error", message),
  info: (message: string) => push("info", message),
};

const ICONS = { success: Check, error: X, info: Info };

export function Toaster() {
  const items = useSyncExternalStore(
    (cb) => { listeners.add(cb); return () => listeners.delete(cb); },
    () => toasts,
    () => toasts,
  );
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-80 flex-col gap-2" aria-live="polite">
      {items.map((t) => {
        const Icon = ICONS[t.kind];
        return (
          <div key={t.id} role="status"
               className={`pointer-events-auto flex items-start gap-3 rounded-lg border px-4 py-3 text-sm shadow-2xl ${
                 t.kind === "error" ? "border-fg bg-fg text-bg" : "border-line-strong bg-surface-2 text-fg"}`}>
            <Icon size={16} className="mt-0.5 shrink-0" />
            <span className="leading-snug">{t.message}</span>
          </div>
        );
      })}
    </div>
  );
}
