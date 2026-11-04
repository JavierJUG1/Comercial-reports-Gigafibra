import { useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { Banknote, Braces, Download, FileSpreadsheet, Loader2, Tv } from "lucide-react";
import { download } from "../api/client";
import type { Comercial, ComercialPeriodo } from "../api/types";
import { delta } from "../lib/delta";
import { MONTHS, MONTHS_SHORT, fmtDate, fmtInt, fmtMoney, fmtPct, fmtPesos } from "../lib/format";
import { useCountUp } from "../lib/motion";
import { DeltaView, Menu, MultiPick, useToast } from "./ui";

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function prevPeriod(p: string): string {
  const [y, m] = p.split("-").map(Number);
  return m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, "0")}`;
}

export function periodLabel(p: string): string {
  const [y, m] = p.split("-").map(Number);
  return `${cap(MONTHS_SHORT[m - 1])} ${y}`;
}

/** Hasta 12 meses consecutivos que terminan en `p` (los que falten quedan como hueco). */
function lastMonths(p: string, n = 12): string[] {
  const out = [p];
  while (out.length < n) out.unshift(prevPeriod(out[0]));
  return out;
}

function Count({ value, run, fmt = (v) => fmtInt(Math.round(v)) }: { value: number; run: boolean; fmt?: (v: number) => string }) {
  return <>{fmt(useCountUp(value, run))}</>;
}

type CardProps = {
  periodo: string;
  mes: string;
  com: Comercial | undefined;
  failed: boolean;
  run: boolean;
  style?: CSSProperties;
  planColor: (plan: string) => string;
};

export function Card({ id, icon, title, sub, actions, children, style, className = "" }: {
  id: string; icon: ReactNode; title: string; sub: ReactNode; actions?: ReactNode; children: ReactNode;
  style?: CSSProperties; className?: string;
}) {
  return (
    <section className={`insight ${className}`} aria-labelledby={id} style={style}>
      <header className="insight__head">
        <span className="insight__icon" aria-hidden>{icon}</span>
        <div className="insight__titles">
          <h2 id={id} className="insight__title">{title}</h2>
          <p className="insight__sub">{sub}</p>
        </div>
        {actions && <div className="insight__actions">{actions}</div>}
      </header>
      {children}
    </section>
  );
}

/* ------------------------------------------------------------------ descargas de cada card */
export type DownloadItem = {
  key: string;
  kind: "excel" | "json";
  title: string;
  desc: string;
  path: string;
  params?: Record<string, string | string[] | undefined>;
};

/**
 * Ícono de descarga de una card: Excel con las cifras de la card y su detalle, y el .json de origen cuando existe.
 * `note` explica de dónde salen los datos cuando el mes no tiene detalle (Excel inicial del proyecto).
 */
export function DownloadMenu({ items, label, note }: { items: DownloadItem[]; label: string; note?: string }) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const bajar = async (it: DownloadItem) => {
    setBusy(it.key);
    try {
      const sp = new URLSearchParams(); // listas como parámetro repetido (plan=A&plan=B)
      for (const [k, v] of Object.entries(it.params || {})) {
        if (Array.isArray(v)) v.forEach((x) => sp.append(k, x));
        else if (v) sp.set(k, v);
      }
      const q = sp.toString();
      const n = await download(q ? `${it.path}?${q}` : it.path, {});
      toast("success", <><b>{n}</b> descargado.</>);
    } catch (e) {
      toast("error", (e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  return (
    <Menu trigger={({ open, toggle }) => (
      <button type="button" className={`insight__dl${open ? " is-open" : ""}`} onClick={toggle} aria-haspopup="menu"
        aria-expanded={open} title={`Descargar los datos de "${label}" para confirmarlos`} aria-label={`Descargar datos de ${label}`}>
        {busy ? <Loader2 aria-hidden className="spin" /> : <Download aria-hidden />}
      </button>
    )}>
      {(close) => (
        <>
          {items.map((it) => (
            <button key={it.key} type="button" role="menuitem" className="menu-item" disabled={!!busy}
              onClick={() => { close(); void bajar(it); }}>
              {it.kind === "excel" ? <FileSpreadsheet /> : <Braces />}
              <span>
                <span className="menu-item__title">{it.title}</span>
                <span className="menu-item__desc">{it.desc}</span>
              </span>
            </button>
          ))}
          {note && <p className="menu-note">{note}</p>}
        </>
      )}
    </Menu>
  );
}

/** Estado sin datos del mes: cargando, calculando en el servidor, error o mes sin cálculo. */
function Pending({ com, failed }: { com: Comercial | undefined; failed: boolean }) {
  if (failed) return <p className="insight__empty">No fue posible cargar los datos comerciales.</p>;
  if (!com) return <div className="insight__skel" aria-hidden><span /><span /><span /></div>;
  if (com.en_curso) {
    return <p className="insight__empty insight__empty--busy"><Loader2 aria-hidden />Calculando con ERPNext…</p>;
  }
  if (com.error) return <p className="insight__empty">No se pudo calcular: {com.error}</p>;
  return <p className="insight__empty">Aún no hay datos de este mes.</p>;
}

function Provisional({ p, dias }: { p: ComercialPeriodo; dias: number }) {
  if (p.definitivo) return null;
  const [y, m] = p.hasta.split("-").map(Number);
  const limite = new Date(Date.UTC(y, m, 1 + dias)).toISOString().slice(0, 10); // primer día del mes siguiente + días
  return (
    <span className="insight__tag" title={`Calculado el ${fmtDate(p.calculado)}. Se actualiza cada día hasta el ${fmtDate(limite)} por pagos e instalaciones registrados con fecha del mes; después queda fijo.`}>
      Provisional
    </span>
  );
}

function comercialItems(tarjeta: "recaudo" | "leads", periodo: string, titulo: string, params?: Record<string, string[] | undefined>): DownloadItem[] {
  return [
    { key: "excel", kind: "excel", title: `Excel · ${titulo}`, path: `/api/descargas/tarjeta/${tarjeta}`,
      params: { periodo, ...params },
      desc: tarjeta === "recaudo" ? "Recaudo por plan, cada pago con su parte de TV y el total de cada mes"
        : "Leads TV por plan, cada lead con sus planes y el total de cada mes" },
    { key: "json", kind: "json", title: "JSON del cálculo", path: `/api/descargas/comercial/${periodo}`,
      desc: "Peticiones a ERPNext usadas, leads y pagos del mes" },
  ];
}

/* ------------------------------------------------------------------ Leads TV (instalados) */
/**
 * Leads convertidos (instalados y aprobados) que traen un plan de TV, por fecha de activación en el mes. Filtro propio de
 * planes: con varios planes elegidos, cada lead cuenta una vez. Columnas: leads TV de los últimos 12 meses.
 */
export function LeadsTvCard({ periodo, mes, com, failed, run, style, planColor }: CardProps) {
  const [planes, setPlanes] = useState<string[]>([]);
  const p = com?.periodos[periodo];
  const opciones = useMemo(() => {
    const tot = new Map<string, number>();
    for (const s of Object.values(com?.periodos || {})) {
      for (const [pl, n] of Object.entries(s.leads.por_plan_tv)) tot.set(pl, (tot.get(pl) || 0) + n);
    }
    return [...tot.entries()].sort((a, b) => b[1] - a[1]).map(([pl]) => pl);
  }, [com]);
  const sel = new Set(planes);
  const leadsTv = (k: string): number | null => {
    const l = com?.periodos[k]?.leads;
    if (!l) return null;
    if (!sel.size) return l.con_tv;
    if (l.combinaciones_tv) return l.combinaciones_tv.filter((c) => c.planes.some((x) => sel.has(x))).reduce((a, c) => a + c.leads, 0);
    return Object.entries(l.por_plan_tv).filter(([pl]) => sel.has(pl)).reduce((a, [, n]) => a + n, 0);
  };
  const cur = leadsTv(periodo) ?? 0;
  const prevK = prevPeriod(periodo);
  const prev = leadsTv(prevK);
  const months = lastMonths(periodo);
  const max = Math.max(1, ...months.map((k) => leadsTv(k) ?? 0));
  const [hover, setHover] = useState<string | null>(null);
  const porPlan = p ? Object.entries(p.leads.por_plan_tv).filter(([pl]) => !sel.size || sel.has(pl)) : [];
  const filtro = sel.size ? ` (${planes.length === 1 ? planes[0] : `${planes.length} planes`})` : "";

  return (
    <Card id="ins-leads-title" icon={<Tv />} title="Leads TV (instalados)" style={style}
      sub={<>Leads convertidos con plan de TV · {mes}{p && <Provisional p={p} dias={com!.regla_dias} />}</>}
      actions={p ? <DownloadMenu label="Leads TV (instalados)" items={comercialItems("leads", periodo, `Leads TV ${periodLabel(periodo)}${filtro}`, { plan: planes })} /> : undefined}>
      <div className="insight__tools">
        <MultiPick label="Plan" size="sm" values={planes} options={opciones} onChange={setPlanes} placeholder="Todos los planes de TV"
          renderOption={(o) => <span className="opt-plan"><span className="seg-sw" style={{ background: planColor(o) }} />{o}</span>} />
      </div>
      {!p ? <Pending com={com} failed={failed} /> : (
        <>
          <div className="rev__head">
            <span className="leader__value num"><Count value={cur} run={run} /> <small>{cur === 1 ? "lead TV" : "leads TV"}</small></span>
            <span className="leader__meta">
              {prev !== null && (
                <span title={`Variación frente a ${periodLabel(prevK)} (${fmtInt(prev)} leads TV)`}>
                  <DeltaView d={delta(prev, cur)} pill />
                </span>
              )}
              <span>instalados en {MONTHS[Number(periodo.slice(5, 7)) - 1]}</span>
            </span>
          </div>
          <div className="lcols lcols--grow">
            <div className="lcols__legend lcols__legend--start" aria-hidden><span>Leads TV por mes{filtro}</span></div>
            <div className="lcols__plot" role="img" onMouseLeave={() => setHover(null)}
              aria-label={`Leads TV por mes: ${months.filter((k) => leadsTv(k) !== null).map((k) => `${periodLabel(k)} ${leadsTv(k)}`).join(", ")}`}>
              {months.map((k, i) => {
                const v = leadsTv(k);
                const edge = i < 2 ? " is-start" : i > months.length - 3 ? " is-end" : "";
                return (
                  <div key={k} className={`lcols__col${k === periodo ? " is-sel" : ""}${hover && hover !== k ? " is-dim" : ""}`}
                    style={{ ["--i" as string]: i }} onMouseEnter={() => setHover(k)}>
                    <span className="lcols__stack" style={{ height: `${run ? ((v ?? 0) / max) * 100 : 0}%` }}>
                      {(v ?? 0) > 0 && <span className="lcols__tv" style={{ flexGrow: 1 }} />}
                    </span>
                    {hover === k && (
                      <span className={`lcols__tip${edge}`}>
                        <span>{periodLabel(k)}</span>
                        {v === null ? <>sin datos</> : <><b>{fmtInt(v)}</b> leads TV</>}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
            <div className="lcols__axis" aria-hidden>
              <span>{periodLabel(months[0])}</span>
              <span>{periodLabel(months[months.length - 1])}</span>
            </div>
          </div>
          <p className="insight__foot" title={porPlan.map(([pl, n]) => `${pl}: ${fmtInt(n)}`).join(" · ") || undefined}>
            {porPlan.length === 0 ? `Ningún lead TV instalado en ${MONTHS[Number(periodo.slice(5, 7)) - 1]}${sel.size ? " con esos planes" : ""}.`
              : <>{sel.size ? "Por plan" : "Plan más contratado"}: <span className="seg-sw" style={{ background: planColor(porPlan[0][0]) }} />{" "}
                <b>{porPlan[0][0]}</b> ({fmtInt(porPlan[0][1])}){porPlan.length > 1 && <> · {porPlan.length - 1} más</>}</>}
          </p>
        </>
      )}
    </Card>
  );
}

/* ------------------------------------------------------------------ Recaudo por plan de TV */
type Row = { key: string; name: string; value: number; facturas: number; color: string; detail?: string };

/**
 * Recaudo efectivo del mes por plan de TV, sin IVA: lo que entró en el mes (pagos con fecha del mes) por la parte de
 * TV de cada factura. Cada mes es independiente (no acumula). Valores completos en pesos, sin decimales.
 */
export function RecaudoCard({ periodo, mes, com, failed, run, style, planColor }: CardProps) {
  const p = com?.periodos[periodo];
  const prev = com?.periodos[prevPeriod(periodo)];
  const total = p?.ingresos.total ?? 0;
  const mesNombre = MONTHS[Number(periodo.slice(5, 7)) - 1];

  const rows: Row[] = p ? Object.entries(p.ingresos.por_plan).filter(([, v]) => Math.abs(v.ingreso) >= 0.5)
    .map(([plan, v]) => ({ key: plan, name: plan, value: v.ingreso, facturas: v.facturas, color: planColor(plan) })) : [];
  if (p && Math.abs(p.ingresos.retirado) >= 0.5) {
    rows.push({ key: "retirado", name: "Plan no identificado", value: p.ingresos.retirado, facturas: 0, color: "var(--seg-other)",
      detail: "La factura tenía TV, pero no se encontró su plan pagado en el corte, en la suscripción ni en su historial." });
  }
  rows.sort((a, b) => b.value - a.value);
  const sinRecaudo = p ? Object.entries(p.ingresos.por_plan).filter(([, v]) => Math.abs(v.ingreso) < 0.5).map(([plan]) => plan) : [];
  const max = Math.max(1, ...rows.map((r) => r.value));

  return (
    <Card id="ins-rev-title" icon={<Banknote />} title="Recaudo por plan de TV" style={style}
      sub={<>Recaudo efectivo del mes · {mes} · sin IVA{p && <Provisional p={p} dias={com!.regla_dias} />}</>}
      actions={p ? <DownloadMenu label="Recaudo por plan de TV" items={comercialItems("recaudo", periodo, `Recaudo ${periodLabel(periodo)}`)} /> : undefined}>
      {!p ? <Pending com={com} failed={failed} /> : (
        <>
          <div className="rev__head">
            <span className="leader__value num" title={fmtMoney(total)}>
              <Count value={total} run={run} fmt={fmtPesos} /> <small>recaudado en {mesNombre}</small>
            </span>
            <span className="leader__meta">
              {prev ? (
                <span title={`Variación frente al recaudo de ${periodLabel(prevPeriod(periodo))} (${fmtPesos(prev.ingresos.total)})`}>
                  <DeltaView d={delta(prev.ingresos.total, total)} pill fmt={fmtPesos} />
                </span>
              ) : null}
              <span><b className="num">{fmtInt(p.ingresos.facturas)}</b> facturas con TV pagadas en el mes</span>
            </span>
          </div>
          {rows.length === 0 ? <p className="insight__empty">No hubo pagos de facturas con TV este mes.</p> : (
            <ul className="rev">
              {rows.map((r, k) => (
                <li key={r.key} className="rev__row" style={{ ["--k" as string]: k }}
                  title={r.detail ?? `${r.name} · recaudado en ${mesNombre}: ${fmtMoney(r.value)} · ${fmtInt(r.facturas)} ${r.facturas === 1 ? "factura" : "facturas"}`}>
                  <span className="seg-sw" style={{ background: r.color }} />
                  <span className="rev__name">{r.name}</span>
                  <span className="rev__track" aria-hidden>
                    <span className="rev__bar" style={{ background: r.color, transform: `scaleX(${run ? Math.max(0, r.value) / max : 0})` }} />
                  </span>
                  <span className="rev__val num">{fmtPesos(r.value)}</span>
                  <span className="rev__pct num">{fmtPct(total ? (r.value / total) * 100 : 0)}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="insight__foot" title={sinRecaudo.length ? `Sin recaudo en ${mesNombre}: ${sinRecaudo.join(", ")}` : undefined}>
            Solo pagos con fecha del mes (no acumula) · parte de TV de cada pago
            {sinRecaudo.length > 0 && <> · {sinRecaudo.length} planes sin recaudo</>}
          </p>
        </>
      )}
    </Card>
  );
}
