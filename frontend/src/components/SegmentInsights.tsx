import { useMemo, useState } from "react";
import { ChartPie, RotateCcw, Trophy } from "lucide-react";
import { useComercial } from "../api/hooks";
import type { Reporte } from "../api/types";
import { DownloadMenu, LeadsTvCard, RecaudoCard, type DownloadItem } from "./ComercialCards";
import { delta } from "../lib/delta";
import { MONTHS, fmtInt, fmtPct, fmtSigned } from "../lib/format";
import { useMedia, useSegmentColors } from "../lib/hooks";
import { useCountUp, useReveal } from "../lib/motion";
import { PieChart, TrendLine } from "./charts";
import { DeltaView, Pick } from "./ui";

const OTROS = "Otros";
const MAX_ROWS = 4; // más de 4 segmentos con suscripciones: los 3 primeros + "Otros"
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

type Part = { key: string; name: string; value: number; pct: number; color: string; detail?: string };

function CountUp({ value, run, pct }: { value: number; run: boolean; pct?: boolean }) {
  const v = useCountUp(value, run);
  return <>{pct ? fmtPct(v) : fmtInt(Math.round(v))}</>;
}

/**
 * Cards pequeñas sobre un corte, con su propio filtro de año y mes (por defecto, el último corte):
 * - Suscripciones por segmento: participación de cada segmento en el corte (gráfico de torta + lista).
 * - Segmento con más suscripciones: el mayor del corte, su variación frente al corte anterior y su tendencia.
 * - Recaudo por plan de TV (recaudo efectivo del mes, sin IVA, no acumula) y Leads convertidos del mes del corte
 *   (ERPNext, ver backend/app/comercial.py).
 * Suscripciones = filas Active + Past Due Date por plan, como en la tabla; el segmento sale de la columna
 * "Segmento plan" del Excel. Los planes se pintan con el color de su segmento (el mismo de la torta).
 */
