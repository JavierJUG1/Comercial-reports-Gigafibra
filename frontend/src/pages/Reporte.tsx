import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownUp, CalendarClock, CheckCircle2, ChevronDown, ChevronUp, CircleSlash, Database, Download, FileJson,
  FileSpreadsheet, FlaskConical, Loader2, SearchX, XCircle,
} from "lucide-react";
import { download } from "../api/client";
import { useCortes, useReporte } from "../api/hooks";
import type { Columna, Corte, Delta, Meta, PlanFila, Reporte as ReporteT } from "../api/types";
import { Sparkline } from "../components/charts";
import {
  Badge, Banner, Button, DeltaView, Empty, MultiPick, Panel, Pick, SearchInput, SegTag, Segmented, Skeleton, Switch,
  useToast,
} from "../components/ui";
import { MONTHS, MONTHS_SHORT, fmtDate, fmtDateTime, fmtDuration, fmtInt, fmtMoney, fmtPct, fmtRelative, fmtSigned, fmtWeekdayDateTime } from "../lib/format";
import { useDebounced, useMedia, useSegmentColors, useTitle } from "../lib/hooks";

/* ------------------------------------------------------------------ utilidades */
/** Variación entre dos cortes. Desde 0 también es una subida normal (0 → 3 = +3); sin porcentaje sobre base cero. */
function delta(prev: number | null | undefined, cur: number | null | undefined): Delta {
  if (prev === null || prev === undefined || cur === null || cur === undefined) return { abs: null, pct: null, kind: "no_data" };
  const diff = cur - prev;
  return { abs: diff, pct: prev === 0 ? null : (diff / prev) * 100, kind: diff > 0 ? "up" : diff < 0 ? "down" : "flat" };
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
/** "Sep 2026" */
const mesAnio = (c: { mes: number; anio: number }) => `${cap(MONTHS_SHORT[c.mes - 1])} ${c.anio}`;
/** Día del corte (fecha real en que se tomó) */
const diaCorte = (c: Columna) => Number(c.fecha.slice(8, 10));
const tomadoOtroMes = (c: Columna) => Number(c.fecha.slice(5, 7)) !== c.mes;
const fechaCorta = (iso: string) => fmtDate(iso).replace(/ \d{4}$/, "");
/** "Sep 2026 · día 30" o, si se tomó en otro mes (recuperación), "Nov 2026 · tomado 2 dic" */
const colNombre = (c: Columna) => (tomadoOtroMes(c) ? `${mesAnio(c)} · tomado ${fechaCorta(c.fecha)}` : `${mesAnio(c)} · día ${diaCorte(c)}`);
/** Cómo se obtuvo el valor de la columna */
const origenCol = (c: Columna) =>
  c.automatico ? (c.disparo === "inicial" ? "corte inicial" : "corte automático") : "valor confirmado del Excel";
function colTitle(c: Columna): string {
  const dia = c.dia_estimado
    ? `Día de corte estimado (fin de mes): el Excel no registra el día de este corte (encabezado “${c.encabezado}”)`
    : `Corte del ${fmtDate(c.fecha)} (encabezado “${c.encabezado}” en el Excel)`;
  const how = c.automatico ? `${origenCol(c)}, hoja ${c.hoja}` : c.tipo === "formula" ? `fórmula COUNTIFS sobre la hoja ${c.hoja}` : origenCol(c);
  return `${dia} · ${how}${c.observacion ? ` · ${c.observacion}` : ""}`;
}

const DISPARO: Record<Corte["disparo"], string> = {
  schedule: "Automático", catch_up: "Automático (recuperación)", retry: "Automático (reintento)", cli: "Soporte técnico",
  desarrollo: "Desarrollo", inicial: "Corte inicial",
};

function EstadoBadge({ e }: { e: Corte["estado"] }) {
  if (e === "exitosa") return <Badge tone="success" icon={<CheckCircle2 />}>Exitoso</Badge>;
  if (e === "fallida") return <Badge tone="danger" icon={<XCircle />}>Fallido</Badge>;
  if (e === "en_curso") return <Badge tone="brand" icon={<Loader2 className="spin" />}>En curso</Badge>;
  return <Badge icon={<CircleSlash />}>Omitido</Badge>;
}

type SortKey = string; // orden | plan | segmento | costo | c:<índice global> | ultimo

/* ------------------------------------------------------------------ página */
export function Reporte({ meta }: { meta: Meta }) {
  useTitle("Reporte mensual");
  const qc = useQueryClient();
  const toast = useToast();
  const rep = useReporte();
  const running = !!meta.en_curso;
  const cortes = useCortes(running);
  const wasRunning = useRef(running);
  useEffect(() => {
    if (wasRunning.current && !running) {
      qc.invalidateQueries({ queryKey: ["reporte"] });
      qc.invalidateQueries({ queryKey: ["cortes"] });
    }
    wasRunning.current = running;
  }, [running, qc]);

  const data = rep.data;
  const [anio, setAnio] = useState<number | null>(null);
  const [mes, setMes] = useState<number | null>(null);
  useEffect(() => { // por defecto, el año en curso (el del último corte): en 2027 la tabla arranca en enero 2027
    if (data && (anio === null || !data.anios.includes(anio))) setAnio(data.anios[data.anios.length - 1]);
  }, [data, anio]);

  const visibles = useMemo(() => (data && anio !== null
    ? data.columnas.map((c, i) => ({ c, i })).filter(({ c }) => c.anio === anio && (mes === null || c.mes === mes))
    : []), [data, anio, mes]);
  const libroDescarga = visibles.length ? visibles[visibles.length - 1].c.libro : data?.libros[data.libros.length - 1]?.anio;
  const nombreDescarga = data?.libros.find((l) => l.anio === libroDescarga)?.descarga ?? meta.excel.nombre ?? "Excel";

  const g = data ? data.columnas.length - 1 : -1;
  const ultima = data && g >= 0 ? data.columnas[g] : null;

  const descargarExcel = async () => {
    try {
      const name = await download("/api/descargas/excel", { anio: libroDescarga ? String(libroDescarga) : undefined });
      toast("success", <>Archivo <b>{name}</b> descargado.</>);
    } catch (e) {
      toast("error", (e as Error).message);
    }
  };

  return (
    <div className="page">
      <header className="page-head">
        <div className="stack" style={{ gap: 0 }}>
          <div className="page-head__eyebrow">Reporte mensual · {meta.origen}</div>
          <h1>Suscripciones de TV por plan</h1>
          <p>Suscripciones en estado {meta.estados.join(" + ")} en cada corte, por plan de televisión.</p>
        </div>
        <div className="page-head__actions">
          <Button variant="secondary" icon={<Download />} onClick={descargarExcel} disabled={!meta.excel.existe} title={nombreDescarga}>
            Descargar Excel
          </Button>
        </div>
      </header>

      {running && meta.en_curso && (
        <Banner tone="info">
          <strong>Generando el corte del {fmtDate(meta.en_curso.fecha_corte)}.</strong> {meta.en_curso.paso || "Procesando…"} La tabla se
          actualiza sola al terminar.
        </Banner>
      )}
      {meta.ultima?.estado === "fallida" && !running && (
        <Banner tone="danger"><strong>El último corte ({fmtDate(meta.ultima.fecha_corte)}) falló:</strong> {meta.ultima.mensaje}</Banner>
      )}
      {!meta.erp.configured && (
        <Banner tone="warning">ERPNext sin credenciales: completa <code>ERPNEXT_API_KEY</code> y <code>ERPNEXT_API_SECRET</code> en <code>backend/.env</code>.</Banner>
      )}

      <div className="kpis kpis--3" style={{ ["--kpi-n" as string]: 3 }}>
        <div className="kpi">
          <span className="kpi__label"><CheckCircle2 aria-hidden />Último corte</span>
          {data && ultima ? (
            <>
              <span className="kpi__value row" style={{ gap: 12 }}>
                <span className="num">{fmtInt(data.totales[g])}</span>
                <DeltaView d={delta(g > 0 ? data.totales[g - 1] : null, data.totales[g])} pill />
              </span>
              <span className="kpi__sub">
                {colNombre(ultima)} · {origenCol(ultima)}
                {g > 0 && <> · vs {mesAnio(data.columnas[g - 1])}</>}
              </span>
            </>
          ) : <Skeleton w={160} h={30} />}
        </div>
        <div className="kpi">
          <span className="kpi__label"><CalendarClock aria-hidden />Próximo corte automático</span>
          <span className="kpi__value kpi__value--text">{meta.programacion.proxima ? fmtWeekdayDateTime(meta.programacion.proxima) : "—"}</span>
          <span className="kpi__sub">{meta.programacion.regla} · {fmtRelative(meta.programacion.proxima)}</span>
        </div>
        <div className="kpi">
          <span className="kpi__label"><Database aria-hidden />Origen de los datos</span>
          <span className="kpi__value kpi__value--text">{meta.origen}</span>
          <span className="kpi__sub">Todas las suscripciones · reporte: {meta.estados.join(" + ")}</span>
        </div>
      </div>

      {!data ? (rep.isError ? (
        <Panel><Empty icon={<SearchX />} title="No hay reporte">{(rep.error as Error).message}</Empty></Panel>
      ) : <Panel><Skeleton h={420} /></Panel>) : anio !== null && (
        <Tabla data={data} anio={anio} setAnio={(y) => { setAnio(y); setMes(null); }} mes={mes} setMes={setMes} visibles={visibles} />
      )}

      <CortesPanel cortes={cortes.data?.cortes} meta={meta} />
    </div>
  );
}

/* ------------------------------------------------------------------ tabla principal */
function Tabla({ data, anio, setAnio, mes, setMes, visibles }: {
  data: ReporteT;
  anio: number;
  setAnio: (y: number) => void;
  mes: number | null;
  setMes: (m: number | null) => void;
  visibles: { c: Columna; i: number }[];
}) {
  const mobile = useMedia("(max-width: 767px)");
  const [search, setSearch] = useState("");
  const q = useDebounced(search, 150).trim().toLowerCase();
  const [seg, setSeg] = useState<string[]>([]);
  const [showVar, setShowVar] = useState(false);
  // Si la tabla no cabe, se abre desplazada al final: el último corte y la tendencia siempre a la vista (Plan queda fijo)
  const wrapRef = useRef<HTMLDivElement>(null);
  const colKey = visibles.map(({ c }) => c.id).join("|");
  const [compact, setCompact] = useState(true);
  useEffect(() => {
    const el = wrapRef.current;
    if (el && el.scrollWidth > el.clientWidth) el.scrollLeft = el.scrollWidth;
  }, [colKey, compact, mobile]);
  const [sortKey, setSortKey] = useState<SortKey>("orden");
  const [dir, setDir] = useState<"asc" | "desc">("asc");
  const segOrder = useMemo(() => [...new Set(data.planes.map((p) => p.segmento || "Sin segmento"))], [data]);
  const color = useSegmentColors(segOrder);
  const idx = visibles.map((v) => v.i);
  const lastI = idx.length ? idx[idx.length - 1] : -1;
  const prevOf = (i: number) => (i > 0 ? i - 1 : -1); // variación contra el corte anterior, aunque sea de otro año
  const mesesDelAnio = [...new Set(data.columnas.filter((c) => c.anio === anio).map((c) => c.mes))].sort((a, b) => a - b);
  // Tendencia: hasta 12 cortes que terminan en el último visible (sirve también en enero, con un solo corte del año)
  const nTrend = lastI >= 0 ? Math.min(12, lastI + 1) : 0;
  const trendIdx = Array.from({ length: nTrend }, (_, k) => lastI - nTrend + 1 + k);

  const rows = useMemo(() => {
    const out = data.planes.filter((p) => (!seg.length || seg.includes(p.segmento || "Sin segmento"))
      && (!q || `${p.plan} ${p.segmento} ${p.descripcion}`.toLowerCase().includes(q)));
    if (sortKey === "orden") return out;
    const val = (p: PlanFila): number | string | null => sortKey === "plan" ? p.plan : sortKey === "segmento" ? `${p.segmento}\u0000${p.plan}`
      : sortKey === "costo" ? p.costo : sortKey === "ultimo" ? delta(p.valores[lastI - 1], p.valores[lastI]).abs
        : p.valores[Number(sortKey.slice(2))];
    return [...out].sort((a, b) => {
      const va = val(a);
      const vb = val(b);
      if (va === null) return 1;
      if (vb === null) return -1;
      const c = typeof va === "number" ? va - (vb as number) : String(va).localeCompare(String(vb), "es");
      return dir === "asc" ? c : -c;
    });
  }, [data, seg, q, sortKey, dir, lastI]);

  const totalAt = (i: number) => (i < 0 ? null : rows.reduce((a, p) => a + (p.valores[i] ?? 0), 0));
  const setSort = (k: SortKey) => {
    if (sortKey === k) setDir(dir === "asc" ? "desc" : "asc");
    else {
      setSortKey(k);
      setDir(["plan", "segmento", "orden"].includes(k) ? "asc" : "desc");
    }
  };
  const filtered = !!q || seg.length > 0 || mes !== null;
  const ord = (c: Columna) => c.anio * 12 + c.mes;
  const gapBefore = (i: number) => i > 0 && ord(data.columnas[i]) - ord(data.columnas[i - 1]) > 1;
  const colCls = (i: number, j: number) => `num${j === 0 ? " tbl__group-sep" : ""}${j > 0 && gapBefore(i) ? " gap-before" : ""}${i === data.columnas.length - 1 ? " is-current" : ""}`;

  return (
    <>
      <div className="filterbar">
        <SearchInput value={search} onChange={setSearch} />
        <Pick label="Año" value={String(anio)} highlight={false} onChange={(v) => setAnio(Number(v))}
          options={[...data.anios].reverse().map((y) => {
            const n = data.columnas.filter((c) => c.anio === y).length;
            return { value: String(y), label: String(y), hint: `${n} ${n === 1 ? "corte" : "cortes"}` };
          })} />
        <Pick label="Mes" value={mes === null ? "" : String(mes)} onChange={(v) => setMes(v ? Number(v) : null)}
          options={[{ value: "", label: "Todos los meses", text: "Todos" },
            ...mesesDelAnio.map((m) => ({ value: String(m), label: cap(MONTHS[m - 1]), text: cap(MONTHS[m - 1]) }))]} />
        <MultiPick label="Segmento" values={seg} options={segOrder} onChange={setSeg}
          renderOption={(o) => <SegTag name={o} color={color(o)} />} />
        {filtered && <Button variant="ghost" size="sm" onClick={() => { setSearch(""); setSeg([]); setMes(null); }}>Limpiar filtros</Button>}
        {!mobile && (
          <div className="row" style={{ marginLeft: "auto", gap: 14 }}>
            <Switch checked={showVar} onChange={setShowVar} label="Variación entre cortes" />
            <Segmented label="Columnas" value={compact ? "compacta" : "completa"} onChange={(v) => setCompact(v === "compacta")}
              options={[{ value: "compacta", label: "Compacta" }, { value: "completa", label: "Completa" }]} />
          </div>
        )}
      </div>

      {rows.length === 0 || idx.length === 0 ? (
        <Panel><Empty icon={<SearchX />} title="Sin resultados">
          {idx.length === 0 ? `No hay cortes para ${mes ? `${MONTHS[mes - 1]} de ` : ""}${anio}.` : "Ningún plan coincide con la búsqueda."}
        </Empty></Panel>
      ) : mobile ? (
        <div className="stack" style={{ gap: 10 }}>
          <div className="mcard mcard--total">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="stack">
                <span className="muted" style={{ fontSize: 12.5 }}>Total · {colNombre(data.columnas[lastI])}</span>
                <span className="num" style={{ fontSize: 24, fontWeight: 600, letterSpacing: "-0.02em" }}>{fmtInt(totalAt(lastI))}</span>
              </span>
              <span className="stack" style={{ alignItems: "flex-end", gap: 6 }}>
                <Sparkline values={trendIdx.map(totalAt)} width={90} height={28} color="var(--text-3)" />
                <DeltaView d={delta(totalAt(prevOf(lastI)), totalAt(lastI))} size="sm" />
              </span>
            </div>
          </div>
          {rows.map((p) => (
            <div key={p.plan} className="mcard">
              <span className="stack" style={{ gap: 6, minWidth: 0 }}>
                <span className="mcard__title">{p.plan}</span>
                <span className="row" style={{ gap: 8 }}>
                  <SegTag name={p.segmento || "—"} color={color(p.segmento || "Sin segmento")} />
                  <span className="muted" style={{ fontSize: 12.5 }}>{p.costo ? fmtMoney(p.costo) : "Sin costo"}</span>
                </span>
              </span>
              <span className="stack" style={{ alignItems: "flex-end", gap: 4 }}>
                <span className="mcard__value num">{fmtInt(p.valores[lastI])}</span>
                <DeltaView d={delta(p.valores[prevOf(lastI)], p.valores[lastI])} size="sm" showPct={false} />
                <Sparkline values={trendIdx.map((i) => p.valores[i])} width={72} height={22} />
              </span>
            </div>
          ))}
        </div>
      ) : (
        <Panel flush className="hist-panel">
          <div className="table-wrap" ref={wrapRef}>
            <table className="tbl tbl--hist">
              <thead>
                <tr className="tbl__groups">
                  <th className="sticky-col">Plan</th>
                  <th colSpan={compact ? 2 : 4} />
                  <th colSpan={idx.length} className="tbl__group-sep" style={{ textAlign: "left" }}>
                    Cortes {anio}{mes ? ` · ${MONTHS[mes - 1]}` : ""}
                  </th>
                  <th className="tbl__group-sep">Tendencia</th>
                </tr>
                <tr>
                  <th className="sticky-col" style={{ minWidth: 250 }}><Sort k="plan" label="Plan" cur={sortKey} dir={dir} set={setSort} /></th>
                  {!compact && <th>Clasificación</th>}
                  <th><Sort k="segmento" label="Segmento" cur={sortKey} dir={dir} set={setSort} /></th>
                  {!compact && <th>Descripción</th>}
                  <th className="num"><Sort k="costo" label="Costo sin IVA" cur={sortKey} dir={dir} set={setSort} num /></th>
                  {visibles.map(({ c, i }, j) => (
                    <th key={c.id} className={colCls(i, j)} style={{ minWidth: 76 }} title={colTitle(c)}>
                      <Sort k={`c:${i}`} cur={sortKey} dir={dir} set={setSort} num
                        label={(
                          <span className="period-head">
                            {mesAnio(c)}
                            <small className={c.dia_estimado ? "is-estimated" : undefined}>
                              {tomadoOtroMes(c) ? `tomado ${fechaCorta(c.fecha)}` : `día ${diaCorte(c)}`}
                            </small>
                          </span>
                        )} />
                    </th>
                  ))}
                  <th className="tbl__group-sep" style={{ minWidth: 128 }}><Sort k="ultimo" label="Último corte" cur={sortKey} dir={dir} set={setSort} /></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.plan} className={idx.every((i) => !p.valores[i]) ? "is-muted" : ""}>
                    <td className="sticky-col">
                      <div className="plan-cell">
                        <span className="plan-cell__name">{p.plan}</span>
                        {compact && <span className="plan-cell__sub" title={p.descripcion || ""}>{[p.clasificacion, p.descripcion].filter(Boolean).join(" · ")}</span>}
                      </div>
                    </td>
                    {!compact && <td className="muted">{p.clasificacion || "—"}</td>}
                    <td><SegTag name={p.segmento || "—"} color={color(p.segmento || "Sin segmento")} /></td>
                    {!compact && <td className="muted"><span className="ellipsis" style={{ display: "block", maxWidth: 230 }} title={p.descripcion || ""}>{p.descripcion || "—"}</span></td>}
                    <td className="num muted">{p.costo === null ? "—" : fmtMoney(p.costo)}</td>
                    {visibles.map(({ c, i }, j) => (
                      <td key={c.id} className={colCls(i, j)}>
                        <Cell v={p.valores[i]} d={delta(p.valores[prevOf(i)], p.valores[i])} showVar={showVar && i > 0} />
                      </td>
                    ))}
                    <td className="tbl__group-sep">
                      <div className="row" style={{ gap: 10, justifyContent: "space-between" }}>
                        <Sparkline values={trendIdx.map((i) => p.valores[i])} width={56} height={24} />
                        <DeltaView d={delta(p.valores[prevOf(lastI)], p.valores[lastI])} size="sm" showPct={false} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td className="sticky-col">Total{q || seg.length ? " (filtrado)" : ""}</td>
                  <td colSpan={compact ? 2 : 4} />
                  {visibles.map(({ c, i }, j) => (
                    <td key={c.id} className={colCls(i, j)}>
                      <Cell v={totalAt(i)} d={delta(totalAt(prevOf(i)), totalAt(i))} showVar={showVar && i > 0} />
                    </td>
                  ))}
                  <td className="tbl__group-sep">
                    <div className="row" style={{ gap: 10, justifyContent: "space-between" }}>
                      <Sparkline values={trendIdx.map(totalAt)} width={56} height={24} color="var(--text-3)" />
                      <DeltaView d={delta(totalAt(prevOf(lastI)), totalAt(lastI))} size="sm" showPct={false} />
                    </div>
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
          <div className="pager">
            <span>{rows.length} de {data.planes.length} planes · {idx.length} {idx.length === 1 ? "corte" : "cortes"} de {anio}
              {visibles.some(({ c }) => c.dia_estimado) && " · día subrayado: estimado (fin de mes), el Excel no lo registra"}</span>
            <span className="muted">Excel actualizado {fmtDateTime(data.actualizado)}</span>
          </div>
        </Panel>
      )}
    </>
  );
}

