import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

/** Filtros en la URL: se pueden compartir y sobreviven a la navegación. Listas separadas por "|". */
export function useUrlState() {
  const [sp, setSp] = useSearchParams();
  const get = useCallback((k: string) => sp.get(k) || "", [sp]);
  const getList = useCallback((k: string) => (sp.get(k) || "").split("|").filter(Boolean), [sp]);
  const set = useCallback(
    (patch: Record<string, string | string[] | null | undefined>) => {
      setSp(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(patch)) {
            const val = Array.isArray(v) ? v.join("|") : v;
            if (val) next.set(k, val);
            else next.delete(k);
          }
          return next;
        },
        { replace: true },
      );
    },
    [setSp],
  );
  const clear = useCallback(
    (keys: string[]) => set(Object.fromEntries(keys.map((k) => [k, null]))),
    [set],
  );
  return { sp, get, getList, set, clear };
}

export function useMeasure<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.getBoundingClientRect().width);
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0;
      setWidth((prev) => (Math.abs(prev - w) > 0.5 ? w : prev));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

export function useMedia(query: string): boolean {
  const [match, setMatch] = useState(() => typeof window !== "undefined" && window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setMatch(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [query]);
  return match;
}

export function useClickOutside(refs: React.RefObject<HTMLElement>[], onOut: () => void, active: boolean) {
  useEffect(() => {
    if (!active) return;
    const handler = (e: MouseEvent | TouchEvent) => {
      if (refs.every((r) => r.current && !r.current.contains(e.target as Node))) onOut();
    };
    const key = (e: KeyboardEvent) => e.key === "Escape" && onOut();
    document.addEventListener("mousedown", handler);
    document.addEventListener("touchstart", handler);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", handler);
      document.removeEventListener("touchstart", handler);
      document.removeEventListener("keydown", key);
    };
  }, [active, onOut, refs]);
}

export function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** Colores de segmento: orden fijo (alfabético) sobre la paleta categórica validada. El color sigue a la entidad. */
const CAT = ["--cat-1", "--cat-2", "--cat-3", "--cat-4", "--cat-5", "--cat-6", "--cat-7", "--cat-8"];
const FALLBACK = "#a1a1a8";
export function useSegmentColors(allSegments: string[] | undefined) {
  return useMemo(() => {
    const map = new Map<string, string>();
    (allSegments || []).filter((s) => s !== "Sin clasificar").forEach((s, i) => {
      map.set(s, i < CAT.length ? `var(${CAT[i]})` : FALLBACK);
    });
    return (seg: string) => map.get(seg) || FALLBACK;
  }, [allSegments]);
}

export function useTitle(title: string) {
  useEffect(() => {
    document.title = title ? `${title} · Gigafibra TV Analytics` : "Gigafibra TV Analytics";
  }, [title]);
}