export function SegmentInsights({ data, labelOf }: { data: Reporte; labelOf: (idx: number) => string }) {
  const run = useReveal();
  const com = useComercial();
  const segOrder = useMemo(() => [...new Set(data.planes.map((p) => p.segmento || "Sin segmento"))], [data]);
  const color = useSegmentColors(segOrder);
  const segOf = useMemo(() => new Map(data.planes.map((p) => [p.plan, p.segmento || "Sin segmento"])), [data]);
  const planColor = (plan: string) => color(segOf.get(plan) || "Sin segmento");
  const [hover, setHover] = useState<string | null>(null);
  const mobile = useMedia("(max-width: 767px)");

  // Corte elegido en el filtro de las cards (null = siempre el último corte)
  const last = data.columnas.length - 1;
  const [sel, setSel] = useState<number | null>(null);
  const i = sel !== null && sel <= last ? sel : last;
  const col = data.columnas[i];
  const yearOptions = [...data.anios].reverse().map((y) => {
    const n = data.columnas.filter((c) => c.anio === y).length;
    return { value: String(y), label: String(y), hint: `${n} ${n === 1 ? "corte" : "cortes"}` };
  });
  const monthOptions = data.columnas.map((c, idx) => ({ c, idx })).filter(({ c }) => c.anio === col.anio)
    .map(({ c, idx }) => ({ value: String(idx), label: cap(MONTHS[c.mes - 1]), text: cap(MONTHS[c.mes - 1]) }));
  const pickIdx = (idx: number) => setSel(idx === last ? null : idx);
  const pickYear = (y: number) => {
    const idxs = data.columnas.map((c, idx) => (c.anio === y ? idx : -1)).filter((idx) => idx >= 0);
    if (idxs.length) pickIdx(idxs[idxs.length - 1]); // al cambiar de año: el último corte de ese año
  };

  const totalsAt = (idx: number) => {
    const m = new Map<string, number>(segOrder.map((s) => [s, 0]));
    for (const p of data.planes) {
      const s = p.segmento || "Sin segmento";
      m.set(s, (m.get(s) ?? 0) + (p.valores[idx] ?? 0));
    }
    return m;
  };
  const cur = totalsAt(i);
  const prev = i > 0 ? totalsAt(i - 1) : null;
  const total = [...cur.values()].reduce((a, b) => a + b, 0);
  const ranked = [...cur.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "es"));
  const conSuscripciones = ranked.filter(([, v]) => v > 0);
  const sinSuscripciones = ranked.filter(([, v]) => v === 0).map(([s]) => s);

  const part = (s: string, v: number): Part => ({ key: s, name: s, value: v, pct: total ? (v / total) * 100 : 0, color: color(s) });
  let parts: Part[] = conSuscripciones.map(([s, v]) => part(s, v));
  if (parts.length > MAX_ROWS) {
    const rest = parts.slice(MAX_ROWS - 1);
    const v = rest.reduce((a, p) => a + p.value, 0);
    parts = [...parts.slice(0, MAX_ROWS - 1), {
      key: OTROS, name: `${OTROS} (${rest.length})`, value: v, pct: total ? (v / total) * 100 : 0, color: "var(--seg-other)",
      detail: rest.map((p) => `${p.name} ${fmtPct(p.pct)}`).join(" · "),
    }];
  }

  const periodo = labelOf(i);
  const leader = conSuscripciones[0];
  const growth = prev ? [...cur.entries()].map(([s, v]) => [s, v - (prev.get(s) ?? 0)] as const).sort((a, b) => b[1] - a[1]) : [];
  const topGrowth = growth[0];
  const n = Math.min(12, i + 1);
  const trendIdx = Array.from({ length: n }, (_, k) => i - n + 1 + k);
  const leaderTrend = leader ? trendIdx.map((idx) => ({ label: labelOf(idx), value: totalsAt(idx).get(leader[0]) ?? null })) : [];

  const mesCompleto = `${cap(MONTHS[col.mes - 1])} ${col.anio}`;

  // Descargas de las cards de suscripciones. Los meses sin hoja cruda (dic 2025 – jul 2026) solo tienen las cantidades
  // confirmadas de la tabla del Excel inicial del proyecto: se indica en la card y en el Excel descargado.
  const conDetalle = !!(col.snapshot || col.hoja);
  const excelInicial = conDetalle ? null : (
    <span className="insight__tag" title={`Cantidades confirmadas de la tabla del Excel inicial del proyecto (columna "${col.encabezado}"). Ese mes no tiene detalle por suscripción.`}>
      Excel inicial
    </span>
  );
  const notaOrigen = conDetalle ? undefined
    : `${mesCompleto}: cantidades de la tabla del Excel inicial del proyecto (columna "${col.encabezado}"); no hay detalle por suscripción.`;
  const segItems = (tarjeta: "segmentos" | "lider", titulo: string): DownloadItem[] => [
    { key: "excel", kind: "excel", title: `Excel · ${titulo}`, path: `/api/descargas/tarjeta/${tarjeta}`, params: { periodo: col.periodo },
      desc: conDetalle ? "Por segmento y por plan, todos los cortes y cada suscripción que cuenta en el corte"
        : "Por segmento y por plan y todos los cortes (cantidades del Excel inicial)" },
    ...(col.snapshot ? [{ key: "json", kind: "json" as const, title: "JSON del corte", path: `/api/descargas/snapshots/${col.snapshot}`,
      desc: "Consulta completa a ERPNext del corte, todas las suscripciones y estados" }] : []),
  ];

  return (
    <div className={`insights${run ? " is-in" : ""}`}>
      <div className="insights__bar">
        <span className="insights__label">Resumen del corte <span className="muted">· {periodo}</span></span>
        <div className="insights__filters" role="group" aria-label="Corte de las cards">
          {sel !== null && (
            <button type="button" className="insights__reset" onClick={() => setSel(null)} title="Volver al último corte">
              <RotateCcw aria-hidden />Último corte
            </button>
          )}
          <Pick label="Año" size="sm" align="right" highlight={false} value={String(col.anio)} options={yearOptions}
            onChange={(v) => pickYear(Number(v))} />
          <Pick label="Mes" size="sm" align="right" highlight={sel !== null} value={String(i)} options={monthOptions}
            onChange={(v) => pickIdx(Number(v))} />
        </div>
      </div>

      <section className="insight" aria-labelledby="ins-seg-title" style={{ ["--d" as string]: 0 }}>
        <header className="insight__head">
          <span className="insight__icon" aria-hidden><ChartPie /></span>
          <div className="insight__titles">
            <h2 id="ins-seg-title" className="insight__title">Suscripciones por segmento</h2>
            <p className="insight__sub">Participación · {periodo} · {fmtInt(total)} suscripciones{excelInicial}</p>
          </div>
          <div className="insight__actions">
            <DownloadMenu label="Suscripciones por segmento" items={segItems("segmentos", `Suscripciones ${periodo}`)} note={notaOrigen} />
          </div>
        </header>
        {total === 0 ? (
          <p className="insight__empty">Este corte no tiene suscripciones registradas.</p>
        ) : (
          <>
            <div className="pie-layout">
              <PieChart slices={parts.map((p) => ({ key: p.key, value: p.value, color: p.color }))} size={mobile ? 104 : 132} run={run}
                active={hover} onHover={setHover}
                label={`Participación por segmento: ${parts.map((p) => `${p.name} ${fmtPct(p.pct)}`).join(", ")}`}
                renderTip={(key) => {
                  const p = parts.find((x) => x.key === key)!;
                  return <><span className="seg-sw" style={{ background: p.color }} /><b>{p.name}</b> {fmtInt(p.value)} · {fmtPct(p.pct)}</>;
                }} />
              <ul className="seglist seglist--stack">
                {parts.map((p, k) => (
                  <li key={p.key} className={`seglist__row${hover && hover !== p.key ? " is-dim" : ""}`}
                    style={{ ["--k" as string]: k }} title={p.detail}
                    onMouseEnter={() => setHover(p.key)} onMouseLeave={() => setHover(null)}>
                    <span className="seg-sw" style={{ background: p.color }} />
                    <span className="seglist__name">{p.name}</span>
                    <span className="seglist__count num">{fmtInt(p.value)}</span>
                    <span className="seglist__pct num"><CountUp value={p.pct} run={run} pct /></span>
                  </li>
                ))}
              </ul>
            </div>
            {sinSuscripciones.length > 0 && (
              <p className="insight__foot" title={sinSuscripciones.join(", ")}>
                Sin suscripciones en el corte: {sinSuscripciones.join(", ")}
              </p>
            )}
          </>
        )}
      </section>

      <section className="insight insight--leader" aria-labelledby="ins-top-title" style={{ ["--d" as string]: 1 }}>
        <header className="insight__head">
          <span className="insight__icon insight__icon--trophy" aria-hidden><Trophy /></span>
          <div className="insight__titles">
            <h2 id="ins-top-title" className="insight__title">Segmento con más suscripciones</h2>
            <p className="insight__sub">{mesCompleto}{excelInicial}</p>
          </div>
          <div className="insight__actions">
            <DownloadMenu label="Segmento con más suscripciones" items={segItems("lider", `Segmentos ${periodo}`)} note={notaOrigen} />
          </div>
        </header>
        {!leader ? (
          <p className="insight__empty">Este corte no tiene suscripciones registradas.</p>
        ) : (
          <>
            <div className="leader">
              <div className="leader__main">
                <span className="leader__name">
                  <span className="seg-sw seg-sw--lg" style={{ background: color(leader[0]) }} />
                  {leader[0]}
                </span>
                <span className="leader__value num">
                  <CountUp value={leader[1]} run={run} /> <small>suscripciones</small>
                </span>
                <span className="leader__meta">
                  {prev && (
                    <span title={`Variación frente al corte anterior (${labelOf(i - 1)})`}>
                      <DeltaView d={delta(prev.get(leader[0]) ?? 0, leader[1])} pill />
                    </span>
                  )}
                  <span><b className="num"><CountUp value={total ? (leader[1] / total) * 100 : 0} run={run} pct /></b> del total</span>
                </span>
              </div>
              <TrendLine points={leaderTrend} accent={color(leader[0])} run={run} width={168} height={58} format={fmtInt}
                label={`Tendencia de ${leader[0]} en los últimos ${leaderTrend.length} cortes`} />
            </div>
            <p className="insight__foot">
              {!prev ? "Primer corte del reporte: sin corte anterior para comparar."
                : topGrowth && topGrowth[1] > 0
                  ? topGrowth[0] === leader[0]
                    ? <>También es el segmento que más creció frente al corte anterior ({fmtSigned(topGrowth[1])}).</>
                    : <>Mayor crecimiento frente al corte anterior: <span className="seg-sw" style={{ background: color(topGrowth[0]) }} /> <b>{topGrowth[0]}</b> ({fmtSigned(topGrowth[1])}).</>
                  : <>Ningún segmento creció frente a {labelOf(i - 1)}.</>}
            </p>
          </>
        )}
      </section>

      <RecaudoCard periodo={col.periodo} mes={mesCompleto} com={com.data} failed={com.isError} run={run}
        planColor={planColor} style={{ ["--d" as string]: 2 }} />
      <LeadsTvCard periodo={col.periodo} mes={mesCompleto} com={com.data} failed={com.isError} run={run}
        planColor={planColor} style={{ ["--d" as string]: 3 }} />
    </div>
  );
}
