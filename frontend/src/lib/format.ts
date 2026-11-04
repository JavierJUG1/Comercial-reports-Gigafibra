// Formato colombiano (es-CO): miles con punto, decimales con coma.
const TZ = "America/Bogota";
const int = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 0 });
const dec1 = new Intl.NumberFormat("es-CO", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const money = new Intl.NumberFormat("es-CO", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const compact = new Intl.NumberFormat("es-CO", { notation: "compact", maximumFractionDigits: 1 });

export const MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
  "octubre", "noviembre", "diciembre"];
export const MONTHS_SHORT = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

export function fmtInt(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : int.format(n);
}

export function fmtSigned(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (n === 0) return "0";
  return (n > 0 ? "+" : "−") + int.format(Math.abs(n));
}

export function fmtPct(n: number | null | undefined, signed = false): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  const body = dec1.format(Math.abs(n)) + " %";
  if (!signed) return (n < 0 ? "−" : "") + body;
  if (Math.abs(n) < 0.05) return "0,0 %";
  return (n > 0 ? "+" : "−") + body;
}

export function fmtMoney(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : "$ " + money.format(n);
}

/** Pesos completos sin decimales: "$ 21.800.719". */
export function fmtPesos(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return (Math.round(n) < 0 ? "−" : "") + "$ " + int.format(Math.abs(Math.round(n)));
}

const upTo1 = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 1 });

/** Pesos abreviados: "$ 40,9 M", "$ 174,5 mil", "$ 950". */
export function fmtMoneyShort(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  const a = Math.abs(n);
  const body = a >= 1e6 ? `${upTo1.format(a / 1e6)} M` : a >= 1e3 ? `${upTo1.format(a / 1e3)} mil` : int.format(a);
  return (n < 0 ? "−" : "") + "$ " + body;
}

export function fmtCompact(n: number): string {
  return Math.abs(n) < 10000 ? int.format(n) : compact.format(n);
}

/** "2026-09-30" → "30 sep 2026" */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS_SHORT[m - 1]} ${y}`;
}

const dtFmt = new Intl.DateTimeFormat("es-CO", {
  timeZone: TZ, day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
});
const dtParts = (iso: string) => {
  const parts = Object.fromEntries(dtFmt.formatToParts(new Date(iso)).map((p) => [p.type, p.value]));
  return parts as Record<string, string>;
};

/** ISO con zona → "30 sep 2026, 23:50" (hora de Bogotá) */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const p = dtParts(iso);
  return `${p.day} ${(p.month || "").replace(".", "")} ${p.year}, ${p.hour}:${p.minute}`;
}

const wdFmt = new Intl.DateTimeFormat("es-CO", { timeZone: TZ, weekday: "short" });
export function fmtWeekdayDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const wd = wdFmt.format(new Date(iso)).replace(".", "");
  return `${wd.charAt(0).toUpperCase()}${wd.slice(1)} ${fmtDateTime(iso)}`;
}

export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "";
  const diff = new Date(iso).getTime() - Date.now();
  const abs = Math.abs(diff);
  const rtf = new Intl.RelativeTimeFormat("es", { numeric: "auto" });
  const units: [Intl.RelativeTimeFormatUnit, number][] = [["day", 86400000], ["hour", 3600000], ["minute", 60000]];
  for (const [unit, ms] of units) {
    if (abs >= ms || unit === "minute") return rtf.format(Math.round(diff / ms), unit);
  }
  return "";
}

export function fmtDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  if (s < 60) return `${dec1.format(s)} s`;
  return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

/** "2026-09" → índice de mes absoluto (para escalas de tiempo con huecos) */
export function monthIndex(period: string): number {
  const [y, m] = period.split("-").map(Number);
  return y * 12 + (m - 1);
}

export function periodParts(period: string): { month: string; year: number } {
  const [y, m] = period.split("-").map(Number);
  const s = MONTHS_SHORT[m - 1];
  return { month: s.charAt(0).toUpperCase() + s.slice(1), year: y };
}

/** Meses sin corte agrupados por año: "abr y may 2026" · "nov 2025, abr y may 2026". */
export function fmtGaps(gaps: { id: string }[]): string {
  const byYear = new Map<number, string[]>();
  for (const g of gaps) {
    const [y, m] = g.id.split("-").map(Number);
    byYear.set(y, [...(byYear.get(y) || []), MONTHS_SHORT[m - 1]]);
  }
  const join = (xs: string[]) => (xs.length > 1 ? `${xs.slice(0, -1).join(", ")} y ${xs[xs.length - 1]}` : xs[0]);
  return [...byYear.entries()].map(([y, ms]) => `${join(ms)} ${y}`).join(", ");
}

export function plural(n: number, one: string, many: string): string {
  return `${fmtInt(n)} ${n === 1 ? one : many}`;
}
