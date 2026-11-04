import { useId, useState, type MouseEvent, type ReactNode } from "react";
import { useTweenMap } from "../lib/motion";

/**
 * Tendencia animada con detalle al pasar el cursor: el trazo (tono de baja jerarquía) se dibuja de izquierda a
 * derecha y el último corte aparece en el color de acento. Al pasar el cursor, guía vertical + valor del corte.
 */
export function TrendLine({ points, width = 176, height = 56, accent = "var(--brand)", run = true, format = String, label }: {
  points: { label: string; value: number | null }[];
  width?: number;
  height?: number;
  accent?: string;
  run?: boolean;
  format?: (v: number) => string;
  label?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const pts = points.map((p, i) => [i, p.value] as const).filter((p): p is readonly [number, number] => p[1] !== null);
  if (pts.length < 2) return <div className="trend" style={{ width, height }} aria-hidden />;
  const lo = Math.min(...pts.map((p) => p[1]));
  const hi = Math.max(...pts.map((p) => p[1]));
  const padX = 5;
  const padY = 7;
  const x = (i: number) => padX + (i / Math.max(1, points.length - 1)) * (width - padX * 2);
  const y = (v: number) => (hi === lo ? height / 2 : padY + (1 - (v - lo) / (hi - lo)) * (height - padY * 2));
  const d = pts.map(([i, v], k) => `${k ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const [li, lv] = pts[pts.length - 1];
  const onMove = (e: MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const k = Math.round(((e.clientX - r.left - padX) / (width - padX * 2)) * (points.length - 1));
    const idx = Math.max(0, Math.min(points.length - 1, k));
    setHover(points[idx].value === null ? null : idx);
  };
  const hv = hover !== null ? points[hover].value : null;
  return (
    <div className="trend" style={{ width, height }} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
      <svg width={width} height={height} role="img" aria-label={label}>
        <path className={`trend__line${run ? " is-drawn" : ""}`} d={d} pathLength={1} />
        {hover !== null && hv !== null && (
          <>
            <line className="trend__guide" x1={x(hover)} x2={x(hover)} y1={2} y2={height - 2} />
            <circle cx={x(hover)} cy={y(hv)} r={4} fill="var(--surface)" stroke="var(--text-2)" strokeWidth={2} />
          </>
        )}
        <circle className={`trend__end${run ? " is-in" : ""}`} cx={x(li)} cy={y(lv)} r={4.5} fill={accent}
          stroke="var(--surface)" strokeWidth={2} />
      </svg>
      {hover !== null && hv !== null && (
        <div className="trend__tip" style={{ left: x(hover) }}>
          <span>{points[hover].label}</span>
          <b>{format(hv)}</b>
        </div>
      )}
    </div>
  );
}

export type PieSlice = { key: string; value: number; color: string };

/**
 * Gráfico de torta animado: aparece con un barrido en sentido horario desde las 12; las porciones se separan con un
 * filo del color de la superficie y, al cambiar los datos, se reacomodan suavemente. Al pasar el cursor, la porción
 * se adelanta un poco y el resto se atenúa.
 */
export function PieChart({ slices, size = 128, run = true, active, onHover, label, renderTip }: {
  slices: PieSlice[];
  size?: number;
  run?: boolean;
  active?: string | null;
  onHover?: (key: string | null) => void;
  label?: string;
  renderTip?: (key: string) => ReactNode;
}) {
  const maskId = `pie-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const vals = useTweenMap(new Map(slices.map((s) => [s.key, s.value])));
  const c = size / 2;
  const r = c - 5; // margen para que la porción activa pueda adelantarse
  const total = slices.reduce((a, s) => a + (vals.get(s.key) ?? 0), 0);
  let a0 = -Math.PI / 2;
  const geo = slices.map((s) => {
    const a = total > 0 ? ((vals.get(s.key) ?? 0) / total) * Math.PI * 2 : 0;
    const g = { ...s, a0, a1: a0 + a, mid: a0 + a / 2, a };
    a0 += a;
    return g;
  });
  const pt = (ang: number, rad: number) => [c + Math.cos(ang) * rad, c + Math.sin(ang) * rad] as const;
  const path = (g: (typeof geo)[number]) => {
    const [x0, y0] = pt(g.a0, r);
    const [x1, y1] = pt(g.a1, r);
    return `M${c},${c} L${x0.toFixed(2)},${y0.toFixed(2)} A${r},${r} 0 ${g.a > Math.PI ? 1 : 0} 1 ${x1.toFixed(2)},${y1.toFixed(2)} Z`;
  };
  const tip = active ? geo.find((g) => g.key === active) : null;
  // Detalle sobre la porción; nunca más a la izquierda que el borde de la torta (no se sale de la card)
  const [tx, ty] = tip ? pt(tip.mid, r * 0.62) : [0, 0];
  return (
    <div className="pie" style={{ width: size, height: size }} onMouseLeave={() => onHover?.(null)}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label}>
        <defs>
          <mask id={maskId}>
            <circle className={`pie__sweep${run ? " is-in" : ""}`} cx={c} cy={c} r={c / 2} fill="none" stroke="#fff"
              strokeWidth={c} pathLength={1} transform={`rotate(-90 ${c} ${c})`} />
          </mask>
        </defs>
        <g mask={`url(#${maskId})`}>
          {geo.filter((g) => g.a > 0.0005).map((g) => {
            const on = active === g.key;
            const [dx, dy] = on ? pt(g.mid, 4).map((v) => v - c) : [0, 0];
            const common = {
              fill: g.color, className: `pie__slice${active && !on ? " is-dim" : ""}`,
              style: { transform: `translate(${dx}px, ${dy}px)` }, onMouseEnter: () => onHover?.(g.key),
            };
            return g.a >= Math.PI * 2 - 0.0005
              ? <circle key={g.key} cx={c} cy={c} r={r} {...common} />
              : <path key={g.key} d={path(g)} {...common} />;
          })}
        </g>
      </svg>
      {tip && renderTip && (
        <div className="pie__tip" style={{ left: Math.max(tx, 64), top: ty }}>{renderTip(tip.key)}</div>
      )}
    </div>
  );
}

/** Tendencia compacta: trazo en tono de baja jerarquía; el último punto en el acento de la marca. */
export function Sparkline({ values, width = 96, height = 28, color = "var(--text-4)", accent = "var(--brand)" }: {
  values: (number | null)[];
  width?: number;
  height?: number;
  color?: string;
  accent?: string;
}) {
  const pts = values.map((v, i) => [i, v] as const).filter((p): p is readonly [number, number] => p[1] !== null);
  if (pts.length < 2) return <svg width={width} height={height} aria-hidden />;
  const lo = Math.min(...pts.map((p) => p[1]));
  const hi = Math.max(...pts.map((p) => p[1]));
  const pad = 3;
  const x = (i: number) => pad + (i / Math.max(1, values.length - 1)) * (width - pad * 2);
  const y = (v: number) => (hi === lo ? height / 2 : pad + (1 - (v - lo) / (hi - lo)) * (height - pad * 2));
  const d = pts.map(([i, v], k) => `${k ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const [li, lv] = pts[pts.length - 1];
  return (
    <svg width={width} height={height} aria-hidden>
      <path d={d} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(li)} cy={y(lv)} r={2.75} fill={accent} stroke="var(--surface)" strokeWidth={1.5} />
    </svg>
  );
}
