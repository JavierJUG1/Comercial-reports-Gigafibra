from __future__ import annotations

import json
import zipfile
from datetime import date

import httpx
import openpyxl
import pytest
from fastapi.testclient import TestClient

from app import report
from app.config import settings
from app.erpnext import ERPNextClient, ERPNextError
from tests.conftest import FakeClient, api_rows

NOV3 = date(2026, 11, 3)
NOV30 = date(2026, 11, 30)
DEC31 = date(2026, 12, 31)
JAN31 = date(2027, 1, 31)
ROWS = {"Plan A": {"Active": 20, "Past Due Date": 2, "Cancelled": 5, "Unpaid": 1}, "Plan C": {"Active": 1},
        "Internet 500": {"Active": 9}}


def _cut(rows, fecha, periodo=None, force=False):
    return report.take_cut("schedule", fecha=fecha, periodo=periodo, force=force, client_factory=lambda: FakeClient(rows))


def _book(year=2026):
    return report.workbook_path(year)


def _entries(path):
    with zipfile.ZipFile(path) as z:
        return {i.filename: z.read(i.filename) for i in z.infolist()}


# ---------------------------------------------------------------- calendario
def test_labels_follow_excel_style():
    assert report.labels_for(NOV30) == ("30-nov", "30NOV2026")
    assert report.labels_for(JAN31) == ("31-ene", "31ENE2027")


def test_columns_get_month_year_and_cut_day():
    headers = ["dec", "ene 26", "26-Feb", "26-Mar", "30-jun", "31-Jul", "30-ago", "30-sep", "30-nov"]
    cols = report.infer_periods(headers, {"30-nov": {"fecha": "2026-11-30", "periodo": "2026-11"}}, 2026)
    assert [c["periodo"] for c in cols] == ["2025-12", "2026-01", "2026-02", "2026-03", "2026-06", "2026-07",
                                           "2026-08", "2026-09", "2026-11"]
    assert [c["fecha"] for c in cols] == ["2025-12-31", "2026-01-31", "2026-02-28", "2026-03-31", "2026-06-30",
                                         "2026-07-31", "2026-08-30", "2026-09-30", "2026-11-30"]
    assert [c["dia_estimado"] for c in cols] == [True, True, True, True, False, False, False, False, False]


def test_pending_cut_only_month_end_from_november(workdir):
    assert report.pending_cut(NOV3) is None
    assert report.pending_cut(date(2026, 10, 31)) is None
    assert report.pending_cut(NOV30) == (NOV30, "2026-11", "fin_de_mes")
    assert report.pending_cut(date(2026, 12, 2)) == (date(2026, 12, 2), "2026-11", "recuperacion")
    _cut(api_rows(ROWS), NOV30)
    assert report.pending_cut(date(2026, 12, 2)) is None and report.pending_cut(NOV30) is None


def test_count_is_by_rows_like_countifs():
    rows = api_rows({"Plan A": {"Active": 2, "Past Due Date": 1, "Unpaid": 4}})
    rows.append(dict(rows[0]))
    assert report.count_rows(rows)["Plan A"] == 4


# ---------------------------------------------------------------- Excel intacto + mes nuevo
def test_summary_reads_confirmed_values(workdir):
    s = report.build_summary()
    assert [c["encabezado"] for c in s["columnas"]] == ["dec", "ene 26", "30-ago", "30-sep"]
    vals = {p["plan"]: p["valores"] for p in s["planes"]}
    assert vals["Plan A"] == [10, 12, 7, 8] and vals["Plan B"] == [5, 4, 2, 2]
    assert s["libros"][0]["descarga"] == "Planes tv corte 2026-09.xlsx" and s["anios"] == [2025, 2026]


