import { useEffect, useState } from "react";
import logo from "../assets/logo-giga.png";
import { SPLASH_DONE } from "../lib/motion";

const KEY = "tva_splash_visto";
const MIN_MS = 2400; // duración mínima para que la animación se lea completa
const EXIT_MS = 650;

/** ¿Corresponde mostrar la animación? Una vez por inicio de sesión (no en cada recarga de la página). */
export function shouldShowSplash(): boolean {
  try {
    return sessionStorage.getItem(KEY) !== "1";
  } catch {
    return false;
  }
}

/** Al cerrar sesión: el próximo inicio de sesión vuelve a mostrar la animación. */
export function resetSplash(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* sin almacenamiento disponible */
  }
}

/**
 * Pantalla de carga de marca: fondo negro, el logo de Gigafibra aparece con un enfoque suave, un brillo recorre el
 * logo y una línea naranja marca el avance; al terminar (y con los datos listos) todo se desvanece hacia la plataforma.
 */
export function BrandSplash({ ready, onDone }: { ready: boolean; onDone: () => void }) {
  const [minDone, setMinDone] = useState(false);
  const [leaving, setLeaving] = useState(false);
  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const t = setTimeout(() => setMinDone(true), reduced ? 600 : MIN_MS);
    return () => clearTimeout(t);
  }, []);
  useEffect(() => {
    if (minDone && ready && !leaving) setLeaving(true);
  }, [minDone, ready, leaving]);
  useEffect(() => {
    if (!leaving) return;
    window.dispatchEvent(new Event(SPLASH_DONE)); // el contenido empieza sus animaciones mientras la pantalla se retira
    try {
      sessionStorage.setItem(KEY, "1");
    } catch {
      /* sin almacenamiento: se mostrará de nuevo, sin efecto en la app */
    }
    const t = setTimeout(onDone, EXIT_MS);
    return () => clearTimeout(t);
  }, [leaving, onDone]);

  return (
    <div className={`splash${leaving ? " is-leaving" : ""}${minDone && !ready ? " is-waiting" : ""}`} role="status"
      aria-live="polite" aria-label="Cargando Gigafibra TV Analytics">
      <div className="splash__glow" aria-hidden />
      <div className="splash__center">
        <div className="splash__logo" style={{ ["--logo" as string]: `url("${logo}")` }}>
          <img src={logo} alt="GIGA+ Fibra" width={144} height={46} />
          <span className="splash__sheen" aria-hidden />
        </div>
        <div className="splash__bar" aria-hidden><span /></div>
        <div className="splash__caption">TV Analytics</div>
      </div>
    </div>
  );
}
