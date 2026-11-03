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