def test_cut_appends_without_touching_existing_data(workdir):
    before = _entries(_book())
    res = _cut(api_rows(ROWS), NOV30)
    assert res["estado"] == "exitosa" and res["total"] == 23 and res["encabezado"] == "30-nov"
    after = _entries(_book())
    raw_parts = [n for n in before if n.startswith("xl/worksheets/sheet") and n != "xl/worksheets/sheet1.xml"]
    for name in raw_parts + ["xl/styles.xml", "xl/sharedStrings.xml"]:
        if name in before:
            assert after[name] == before[name], name

    wb = openpyxl.load_workbook(_book())
    assert wb.sheetnames == ["Planes TV mensual 2026", "Subscription", "30SEP2026", "30NOV2026"]
    ws = wb["Planes TV mensual 2026"]
    t = ws.tables["Tabla2"]
    assert t.ref == "A1:J4" and [c.name for c in t.tableColumns][-1] == "30-nov"
    assert ws["H2"].value.startswith("=COUNTIFS('Subscription'!") and ws["I2"].value.startswith("=COUNTIFS('30SEP2026'!")
    assert ws["J2"].value == "=COUNTIFS('30NOV2026'!$L:$L, $A2, '30NOV2026'!$D:$D, \"Active\")\n+COUNTIFS('30NOV2026'!$L:$L, $A2, '30NOV2026'!$D:$D, \"Past Due Date\")"
    assert wb["30NOV2026"].max_row == len(api_rows(ROWS)) + 1  # todas las filas, todos los estados
    assert "xl/calcChain.xml" not in after
    wbv = openpyxl.load_workbook(_book(), data_only=True, read_only=True)
    assert [r[9] for r in wbv["Planes TV mensual 2026"].iter_rows(min_row=2, max_row=4, values_only=True)] == [22, 0, 1]

    snap = json.loads((settings.REPORT_DIR / "snapshots" / "2026-11-30.json").read_text(encoding="utf-8"))
    assert snap["filas"] == len(api_rows(ROWS)) and snap["origen"] == "ERPNext API Gigafibra"
    assert {r["status"] for r in snap["data"]} == {"Active", "Past Due Date", "Cancelled", "Unpaid"}
    assert snap["curaduria"]["filas_por_estado"] == {"Active": 30, "Past Due Date": 2, "Unpaid": 1, "Cancelled": 5}
    assert snap["curaduria"]["reporte"]["total"] == 23

    s = report.summary()
    last = s["columnas"][-1]
    assert last["fecha"] == "2026-11-30" and not last["dia_estimado"] and last["automatico"]
    assert s["libros"][0]["descarga"] == "Planes tv corte 2026-11.xlsx"


def test_one_cut_per_month_and_rebuild(workdir):
    _cut(api_rows({"Plan A": {"Active": 3}}), NOV30)
    assert _cut(api_rows({"Plan A": {"Active": 99}}), NOV30)["estado"] == "omitida"
    assert report.summary()["planes"][0]["valores"][-1] == 3
    rebuilt = _cut(api_rows({"Plan A": {"Active": 5}}), NOV30, force=True)
    assert rebuilt["estado"] == "exitosa" and rebuilt["reemplazo"] is True
    assert openpyxl.load_workbook(_book(), read_only=True).sheetnames.count("30NOV2026") == 1
    assert report.summary()["planes"][0]["valores"][-1] == 5


def test_new_year_starts_a_new_workbook(workdir):
    _cut(api_rows({"Plan A": {"Active": 3}}), NOV30)
    _cut(api_rows({"Plan A": {"Active": 4}}), DEC31)
    res = _cut(api_rows({"Plan A": {"Active": 6}, "Plan B": {"Past Due Date": 2}}), JAN31)
    assert res["estado"] == "exitosa" and res["libro_nuevo"] is True
    assert [y for y, _ in report.workbooks()] == [2026, 2027]
    wb = openpyxl.load_workbook(_book(2027))
    assert wb.sheetnames == ["Planes TV mensual 2027", "31ENE2027"]
    ws = wb["Planes TV mensual 2027"]
    assert ws.tables["Tabla2"].ref == "A1:F4" and ws["F1"].value == "31-ene" and ws["A2"].value == "Plan A"
    assert ws["F2"].value.startswith("=COUNTIFS('31ENE2027'!")
    _cut(api_rows({"Plan A": {"Active": 7}}), date(2027, 2, 28))  # el segundo mes se agrega sin reescribir
    wb = openpyxl.load_workbook(_book(2027))
    assert wb["Planes TV mensual 2027"].tables["Tabla2"].ref == "A1:G4"
    s = report.summary()
    assert s["anios"] == [2025, 2026, 2027]
    assert [c["etiqueta"] for c in s["columnas"]][-4:] == ["Nov 2026", "Dic 2026", "Ene 2027", "Feb 2027"]
    assert {p["plan"]: p["valores"][-2:] for p in s["planes"]} == {"Plan A": [6, 7], "Plan B": [2, 0], "Plan C": [0, 0]}
    assert [lb["descarga"] for lb in s["libros"]] == ["Planes tv corte 2026-12.xlsx", "Planes tv corte 2027-02.xlsx"]
    assert openpyxl.load_workbook(_book(2026)).sheetnames[-1] == "31DIC2026"  # 2026 queda cerrado


