"""Cards comerciales por corte: leads convertidos e ingresos por plan de TV (ERPNext API, solo lectura).

Peticiones de Postman en config/consultas_comerciales.json (colección "ERPNext API"):
- Leads: estado Converted (instalados y aprobados) con fecha de activación dentro del mes del corte.
- Ingresos: pagos recibidos del mes (Payment Entry, posting_date en el mes) aplicados a facturas con líneas de TV
  ("Canais de TV", el ítem de los planes del reporte). De cada pago se toma la parte de TV:
      ingreso = valor neto de la línea de TV × (valor aplicado a la factura / total de la factura)
  El plan de cada línea sale del corte del mes (snapshot o hoja cruda del Excel), o del corte posterior más cercano,
  o de los planes actuales de la suscripción, o de su historial (Version: plan quitado después de la factura).

Cada mes se guarda en indicadores/AAAA-MM.json (resumen) y AAAA-MM-detalle.json (filas usadas, para auditar).
Un mes se recalcula hasta COMERCIAL_REFRESH_DAYS días después de cerrar (pagos registrados con fecha del mes);
después queda fijo.
"""
from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable

import openpyxl

from . import report
from .config import settings
from .erpnext import ERPNextError, get_client

log = logging.getLogger("tva.comercial")
_lock = threading.Lock()
_state: dict[str, Any] = {"en_curso": False, "error": None, "ultimo": None}
RETIRADO = "Plan de TV retirado de la suscripción"


