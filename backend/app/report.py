"""Reporte mensual de suscripciones de TV (automático, último día de cada mes desde REPORT_START).

Cada corte:
1. Ejecuta la consulta de suscripciones de ERPNext ("vista reporte": todas las suscripciones, una fila por plan,
   SIN filtro de estado).
2. Guarda la respuesta completa como snapshot .json + un resumen por estado y por plan para curaduría.
3. Agrega el mes al libro de su año sin reescribirlo (ver xlsx_append): hoja cruda nueva (p. ej. "30NOV2026") y
   columna nueva en la tabla (p. ej. "30-nov") con la misma fórmula del Excel:
   =COUNTIFS(hoja!L:L, plan, hoja!D:D, "Active") + COUNTIFS(hoja!L:L, plan, hoja!D:D, "Past Due Date")
   Las columnas y hojas existentes (datos confirmados) no se modifican.
   El primer corte de cada año crea el libro de ese año (mismos planes y tabla), que arranca en enero.
4. Recalcula la tabla del portal (resumen.json).
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import time
import zipfile
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

import openpyxl

from . import xlsx_append
from .config import settings
from .erpnext import ERPNextError, consulta, get_client

log = logging.getLogger("tva.report")

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
MESES_LARGOS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
                "noviembre", "diciembre"]
MONTH_TOKENS = {**{m: i + 1 for i, m in enumerate(MESES)}, "jan": 1, "apr": 4, "aug": 8, "set": 9, "dec": 12}
CREATION_FORMAT = "yyyy\\-mm\\-dd\\ h:mm:ss"
COST_FORMAT = '_-"$"\\ * #,##0.00_-;\\-"$"\\ * #,##0.00_-;_-"$"\\ * "-"??_-;_-@_-'
OBS_DESARROLLO = "Corte generado en el desarrollo de la aplicación"
_lock = threading.Lock()
_running: dict[str, Any] | None = None
_FORMULA_RE = re.compile(r"COUNTIFS\(\s*'?([^'!]+?)'?!\$L:\$L\s*,\s*\$A\d+\s*,\s*'?[^'!]+?'?!\$D:\$D\s*,\s*\"([^\"]+)\"\s*\)",
                         re.IGNORECASE)


class ReportError(Exception):
    def __init__(self, message: str, code: str = "error", detail: str = ""):
        super().__init__(message)
        self.message = message
        self.code = code
        self.detail = detail or message


# ---------------------------------------------------------------------------- rutas, libros y registro
def now() -> datetime:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(settings.TIMEZONE))


def report_dir() -> Path:
    d = settings.REPORT_DIR
    for sub in ("snapshots", "respaldos", "desarrollo"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def workbook_path(year: int) -> Path:
    return settings.REPORT_DIR / settings.EXCEL_FILE_PATTERN.format(anio=year)


def sheet_for(year: int) -> str:
    return settings.EXCEL_SHEET_PATTERN.format(anio=year)


def workbooks() -> list[tuple[int, Path]]:
    """Libros existentes por año, en orden."""
    rx = re.compile("^" + re.escape(settings.EXCEL_FILE_PATTERN).replace(re.escape("{anio}"), r"(\d{4})") + "$")
    out = []
    if settings.REPORT_DIR.exists():
        for p in settings.REPORT_DIR.iterdir():
            m = rx.match(p.name)
            if m and p.is_file():
                out.append((int(m.group(1)), p))
    return sorted(out)


def has_workbook() -> bool:
    return bool(workbooks())


def _registry_path() -> Path:
    return report_dir() / "cortes.json"


def registry() -> dict[str, dict[str, Any]]:
    """Cortes automáticos por periodo: {"AAAA-MM": {fecha, libro, encabezado, hoja, snapshot, respaldo, ...}}."""
    p = _registry_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save_json(path: Path, data: Any, indent: int | None = 1) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=indent, default=str), encoding="utf-8")
    os.replace(tmp, path)


def runs() -> list[dict[str, Any]]:
    p = report_dir() / "ejecuciones.jsonl"
    out = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []
    out.reverse()
    if _running:
        out.insert(0, dict(_running))
    return out


def find_run(run_id: str) -> dict[str, Any] | None:
    return next((r for r in runs() if r.get("id") == run_id and r.get("estado") == "exitosa"), None)


def _log_run(rec: dict[str, Any]) -> None:
    with open(report_dir() / "ejecuciones.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def running() -> dict[str, Any] | None:
    return dict(_running) if _running else None


# ---------------------------------------------------------------------------- calendario
def labels_for(d: date) -> tuple[str, str]:
    """Encabezado y nombre de hoja con el estilo del Excel: ("30-nov", "30NOV2026")."""
    return f"{d.day}-{MESES[d.month - 1]}", f"{d.day:02d}{MESES[d.month - 1].upper()}{d.year}"


def cut_labels(fecha: date, periodo: str) -> tuple[str, str]:
    """Encabezado de la columna = fin del mes que representa (p. ej. "31-oct"); hoja cruda = fecha real en que se
    tomaron los datos (p. ej. "03NOV2026"). En un corte de fin de mes ambas coinciden."""
    header = labels_for(month_end(date(int(periodo[:4]), int(periodo[5:7]), 1)))[0]
    return header, labels_for(fecha)[1]


def month_end(d: date) -> date:
    nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return nxt - timedelta(days=1)


def start_month() -> date:
    y, m = (int(x) for x in (settings.REPORT_START or "2026-11").split("-"))
    return date(y, m, 1)


def pending_cut(today: date | None = None) -> tuple[date, str, str] | None:
    """Corte que corresponde tomar hoy, si alguno: (fecha, periodo AAAA-MM, motivo).

    - Último día del mes (desde REPORT_START) sin corte → corte del día ("fin_de_mes").
    - Mes anterior (desde REPORT_START) sin corte → se toma hoy, con la fecha real, para ese mes ("recuperacion").
    """
    today = today or now().date()
    taken = set(registry())
    if today == month_end(today) and today >= start_month() and today.strftime("%Y-%m") not in taken:
        return today, today.strftime("%Y-%m"), "fin_de_mes"
    prev_end = today.replace(day=1) - timedelta(days=1)
    if prev_end >= start_month() and prev_end.strftime("%Y-%m") not in taken:
        return today, prev_end.strftime("%Y-%m"), "recuperacion"
    return None


def parse_header(header: str) -> tuple[int | None, int | None, int | None]:
    """(día, mes, año) a partir de encabezados como 'dec', 'ene 26', '26-Feb', '30-sep', '30-nov 27'."""
    h = re.sub(r"\s+", " ", str(header or "").strip().lower())
    m = re.search(r"[a-z]{3,}", h)
    if not m or m.group(0)[:3] not in MONTH_TOKENS:
        return None, None, None
    month = MONTH_TOKENS[m.group(0)[:3]]
    year = None
    after = re.match(r"^\s*(?:\d{1,2}-)?[a-z]+\.?\s+(\d{2}|\d{4})$", h)
    if after:
        y = int(after.group(1))
        year = y + 2000 if y < 100 else y
    day = None
    dm = re.match(r"^(\d{1,2})-[a-z]+", h)
    # "30-sep" = día. En los encabezados antiguos ("26-Feb", "26-Mar") el número es el año: 20–27 se lee como año.
    # Las fechas de los cortes de la plataforma salen de cortes.json, así que esta regla solo aplica a columnas manuales.
    if dm:
        n = int(dm.group(1))
        if 20 <= n <= 27 and year is None:
            year = 2000 + n
        else:
            day = n
    return day, month, year


def infer_periods(headers: list[str], known: dict[str, dict[str, str]], default_year: int) -> list[dict[str, Any]]:
    """Ubica cada columna en el calendario. `known` = {encabezado: {fecha, periodo}} de los cortes automáticos.

    Si el encabezado no trae el día (p. ej. 'dec', 'ene 26'), el día de corte se toma como fin de mes y se marca
    como estimado.
    """
    parsed = [parse_header(h) for h in headers]
    years: list[int | None] = [None] * len(headers)
    for i, h in enumerate(headers):
        if h in known:
            years[i] = int(known[h]["periodo"][:4])
        elif parsed[i][2]:
            years[i] = parsed[i][2]
    anchor = next((i for i, y in enumerate(years) if y), None)
    if anchor is None:
        anchor, years[0] = 0, default_year
    for i in range(anchor + 1, len(headers)):
        if years[i] is None:
            pm, cm = parsed[i - 1][1] or 1, parsed[i][1] or 1
            years[i] = years[i - 1] + (1 if cm < pm else 0)
    for i in range(anchor - 1, -1, -1):
        if years[i] is None:
            nm, cm = parsed[i + 1][1] or 1, parsed[i][1] or 1
            years[i] = years[i + 1] - (1 if cm > nm else 0)
    out = []
    for i, h in enumerate(headers):
        day, month, _ = parsed[i]
        k = known.get(h)
        if k:
            y, month = int(k["periodo"][:4]), int(k["periodo"][5:7])
            fecha, estimado = k["fecha"], False
        else:
            month = month or 1
            y = years[i] or default_year
            if day:
                fecha, estimado = date(y, month, min(day, month_end(date(y, month, 1)).day)).isoformat(), False
            else:
                fecha, estimado = month_end(date(y, month, 1)).isoformat(), True
        out.append({"encabezado": h, "periodo": f"{y:04d}-{month:02d}", "anio": y, "mes": month, "fecha": fecha,
                    "dia_estimado": estimado, "etiqueta": f"{MESES[month - 1].capitalize()} {y}"})
    return out


# ---------------------------------------------------------------------------- conteo
def count_rows(rows: Iterable[dict[str, Any]], statuses: list[str] | None = None) -> Counter:
    """Filas por plan en los estados del reporte (equivale a COUNTIFS por plan y estado)."""
    wanted = set(statuses or settings.COUNT_STATUSES)
    return Counter(r.get("plan") for r in rows if r.get("status") in wanted and r.get("plan"))


def _sheet_counts(ws, statuses: list[str]) -> Counter:
    wanted = set(statuses)
    c: Counter = Counter()
    for row in ws.iter_rows(min_row=2, values_only=True):
        if len(row) >= 12 and row[3] in wanted and row[11]:
            c[row[11]] += 1
    return c


def _formula_refs(value: Any) -> list[tuple[str, str]]:
    if not isinstance(value, str) or not value.startswith("="):
        return []
    return [(m.group(1).strip(), m.group(2)) for m in _FORMULA_RE.finditer(value)]


def formula(sheet: str, row: int, statuses: list[str] | None = None) -> str:
    """Misma fórmula del Excel, con el mismo formato (una línea por estado)."""
    sts = statuses or settings.COUNT_STATUSES
    return "\n+".join(f"COUNTIFS('{sheet}'!$L:$L, $A{row}, '{sheet}'!$D:$D, \"{s}\")" for s in sts)


# ---------------------------------------------------------------------------- tabla del portal
def _read_book(year: int, path: Path, reg: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Columnas y valores de la hoja del reporte de un libro (valores fijos y resultado de cada fórmula)."""
    sheet = sheet_for(year)
    wb_f = openpyxl.load_workbook(path, read_only=True, data_only=False)
    wb_v = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if sheet not in wb_f.sheetnames:
            raise ReportError(f"El libro {path.name} no tiene la hoja '{sheet}'.", "schema")
        frows = list(wb_f[sheet].iter_rows(values_only=True))
        vrows = list(wb_v[sheet].iter_rows(values_only=True))
        header = list(frows[0])
        ncols = len(header)
        while ncols and header[ncols - 1] in (None, ""):
            ncols -= 1
        month_cols = list(range(5, ncols))
        known = {v["encabezado"]: v for v in reg.values() if int(v.get("libro", 0)) == year}
        cols = infer_periods([str(header[c]) for c in month_cols], known, year)
        plans, cache = [], {}
        for fr, vr in zip(frows[1:], vrows[1:]):
            if not fr or not fr[0] or not str(fr[0]).strip():
                break
            plan = str(fr[0]).strip()
            vals = []
            for c in month_cols:
                f = fr[c] if c < len(fr) else None
                v = vr[c] if c < len(vr) else None
                refs = _formula_refs(f)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    vals.append(int(v))
                elif refs:  # fórmula sin valor calculado: se evalúa igual que COUNTIFS
                    sh, sts = refs[0][0], tuple(sorted({s for _, s in refs}))
                    if (sh, sts) not in cache:
                        cache[(sh, sts)] = _sheet_counts(wb_f[sh], list(sts)) if sh in wb_f.sheetnames else Counter()
                    vals.append(cache[(sh, sts)].get(plan, 0))
                else:
                    vals.append(None)
            plans.append({"plan": plan, "clasificacion": fr[1], "segmento": fr[2],
                          "descripcion": (str(fr[3]).strip() if fr[3] else None),
                          "costo": float(fr[4]) if isinstance(fr[4], (int, float)) else None, "valores": vals})
        first = frows[1] if len(frows) > 1 else []
        for j, col in enumerate(cols):
            refs = _formula_refs(first[month_cols[j]] if month_cols[j] < len(first) else None)
            entry = known.get(col["encabezado"], {})
            col.update(libro=year, hoja=refs[0][0] if refs else None, tipo="formula" if refs else "valor",
                       automatico=bool(entry), snapshot=entry.get("snapshot"), disparo=entry.get("disparo"),
                       observacion=entry.get("observacion"))
    finally:
        wb_f.close()
        wb_v.close()
    return {"columnas": cols, "planes": plans}