def test_recovery_cut_goes_to_its_month(workdir):
    assert report.pending_cut(date(2027, 1, 2)) == (date(2027, 1, 2), "2026-12", "recuperacion")
    assert report.pending_cut(date(2026, 12, 2)) == (date(2026, 12, 2), "2026-11", "recuperacion")
    res = _cut(api_rows({"Plan A": {"Active": 1}}), date(2026, 12, 2), periodo="2026-11")
    # La columna se titula con el mes que representa; la hoja cruda conserva la fecha real de los datos
    assert res["periodo"] == "2026-11" and res["encabezado"] == "30-nov" and res["hoja"] == "02DIC2026"
    col = report.summary()["columnas"][-1]
    assert col["periodo"] == "2026-11" and col["fecha"] == "2026-12-02" and col["encabezado"] == "30-nov"


def test_saved_cut_is_included_as_october(workdir):
    dev = report.take_dev_cut(fecha=NOV3, client_factory=lambda: FakeClient(api_rows(ROWS)))
    obs = "Corte de octubre tomado el 3 nov (generado en el desarrollo de la aplicación)"
    res = report.include_snapshot(dev["snapshot"], "2026-10", obs)
    assert res["estado"] == "exitosa" and res["total"] == 23 and res["reemplaza"] == [dev["id"]]
    assert (res["periodo"], res["encabezado"], res["hoja"]) == ("2026-10", "31-oct", "03NOV2026")
    entry = report.registry()["2026-10"]
    assert entry["observacion"] == obs and entry["disparo"] == "inicial" and entry["fecha"] == "2026-11-03"
    wb = openpyxl.load_workbook(_book(), read_only=True)
    assert wb.sheetnames[-1] == "03NOV2026"
    assert [v for v in next(wb["Planes TV mensual 2026"].iter_rows(max_row=1, values_only=True)) if v][-1] == "31-oct"
    wb.close()
    col = report.summary()["columnas"][-1]
    assert (col["etiqueta"], col["fecha"], col["disparo"], col["observacion"]) == ("Oct 2026", "2026-11-03", "inicial", obs)
    assert report.download_name(2026) == "Planes tv corte 2026-10.xlsx"
    # Un solo registro en Cortes generados: el de desarrollo queda reemplazado (sus archivos de prueba se retiran)
    runs = report.runs()
    assert [r["disparo"] for r in runs] == ["inicial"] and runs[0]["observacion"] == obs
    assert not (settings.REPORT_DIR / dev["excel"]).exists()
    assert not (settings.REPORT_DIR / "snapshots" / dev["snapshot"]).exists()
    snap = json.loads((settings.REPORT_DIR / "snapshots" / "2026-11-03.json").read_text(encoding="utf-8"))
    assert snap["periodo"] == "2026-10" and snap["observacion"] == obs and snap["filas"] == len(api_rows(ROWS))
    # Noviembre sigue siendo automático y queda después de octubre
    assert report.pending_cut(NOV30) == (NOV30, "2026-11", "fin_de_mes")
    _cut(api_rows(ROWS), NOV30)
    assert [c["encabezado"] for c in report.summary()["columnas"]][-3:] == ["30-sep", "31-oct", "30-nov"]


