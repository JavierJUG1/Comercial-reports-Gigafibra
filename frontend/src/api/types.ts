export type DeltaKind = "up" | "down" | "flat" | "new" | "no_data";
export interface Delta {
  abs: number | null;
  pct: number | null;
  kind: DeltaKind;
}

export interface User {
  email: string;
  name: string;
  initials: string;
  roles: string[];
  source: string;
}

export interface Corte {
  id: string;
  fecha_corte: string;
  disparo: "schedule" | "catch_up" | "retry" | "cli" | "desarrollo" | "inicial";
  periodo?: string;
  libro?: number;
  observacion?: string;
  excel?: string;
  usuario: string;
  inicio: string;
  fin?: string;
  estado: "en_curso" | "exitosa" | "fallida" | "omitida";
  encabezado: string;
  hoja: string;
  paso?: string;
  duracion_ms?: number;
  filas?: number;
  suscripciones?: number;
  total?: number;
  snapshot?: string;
  filas_por_estado?: Record<string, number>;
  reemplazo?: boolean;
  mensaje?: string;
  detalle?: string;
}

export interface Meta {
  app: { name: string; env_label: string; timezone: string };
  user: User;
  erp: { configured: boolean };
  origen: string;
  estados: string[];
  programacion: { activa: boolean; proxima: string | null; regla: string; desde: string };
  excel: { existe: boolean; nombre: string };
  en_curso: Corte | null;
  ultima: Corte | null;
}

export interface Columna {
  id: string;
  libro: number;
  encabezado: string;
  periodo: string;
  anio: number;
  mes: number;
  fecha: string;
  dia_estimado: boolean;
  etiqueta: string;
  hoja: string | null;
  tipo: "valor" | "formula";
  automatico: boolean;
  snapshot: string | null;
  /** Origen del corte (cortes de la plataforma) y nota, p. ej. el corte inicial de octubre 2026 */
  disparo?: string | null;
  observacion?: string | null;
}

export interface PlanFila {
  plan: string;
  clasificacion: string | null;
  segmento: string | null;
  descripcion: string | null;
  costo: number | null;
  valores: (number | null)[];
}

export interface Libro {
  anio: number;
  descarga: string;
  hoja: string;
  actualizado: string;
}

export interface Reporte {
  actualizado: string;
  tabla: string;
  libros: Libro[];
  anios: number[];
  estados: string[];
  columnas: Columna[];
  planes: PlanFila[];
  totales: number[];
}
