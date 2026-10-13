"use client";

import { forwardRef, useId, useState } from "react";
import { X } from "lucide-react";
import { cn } from "./cn";

export function Field({ label, help, children, className, htmlFor }: {
  label?: React.ReactNode; help?: React.ReactNode; children: React.ReactNode; className?: string; htmlFor?: string;
}) {
  return (
    <div className={className}>
      {label && <label htmlFor={htmlFor} className="label">{label}</label>}
      {children}
      {help && <p className="help">{help}</p>}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...props }, ref,
) {
  return <input ref={ref} className={cn("input", className)} {...props} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea(
  { className, rows = 4, ...props }, ref,
) {
  return <textarea ref={ref} rows={rows} className={cn("input resize-y leading-relaxed", className)} {...props} />;
});

export function Select({ value, onChange, options, placeholder, className, disabled, id }: {
  value: string; onChange: (value: string) => void; options: Array<{ value: string; label: string; group?: string }>;
  placeholder?: string; className?: string; disabled?: boolean; id?: string;
}) {
  const groups = [...new Set(options.map((o) => o.group ?? ""))];
  const render = (items: typeof options) => items.map((o) => <option key={o.value} value={o.value}>{o.label}</option>);
  return (
    <select id={id} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}
            className={cn("input cursor-pointer appearance-none bg-[length:12px] bg-[right_0.75rem_center] bg-no-repeat pr-8",
                          "bg-[url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 12 12%22><path d=%22M3 4.5l3 3 3-3%22 stroke=%22%238a8a8a%22 fill=%22none%22 stroke-width=%221.5%22/></svg>')]",
                          className)}>
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {groups.length > 1
        ? groups.map((g) => <optgroup key={g} label={g || "Sin categoría"}>{render(options.filter((o) => (o.group ?? "") === g))}</optgroup>)
        : render(options)}
    </select>
  );
}

export function NumberInput({ value, onChange, min, max, step, suffix, id }: {
  value: number | null | undefined; onChange: (value: number) => void; min?: number; max?: number; step?: number;
  suffix?: string; id?: string;
}) {
  return (
    <div className="relative">
      <input id={id} type="number" className={cn("input tabular-nums", suffix && "pr-14")} value={value ?? ""} min={min}
             max={max} step={step ?? 1}
             onChange={(e) => {
               const next = e.target.value === "" ? (min ?? 0) : Number(e.target.value);
               if (Number.isFinite(next)) onChange(next);
             }} />
      {suffix && <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-muted">{suffix}</span>}
    </div>
  );
}

export function Toggle({ checked, onChange, label, description, disabled }: {
  checked: boolean; onChange: (value: boolean) => void; label?: React.ReactNode; description?: React.ReactNode; disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex items-start justify-between gap-4">
      {(label || description) && (
        <label htmlFor={id} className="min-w-0 cursor-pointer">
          {label && <span className="block text-sm font-medium text-fg">{label}</span>}
          {description && <span className="mt-0.5 block text-xs leading-relaxed text-muted">{description}</span>}
        </label>
      )}
      <button id={id} type="button" role="switch" aria-checked={checked} disabled={disabled} onClick={() => onChange(!checked)}
              className={cn("relative h-5 w-9 shrink-0 rounded-full border transition-colors disabled:opacity-50",
                            checked ? "border-fg bg-fg" : "border-line-strong bg-surface-3")}>
        <span className={cn("absolute top-0.5 size-3.5 rounded-full transition-all",
                            checked ? "left-[18px] bg-bg" : "left-0.5 bg-muted")} />
      </button>
    </div>
  );
}

export function ColorInput({ value, onChange }: { value: string | null | undefined; onChange: (value: string) => void }) {
  const color = /^#?[0-9a-f]{6}$/i.test(value ?? "") ? `#${(value ?? "").replace("#", "")}` : "#ffffff";
  return (
    <div className="flex items-center gap-2">
      <label className="relative size-9 shrink-0 cursor-pointer overflow-hidden rounded-lg border border-line" style={{ background: color }}>
        <input type="color" value={color} onChange={(e) => onChange(e.target.value)} className="absolute inset-0 cursor-pointer opacity-0" />
      </label>
      <Input value={value ?? ""} placeholder="#FFFFFF" maxLength={7} onChange={(e) => onChange(e.target.value)} className="font-mono" />
    </div>
  );
}

export function TagInput({ value, onChange, placeholder, max = 200 }: {
  value: string[]; onChange: (value: string[]) => void; placeholder?: string; max?: number;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const items = draft.split(",").map((s) => s.trim()).filter(Boolean).filter((s) => !value.includes(s));
    if (items.length) onChange([...value, ...items].slice(0, max));
    setDraft("");
  };
  return (
    <div className="input flex min-h-9 flex-wrap items-center gap-1.5 py-1.5">
      {value.map((tag) => (
        <span key={tag} className="inline-flex items-center gap-1 rounded-md border border-line-strong bg-surface-3 px-2 py-0.5 text-xs">
          {tag}
          <button type="button" aria-label={`Quitar ${tag}`} onClick={() => onChange(value.filter((t) => t !== tag))}
                  className="text-muted hover:text-fg"><X size={12} /></button>
        </span>
      ))}
      <input value={draft} placeholder={value.length ? "" : placeholder} onChange={(e) => setDraft(e.target.value)}
             onKeyDown={(e) => {
               if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); }
               if (e.key === "Backspace" && !draft && value.length) onChange(value.slice(0, -1));
             }}
             onBlur={add} className="min-w-24 flex-1 bg-transparent text-sm outline-none placeholder:text-faint" />
    </div>
  );
}
