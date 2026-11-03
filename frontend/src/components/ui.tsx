import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  AlertTriangle, ArrowDown, ArrowUp, Check, CheckCircle2, ChevronDown, Info, Minus, Search, Sparkles, X, XCircle,
} from "lucide-react";
import type { Delta as DeltaT } from "../api/types";
import { fmtInt, fmtPct, fmtSigned } from "../lib/format";
import { useClickOutside } from "../lib/hooks";

/* ------------------------------------------------------------------ básicos */
export function Button({ variant = "secondary", size, icon, block, children, className = "", ...rest }: {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm";
  icon?: ReactNode;
  block?: boolean;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const cls = ["btn", `btn--${variant}`, size ? `btn--${size}` : "", !children ? "btn--icon" : "", block ? "btn--block" : "", className]
    .filter(Boolean).join(" ");
  return (
    <button type="button" className={cls} {...rest}>
      {icon}
      {children}
    </button>
  );
}

export function Panel({ title, desc, actions, children, foot, flush, className = "", id }: {
  title?: ReactNode;
  desc?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  foot?: ReactNode;
  flush?: boolean;
  className?: string;
  id?: string;
}) {
  return (
    <section className={`panel ${className}`} aria-labelledby={title && id ? `${id}-t` : undefined}>
      {(title || actions) && (
        <header className="panel__head">
          <div className="stack">
            {title && <h2 className="panel__title" id={id ? `${id}-t` : undefined}>{title}</h2>}
            {desc && <p className="panel__desc">{desc}</p>}
          </div>
          {actions && <div className="row">{actions}</div>}
        </header>
      )}
      <div className={flush ? "panel__body panel__body--flush" : "panel__body"}>{children}</div>
      {foot && <footer className="panel__foot">{foot}</footer>}
    </section>
  );
}

export function Badge({ tone = "neutral", icon, children, title }: {
  tone?: "neutral" | "success" | "danger" | "warning" | "info" | "brand" | "outline";
  icon?: ReactNode;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span className={`badge badge--${tone}`} title={title}>
      {icon}
      {children}
    </span>
  );
}

export function SegTag({ name, color }: { name: string; color: string }) {
  return (
    <span className="seg-tag">
      <i style={{ background: color }} aria-hidden />
      <span className="ellipsis">{name}</span>
    </span>
  );
}

/** Variación con signo, flecha y color. Base cero → "Nuevo" / "Sin base comparable" (nunca un % inválido). */
export function DeltaView({ d, pill, showPct = true, showAbs = true, size }: {
  d: DeltaT | null | undefined;
  pill?: boolean;
  showPct?: boolean;
  showAbs?: boolean;
  size?: "sm";
}) {
  if (!d || d.kind === "no_data") {
    return <span className={`delta delta--no_data${pill ? " delta--pill" : ""}`} title="Sin dato comparable">—</span>;
  }
  const Icon = d.kind === "up" ? ArrowUp : d.kind === "down" ? ArrowDown : d.kind === "new" ? Sparkles : Minus;
  const pct = d.pct !== null ? fmtPct(d.pct, true) : null;
  const title = d.kind === "new" ? "Nuevo: el periodo base no tenía suscripciones (sin base comparable)"
    : d.kind === "flat" && d.pct === null ? "Sin base comparable: el periodo base no tenía suscripciones"
      : undefined;
  return (
    <span className={`delta delta--${d.kind}${pill ? " delta--pill" : ""}`} title={title}
      style={size === "sm" ? { fontSize: 12 } : undefined}>
      <Icon aria-hidden />
      {showAbs && <span>{d.kind === "flat" && d.abs === 0 ? "0" : fmtSigned(d.abs)}</span>}
      {showPct && pct && d.kind !== "flat" && <span className="delta__pct">{showAbs ? `· ${pct}` : pct}</span>}
      {showPct && d.kind === "new" && <span className="delta__pct">{showAbs ? "· Nuevo" : "Nuevo"}</span>}
      <span className="sr-only">{d.kind === "up" ? "aumento" : d.kind === "down" ? "disminución" : ""}</span>
    </span>
  );
}

export function Banner({ tone = "info", children, action }: {
  tone?: "info" | "warning" | "danger";
  children: ReactNode;
  action?: ReactNode;
}) {
  const Icon = tone === "danger" ? XCircle : tone === "warning" ? AlertTriangle : Info;
  return (
    <div className={`banner banner--${tone}`} role={tone === "danger" ? "alert" : "status"}>
      <Icon aria-hidden />
      <div className="banner__body">{children}</div>
      {action}
    </div>
  );
}

export function Skeleton({ w = "100%", h = 14, r }: { w?: number | string; h?: number; r?: number }) {
  return <div className="skel" style={{ width: w, height: h, borderRadius: r }} aria-hidden />;
}

export function Empty({ icon, title, children, action }: {
  icon: ReactNode;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty__icon">{icon}</div>
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function Switch({ checked, onChange, label, disabled }: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button type="button" role="switch" aria-checked={checked} className="switch" disabled={disabled}
      onClick={() => onChange(!checked)}>
      <span className="switch__track" aria-hidden />
      {label}
    </button>
  );
}

export function Segmented<T extends string>({ value, onChange, options, label }: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: ReactNode; count?: number }[];
  label: string;
}) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
          {o.count !== undefined && <span className="seg__count">{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function SearchInput({ value, onChange, placeholder = "Buscar plan…", width }: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  width?: number;
}) {
  return (
    <label className="search">
      <Search aria-hidden />
      <span className="sr-only">{placeholder}</span>
      <input type="search" value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)}
        style={width ? { width } : undefined} />
      {value && (
        <button type="button" className="search__clear" onClick={() => onChange("")} aria-label="Borrar búsqueda">
          <X />
        </button>
      )}
    </label>
  );
}