function Cell({ v, d, showVar }: { v: number | null; d: Delta; showVar: boolean }) {
  if (v === null) return <span className="nodata">—</span>;
  return (
    <>
      <span className="cell-value num">{fmtInt(v)}</span>
      {showVar && (
        <span className={`cell-delta delta--${d.kind} num`} title={d.pct !== null ? fmtPct(d.pct, true) : undefined}>
          {d.kind === "no_data" ? " " : d.abs === 0 ? "=" : fmtSigned(d.abs)}
        </span>
      )}
    </>
  );
}

function Sort({ k, label, cur, dir, set, num }: {
  k: SortKey; label: React.ReactNode; cur: SortKey; dir: string; set: (k: SortKey) => void; num?: boolean;
}) {
  const active = cur === k;
  const Icon = !active ? ArrowDownUp : dir === "asc" ? ChevronUp : ChevronDown;
  return (
    <button type="button" className={`sort-btn${active ? " is-sorted" : ""}`} onClick={() => set(k)}
      aria-label={`Ordenar por ${typeof label === "string" ? label : "corte"}`}>
      {num ? <><Icon aria-hidden />{label}</> : <>{label}<Icon aria-hidden /></>}
    </button>
  );
}

/* ------------------------------------------------------------------ historial de cortes */
function CortesPanel({ cortes, meta }: { cortes: Corte[] | undefined; meta: Meta }) {
  const toast = useToast();
  const [open, setOpen] = useState<string | null>(null);
  const mobile = useMedia("(max-width: 767px)");
  const bajar = async (path: string, params: Record<string, string>, que: string) => {
    try {
      const n = await download(path, params);
      toast("success", <>{que} <b>{n}</b> descargado.</>);
    } catch (e) {
      toast("error", (e as Error).message);
    }
  };
  const lista = (cortes || []).filter((c) => c.estado !== "omitida");
  const columnaDe = (c: Corte) => {
    if (c.disparo === "desarrollo") return "No incluido en el reporte";
    const [y, m] = (c.periodo || c.fecha_corte).split("-").map(Number);
    return Number(c.fecha_corte.slice(5, 7)) !== m
      ? `${mesAnio({ anio: y, mes: m })} · tomado ${fechaCorta(c.fecha_corte)}`
      : `${mesAnio({ anio: y, mes: m })} · día ${Number(c.fecha_corte.slice(8, 10))}`;
  };
  return (
    <Panel flush title="Cortes generados"
      desc="Cada corte guarda la consulta completa (todos los estados) en .json y agrega su hoja y su columna al Excel del año">
      {!cortes ? <div style={{ padding: 18 }}><Skeleton h={120} /></div> : lista.length === 0 ? (
        <Empty icon={<CalendarClock />} title="Aún no hay cortes automáticos">
          El primero se genera el {meta.programacion.proxima ? fmtWeekdayDateTime(meta.programacion.proxima).toLowerCase() : "último día del mes"}.
        </Empty>
      ) : (
        <div className="table-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Fecha del corte</th>
                {!mobile && <th>Columna del reporte · hoja</th>}
                <th>Estado</th>
                <th className="num">Reporte</th>
                {!mobile && <th className="num">Filas en el .json</th>}
                {!mobile && <th className="num">Duración</th>}
                {!mobile && <th>Origen</th>}
                <th className="num">Descargas</th>
              </tr>
            </thead>
            <tbody>
              {lista.map((c) => {
                const dev = c.disparo === "desarrollo";
                return (
                  <Fragment key={`${c.id}-${c.estado}`}>
                    <tr className="is-click" onClick={() => setOpen(open === c.id ? null : c.id)} aria-expanded={open === c.id}>
                      <td>
                        <span className="stack" style={{ gap: 3 }}>
                          <span style={{ fontWeight: 500 }}>{fmtDate(c.fecha_corte)}</span>
                          {c.observacion
                            ? <span className="obs"><FlaskConical aria-hidden />{c.observacion}</span>
                            : <span className="muted" style={{ fontSize: 12 }}>{fmtDateTime(c.inicio)}</span>}
                        </span>
                      </td>
                      {!mobile && <td>{columnaDe(c)} <span className="muted">· {c.hoja}</span></td>}
                      <td><EstadoBadge e={c.estado} /></td>
                      <td className="num" style={{ fontWeight: 500 }}>{fmtInt(c.total)}</td>
                      {!mobile && <td className="num muted">{fmtInt(c.filas)}</td>}
                      {!mobile && <td className="num muted">{c.duracion_ms ? fmtDuration(c.duracion_ms) : "—"}</td>}
                      {!mobile && <td className="muted">{dev ? <Badge tone="warning">Desarrollo</Badge> : DISPARO[c.disparo] ?? c.disparo}</td>}
                      <td className="num">
                        <span className="row" style={{ gap: 2, justifyContent: "flex-end" }}>
                          {c.snapshot && (
                            <button type="button" className="icon-btn" title={`JSON con todas las suscripciones (todos los estados): ${c.snapshot}`}
                              aria-label={`Descargar ${c.snapshot}`}
                              onClick={(e) => { e.stopPropagation(); bajar(`/api/descargas/snapshots/${encodeURIComponent(c.snapshot!)}`, {}, "Snapshot"); }}>
                              <FileJson />
                            </button>
                          )}
                          {c.estado === "exitosa" && (
                            <button type="button" className="icon-btn" title={dev ? "Excel de este corte de desarrollo" : `Excel con este corte (hoja ${c.hoja})`}
                              aria-label="Descargar Excel del corte"
                              onClick={(e) => { e.stopPropagation(); bajar("/api/descargas/excel", { corte: c.id }, "Excel"); }}>
                              <FileSpreadsheet />
                            </button>
                          )}
                        </span>
                      </td>
                    </tr>
                    {open === c.id && (
                      <tr className="run-detail">
                        <td colSpan={mobile ? 4 : 8}>
                          <div className="run-detail__body">
                            {c.mensaje && <p className={c.estado === "fallida" ? "run-detail__msg is-error" : "run-detail__msg"}>{c.mensaje}</p>}
                            {c.filas_por_estado && (
                              <dl className="run-detail__meta">
                                {Object.entries(c.filas_por_estado).map(([st, n]) => (
                                  <div key={st}>
                                    <dt>{st}{meta.estados.includes(st) ? " · cuenta" : ""}</dt>
                                    <dd className="num">{fmtInt(n)} filas</dd>
                                  </div>
                                ))}
                              </dl>
                            )}
                            <span className="muted" style={{ fontSize: 12 }}>Ejecutado el {fmtDateTime(c.inicio)}</span>
                            {c.detalle && c.estado === "fallida" && <pre className="run-detail__err">{c.detalle}</pre>}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