def test_dev_cut_is_listed_but_keeps_official_excel(workdir):
    before = _book().read_bytes()
    res = report.take_dev_cut(fecha=NOV3, client_factory=lambda: FakeClient(api_rows(ROWS)))
    assert res["observacion"] == "Corte generado en el desarrollo de la aplicación" and res["total"] == 23
    assert _book().read_bytes() == before and report.registry() == {}
    assert report.pending_cut(NOV30) == (NOV30, "2026-11", "fin_de_mes")  # no cuenta como corte de noviembre
    dev = settings.REPORT_DIR / res["excel"]
    assert dev.name == "Planes tv corte 2026-11-03 (desarrollo).xlsx"
    assert openpyxl.load_workbook(dev, read_only=True).sheetnames[-1] == "03NOV2026"
    snap = json.loads((settings.REPORT_DIR / "snapshots" / res["snapshot"]).read_text(encoding="utf-8"))
    assert snap["observacion"] == res["observacion"] and snap["filas"] == len(api_rows(ROWS))
    assert report.runs()[0]["disparo"] == "desarrollo"


def test_failed_query_leaves_excel_untouched(workdir):
    before = _book().read_bytes()

    class Boom(FakeClient):
        def report_rows(self):
            raise ERPNextError("ERPNext no está disponible en este momento.", "503", retryable=True)

    with pytest.raises(report.ReportError) as exc:
        report.take_cut("schedule", fecha=NOV30, client_factory=lambda: Boom([]))
    assert exc.value.code == "retryable"
    assert _book().read_bytes() == before
    assert report.runs()[0]["estado"] == "fallida"


# ---------------------------------------------------------------- cliente HTTP
def test_client_sends_the_report_request_and_retries(monkeypatch):
    monkeypatch.setattr(settings, "ERPNEXT_API_KEY", "key")
    monkeypatch.setattr(settings, "ERPNEXT_API_SECRET", "secret")
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if len(seen) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": api_rows({"Plan A": {"Active": 1}})})

    with ERPNextClient(transport=httpx.MockTransport(handler), sleep=lambda _s: None) as c:
        rows = c.report_rows()
    assert len(rows) == 1 and len(seen) == 2
    req = seen[-1]
    assert req.url.path == "/api/resource/Subscription" and req.headers["Authorization"] == "token key:secret"
    fields = json.loads(req.url.params["fields"])
    assert "plans.plan as plan" in fields and "status" in fields and "filters" not in req.url.params


# ---------------------------------------------------------------- API
def test_api(workdir):
    from app.main import app
    dev = report.take_dev_cut(fecha=NOV3, client_factory=lambda: FakeClient(api_rows(ROWS)))
    _cut(api_rows(ROWS), NOV30)
    with TestClient(app) as client:
        assert client.get("/api/reporte").status_code == 401
        assert client.post("/api/auth/dev-login", json={"email": "ana@gigafibra.co"}).status_code == 200
        meta = client.get("/api/meta").json()
        assert meta["origen"] == "ERPNext API Gigafibra" and "postman" not in json.dumps(meta).lower()
        assert meta["excel"]["nombre"] == "Planes tv corte 2026-11.xlsx"
        assert client.post("/api/cortes", json={}).status_code in (404, 405)
        cortes = client.get("/api/cortes").json()["cortes"]
        assert [c["disparo"] for c in cortes[:2]] == ["schedule", "desarrollo"]
        x = client.get("/api/descargas/excel")
        assert x.status_code == 200 and "Planes%20tv%20corte%202026-11.xlsx" in x.headers["content-disposition"]
        d = client.get(f"/api/descargas/excel?corte={dev['id']}")
        assert d.status_code == 200 and "desarrollo" in d.headers["content-disposition"]
        assert client.get(f"/api/descargas/snapshots/{dev['snapshot']}").json()["observacion"]
        assert client.get("/api/descargas/snapshots/..%2F..%2F.env").status_code in (400, 404)
