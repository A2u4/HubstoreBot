export function PageHeader({ title, description, actions, icon }: {
  title: string; description?: string; actions?: React.ReactNode; icon?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="flex items-center gap-3">
        {icon && <div className="flex size-10 items-center justify-center rounded-xl border border-line bg-surface-2">{icon}</div>}
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
