import { Loader2 } from "lucide-react";
import { cn } from "./cn";

export function Spinner({ label, className }: { label?: string; className?: string }) {
  return (
    <div className={cn("flex items-center justify-center gap-2 py-12 text-sm text-muted", className)}>
      <Loader2 size={16} className="animate-spin" /> {label ?? "Cargando..."}
    </div>
  );
}

export function Empty({ title, description, icon, action }: {
  title: string; description?: string; icon?: React.ReactNode; action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      {icon && <div className="mb-1 text-faint">{icon}</div>}
      <p className="text-sm font-medium text-fg-2">{title}</p>
      {description && <p className="max-w-sm text-xs text-muted">{description}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

export function Badge({ children, tone = "default", className }: {
  children: React.ReactNode; tone?: "default" | "solid" | "muted"; className?: string;
}) {
  const tones = {
    default: "border-line-strong text-fg-2",
    solid: "border-fg bg-fg text-bg",
    muted: "border-line text-muted",
  };
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium", tones[tone], className)}>
      {children}
    </span>
  );
}

export function Stat({ label, value, hint, icon }: { label: string; value: React.ReactNode; hint?: string; icon?: React.ReactNode }) {
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between text-muted">
        <span className="text-xs font-medium uppercase tracking-wider">{label}</span>
        {icon}
      </div>
      <div className="mt-2 text-2xl font-semibold tabular-nums tracking-tight">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, tabs }: {
  value: T; onChange: (value: T) => void; tabs: Array<{ id: T; label: string; count?: number }>;
}) {
  return (
    <div className="mb-5 flex gap-1 overflow-x-auto border-b border-line" role="tablist">
      {tabs.map((tab) => (
        <button key={tab.id} type="button" role="tab" aria-selected={value === tab.id} onClick={() => onChange(tab.id)}
                className={cn("-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm transition-colors",
                              value === tab.id ? "border-fg text-fg" : "border-transparent text-muted hover:text-fg-2")}>
          {tab.label}
          {tab.count !== undefined && <span className="ml-1.5 text-xs text-faint">{tab.count}</span>}
        </button>
      ))}
    </div>
  );
}