def build_summary() -> dict[str, Any]:
    """Une los libros de todos los años en una sola tabla (columnas en orden cronológico)."""
    books = workbooks()
    if not books:
        raise ReportError("Aún no se ha cargado el Excel del reporte.", "no_excel")
    reg = registry()
    columns: list[dict[str, Any]] = []
    plans: dict[str, dict[str, Any]] = {}
    for year, path in books:
        data = _read_book(year, path, reg)
        offset = len(columns)
        columns.extend(data["columnas"])
        for p in data["planes"]:
            cur = plans.setdefault(p["plan"], {**{k: p[k] for k in ("plan", "clasificacion", "segmento", "descripcion", "costo")},
                                               "valores": []})
            cur.update({k: p[k] for k in ("clasificacion", "segmento", "descripcion", "costo")})  # dato más reciente
            cur["valores"] += [None] * (offset - len(cur["valores"]))
            cur["valores"] += p["valores"]
    for p in plans.values():
        p["valores"] += [None] * (len(columns) - len(p["valores"]))
    for i, c in enumerate(columns):
        c["id"] = f"{c['libro']}:{i}"
    plan_list = list(plans.values())
    libros = []
    for year, path in books:
        last = [c for c in columns if c["libro"] == year]
        libros.append({"anio": year, "descarga": download_name(year, last), "hoja": sheet_for(year),
                       "actualizado": datetime.fromtimestamp(path.stat().st_mtime, now().tzinfo).isoformat()})
    summary = {
        "actualizado": max(lb["actualizado"] for lb in libros), "tabla": settings.EXCEL_TABLE,
        "estados": settings.COUNT_STATUSES, "columnas": columns, "planes": plan_list, "libros": libros,
        "anios": sorted({c["anio"] for c in columns}),
        "totales": [sum(p["valores"][j] or 0 for p in plan_list) for j in range(len(columns))],
    }
    _save_json(report_dir() / "resumen.json", summary)
    return summary


