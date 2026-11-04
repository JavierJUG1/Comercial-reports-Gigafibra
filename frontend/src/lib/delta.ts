import type { Delta } from "../api/types";

/** Variación entre dos cortes. Desde 0 también es una subida normal (0 → 3 = +3); sin porcentaje sobre base cero. */
export function delta(prev: number | null | undefined, cur: number | null | undefined): Delta {
  if (prev === null || prev === undefined || cur === null || cur === undefined) return { abs: null, pct: null, kind: "no_data" };
  const diff = cur - prev;
  return { abs: diff, pct: prev === 0 ? null : (diff / prev) * 100, kind: diff > 0 ? "up" : diff < 0 ? "down" : "flat" };
}
