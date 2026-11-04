import { useCallback, useState } from "react";

/**
 * Modo claro / oscuro del portal. El usuario lo cambia con el botón de la barra superior; la elección se guarda en
 * este navegador (localStorage) y se aplica antes de pintar la página (script en index.html), sin parpadeo.
 * Por defecto, modo claro.
 */
export type Theme = "light" | "dark";
export const THEME_KEY = "tva_tema";

export function storedTheme(): Theme {
  try {
    return localStorage.getItem(THEME_KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

export function applyTheme(theme: Theme, animate = false): void {
  const root = document.documentElement;
  if (animate && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    root.classList.add("theme-anim");
    window.setTimeout(() => root.classList.remove("theme-anim"), 320);
  }
  root.dataset.theme = theme;
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(storedTheme);
  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    applyTheme(t, true);
    try {
      localStorage.setItem(THEME_KEY, t);
    } catch {
      /* sin almacenamiento: el cambio dura hasta recargar */
    }
  }, []);
  return [theme, setTheme];
}
