import { useEffect, useRef, useState } from "react";

export const SPLASH_DONE = "tva:splash-done";

const reducedMotion = () => {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
};

/**
 * true cuando el contenido ya está a la vista: de inmediato o, si la animación de carga de marca está en pantalla,
 * cuando esta empieza a retirarse. Así las animaciones de entrada no ocurren ocultas debajo de ella.
 */
export function useReveal(): boolean {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!document.querySelector(".splash:not(.is-leaving)")) {
      const raf = requestAnimationFrame(() => setReady(true));
      return () => cancelAnimationFrame(raf);
    }
    const on = () => setReady(true);
    window.addEventListener(SPLASH_DONE, on, { once: true });
    const fallback = window.setTimeout(on, 8000);
    return () => {
      window.removeEventListener(SPLASH_DONE, on);
      window.clearTimeout(fallback);
    };
  }, []);
  return ready;
}

/**
 * Valores por clave que pasan suavemente de los mostrados a los nuevos (p. ej. las porciones de la torta al cambiar
 * de corte). La primera vez se muestran directo: la entrada la anima quien los dibuja.
 */
export function useTweenMap(target: Map<string, number>, duration = 650): Map<string, number> {
  const sig = [...target].map(([k, v]) => `${k}:${v}`).join("|");
  const [shown, setShown] = useState(target);
  const ref = useRef<Map<string, number> | null>(null);
  useEffect(() => {
    const from = ref.current;
    if (!from || reducedMotion()) {
      ref.current = new Map(target);
      setShown(new Map(target));
      return;
    }
    const keys = new Set([...from.keys(), ...target.keys()]);
    let raf = 0;
    const t0 = performance.now();
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / duration);
      const e = 1 - Math.pow(1 - k, 3);
      const m = new Map<string, number>();
      keys.forEach((key) => m.set(key, (from.get(key) ?? 0) + ((target.get(key) ?? 0) - (from.get(key) ?? 0)) * e));
      ref.current = m;
      setShown(m);
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [sig, duration]); // eslint-disable-line react-hooks/exhaustive-deps
  return shown;
}

/** Número que sube suavemente hasta `target` (desde 0 la primera vez, luego desde el valor mostrado). */
export function useCountUp(target: number, run: boolean, duration = 950): number {
  const [value, setValue] = useState(0);
  const shown = useRef(0);
  useEffect(() => {
    if (!run) return;
    const from = shown.current;
    if (reducedMotion() || from === target) {
      shown.current = target;
      setValue(target);
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / duration);
      const v = from + (target - from) * (1 - Math.pow(1 - k, 3));
      shown.current = v;
      setValue(v);
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, run, duration]);
  return value;
}
