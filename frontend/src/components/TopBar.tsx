import { useCallback, useMemo, useRef, useState } from "react";
import { LogOut, Moon, Sun } from "lucide-react";
import logo from "../assets/logo-giga.png";
import type { Meta } from "../api/types";
import { useClickOutside } from "../lib/hooks";
import { useTheme } from "../lib/theme";

/** Botón del modo oscuro: luna para activarlo, sol para volver al modo claro. */
function ThemeToggle() {
  const [theme, setTheme] = useTheme();
  const dark = theme === "dark";
  const label = dark ? "Desactivar modo oscuro" : "Activar modo oscuro";
  return (
    <button type="button" className={`topbar__theme${dark ? " is-dark" : ""}`} onClick={() => setTheme(dark ? "light" : "dark")}
      aria-pressed={dark} aria-label={label} title={label}>
      <span className="topbar__theme-icon" aria-hidden>{dark ? <Sun /> : <Moon />}</span>
      <span className="topbar__theme-text">{dark ? "Modo claro" : "Modo oscuro"}</span>
    </button>
  );
}

export function TopBar({ meta, onLogout }: { meta: Meta; onLogout: () => void }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useClickOutside(useMemo(() => [root], []), close, open);
  const u = meta.user;
  return (
    <header className="topbar">
      <div className="topbar__in">
        <div className="topbar__brand">
          <img src={logo} alt="GIGA+ Fibra" width={70} height={22} />
          <span className="topbar__product">TV Analytics</span>
          {meta.app.env_label && <span className="env-chip">{meta.app.env_label}</span>}
        </div>
        <div className="topbar__end">
        <ThemeToggle />
        <div className="pick" ref={root}>
          <button type="button" className="topbar__user" onClick={() => setOpen((o) => !o)} aria-haspopup="menu"
            aria-expanded={open} aria-label={`Cuenta de ${u.name}`}>
            <span className="topbar__name">{u.name}</span>
            <span className="avatar">{u.initials}</span>
          </button>
          {open && (
            <div className="pop pop--right menu" role="menu">
              <div style={{ padding: "8px 10px 10px", borderBottom: "1px solid var(--divider)", marginBottom: 4 }}>
                <div style={{ fontWeight: 600, fontSize: 13.5 }}>{u.name}</div>
                <div className="muted" style={{ fontSize: 12.5 }}>{u.email}</div>
                <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>Consulta y descarga</div>
              </div>
              <button type="button" role="menuitem" className="menu-item" onClick={onLogout}>
                <LogOut />
                <span className="menu-item__title">Cerrar sesión</span>
              </button>
            </div>
          )}
        </div>
        </div>
      </div>
    </header>
  );
}
