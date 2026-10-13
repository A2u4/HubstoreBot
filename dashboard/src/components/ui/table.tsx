import { cn } from "./cn";

export interface Column<T> {
  key: string;
  header: React.ReactNode;
  render: (row: T) => React.ReactNode;
  className?: string;
}

export function Table<T>({ columns, rows, rowKey, empty, onRowClick }: {
  columns: Array<Column<T>>; rows: T[]; rowKey: (row: T) => string; empty?: React.ReactNode; onRowClick?: (row: T) => void;
}) {
  if (!rows.length && empty) return <>{empty}</>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line">
            {columns.map((c) => (
              <th key={c.key} className={cn("whitespace-nowrap px-4 py-2.5 text-left text-xs font-medium uppercase tracking-wider text-muted", c.className)}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)} onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={cn("border-b border-line/60 last:border-0", onRowClick && "cursor-pointer hover:bg-surface-2")}>
              {columns.map((c) => <td key={c.key} className={cn("px-4 py-3 align-middle", c.className)}>{c.render(row)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Pager({ page, pages, onChange }: { page: number; pages: number; onChange: (page: number) => void }) {
  if (pages <= 1) return null;
  return (
    <div className="flex items-center justify-between border-t border-line px-4 py-3 text-xs text-muted">
      <span>Página {page} de {pages}</span>
      <div className="flex gap-2">
        <button type="button" disabled={page <= 1} onClick={() => onChange(page - 1)}
                className="rounded-md border border-line px-2.5 py-1 hover:border-line-strong hover:text-fg disabled:opacity-40">Anterior</button>
        <button type="button" disabled={page >= pages} onClick={() => onChange(page + 1)}
                className="rounded-md border border-line px-2.5 py-1 hover:border-line-strong hover:text-fg disabled:opacity-40">Siguiente</button>
      </div>
    </div>
  );
}