def summary() -> dict[str, Any]:
    p = report_dir() / "resumen.json"
    sources = [path for _, path in workbooks()] + ([_registry_path()] if _registry_path().exists() else [])
    if p.exists() and sources and p.stat().st_mtime >= max(s.stat().st_mtime for s in sources):
        return json.loads(p.read_text(encoding="utf-8"))
    return build_summary()


def download_name(year: int, cols: list[dict[str, Any]] | None = None) -> str:
    """'Planes tv corte AAAA-MM.xlsx' con el año-mes del último corte del libro."""
    if cols is None:
        cols = [c for c in summary()["columnas"] if c["libro"] == year]
    periodo = cols[-1]["periodo"] if cols else f"{year}-01"
    return settings.EXCEL_DOWNLOAD_PATTERN.format(periodo=periodo)


# ---------------------------------------------------------------------------- snapshot
RAW_STATUS_ORDER = ["Active", "Past Due Date", "Unpaid", "Temporarily Suspended", "Trialling", "Cancelled", "Completed"]


def curation(rows: list[dict[str, Any]], plans: list[str]) -> dict[str, Any]:
    """Resumen para verificar el .json contra el Excel."""
    by_status = Counter(r.get("status") or "Sin estado" for r in rows)
    subs_by_status: dict[str, set] = {}
    for r in rows:
        subs_by_status.setdefault(r.get("status") or "Sin estado", set()).add(r.get("name"))
    report = count_rows(rows)
    by_plan_status: dict[str, Counter] = {}
    for r in rows:
        if r.get("plan") in plans:
            by_plan_status.setdefault(r["plan"], Counter())[r.get("status") or "Sin estado"] += 1
    order = sorted(by_status, key=lambda s: (RAW_STATUS_ORDER.index(s) if s in RAW_STATUS_ORDER else 99, s))
    return {
        "filtro_de_estado_en_la_consulta": "ninguno (todas las suscripciones)",
        "filas_por_estado": {s: by_status[s] for s in order},
        "suscripciones_por_estado": {s: len(subs_by_status[s]) for s in order},
        "reporte": {
            "estados_que_cuentan": settings.COUNT_STATUSES,
            "regla": "filas por plan con estado en estados_que_cuentan (igual que COUNTIFS en el Excel)",
            "por_plan": {p: report.get(p, 0) for p in plans},
            "total": sum(report.get(p, 0) for p in plans),
            "detalle_por_plan_y_estado": {p: dict(by_plan_status.get(p, {})) for p in plans},
        },
    }


