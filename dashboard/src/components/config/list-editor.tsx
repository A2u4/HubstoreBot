"use client";

import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";

/** Edit an array of objects inline (stats channels, dar-rango role patterns, ...). */
export function ListEditor<T extends { id: string }>({ value, onChange, create, renderItem, addLabel, max = 50, empty }: {
  value: T[] | null | undefined;
  onChange: (value: T[]) => void;
  create: () => T;
  renderItem: (item: T, update: (patch: Partial<T>) => void) => React.ReactNode;
  addLabel: string;
  max?: number;
  empty?: string;
}) {
  const items = value ?? [];
  const update = (id: string, patch: Partial<T>) => onChange(items.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  return (
    <div className="space-y-3">
      {items.length === 0 && empty && <p className="text-sm text-muted">{empty}</p>}
      {items.map((item) => (
        <div key={item.id} className="relative rounded-lg border border-line bg-surface-2 p-4 pr-12">
          {renderItem(item, (patch) => update(item.id, patch))}
          <button type="button" aria-label="Eliminar" onClick={() => onChange(items.filter((i) => i.id !== item.id))}
                  className="absolute right-3 top-3 rounded-md p-1.5 text-muted hover:bg-surface-3 hover:text-fg">
            <Trash2 size={15} />
          </button>
        </div>
      ))}
      {items.length < max && (
        <Button size="sm" icon={<Plus size={14} />} onClick={() => onChange([...items, create()])}>{addLabel}</Button>
      )}
    </div>
  );
}

export function newId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}
