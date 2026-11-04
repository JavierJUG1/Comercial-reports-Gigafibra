"""Excel de cada card del portal, para confirmar sus cifras (solo lectura, se arma al descargar).

- segmentos / lider: suscripciones del corte por segmento y por plan (Active + Past Due Date, como la tabla), todos los
  cortes por segmento y, si el mes tiene detalle (snapshot o hoja cruda del Excel), cada suscripción que cuenta. Los
  meses sin detalle (dic 2025 – jul 2026) solo tienen las cantidades confirmadas de la tabla del Excel inicial del
  proyecto, y el libro lo dice.
- recaudo: recaudo efectivo del mes por plan de TV, cada pago con su parte de TV y el total de cada mes.
- leads: leads TV (instalados) por plan, cada lead y el total de cada mes; con el mismo filtro de planes de la card.
"""
from __future__ import annotations

import io
import json
from collections import Counter
from typing import Any, Iterable

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import comercial, report
from .config import settings

TARJETAS = {
    "segmentos": "Suscripciones por segmento",
    "lider": "Segmento con más suscripciones",
    "recaudo": "Recaudo por plan de TV",
    "leads": "Leads TV (instalados)",
}
PESOS = '"$" #,##0'
PESOS_2 = '"$" #,##0.00'
ENTERO = "#,##0"
PORCENTAJE = "0.0%"
_HEAD_FILL = PatternFill("solid", fgColor="FF6900")
_HEAD_FONT = Font(bold=True, color="FFFFFF")
_TOTAL_FONT = Font(bold=True)


class DownloadError(Exception):
    def __init__(self, message: str, status: int = 404):
        super().__init__(message)
        self.message = message
        self.status = status


def mes_largo(periodo: str) -> str:
    y, m = int(periodo[:4]), int(periodo[5:7])
    return f"{report.MESES_LARGOS[m - 1].capitalize()} {y}"


def file_name(tarjeta: str, periodo: str, filtrado: bool = False) -> str:
    return f"{TARJETAS[tarjeta].replace('(', '').replace(')', '')} {periodo}{' (filtrado)' if filtrado else ''}.xlsx"


# ---------------------------------------------------------------------------- escritura
def _intro(ws, title: str, lines: Iterable[str]) -> int:
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=14)
    r = 2
    for line in lines:
        ws.cell(row=r, column=1, value=line).alignment = Alignment(wrap_text=False)
        r += 1
    return r + 1  # una fila en blanco antes de la tabla


def _table(ws, start: int, header: list[str], rows: list[list[Any]], formats: dict[int, str] | None = None,
           total: list[Any] | None = None, widths: list[int] | None = None, filters: bool = True) -> int:
    for j, h in enumerate(header, start=1):
        c = ws.cell(row=start, column=j, value=h)
        c.fill, c.font = _HEAD_FILL, _HEAD_FONT
    r = start
    for row in rows:
        r += 1
        for j, v in enumerate(row, start=1):
            c = ws.cell(row=r, column=j, value=v)
            if formats and j in formats and isinstance(v, (int, float)):
                c.number_format = formats[j]
    if total is not None:
        r += 1
        for j, v in enumerate(total, start=1):
            c = ws.cell(row=r, column=j, value=v)
            c.font = _TOTAL_FONT
            if formats and j in formats and isinstance(v, (int, float)):
                c.number_format = formats[j]
    if filters and rows:
        ws.auto_filter.ref = f"A{start}:{get_column_letter(len(header))}{start + len(rows)}"
    for j, w in enumerate(widths or [], start=1):
        ws.column_dimensions[get_column_letter(j)].width = w
    return r + 2


def _sheet(wb, title: str, header: list[str], rows: list[list[Any]], formats: dict[int, str] | None = None,
           widths: list[int] | None = None, note: str | None = None) -> None:
    ws = wb.create_sheet(title)
    start = 1
    if note:
        ws["A1"] = note
        ws["A1"].font = Font(italic=True, color="6B6B73")
        start = 3
    _table(ws, start, header, rows, formats, widths=widths)
    ws.freeze_panes = ws.cell(row=start + 1, column=1)


def _bytes(wb) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------- suscripciones (segmentos y líder)
def _column(periodo: str) -> tuple[dict[str, Any], int, dict[str, Any]]:
    summ = report.summary()
    for i, c in enumerate(summ["columnas"]):
        if c["periodo"] == periodo:
            return c, i, summ
    raise DownloadError("Ese mes no tiene corte en el reporte.")