def _raw_rows(rows: list[dict[str, Any]]) -> Iterable[list[Any]]:
    cols = consulta()["columnas_excel"]
    for i, r in enumerate(rows, start=1):
        out = []
        for _, field in cols:
            if field is None:
                out.append(i)
            elif field == "creation" and isinstance(r.get(field), str) and r.get(field):
                try:
                    out.append(datetime.fromisoformat(r[field].replace(" ", "T")[:26]))
                except ValueError:
                    out.append(r[field])
            else:
                out.append(r.get(field))
        yield out


def _query(client_factory: Callable | None, rec: dict[str, Any]) -> list[dict[str, Any]]:
    with (client_factory or get_client)() as client:
        rows = client.report_rows()
        rec["solicitudes"] = client.attempts
    if not rows:
        raise ReportError("ERPNext no devolvió suscripciones.", "empty")
    missing = {"status", "plan", "name"} - set(rows[0])
    if missing:
        raise ReportError("La consulta no trae las columnas esperadas.", "schema", f"faltan {missing}")
    return rows


def _write_snapshot(name: str, fecha: date, taken: datetime, rows: list[dict[str, Any]], cur: dict[str, Any],
                    observacion: str | None = None, periodo: str | None = None) -> None:
    c = consulta()
    data = {"corte": fecha.isoformat(), "tomado": taken.isoformat(), "origen": "ERPNext API Gigafibra"}
    if periodo:
        data["periodo"] = periodo
    if observacion:
        data["observacion"] = observacion
    data.update({"consulta": {"nombre": c["nombre"], "metodo": c["metodo"], "ruta": c["ruta"], "parametros": c["parametros"]},
                 "filas": len(rows), "suscripciones": len({r.get("name") for r in rows}), "curaduria": cur, "data": rows})
    _save_json(report_dir() / "snapshots" / name, data, indent=None)