/* ------------------------------------------------------------------ selector (popover) */
export interface PickOption {
  value: string;
  label: ReactNode;
  text?: string; // texto para el botón
  hint?: ReactNode;
  group?: string;
  disabled?: boolean;
}

export function Pick({ label, value, options, onChange, placeholder = "Todos", align, size, icon, highlight }: {
  label: string;
  value: string;
  options: PickOption[];
  onChange: (v: string) => void;
  placeholder?: string;
  align?: "right";
  size?: "lg";
  icon?: ReactNode;
  highlight?: boolean; // resalta el control cuando el filtro se aparta del valor por defecto
}) {
  const [open, setOpen] = useState(false);
  const [focus, setFocus] = useState(-1);
  const root = useRef<HTMLDivElement>(null);
  const listId = useId();
  const close = useCallback(() => setOpen(false), []);
  useClickOutside(useMemo(() => [root], []), close, open);
  const current = options.find((o) => o.value === value);
  const enabled = options.filter((o) => !o.disabled);

  useEffect(() => {
    if (open) setFocus(Math.max(0, enabled.findIndex((o) => o.value === value)));
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const onKey = (e: React.KeyboardEvent) => {
    if (!open && (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      setOpen(true);
      return;
    }
    if (!open) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setFocus((f) => Math.min(enabled.length - 1, f + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setFocus((f) => Math.max(0, f - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const o = enabled[focus];
      if (o) {
        onChange(o.value);
        setOpen(false);
      }
    } else if (e.key === "Tab") setOpen(false);
  };

  let lastGroup: string | undefined;
  return (
    <div className="pick" ref={root} onKeyDown={onKey}>
      <button type="button" className={`pick__btn${size ? " pick__btn--lg" : ""}${(highlight ?? !!value) ? " is-set" : ""}`}
        aria-haspopup="listbox" aria-expanded={open} aria-controls={listId} onClick={() => setOpen((o) => !o)}>
        {icon}
        <span className="pick__label">{label}</span>
        <span className="pick__value">{current ? current.text ?? current.label : placeholder}</span>
        <ChevronDown aria-hidden />
      </button>
      {open && (
        <div className={`pop${align === "right" ? " pop--right" : ""}`} role="listbox" id={listId} aria-label={label}>
          {options.map((o) => {
            const header = o.group && o.group !== lastGroup ? o.group : null;
            lastGroup = o.group;
            const idx = enabled.indexOf(o);
            return (
              <div key={o.value || "__all"}>
                {header && <div className="pop__group">{header}</div>}
                <button type="button" role="option" aria-selected={o.value === value} disabled={o.disabled}
                  className={`opt${o.value === value ? " is-selected" : ""}${idx === focus ? " is-focus" : ""}`}
                  onMouseEnter={() => setFocus(idx)}
                  onClick={() => { onChange(o.value); setOpen(false); }}>
                  <span className="opt__check">{o.value === value && <Check size={16} />}</span>
                  <span className="ellipsis">{o.label}</span>
                  {o.hint !== undefined && <span className="opt__hint">{o.hint}</span>}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** Selección múltiple con casillas (clasificación, segmento). */
export function MultiPick({ label, values, options, onChange, renderOption }: {
  label: string;
  values: string[];
  options: string[];
  onChange: (v: string[]) => void;
  renderOption?: (o: string) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useClickOutside(useMemo(() => [root], []), close, open);
  const toggle = (o: string) => onChange(values.includes(o) ? values.filter((v) => v !== o) : [...values, o]);
  const text = values.length === 0 ? "Todos" : values.length === 1 ? values[0] : `${values.length} seleccionados`;
  return (
    <div className="pick" ref={root}>
      <button type="button" className={`pick__btn${values.length ? " is-set" : ""}`} aria-haspopup="listbox"
        aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="pick__label">{label}</span>
        <span className="pick__value">{text}</span>
        <ChevronDown aria-hidden />
      </button>
      {open && (
        <div className="pop" role="listbox" aria-multiselectable aria-label={label}>
          {options.length === 0 && <div className="opt muted">Sin opciones</div>}
          {options.map((o) => {
            const sel = values.includes(o);
            return (
              <button key={o} type="button" role="option" aria-selected={sel}
                className={`opt${sel ? " is-selected" : ""}`} onClick={() => toggle(o)}>
                <span className="opt__box">{sel && <Check />}</span>
                <span className="ellipsis">{renderOption ? renderOption(o) : o}</span>
              </button>
            );
          })}
          {values.length > 0 && (
            <div className="pop__foot">
              <Button variant="ghost" size="sm" onClick={() => onChange([])}>Quitar selección</Button>
              <Button variant="ghost" size="sm" onClick={close}>Listo</Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ menú */
export function Menu({ trigger, children, align = "right" }: {
  trigger: (props: { open: boolean; toggle: () => void }) => ReactNode;
  children: (close: () => void) => ReactNode;
  align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useClickOutside(useMemo(() => [root], []), close, open);
  return (
    <div className="pick" ref={root}>
      {trigger({ open, toggle: () => setOpen((o) => !o) })}
      {open && <div className={`pop menu${align === "right" ? " pop--right" : ""}`} role="menu">{children(close)}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ superposiciones */
function useLockScroll(active: boolean) {
  useEffect(() => {
    if (!active) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [active]);
}

export function Drawer({ open, onClose, children, labelledBy }: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  labelledBy?: string;
}) {
  useLockScroll(open);
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, [open, onClose]);
  if (!open) return null;
  return createPortal(
    <>
      <div className="scrim" onClick={onClose} aria-hidden />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby={labelledBy}>{children}</aside>
    </>,
    document.body,
  );
}

export function Dialog({ open, onClose, title, desc, children, foot }: {
  open: boolean;
  onClose: () => void;
  title: string;
  desc?: ReactNode;
  children: ReactNode;
  foot: ReactNode;
}) {
  useLockScroll(open);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, [open, onClose]);
  if (!open) return null;
  return createPortal(
    <>
      <div className="scrim" onClick={onClose} aria-hidden />
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby={id}>
        <div className="dialog__head">
          <h2 id={id}>{title}</h2>
          {desc && <p>{desc}</p>}
        </div>
        <div className="dialog__body">{children}</div>
        <div className="dialog__foot">{foot}</div>
      </div>
    </>,
    document.body,
  );
}

/* ------------------------------------------------------------------ avisos */
type Toast = { id: number; tone: "success" | "error" | "info"; text: ReactNode };
const ToastCtx = createContext<(tone: Toast["tone"], text: ReactNode) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((tone: Toast["tone"], text: ReactNode) => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs, { id, tone, text }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), 5200);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      {createPortal(
        <div className="toasts" aria-live="polite">
          {items.map((t) => (
            <div key={t.id} className={`toast toast--${t.tone}`}>
              {t.tone === "success" ? <CheckCircle2 /> : t.tone === "error" ? <XCircle /> : <Info />}
              <div>{t.text}</div>
            </div>
          ))}
        </div>,
        document.body,
      )}
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);

export function Num({ v }: { v: number | null | undefined }) {
  return <span className={v === null || v === undefined ? "nodata" : "num"}>{fmtInt(v)}</span>;
}