def origen_corte(col: dict[str, Any]) -> tuple[str, bool]:
    """(texto del origen, tiene detalle por suscripción)."""
    enc = col.get("encabezado")
    if col.get("snapshot"):
        return (f"Corte automático de la plataforma (columna '{enc}' del Excel), consulta a ERPNext guardada en "
                f"{col['snapshot']}. Detalle en la hoja 'Suscripciones del corte'."), True
    if col.get("hoja"):
        return (f"Excel del proyecto, columna '{enc}' (COUNTIFS sobre la hoja '{col['hoja']}'). Detalle en la hoja "
                "'Suscripciones del corte'."), True
    return (f"Cantidades confirmadas de la tabla del Excel inicial del proyecto (columna '{enc}'). Ese mes no tiene "
            "detalle por suscripción en el Excel: las cifras son las que se entregaron en esa tabla."), False


def _cut_rows(col: dict[str, Any], plans: set[str]) -> list[tuple[str, str, str]] | None:
    """Suscripciones que cuentan en el corte (estado Active o Past Due Date y plan de la tabla): (ID, estado, plan)."""
    wanted = set(settings.COUNT_STATUSES)
    if col.get("snapshot"):
        path = report.report_dir() / "snapshots" / col["snapshot"]
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8")).get("data") or []
        rows = ((r.get("name"), r.get("status"), r.get("plan")) for r in data)
    elif col.get("hoja"):
        path = report.workbook_path(int(col["libro"]))
        if not path.is_file():
            return None
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            if col["hoja"] not in wb.sheetnames:
                return None
            rows = [(r[1], r[3], r[11]) for r in wb[col["hoja"]].iter_rows(min_row=2, values_only=True) if len(r) >= 12]
        finally:
            wb.close()
    else:
        return None
    return [(str(s), st, p) for s, st, p in rows if s and st in wanted and p in plans]


def suscripciones_xlsx(tarjeta: str, periodo: str) -> bytes:
    col, i, summ = _column(periodo)
    prev = summ["columnas"][i - 1] if i > 0 else None
    planes = summ["planes"]
    seg_of = {p["plan"]: p["segmento"] or "Sin segmento" for p in planes}
    segs = list(dict.fromkeys(seg_of.values()))
    cur = Counter({s: 0 for s in segs})
    old = Counter({s: 0 for s in segs})
    for p in planes:
        cur[seg_of[p["plan"]]] += p["valores"][i] or 0
        if prev:
            old[seg_of[p["plan"]]] += p["valores"][i - 1] or 0
    total = sum(cur.values())
    ranked = sorted(segs, key=lambda s: (-cur[s], s))
    origen, con_detalle = origen_corte(col)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Resumen"
    lines = [f"Mes del corte: {mes_largo(periodo)} · columna '{col['encabezado']}'",
             f"Suscripciones en corte: estado {' + '.join(settings.COUNT_STATUSES)} por plan (igual que la tabla del portal).",
             f"Origen: {origen}"]
    if tarjeta == "lider" and total:
        lider = ranked[0]
        lines.append(f"Segmento con más suscripciones: {lider} con {cur[lider]:,} suscripciones "
                     f"({cur[lider] / total:.1%} del total).".replace(",", "."))
    if prev:
        lines.append(f"Corte anterior para comparar: {mes_largo(prev['periodo'])} (columna '{prev['encabezado']}').")
    r = _intro(ws, f"{TARJETAS[tarjeta]} — {mes_largo(periodo)}", lines)
    head = ["Segmento", "Suscripciones", "Participación"] + (["Corte anterior", "Variación"] if prev else [])
    rows = [[s, cur[s], (cur[s] / total if total else 0)] + ([old[s], cur[s] - old[s]] if prev else []) for s in ranked]
    tot = ["Total", total, 1 if total else 0] + ([sum(old.values()), total - sum(old.values())] if prev else [])
    _table(ws, r, head, rows, {2: ENTERO, 3: PORCENTAJE, 4: ENTERO, 5: '+#,##0;-#,##0;0'}, total=tot,
           widths=[34, 16, 14, 16, 12], filters=False)

    _sheet(wb, "Por plan", ["Plan", "Segmento", "Clasificación", "Suscripciones"] + (["Corte anterior", "Variación"] if prev else []),
           [[p["plan"], seg_of[p["plan"]], p.get("clasificacion"), p["valores"][i] or 0]
            + ([p["valores"][i - 1] or 0, (p["valores"][i] or 0) - (p["valores"][i - 1] or 0)] if prev else [])
            for p in planes],
           {4: ENTERO, 5: ENTERO, 6: '+#,##0;-#,##0;0'}, widths=[50, 16, 18, 15, 15, 12])

    cols = summ["columnas"]
    _sheet(wb, "Por corte", ["Segmento"] + [f"{c['etiqueta']} ({c['encabezado']})" for c in cols],
           [[s] + [sum(p["valores"][j] or 0 for p in planes if seg_of[p["plan"]] == s) for j in range(len(cols))] for s in segs]
           + [["Total"] + [sum(p["valores"][j] or 0 for p in planes) for j in range(len(cols))]],
           {j: ENTERO for j in range(2, len(cols) + 2)}, widths=[22] + [18] * len(cols),
           note="Suscripciones por segmento en cada corte del reporte (la tendencia de la card del segmento líder).")

    detail = _cut_rows(col, set(seg_of)) if con_detalle else None
    if detail is not None:
        _sheet(wb, "Suscripciones del corte", ["ID suscripción", "Estado", "Plan", "Segmento"],
               [[s, st, p, seg_of[p]] for s, st, p in sorted(detail, key=lambda x: (x[2], x[0]))],
               widths=[22, 16, 50, 16],
               note=f"{len(detail):,} filas = {total:,} suscripciones del corte (una fila por plan, como COUNTIFS).".replace(",", "."))
    else:
        ws2 = wb.create_sheet("Sin detalle")
        ws2["A1"] = (f"{mes_largo(periodo)}: cantidades confirmadas de la tabla del Excel inicial del proyecto "
                     f"(columna '{col['encabezado']}'). El Excel no trae el listado de suscripciones de ese mes.")
        ws2.column_dimensions["A"].width = 120
    return _bytes(wb)