def _append_to(path: Path, year: int, header: str, sheet: str, rows: list[dict[str, Any]], counts: Counter) -> None:
    """Agrega el corte a un libro existente sin reescribirlo."""
    c = consulta()
    plan_by_row = _plans_by_row(path, year)
    try:
        xlsx_append.append_cut(
            path, path, sheet_name=sheet_for(year), table_name=settings.EXCEL_TABLE, new_sheet=sheet, header=header,
            raw_header=[n for n, _ in c["columnas_excel"]], raw_rows=_raw_rows(rows),
            formula=lambda s, r: formula(s, r), cached=lambda r: counts.get(plan_by_row[r], 0) if r in plan_by_row else None)
    except PermissionError as exc:
        raise ReportError("No se pudo guardar el Excel: el archivo está abierto en otro programa.", "locked", repr(exc))
    except xlsx_append.XlsxError as exc:
        raise ReportError(f"No se pudo agregar el corte al Excel: {exc}", "excel", str(exc))


def _plans_by_row(path: Path, year: int) -> dict[int, str]:
    wb = openpyxl.load_workbook(path, read_only=True)
    try:
        out = {}
        for i, row in enumerate(wb[sheet_for(year)].iter_rows(min_row=2, max_col=1, values_only=True), start=2):
            if not row[0] or not str(row[0]).strip():
                break
            out[i] = str(row[0]).strip()
        return out
    finally:
        wb.close()


