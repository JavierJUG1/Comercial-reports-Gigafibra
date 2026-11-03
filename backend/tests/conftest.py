"""Entorno de pruebas: carpeta de reporte temporal, Excel sintético con la estructura real y ERPNext simulado."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import openpyxl
import pytest
from openpyxl.worksheet.table import Table, TableColumn, TableFormula, TableStyleInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import report  # noqa: E402
from app.config import settings  # noqa: E402

PLANS = ["Plan A", "Plan B", "Plan C"]
RAW_HEADER = ["Sr", "ID", "Docstatus", "Status", "Party", "Creation", "Lead", "Estrato", "Party Type", "Ciudad",
              "PPPoE Username", "Plan (Subscription Plan Detail)", "Total Price", "Motivo de Desconto",
              "Cliente B2B", "Conjunto", "Name (Subscription Plan Detail)"]


def raw_rows(spec: dict[str, dict[str, int]]) -> list[list]:
    """{'Plan A': {'Active': 3, 'Unpaid': 1}} → filas con el formato de las hojas crudas del Excel."""
    rows, n = [], 0
    for plan, sts in spec.items():
        for st, k in sts.items():
            for _ in range(k):
                n += 1
                rows.append([n, f"SUS-{n:04d}", 0, st, "Cliente", datetime(2026, 1, 1), None, "3", "Customer",
                             "Bogotá", "OLT", plan, 59900, None, 0, None, f"d{n}"])
    return rows


def countifs(sheet: str, row: int) -> str:
    return (f"=COUNTIFS('{sheet}'!$L:$L, $A{row}, '{sheet}'!$D:$D, \"Active\")\n"
            f"+COUNTIFS('{sheet}'!$L:$L, $A{row}, '{sheet}'!$D:$D, \"Past Due Date\")")


def make_workbook(path: Path) -> None:
    """Réplica reducida del Excel real: 'dec', 'ene 26' con valores; '30-ago' y '30-sep' con COUNTIFS."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Planes TV mensual 2026"
    headers = ["plan name", "Clasificacion", "Segmento plan", "descripcion", "Costo sin IVA", "dec", "ene 26", "30-ago", "30-sep"]
    ws.append(headers)
    static = {"Plan A": (10, 12), "Plan B": (5, 4), "Plan C": (0, 0)}
    for i, p in enumerate(PLANS, start=2):
        ws.append([p, "Valor Agregado", "TV", f"Desc {p}", 1000.5, *static[p], countifs("Subscription", i),
                   countifs("30SEP2026", i)])
    t = Table(displayName="Tabla2", ref=f"A1:I{len(PLANS) + 1}")
    t._initialise_columns()
    for tc, h in zip(t.tableColumns, headers):  # Excel nombra las columnas igual que el encabezado
        tc.name = h
    t.tableColumns[7].calculatedColumnFormula = TableFormula(attr_text=countifs("Subscription", 2)[1:])
    t.tableColumns[8].calculatedColumnFormula = TableFormula(attr_text=countifs("30SEP2026", 2)[1:])
    t.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(t)
    for name, spec in [("Subscription", {"Plan A": {"Active": 7, "Cancelled": 2}, "Plan B": {"Past Due Date": 2}}),
                       ("30SEP2026", {"Plan A": {"Active": 8, "Unpaid": 3}, "Plan B": {"Active": 1, "Past Due Date": 1}})]:
        raw = wb.create_sheet(name)
        raw.append(RAW_HEADER)
        for r in raw_rows(spec):
            raw.append(r)
    wb.save(path)


def api_rows(spec: dict[str, dict[str, int]]) -> list[dict]:
    """Filas como las devuelve la petición de Postman (fieldnames de ERPNext)."""
    out, n = [], 0
    for plan, sts in spec.items():
        for st, k in sts.items():
            for _ in range(k):
                n += 1
                out.append({"name": f"SUS-N{n:04d}", "docstatus": 0, "status": st, "party": "Cliente",
                            "creation": "2026-11-03 10:11:28.745000", "custom_lead": None, "custom_estrato": "3",
                            "party_type": "Customer", "custom_ciudad_l": "Soacha", "custom_pppoe_username": "OLT",
                            "plan": plan, "custom_total_price": 89800.0, "custom_motivo_de_desconto": None,
                            "custom_cliente_b2b": 0, "custom_conjunto": None, "plan_detail_name": f"x{n}"})
    return out


class FakeClient:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.attempts = 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def report_rows(self):
        return self.rows


@pytest.fixture()
def workdir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "REPORT_DIR", tmp_path / "reporte")
    monkeypatch.setattr(settings, "SCHEDULER_ENABLED", False)
    monkeypatch.setattr(settings, "AUTH_MODE", "debug")
    monkeypatch.setattr(settings, "COUNT_STATUSES", ["Active", "Past Due Date"])
    monkeypatch.setattr(settings, "ERPNEXT_API_KEY", "k")
    monkeypatch.setattr(settings, "ERPNEXT_API_SECRET", "s")
    src = tmp_path / "origen.xlsx"
    make_workbook(src)
    report.import_excel(src, 2026)
    return tmp_path