# ---------------------------------------------------------------------------- recaudo
def _detail(periodo: str) -> dict[str, Any]:
    path = comercial.detail_path(periodo)
    if path is None:
        raise DownloadError("Aún no hay datos comerciales de ese mes.")
    return json.loads(path.read_text(encoding="utf-8"))


def _estado(s: dict[str, Any]) -> str:
    return "definitivo" if s.get("definitivo") else "provisional (se recalcula hasta 5 días después del cierre)"


def recaudo_xlsx(periodo: str) -> bytes:
    d = _detail(periodo)
    ing = d["ingresos"]
    seg_of = {p["plan"]: p["segmento"] or "Sin segmento" for p in report.summary()["planes"]}
    prev = comercial.load(comercial.previous(periodo))
    total = ing["total"]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Resumen"
    lines = [
        f"Recaudo efectivo del mes, sin IVA y sin acumular: pagos recibidos del {d['desde']} al {d['hasta']} (Payment Entry).",
        "De cada pago se toma la parte de TV: valor neto de la línea 'Canais de TV' × valor aplicado ÷ total de la factura.",
        f"Origen: ERPNext API Gigafibra · calculado el {d['calculado'][:16].replace('T', ' ')} · {_estado(d)}.",
        f"{ing['pagos']:,} pagos de {ing['facturas']:,} facturas con TV. El detalle de cada pago está en la hoja 'Pagos'.".replace(",", "."),
    ]
    if prev:
        lines.append(f"Mes anterior ({mes_largo(prev['periodo'])}): $ {prev['ingresos']['total']:,.0f}".replace(",", "."))
    r = _intro(ws, f"Recaudo por plan de TV — {mes_largo(periodo)}", lines)
    rows = [[p, seg_of.get(p, ""), v["ingreso"], v["facturas"], (v["ingreso"] / total if total else 0)]
            for p, v in ing["por_plan"].items()]
    if ing.get("retirado"):
        rows.append(["Plan no identificado", "", ing["retirado"], None, ing["retirado"] / total if total else 0])
    rows.sort(key=lambda x: -x[2])
    _table(ws, r, ["Plan", "Segmento", "Recaudo sin IVA", "Facturas", "Participación"], rows,
           {3: PESOS, 4: ENTERO, 5: PORCENTAJE}, total=["Total", "", total, ing["facturas"], 1 if total else 0],
           widths=[50, 16, 18, 12, 14], filters=False)

    _sheet(wb, "Pagos", ["Pago", "Fecha del pago", "Factura", "Suscripción", "Valor aplicado", "Total factura",
                         "Línea de TV sin IVA", "Plan", "Plan según", "Recaudo TV sin IVA"],
           [[x["pago"], x["fecha"], x["factura"], x["suscripcion"], x["valor_aplicado"], x["total_factura"],
             x["linea_tv"], x["plan"], x["plan_segun"], x["ingreso"]] for x in ing["detalle"]],
           {5: PESOS_2, 6: PESOS_2, 7: PESOS_2, 10: PESOS_2}, widths=[22, 14, 14, 20, 15, 15, 17, 48, 22, 18],
           note="Una fila por línea de TV de cada factura pagada en el mes. La suma de 'Recaudo TV sin IVA' es el total del mes.")

    _sheet(wb, "Recaudo por mes", ["Mes", "Recaudo sin IVA", "Facturas pagadas", "Estado"],
           [[mes_largo(p), s["ingresos"]["total"], s["ingresos"]["facturas"], _estado(s)]
            for p, s in comercial.summaries().items()],
           {2: PESOS, 3: ENTERO}, widths=[18, 18, 16, 56], note="Cada mes cuenta solo los pagos con fecha de ese mes.")
    return _bytes(wb)