def create_year_workbook(year: int, header: str, sheet: str, rows: list[dict[str, Any]]) -> Path:
    """Primer corte de un año: libro nuevo con los mismos planes y la misma tabla, empezando en este mes."""
    prev = [(y, p) for y, p in workbooks() if y < year]
    if not prev:
        raise ReportError(f"No hay un libro anterior para crear el de {year}.", "no_excel")
    py, ppath = prev[-1]
    src = openpyxl.load_workbook(ppath, read_only=True)
    try:
        prows = list(src[sheet_for(py)].iter_rows(values_only=True))
    finally:
        src.close()
    head = [str(h) for h in prows[0][:5]]
    plans = [r[:5] for r in prows[1:] if r and r[0] and str(r[0]).strip()]
    from openpyxl.worksheet.table import Table, TableColumn, TableFormula, TableStyleInfo

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_for(year)
    ws.append(head + [header])
    for i, p in enumerate(plans, start=2):
        ws.append(list(p) + ["=" + formula(sheet, i)])
        ws.cell(i, 5).number_format = COST_FORMAT
    ws.cell(1, 6).number_format = "d-mmm"
    for letter, width in (("A", 43.57), ("B", 14.57), ("C", 13), ("D", 13), ("E", 16.29), ("F", 13)):
        ws.column_dimensions[letter].width = width
    table = Table(displayName=settings.EXCEL_TABLE, ref=f"A1:F{len(plans) + 1}")
    table.tableColumns = [TableColumn(id=i + 1, name=h) for i, h in enumerate(head + [header])]
    table.tableColumns[-1].calculatedColumnFormula = TableFormula(attr_text=formula(sheet, 2))
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(table)
    raw = wb.create_sheet(sheet)
    cols = consulta()["columnas_excel"]
    raw.append([n for n, _ in cols])
    for r in _raw_rows(rows):
        raw.append(r)
    fi = next(i for i, (_, f) in enumerate(cols, start=1) if f == "creation")
    for (cell,) in raw.iter_rows(min_row=2, min_col=fi, max_col=fi):
        cell.number_format = CREATION_FORMAT
    for letter, width in (("B", 16.86), ("C", 9.14), ("E", 34.71), ("F", 18.14)):
        raw.column_dimensions[letter].width = width
    wb.calculation.fullCalcOnLoad = True
    dest = workbook_path(year)
    tmp = dest.with_name(f".{dest.stem}.tmp.xlsx")
    wb.save(tmp)
    os.replace(tmp, dest)
    return dest