@lru_cache(maxsize=1)
def consultas() -> dict[str, Any]:
    with open(settings.CONSULTAS_COMERCIALES_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def folder() -> Path:
    d = report.report_dir() / "indicadores"
    d.mkdir(parents=True, exist_ok=True)
    return d


def state() -> dict[str, Any]:
    return dict(_state)


# ---------------------------------------------------------------------------- calendario
def bounds(periodo: str) -> dict[str, date]:
    """Primer y último día del mes, primer día del siguiente y primer día de la ventana de facturas."""
    y, m = int(periodo[:4]), int(periodo[5:7])
    desde = date(y, m, 1)
    hasta = report.month_end(desde)
    k = y * 12 + (m - 1) - int(consultas().get("meses_facturas", 12))
    return {"desde": desde, "hasta": hasta, "hasta_excl": hasta + timedelta(days=1),
            "facturas_desde": date(k // 12, k % 12 + 1, 1)}


def previous(periodo: str) -> str:
    y, m = int(periodo[:4]), int(periodo[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


HISTORY_MONTHS = 11  # meses previos al primer corte: la tendencia de 12 meses del primer corte queda completa


def periods_needed(cut_periods: Iterable[str]) -> list[str]:
    """Todos los meses desde 11 meses antes del primer corte hasta el último corte (variación y tendencia)."""
    cuts = sorted(set(cut_periods))
    if not cuts:
        return []
    out, p = [], cuts[0]
    for _ in range(HISTORY_MONTHS):
        p = previous(p)
    while p <= cuts[-1]:
        out.append(p)
        y, m = int(p[:4]), int(p[5:7])
        p = f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}"
    return out


def is_final(summary: dict[str, Any] | None) -> bool:
    """Definitivo: calculado al menos COMERCIAL_REFRESH_DAYS días después de cerrar el mes."""
    if not summary or not summary.get("calculado"):
        return False
    limit = bounds(summary["periodo"])["hasta_excl"] + timedelta(days=settings.COMERCIAL_REFRESH_DAYS)
    return datetime.fromisoformat(summary["calculado"]).date() >= limit


# ---------------------------------------------------------------------------- consultas
def _fill(value: Any, vals: dict[str, Any]) -> Any:
    """Reemplaza los marcadores {x}; un marcador solo (p. ej. "{planes_tv}") puede ser una lista."""
    if isinstance(value, str):
        if value.startswith("{") and value.endswith("}") and value[1:-1] in vals:
            return vals[value[1:-1]]
        for k, v in vals.items():
            if isinstance(v, str):
                value = value.replace("{" + k + "}", v)
        return value
    if isinstance(value, list):
        return [_fill(v, vals) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, vals) for k, v in value.items()}
    return value


def request(key: str, **vals: Any) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """(ruta, parámetros HTTP, parámetros legibles) de una petición de Postman con los marcadores reemplazados."""
    c = consultas()
    q = c["consultas"][key]
    filled = _fill(q["parametros"], {"item_tv": c["item_tv"], **vals})
    http = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v) for k, v in filled.items()}
    return q["ruta"], http, filled


def _rows(client: Any, key: str, **vals: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path, http, filled = request(key, **vals)
    data = client.get(path, http)
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ERPNextError("ERPNext devolvió un formato inesperado.", f"{key}: {str(data)[:300]}")
    q = consultas()["consultas"][key]
    return rows, {"nombre": q["nombre"], "peticion_id": q["peticion_id"], "metodo": "GET", "ruta": path,
                  "parametros": filled, "filas": len(rows)}


def _iso(d: date) -> str:
    return d.isoformat()


# ---------------------------------------------------------------------------- planes por suscripción
def live_plans(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Planes de TV actuales de cada suscripción, en el orden de su tabla de planes."""
    by: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for r in rows:
        if r.get("name") and r.get("plan"):
            by[r["name"]].append((int(r.get("plan_idx") or 0), r["plan"]))
    return {k: [p for _, p in sorted(v)] for k, v in by.items()}


def cut_plans(col: dict[str, Any] | None, tv: set[str]) -> dict[str, list[str]] | None:
    """Planes de TV de cada suscripción según el corte del mes: snapshot .json o hoja cruda del Excel."""
    if not col:
        return None
    pairs: Iterable[tuple[Any, Any]]
    wb = None
    try:
        if col.get("snapshot"):
            snap = report.report_dir() / "snapshots" / col["snapshot"]
            if not snap.is_file():
                return None
            rows = json.loads(snap.read_text(encoding="utf-8")).get("data") or []
            pairs = ((r.get("name"), r.get("plan")) for r in rows)
        elif col.get("hoja") and col.get("libro"):
            path = report.workbook_path(int(col["libro"]))
            if not path.is_file():
                return None
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            if col["hoja"] not in wb.sheetnames:
                return None
            pairs = ((row[1], row[11]) for row in wb[col["hoja"]].iter_rows(min_row=2, values_only=True)
                     if len(row) >= 12)
        else:
            return None
        out: dict[str, list[str]] = defaultdict(list)
        for sub, plan in pairs:
            if sub and plan in tv and plan not in out[sub]:
                out[str(sub)].append(plan)
        return dict(out)
    finally:
        if wb is not None:
            wb.close()


History = dict[str, list[tuple[str, int, str]]]  # suscripción → [(fecha en que se quitó, idx, plan de TV)]


def removed_plans(rows: list[dict[str, Any]], tv: set[str]) -> History:
    """Planes de TV quitados o reemplazados en cada suscripción, según su historial (Version). Solo se lee `plans`."""
    out: History = defaultdict(list)
    for r in rows:
        try:
            data = json.loads(r.get("data") or "{}")
        except ValueError:
            continue
        sub, when = r.get("docname"), str(r.get("creation") or "")[:10]
        if not sub or not when:
            continue
        for item in data.get("removed") or []:
            if len(item) == 2 and item[0] == "plans" and isinstance(item[1], dict) and item[1].get("plan") in tv:
                out[sub].append((when, int(item[1].get("idx") or 0), item[1]["plan"]))
        for item in data.get("row_changed") or []:
            if len(item) == 4 and item[0] == "plans":
                for change in item[3] or []:
                    if len(change) == 3 and change[0] == "plan" and change[1] in tv:
                        out[sub].append((when, int(item[1] or 0) + 1, change[1]))
    return dict(out)


def resolver(cut: dict[str, list[str]] | None, live: dict[str, list[str]],
             later: list[dict[str, list[str]]] | None = None,
             history: History | None = None,
             costos: dict[str, float] | None = None) -> Callable[[str | None, str | None], tuple[list[str], str]]:
    """Planes de TV de una suscripción para una factura del mes, en este orden:
    1. los del corte del mes (snapshot u hoja cruda del Excel);
    2. los del corte posterior más cercano (meses sin hoja cruda);
    3. los actuales en ERPNext;
    4. los que tenía al facturar según su historial (planes quitados en o después de la fecha de la factura);
    5. si nada de lo anterior, "retirado".
    Si 1–3 solo dan planes gratis ($ 0, p. ej. "Giga Fibra TV - Free") y el historial muestra un plan pagado que se
    quitó después de la factura, ese plan pagado también estaba al facturar y se agrega ("…+historial").
    Con varios planes de TV se respeta el orden de la tabla de planes de la suscripción (orden de la factura)."""
    cost = costos or {}

    def ordered(s: list[str], lv: list[str]) -> list[str]:
        return s if len(s) == 1 else [p for p in lv if p in s] + [p for p in s if p not in lv]

    def at_invoice(key: str, fecha: str | None) -> list[str]:
        h = (history or {}).get(key) or []
        d = str(fecha or "")[:10]
        return list(dict.fromkeys(p for _, p in sorted((idx, plan) for when, idx, plan in h if when >= d)))

    def with_paid(plans: list[str], src: str, key: str, fecha: str | None) -> tuple[list[str], str]:
        if costos and plans and all(not cost.get(p) for p in plans):
            paid = [p for p in at_invoice(key, fecha) if cost.get(p) and p not in plans]
            if paid:
                return paid + plans, f"{src}+historial"
        return plans, src

    def f(sub: str | None, fecha: str | None = None) -> tuple[list[str], str]:
        key = sub or ""
        lv = live.get(key, [])
        s = (cut or {}).get(key)
        if s:
            return with_paid(ordered(s, lv), "corte", key, fecha)
        for c in later or []:
            if c.get(key):
                return with_paid(ordered(c[key], lv), "corte_posterior", key, fecha)
        if lv:
            return with_paid(lv, "suscripcion", key, fecha)
        h = (history or {}).get(key)
        if h:
            return at_invoice(key, fecha) or [max(h)[2]], "historial"
        return [], "retirado"
    return f


# ---------------------------------------------------------------------------- cálculo
def compute_leads(rows: list[dict[str, Any]], tv: set[str]) -> dict[str, Any]:
    leads: dict[str, dict[str, Any]] = {}
    for r in rows:
        n = r.get("name")
        if not n:
            continue
        d = leads.setdefault(n, {"lead": n, "activacion": r.get("custom_activation_date"),
                                 "suscripcion": r.get("custom_subscription"), "planes": []})
        if r.get("plan") and r["plan"] not in d["planes"]:
            d["planes"].append(r["plan"])
    por_plan: dict[str, int] = defaultdict(int)
    combos: dict[tuple[str, ...], int] = defaultdict(int)
    con_tv = 0
    for d in leads.values():
        tv_plans = [p for p in d["planes"] if p in tv]
        d["con_tv"] = bool(tv_plans)
        con_tv += bool(tv_plans)
        for p in tv_plans:
            por_plan[p] += 1
        if tv_plans:
            combos[tuple(sorted(tv_plans))] += 1
    # Combinaciones de planes de TV por lead: el filtro de planes del portal cuenta cada lead una sola vez
    return {"convertidos": len(leads), "con_tv": con_tv,
            "por_plan_tv": dict(sorted(por_plan.items(), key=lambda x: (-x[1], x[0]))),
            "combinaciones_tv": [{"planes": list(k), "leads": v} for k, v in sorted(combos.items(), key=lambda x: -x[1])],
            "detalle": list(leads.values())}


def pair_lines(lines: list[tuple[int, float]], plans: list[str],
               costos: dict[str, float] | None = None) -> list[tuple[float, str | None]]:
    """Plan de cada línea de TV de una factura.

    Un plan: todas sus líneas. Varios planes de TV en la suscripción (p. ej. "TV + 1 SetBox" y "TV - Free"): la línea
    de mayor valor va al plan de mayor costo sin IVA (Excel), la siguiente al siguiente, y las de $ 0 a los planes
    gratis; a igual valor o costo se respeta el orden de la factura y de la tabla de planes. Sin plan: None."""
    by_idx = sorted(lines)
    if not plans:
        return [(net, None) for _, net in by_idx]
    if len(plans) == 1:
        return [(net, plans[0]) for _, net in by_idx]
    cost = costos or {}
    if len({float(cost.get(p) or 0) for p in plans}) == 1:  # mismo costo: k-ésima línea → k-ésimo plan
        return [(net, plans[min(k, len(plans) - 1)]) for k, (_, net) in enumerate(by_idx)]
    plans_desc = sorted(enumerate(plans), key=lambda x: (-float(cost.get(x[1]) or 0), x[0]))
    lines_desc = sorted(enumerate(by_idx), key=lambda x: (-abs(x[1][1]), x[0]))
    out: list[tuple[float, str | None]] = []
    for k, (_, (_, net)) in enumerate(lines_desc):
        out.append((net, plans_desc[min(k, len(plans_desc) - 1)][1]))
    return out


def compute_ingresos(pagos: list[dict[str, Any]], lineas: list[dict[str, Any]],
                     plan_de: Callable[[str | None, str | None], tuple[list[str], str]], tv: list[str],
                     costos: dict[str, float] | None = None) -> dict[str, Any]:
    """Recaudo efectivo del mes por plan de TV (sin IVA): solo los pagos de `pagos` (los del mes), sin acumular."""
    inv: dict[str, dict[str, Any]] = {}
    for r in lineas:
        i = inv.setdefault(r["name"], {"sub": r.get("custom_subscription"), "fecha": r.get("posting_date"), "lines": [],
                                       "base": float(r.get("rounded_total") or r.get("grand_total") or 0)})
        i["lines"].append((int(r.get("item_idx") or 0), float(r.get("net_amount") or 0)))
    por_plan = {p: 0.0 for p in tv}
    facturas_plan: dict[str, set] = defaultdict(set)
    origen: dict[str, int] = defaultdict(int)
    retirado, detalle, pagos_tv, facturas = 0.0, [], set(), set()
    for r in pagos:
        if r.get("reference_doctype") not in (None, "Sales Invoice"):
            continue
        i = inv.get(r.get("reference_name") or "")
        if not i or not i["base"]:
            continue
        asignado = float(r.get("allocated_amount") or 0)
        ratio = asignado / i["base"]
        plans, src = plan_de(i["sub"], i["fecha"])
        origen[src] += 1
        pagos_tv.add(r["name"])
        facturas.add(r["reference_name"])
        for net, plan in pair_lines(i["lines"], plans, costos):
            v = net * ratio
            if v and costos and plan in costos and not costos[plan]:
                plan = None  # un plan gratis no recauda: la línea con valor queda como "no identificado"
            if plan in por_plan:
                por_plan[plan] += v
                if v:
                    facturas_plan[plan].add(r["reference_name"])
            else:
                retirado += v
            detalle.append({"pago": r["name"], "fecha": r.get("posting_date"), "factura": r["reference_name"],
                            "suscripcion": i["sub"], "valor_aplicado": asignado, "total_factura": i["base"],
                            "linea_tv": net, "plan": plan or RETIRADO, "plan_segun": src, "ingreso": round(v, 2)})
    total = sum(por_plan.values()) + retirado
    return {
        "total": round(total, 2), "pagos": len(pagos_tv), "facturas": len(facturas),
        "por_plan": {p: {"ingreso": round(v, 2), "facturas": len(facturas_plan.get(p, ()))}
                     for p, v in sorted(por_plan.items(), key=lambda x: -x[1])},
        "retirado": round(retirado, 2), "plan_segun": dict(origen), "detalle": detalle,
    }


def _summary(data: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in data.items() if k not in ("leads", "ingresos", "consultas")}
    out["leads"] = {k: v for k, v in data["leads"].items() if k != "detalle"}
    out["ingresos"] = {k: v for k, v in data["ingresos"].items() if k != "detalle"}
    return out


def _source(col: dict[str, Any]) -> dict[str, Any]:
    return {"periodo": col["periodo"], "encabezado": col.get("encabezado"),
            "fuente": "snapshot" if col.get("snapshot") else "hoja", "archivo": col.get("snapshot") or col.get("hoja")}


def compute_period(periodo: str, client: Any, *, tv: list[str], live: dict[str, list[str]],
                   lineas: list[dict[str, Any]], lineas_q: dict[str, Any], subs_q: dict[str, Any],
                   cuts: dict[str, tuple[dict[str, Any], dict[str, list[str]]]],
                   history: History | None = None, history_q: dict[str, Any] | None = None,
                   costos: dict[str, float] | None = None, lineas_hasta: date | None = None) -> dict[str, Any]:
    """`cuts` = {periodo: (columna, planes por suscripción)} de los cortes con datos crudos (snapshot u hoja);
    `costos` = costo sin IVA de cada plan (Excel), para repartir las líneas cuando hay varios planes de TV."""
    b = bounds(periodo)
    tvset = set(tv)
    leads_rows, leads_q = _rows(client, "leads", desde=_iso(b["desde"]), hasta_excl=_iso(b["hasta_excl"]))
    pagos_rows, pagos_q = _rows(client, "pagos", desde=_iso(b["desde"]), hasta=_iso(b["hasta"]))
    # Facturas desde 12 meses antes del mes y sin tope: un pago del mes a una factura emitida después (pago anticipado)
    # es dinero que entró en el mes y cuenta en el mes
    window = [r for r in lineas if _iso(b["facturas_desde"]) <= str(r.get("posting_date") or "")[:10]]
    own = cuts.get(periodo)
    later = [cuts[p] for p in sorted(cuts) if p > periodo]
    q_lineas = {**lineas_q, "parametros": _fill(consultas()["consultas"]["facturas_tv"]["parametros"],
                                                 {"item_tv": consultas()["item_tv"], "facturas_desde": _iso(b["facturas_desde"]),
                                                  "hasta": _iso(lineas_hasta or b["hasta"])}), "filas": len(window)}
    data = {
        "periodo": periodo, "desde": _iso(b["desde"]), "hasta": _iso(b["hasta"]),
        "calculado": report.now().isoformat(), "origen": "ERPNext API Gigafibra",
        "planes_segun": {"corte": _source(own[0]) if own else None,
                         "cortes_posteriores": [_source(c) for c, _ in later]},
        "consultas": {"leads": leads_q, "pagos": pagos_q, "facturas_tv": q_lineas, "suscripciones_tv": subs_q,
                      **({"historial_planes": history_q} if history_q else {})},
        "leads": compute_leads(leads_rows, tvset),
        "ingresos": compute_ingresos(pagos_rows, window,
                                     resolver(own[1] if own else None, live, [m for _, m in later], history, costos),
                                     tv, costos),
    }
    data["definitivo"] = is_final(data)
    return data


def fetch_history(client: Any, lineas: list[dict[str, Any]], live: dict[str, list[str]],
                  cuts: dict[str, tuple[dict[str, Any], dict[str, list[str]]]],
                  tv: set[str], costos: dict[str, float] | None = None) -> tuple[History, dict[str, Any] | None]:
    """Historial de planes de las suscripciones facturadas con TV que hoy ya no tienen TV, o que en algún corte o hoy
    solo tienen planes gratis (su plan pagado pudo quitarse después de la factura). Las demás se resuelven con el corte
    o con sus planes actuales."""
    cost = costos or {}
    billed = {r["custom_subscription"] for r in lineas if r.get("custom_subscription")}
    only_free = set()
    if costos:
        for source in [live, *(m for _, m in cuts.values())]:
            only_free.update(s for s, plans in source.items() if s in billed and plans and not any(cost.get(p) for p in plans))
    subs = sorted((billed - set(live)) | only_free)
    if not subs:
        return {}, None
    size = int(consultas()["consultas"]["historial_planes"].get("lote", 100))
    rows: list[dict[str, Any]] = []
    q: dict[str, Any] | None = None
    for k in range(0, len(subs), size):
        part, q = _rows(client, "historial_planes", suscripciones=subs[k:k + size])
        rows.extend(part)
    assert q is not None
    q = {**q, "parametros": _fill(consultas()["consultas"]["historial_planes"]["parametros"],
                                  {"suscripciones": [f"{len(subs)} suscripciones en lotes de {size}"]}),
         "filas": len(rows), "suscripciones": len(subs)}
    return removed_plans(rows, tv), q


def _save(data: dict[str, Any]) -> None:
    d = folder()
    report._save_json(d / f"{data['periodo']}-detalle.json", data, indent=None)
    report._save_json(d / f"{data['periodo']}.json", _summary(data))


def load(periodo: str) -> dict[str, Any] | None:
    p = folder() / f"{periodo}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def summaries() -> dict[str, dict[str, Any]]:
    out = {}
    for p in sorted(folder().glob("????-??.json")):
        try:
            out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("Indicador ilegible: %s", p.name)
    return out


def detail_path(periodo: str) -> Path | None:
    p = folder() / f"{periodo}-detalle.json"
    return p if p.is_file() else None


def ensure(periods: list[str] | None = None, force: bool = False, client_factory: Callable | None = None) -> dict[str, Any]:
    """Calcula los meses que faltan o que aún no son definitivos. Devuelve {calculados, omitidos, error}."""
    if not _lock.acquire(blocking=False):
        return {"calculados": [], "omitidos": [], "error": "Ya hay un cálculo en curso."}
    _state.update(en_curso=True, error=None)
    done: list[str] = []
    try:
        summ = report.summary()
        cols = {c["periodo"]: c for c in summ["columnas"]}
        tv = [p["plan"] for p in summ["planes"]]
        costos = {p["plan"]: float(p.get("costo") or 0) for p in summ["planes"]}
        wanted = periods or periods_needed(cols)
        todo = [p for p in wanted if force or not is_final(load(p))]
        if not todo:
            return {"calculados": [], "omitidos": wanted, "error": None}
        with (client_factory or get_client)() as client:
            subs_rows, subs_q = _rows(client, "suscripciones_tv", planes_tv=tv)
            live = live_plans(subs_rows)
            lo = min(bounds(p)["facturas_desde"] for p in todo)
            hi = max(max(bounds(p)["hasta"] for p in todo), report.now().date())  # hasta hoy: pagos anticipados
            lineas, lineas_q = _rows(client, "facturas_tv", facturas_desde=_iso(lo), hasta=_iso(hi))
            # Planes por suscripción de los cortes con datos crudos, desde el primer mes a calcular
            cuts = {}
            for p, col in cols.items():
                if p >= min(todo) and (col.get("snapshot") or col.get("hoja")):
                    m = cut_plans(col, set(tv))
                    if m is not None:
                        cuts[p] = (col, m)
            history, history_q = fetch_history(client, lineas, live, cuts, set(tv), costos)
            for p in todo:
                data = compute_period(p, client, tv=tv, live=live, lineas=lineas, lineas_q=lineas_q,
                                      subs_q=subs_q, cuts=cuts, history=history, history_q=history_q, costos=costos,
                                      lineas_hasta=hi)
                _save(data)
                done.append(p)
                log.info("Indicadores %s: %s leads convertidos, ingresos TV %.0f", p, data["leads"]["convertidos"],
                         data["ingresos"]["total"])
        return {"calculados": done, "omitidos": [p for p in wanted if p not in todo], "error": None}
    except (ERPNextError, report.ReportError) as exc:
        msg = getattr(exc, "user_message", None) or getattr(exc, "message", str(exc))
        log.warning("Indicadores comerciales: %s (%s)", msg, getattr(exc, "detail", ""))
        _state["error"] = msg
        return {"calculados": done, "omitidos": [], "error": msg}
    finally:
        _state.update(en_curso=False, ultimo=report.now().isoformat())
        _lock.release()


def ensure_background() -> None:
    """Para el programador y el arranque: no bloquea y no falla si ERPNext no está configurado."""
    if not settings.erp_configured or not report.has_workbook():
        return
    threading.Thread(target=ensure, name="indicadores-comerciales", daemon=True).start()
