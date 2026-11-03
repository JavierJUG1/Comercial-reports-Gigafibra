// Cliente HTTP: misma origen que el backend (cookie de sesión HttpOnly). Nunca maneja credenciales de ERPNext.
export const BASE = (import.meta.env.BASE_URL || "/").replace(/\/+$/, "");

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type Params = Record<string, string | number | boolean | null | undefined | string[]>;

export function qs(params: Params = {}): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === "" || (Array.isArray(v) && v.length === 0)) continue;
    sp.set(k, Array.isArray(v) ? v.join("|") : String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    credentials: "same-origin",
    ...init,
    headers: { Accept: "application/json", ...(init.body ? { "Content-Type": "application/json" } : {}), ...init.headers },
  });
  if (!resp.ok) {
    let msg = resp.statusText || "Error de comunicación";
    try {
      const data = await resp.json();
      if (typeof data?.detail === "string") msg = data.detail;
    } catch {
      /* respuesta sin JSON */
    }
    if (resp.status === 401 && !path.startsWith("/api/auth")) {
      window.dispatchEvent(new CustomEvent("tva:unauthorized"));
    }
    throw new ApiError(resp.status, msg);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

/** Descarga de un Excel del backend (mismos filtros que la pantalla). */
export async function download(path: string, params: Params): Promise<string> {
  const resp = await fetch(`${BASE}${path}${qs(params)}`, { credentials: "same-origin" });
  if (!resp.ok) {
    let msg = "No fue posible generar el archivo.";
    try {
      msg = (await resp.json()).detail || msg;
    } catch {
      /* sin detalle */
    }
    throw new ApiError(resp.status, msg);
  }
  const blob = await resp.blob();
  const cd = resp.headers.get("content-disposition") || "";
  // RFC 5987 (filename*=utf-8''…) para nombres con espacios o tildes; si no, filename="…".
  const encoded = /filename\*=(?:utf-8|UTF-8)''([^;]+)/.exec(cd)?.[1];
  const name = (encoded && decodeURIComponent(encoded)) || /filename="?([^";]+)"?/.exec(cd)?.[1] || "descarga";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
  return name;
}