# ---------------------------------------------------------------------------- corte automático
def take_cut(trigger: str, user: str | None = None, fecha: date | None = None, periodo: str | None = None,
             force: bool = False, client_factory: Callable | None = None, observacion: str | None = None,
             tomado: datetime | None = None) -> dict[str, Any]:
    """Toma el corte de un mes (uno por mes). `force` rehace el último corte (restaura el libro previo).

    `observacion` queda en el registro, el historial y el .json; `tomado` conserva la hora real de una consulta
    ya hecha (ver include_snapshot)."""
    global _running
    if not has_workbook():
        raise ReportError("Aún no se ha cargado el Excel del reporte (scripts.reporte inicializar).", "no_excel")
    if not _lock.acquire(blocking=False):
        raise ReportError("Ya hay un corte en curso.", "running")
    fecha = fecha or now().date()
    periodo = periodo or fecha.strftime("%Y-%m")
    year = int(periodo[:4])
    header, sheet = cut_labels(fecha, periodo)
    started = now()
    rec: dict[str, Any] = {"id": started.strftime("%Y%m%d%H%M%S"), "fecha_corte": fecha.isoformat(), "periodo": periodo,
                           "libro": year, "disparo": trigger, "usuario": user or "sistema", "inicio": started.isoformat(),
                           "estado": "en_curso", "encabezado": header, "hoja": sheet}
    if observacion:
        rec["observacion"] = observacion
    try:
        reg = registry()
        if periodo in reg and not force:
            rec.update(estado="omitida", fin=now().isoformat(),
                       mensaje=f"El corte de {MESES_LARGOS[int(periodo[5:]) - 1]} {year} ya existe.")
            _log_run(rec)
            return rec
        replaced = periodo in reg
        if replaced:
            if periodo != sorted(reg)[-1]:
                raise ReportError("Solo se puede rehacer el último corte.", "not_last")
            prev = reg.pop(periodo)
            if prev.get("respaldo"):
                backup = report_dir() / "respaldos" / prev["respaldo"]
                if not backup.exists():
                    raise ReportError("No está el respaldo previo a ese corte; no se puede rehacer.", "no_backup")
                shutil.copy2(backup, workbook_path(year))
            else:  # fue el corte que creó el libro del año
                workbook_path(year).unlink(missing_ok=True)
            _save_json(_registry_path(), reg)
        _running = rec
        t0 = time.monotonic()
        rec["paso"] = "Consultando ERPNext…"
        rows = _query(client_factory, rec)
        taken = tomado or now()
        counts = count_rows(rows)
        plans = [p["plan"] for p in summary()["planes"]] if has_workbook() else []
        cur = curation(rows, plans)
        rec["paso"] = "Guardando snapshot .json…"
        snap_name = f"{fecha.isoformat()}.json"
        _write_snapshot(snap_name, fecha, taken, rows, cur, observacion, periodo)

        rec["paso"] = "Agregando el corte al Excel…"
        path = workbook_path(year)
        backup_name = None
        if path.exists():
            backup_name = f"{path.stem} · antes de {header} · {taken:%Y-%m-%d %H%M%S}.xlsx"
            shutil.copy2(path, report_dir() / "respaldos" / backup_name)
            _append_to(path, year, header, sheet, rows, counts)
        else:
            create_year_workbook(year, header, sheet, rows)
        _prune_backups()

        reg = registry()
        reg[periodo] = {"fecha": fecha.isoformat(), "periodo": periodo, "libro": year, "encabezado": header, "hoja": sheet,
                        "snapshot": snap_name, "respaldo": backup_name, "tomado": taken.isoformat(), "filas": len(rows),
                        "disparo": trigger}
        if observacion:
            reg[periodo]["observacion"] = observacion
        _save_json(_registry_path(), dict(sorted(reg.items())))
        rec["paso"] = "Actualizando la tabla del portal…"
        build_summary()
        total = cur["reporte"]["total"]
        rec.update(estado="exitosa", fin=now().isoformat(), duracion_ms=int((time.monotonic() - t0) * 1000),
                   filas=len(rows), suscripciones=len({r.get("name") for r in rows}), total=total, snapshot=snap_name,
                   filas_por_estado=cur["filas_por_estado"], reemplazo=replaced, libro_nuevo=backup_name is None)
        mes = f"{MESES_LARGOS[int(periodo[5:]) - 1]} {year}"
        cuando = (f"Corte del {fecha:%d/%m/%Y}" if fecha.strftime("%Y-%m") == periodo
                  else f"Corte de {mes}, tomado el {fecha:%d/%m/%Y}")
        miles = lambda n: f"{n:,}".replace(",", ".")  # noqa: E731
        rec["mensaje"] = (f"{cuando}: {miles(total)} suscripciones de TV ({' + '.join(settings.COUNT_STATUSES)}) "
                          f"en la columna {header} del libro {year} (hoja {sheet}); {miles(len(rows))} filas de todos "
                          f"los estados en {snap_name}.")
        if backup_name is None:
            rec["mensaje"] += f" Se creó el libro de {year}."
        rec.pop("paso", None)
        _log_run(rec)
        return rec
    except (ERPNextError, ReportError) as exc:
        msg = exc.user_message if isinstance(exc, ERPNextError) else exc.message
        rec.update(estado="fallida", fin=now().isoformat(), mensaje=msg, detalle=exc.detail[:2000])
        rec.pop("paso", None)
        _log_run(rec)
        code = "retryable" if isinstance(exc, ERPNextError) and exc.retryable else getattr(exc, "code", "error")
        raise ReportError(msg, code, exc.detail) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("Error inesperado en el corte")
        rec.update(estado="fallida", fin=now().isoformat(), mensaje="Error inesperado durante el corte.", detalle=repr(exc))
        rec.pop("paso", None)
        _log_run(rec)
        raise ReportError("Error inesperado durante el corte.", "error", repr(exc)) from exc
    finally:
        _running = None
        _lock.release()


def take_dev_cut(fecha: date | None = None, client_factory: Callable | None = None) -> dict[str, Any]:
    """Corte de prueba hecho durante el desarrollo: queda en el historial con su .json y un Excel propio,
    sin tocar el libro oficial ni contar como corte del mes."""
    fecha = fecha or now().date()
    year = max(y for y, _ in workbooks())
    header, sheet = labels_for(fecha)
    started = now()
    rec: dict[str, Any] = {"id": started.strftime("%Y%m%d%H%M%S") + "D", "fecha_corte": fecha.isoformat(),
                           "periodo": fecha.strftime("%Y-%m"), "libro": year, "disparo": "desarrollo", "usuario": "desarrollo",
                           "inicio": started.isoformat(), "estado": "en_curso", "encabezado": header, "hoja": sheet,
                           "observacion": OBS_DESARROLLO}
    t0 = time.monotonic()
    rows = _query(client_factory, rec)
    taken = now()
    plans = [p["plan"] for p in summary()["planes"]]
    cur = curation(rows, plans)
    snap_name = f"{fecha.isoformat()}-desarrollo.json"
    _write_snapshot(snap_name, fecha, taken, rows, cur, OBS_DESARROLLO)
    xname = f"{settings.EXCEL_DOWNLOAD_PATTERN.format(periodo=fecha.isoformat())[:-5]} (desarrollo).xlsx"
    dest = report_dir() / "desarrollo" / xname
    shutil.copy2(workbook_path(year), dest)
    _append_to(dest, year, header, sheet, rows, count_rows(rows))
    rec.update(estado="exitosa", fin=now().isoformat(), duracion_ms=int((time.monotonic() - t0) * 1000), filas=len(rows),
               suscripciones=len({r.get("name") for r in rows}), total=cur["reporte"]["total"], snapshot=snap_name,
               excel=f"desarrollo/{xname}", filas_por_estado=cur["filas_por_estado"])
    rec["mensaje"] = (f"{OBS_DESARROLLO}: {cur['reporte']['total']:,} suscripciones de TV "
                      f"({' + '.join(settings.COUNT_STATUSES)}) con datos del {fecha:%d/%m/%Y}. No forma parte del "
                      f"Excel oficial ni cuenta como corte de {MESES_LARGOS[fecha.month - 1]}.").replace(",", ".")
    _log_run(rec)
    return rec