# ---------------------------------------------------------------------------- leads TV
def _leads_tv(summary: dict[str, Any], planes: set[str] | None) -> int:
    leads = summary["leads"]
    if not planes:
        return leads["con_tv"]
    if "combinaciones_tv" in leads:
        return sum(c["leads"] for c in leads["combinaciones_tv"] if planes & set(c["planes"]))
    return sum(n for p, n in leads["por_plan_tv"].items() if p in planes)


def leads_xlsx(periodo: str, planes: list[str] | None = None) -> bytes:
    d = _detail(periodo)
    tv = {p["plan"] for p in report.summary()["planes"]}
    sel = {p for p in planes or [] if p in tv} or None
    leads = []
    for x in d["leads"]["detalle"]:
        tvp = [p for p in x.get("planes") or [] if p in tv]
        if tvp and (not sel or sel & set(tvp)):
            leads.append({**x, "tv": tvp})
    por_plan = Counter(p for x in leads for p in x["tv"] if not sel or p in sel)
    prev = comercial.load(comercial.previous(periodo))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Resumen"
    lines = [
        "Leads en estado Converted (instalados y aprobados) con un plan de TV, por fecha de activación "
        f"(custom_activation_date) del {d['desde']} al {d['hasta']}.",
        f"Planes: {', '.join(sorted(sel)) if sel else 'todos los planes de TV'}.",
        f"Origen: ERPNext API Gigafibra · calculado el {d['calculado'][:16].replace('T', ' ')} · {_estado(d)}.",
        f"Leads TV del mes: {len(leads):,} (cada lead cuenta una vez aunque tenga varios planes de TV).".replace(",", "."),
    ]
    if prev:
        lines.append(f"Mes anterior ({mes_largo(prev['periodo'])}): {_leads_tv(prev, sel):,} leads TV.".replace(",", "."))
    r = _intro(ws, f"Leads TV (instalados) — {mes_largo(periodo)}", lines)
    _table(ws, r, ["Plan de TV", "Leads"], [[p, n] for p, n in por_plan.most_common()], {2: ENTERO},
           total=["Leads TV (sin repetir)", len(leads)], widths=[50, 12], filters=False)

    _sheet(wb, "Leads TV", ["Lead", "Fecha de activación", "Suscripción", "Planes de TV"],
           [[x["lead"], x.get("activacion"), x.get("suscripcion"), " · ".join(x["tv"])]
            for x in sorted(leads, key=lambda x: str(x.get("activacion")))],
           widths=[24, 22, 22, 70], note="Un lead por fila, con sus planes de TV.")
    _sheet(wb, "Leads TV por mes", ["Mes", "Leads TV", "Estado"],
           [[mes_largo(p), _leads_tv(s, sel), _estado(s)] for p, s in comercial.summaries().items()],
           {2: ENTERO}, widths=[18, 12, 56])
    return _bytes(wb)


def build(tarjeta: str, periodo: str, planes: list[str] | None = None) -> tuple[bytes, str]:
    if tarjeta not in TARJETAS:
        raise DownloadError("Card desconocida.", 400)
    if tarjeta in ("segmentos", "lider"):
        return suscripciones_xlsx(tarjeta, periodo), file_name(tarjeta, periodo)
    if tarjeta == "recaudo":
        return recaudo_xlsx(periodo), file_name(tarjeta, periodo)
    return leads_xlsx(periodo, planes), file_name(tarjeta, periodo, filtrado=bool(planes))
