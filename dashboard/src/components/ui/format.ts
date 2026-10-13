export function formatDate(value: string | Date | null | undefined, withTime = true): string {
  if (!value) return "—";
  const date = typeof value === "string" ? new Date(value.endsWith("Z") || value.includes("+") ? value : `${value}Z`) : value;
  return date.toLocaleString("es", withTime
    ? { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }
    : { day: "2-digit", month: "short", year: "numeric" });
}

export function relativeTime(value: string | Date | null | undefined): string {
  if (!value) return "—";
  const ms = new Date(value).getTime() - Date.now();
  const units: Array<[Intl.RelativeTimeFormatUnit, number]> = [["day", 86_400_000], ["hour", 3_600_000], ["minute", 60_000]];
  const rtf = new Intl.RelativeTimeFormat("es", { numeric: "auto" });
  for (const [unit, size] of units) if (Math.abs(ms) >= size) return rtf.format(Math.round(ms / size), unit);
  return "ahora";
}

export function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toLocaleString("es");
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}