def include_snapshot(snapshot: str, periodo: str, observacion: str, trigger: str = "inicial") -> dict[str, Any]:
    """Incluye en el reporte, como corte de `periodo`, una consulta ya guardada (p. ej. el corte de desarrollo del
    3-nov-2026 como corte de octubre). Usa exactamente las filas del .json, sin volver a consultar ERPNext.

    Si la consulta venía de un corte de desarrollo, ese registro se reemplaza por el corte incluido (su .json y su
    Excel de prueba se retiran: el .json oficial conserva las mismas filas)."""
    src = report_dir() / "snapshots" / snapshot
    if not src.exists():
        raise ReportError(f"No existe el snapshot {snapshot}.", "not_found")
    data = json.loads(src.read_text(encoding="utf-8"))
    rows = data["data"]
    fecha = date.fromisoformat(data["corte"])
    tomado = datetime.fromisoformat(data["tomado"]) if data.get("tomado") else None

    class _Saved:
        attempts = 0  # no se consulta ERPNext

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def report_rows(self):
            return rows

    res = take_cut(trigger, "soporte", fecha=fecha, periodo=periodo, client_factory=_Saved, observacion=observacion,
                   tomado=tomado)
    if res["estado"] != "exitosa":
        return res
    log_path = report_dir() / "ejecuciones.jsonl"
    lines = log_path.read_text(encoding="utf-8").splitlines()
    keep, retired = [], []
    for line in lines:
        r = json.loads(line) if line.strip() else None
        if r and r.get("disparo") == "desarrollo" and r.get("snapshot") == snapshot:
            retired.append(r)
        elif line.strip():
            keep.append(line)
    if retired:
        tmp = log_path.with_suffix(".jsonl.tmp")
        tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
        os.replace(tmp, log_path)
        for r in retired:
            if r.get("excel"):
                (report_dir() / r["excel"]).unlink(missing_ok=True)
        if snapshot != res["snapshot"]:
            src.unlink(missing_ok=True)
        res["reemplaza"] = [r["id"] for r in retired]
    return res


def _prune_backups() -> None:
    """Conserva el original y los últimos EXCEL_BACKUPS_KEEP respaldos previos a cada corte."""
    keep = settings.EXCEL_BACKUPS_KEEP
    if keep <= 0:
        return
    files = sorted((report_dir() / "respaldos").glob("* · antes de *.xlsx"), key=lambda p: p.stat().st_mtime)
    for old in files[:-keep]:
        old.unlink(missing_ok=True)


def import_excel(source: Path, year: int, replace: bool = False) -> Path:
    """Carga el Excel de referencia como libro del año. El original se guarda aparte y nunca se borra."""
    report_dir()
    dest = workbook_path(year)
    if dest.exists() and not replace:
        raise ReportError(f"Ya existe {dest.name}; usa --reemplazar para sobrescribirlo (se respalda).", "exists")
    with zipfile.ZipFile(source) as z:
        xlsx_append.inspect(z, sheet_for(year), settings.EXCEL_TABLE)  # valida hoja y tabla
    if dest.exists():
        shutil.copy2(dest, report_dir() / "respaldos" / f"{dest.stem} · reemplazado {now():%Y-%m-%d %H%M%S}.xlsx")
    shutil.copy2(source, dest)
    shutil.copy2(source, report_dir() / "respaldos" / f"original · {source.name}")
    build_summary()
    return dest
