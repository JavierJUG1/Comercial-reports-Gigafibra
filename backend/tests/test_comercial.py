"""Cards comerciales: leads convertidos e ingresos por plan de TV (ERPNext simulado)."""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import comercial, report

TV = ["Plan A", "Plan B", "Plan C"]


def _ver(sub, when, removed=(), changed=()):
    """Fila de Version como la devuelve ERPNext (solo lo que lee el backend)."""
    data = {"added": [], "changed": [], "removed": [["plans", {"plan": p, "idx": i}] for p, i in removed],
            "row_changed": [["plans", i - 1, "x", [["plan", old, new]]] for old, new, i in changed]}
    return {"docname": sub, "creation": f"{when} 10:00:00", "data": json.dumps(data)}


def _inv(name, fecha, sub, base, lines, ret=0):
    return [{"name": name, "posting_date": fecha, "custom_subscription": sub, "is_return": ret, "grand_total": base,
             "rounded_total": base, "item_idx": idx, "net_amount": net} for idx, net in lines]


def _pay(name, fecha, factura, valor):
    return {"name": name, "posting_date": fecha, "reference_doctype": "Sales Invoice", "reference_name": factura,
            "allocated_amount": valor}


# Corte de septiembre (hoja 30SEP2026 del Excel de prueba): SUS-0001…0011 = Plan A, SUS-0012…0013 = Plan B
DATA = {
    "leads": [
        {"name": "L1", "status": "Converted", "custom_activation_date": "2026-09-03 09:00:00", "custom_subscription": "S1",
         "plan": "Internet 500"},
        {"name": "L1", "status": "Converted", "custom_activation_date": "2026-09-03 09:00:00", "custom_subscription": "S1",
         "plan": "Plan A"},
        {"name": "L2", "status": "Converted", "custom_activation_date": "2026-09-15 10:00:00", "custom_subscription": "S2",
         "plan": "Internet 500"},
        {"name": "L3", "status": "Converted", "custom_activation_date": "2026-09-30 23:10:00", "custom_subscription": "S3",
         "plan": None},
        {"name": "L4", "status": "Converted", "custom_activation_date": "2026-08-10 08:00:00", "custom_subscription": "S4",
         "plan": "Plan B"},
    ],
    "facturas": (
        _inv("FAC1", "2026-09-05", "SUS-0001", 119000, [(2, 25000)])            # corte → Plan A
        + _inv("FAC2", "2026-09-06", "SUS-0012", 100000, [(2, 20000)])          # corte → Plan B (pago parcial)
        + _inv("FAC3", "2026-09-07", "SUS-0900", 10000, [(3, 3000), (2, 1000)])  # actual: Plan C (idx 2), Plan B (idx 3)
        + _inv("FAC4", "2026-08-20", "SUS-0950", 50000, [(2, 5000)])            # historial: Plan C quitado en octubre
        + _inv("NC1", "2026-09-10", "SUS-0002", -59500, [(2, -5000)], ret=1)     # nota crédito → Plan A
        + _inv("FAC6", "2026-09-11", "SUS-0960", 10000, [(2, 2000)])            # sin rastro del plan → retirado
        + _inv("VIEJA", "2024-01-05", "SUS-0001", 10000, [(2, 9999)])           # fuera de la ventana de 12 meses
        + _inv("FAC7", "2026-10-02", "SUS-0003", 1190, [(2, 1000)])             # emitida después: pago anticipado
    ),
    "pagos": [
        _pay("PE1", "2026-09-08", "FAC1", 119000),
        _pay("PE2", "2026-09-09", "FAC2", 50000),
        _pay("PE3", "2026-09-09", "FAC3", 10000),
        _pay("PE4", "2026-09-12", "FAC4", 50000),
        _pay("PE5", "2026-09-12", "NC1", -59500),
        _pay("PE6", "2026-09-13", "FAC6", 10000),
        _pay("PE7", "2026-09-13", "FAC-INTERNET", 89900),  # factura sin TV: no cuenta
        _pay("PE8", "2026-09-14", "VIEJA", 10000),
        _pay("PE9", "2026-08-30", "FAC4", 1),               # otro mes
        _pay("PE10", "2026-09-28", "FAC7", 1190),           # entró en septiembre aunque la factura sea de octubre
    ],
    "subs": [{"name": "SUS-0900", "status": "Active", "plan": "Plan B", "plan_idx": 3},
             {"name": "SUS-0900", "status": "Active", "plan": "Plan C", "plan_idx": 2},
             {"name": "SUS-0001", "status": "Active", "plan": "Plan B", "plan_idx": 2}],  # hoy distinto al corte
    "versiones": [_ver("SUS-0950", "2026-07-01", removed=[("Plan A", 2)]),   # antes de la factura: no aplica
                  _ver("SUS-0950", "2026-10-01", removed=[("Plan C", 2)])],
}


class FakeERP:
    def __init__(self, data=DATA):
        self.data = data
        self.calls: list[tuple[str, dict]] = []
        self.attempts = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def get(self, path, params):
        self.calls.append((path, params))
        f = json.loads(params["filters"])
        if path == "/api/resource/Lead":
            lo, hi = f[1][2][:10], f[2][2][:10]
            rows = [r for r in self.data["leads"] if lo <= r["custom_activation_date"][:10] < hi]
        elif path == "/api/resource/Payment Entry":
            lo, hi = f[2][2], f[3][2]
            rows = [r for r in self.data["pagos"] if lo <= r["posting_date"] <= hi]
        elif path == "/api/resource/Sales Invoice":
            lo, hi = f[1][2], f[2][2]
            rows = [r for r in self.data["facturas"] if lo <= r["posting_date"] <= hi]
        elif path == "/api/resource/Subscription":
            rows = self.data["subs"]
        elif path == "/api/resource/Version":
            rows = [r for r in self.data["versiones"] if r["docname"] in f[1][2]]
        else:
            raise AssertionError(path)
        return {"data": rows}


def _at(monkeypatch, y, m, d):
    monkeypatch.setattr(report, "now", lambda: datetime(y, m, d, 7, 0, tzinfo=ZoneInfo("America/Bogota")))


# ---------------------------------------------------------------- piezas
def test_periods_and_bounds():
    needed = comercial.periods_needed(["2026-01", "2025-12", "2026-03"])
    assert needed[0] == "2025-01" and needed[-1] == "2026-03" and len(needed) == 15  # 11 meses antes del primer corte
    b = comercial.bounds("2026-01")
    assert (str(b["desde"]), str(b["hasta"]), str(b["hasta_excl"]), str(b["facturas_desde"])) == \
        ("2026-01-01", "2026-01-31", "2026-02-01", "2025-01-01")
    assert comercial.previous("2026-01") == "2025-12"


def test_request_fills_postman_placeholders():
    path, http, filled = comercial.request("suscripciones_tv", planes_tv=TV)
    assert path == "/api/resource/Subscription"
    assert json.loads(http["filters"]) == [["Subscription Plan Detail", "plan", "in", TV]]
    _, http, _ = comercial.request("facturas_tv", facturas_desde="2025-10-01", hasta="2026-10-31")
    assert ["Sales Invoice Item", "item_code", "=", "Canais de TV"] in json.loads(http["filters"])
    assert "{" not in http["filters"]


def test_leads_are_counted_once_and_flagged_with_tv():
    out = comercial.compute_leads(DATA["leads"][:4], set(TV))
    assert (out["convertidos"], out["con_tv"], out["por_plan_tv"]) == (3, 1, {"Plan A": 1})
    assert out["detalle"][0]["planes"] == ["Internet 500", "Plan A"]
    # Un lead con dos planes de TV cuenta una vez: las combinaciones permiten filtrar por planes sin repetir
    two = [{"name": "L9", "plan": "Plan A", "custom_activation_date": "2026-09-01"},
           {"name": "L9", "plan": "Plan B", "custom_activation_date": "2026-09-01"}]
    out = comercial.compute_leads(DATA["leads"][:4] + two, set(TV))
    assert out["con_tv"] == 2 and out["por_plan_tv"] == {"Plan A": 2, "Plan B": 1}
    assert out["combinaciones_tv"] == [{"planes": ["Plan A"], "leads": 1}, {"planes": ["Plan A", "Plan B"], "leads": 1}]


def test_plan_resolution_order():
    cut = {"S1": ["Plan A"]}
    later = [{"S2": ["Plan B"]}]
    live = {"S1": ["Plan C"], "S2": ["Plan C"], "S3": ["Plan B", "Plan A"]}
    hist = comercial.removed_plans([_ver("S4", "2026-03-01", removed=[("Plan A", 2)]),
                                    _ver("S4", "2026-06-01", changed=[("Plan B", "Internet 1G", 3)]),
                                    _ver("S5", "2025-01-01", removed=[("Plan C", 2)])], set(TV))
    f = comercial.resolver(cut, live, later, hist)
    assert f("S1", "2026-09-01") == (["Plan A"], "corte")
    assert f("S2", "2026-09-01") == (["Plan B"], "corte_posterior")
    assert f("S3", "2026-09-01") == (["Plan B", "Plan A"], "suscripcion")
    assert f("S4", "2026-02-15") == (["Plan A", "Plan B"], "historial")  # ambos estaban al facturar (orden idx)
    assert f("S4", "2026-04-15") == (["Plan B"], "historial")            # Plan A ya se había quitado
    assert f("S5", "2026-09-01") == (["Plan C"], "historial")            # último plan conocido
    assert f("S9", "2026-09-01") == ([], "retirado")


def test_lines_go_to_the_plan_that_matches_their_value():
    costos = {"TV Free": 0, "TV 1 SetBox": 8319.33, "Disney": 25126.05}
    # La suscripción lista primero el plan gratis: igual la línea pagada va al plan pagado y la de $ 0 al gratis
    assert comercial.pair_lines([(2, 1878.56), (3, 0.0)], ["TV Free", "TV 1 SetBox"], costos) == \
        [(1878.56, "TV 1 SetBox"), (0.0, "TV Free")]
    assert comercial.pair_lines([(2, 0.0), (3, 25126.05), (4, 8319.33)], ["TV 1 SetBox", "TV Free", "Disney"], costos) == \
        [(25126.05, "Disney"), (8319.33, "TV 1 SetBox"), (0.0, "TV Free")]
    assert comercial.pair_lines([(2, -5000.0)], ["TV 1 SetBox"], costos) == [(-5000.0, "TV 1 SetBox")]  # nota crédito
    assert comercial.pair_lines([(2, 10.0), (3, 20.0)], ["TV 1 SetBox"], costos) == [(10.0, "TV 1 SetBox"), (20.0, "TV 1 SetBox")]
    assert comercial.pair_lines([(2, 10.0)], [], costos) == [(10.0, None)]
    # Mismo costo: se respeta el orden de la tabla de planes
    assert comercial.pair_lines([(2, 5.0), (3, 5.0)], ["A", "B"]) == [(5.0, "A"), (5.0, "B")]


def test_free_plan_never_collects():
    costos = {"Free": 0, "Paid": 25126.05}
    hist = comercial.removed_plans([_ver("S1", "2026-09-20", removed=[("Paid", 2)])], {"Free", "Paid"})
    f = comercial.resolver({"S1": ["Free"], "S2": ["Free"]}, {}, [], hist, costos)
    # Factura del 1 de septiembre: el plan pagado se quitó el 20 → estaba al facturar
    assert f("S1", "2026-09-01") == (["Paid", "Free"], "corte+historial")
    assert f("S1", "2026-10-01") == (["Free"], "corte")
    lineas = _inv("F1", "2026-09-01", "S1", 1190, [(2, 1000), (3, 0)]) + _inv("F2", "2026-09-01", "S2", 595, [(2, 500)])
    out = comercial.compute_ingresos([_pay("P1", "2026-09-05", "F1", 1190), _pay("P2", "2026-09-05", "F2", 595)], lineas, f,
                                     ["Paid", "Free"], costos)
    assert out["por_plan"]["Paid"]["ingreso"] == 1000 and out["por_plan"]["Free"]["ingreso"] == 0
    assert out["retirado"] == 500  # S2 solo tiene el plan gratis y no hay historial: no se le atribuye al gratis


def test_tv_income_is_the_tv_share_of_each_payment():
    plan_de = comercial.resolver({"SUS-0001": ["Plan A"], "SUS-0002": ["Plan A"], "SUS-0003": ["Plan A"],
                                  "SUS-0012": ["Plan B"]},
                                 comercial.live_plans(DATA["subs"]), [],
                                 comercial.removed_plans(DATA["versiones"], set(TV)))
    pagos = [p for p in DATA["pagos"] if p["posting_date"].startswith("2026-09")]
    lineas = [r for r in DATA["facturas"] if r["name"] != "VIEJA"]
    out = comercial.compute_ingresos(pagos, lineas, plan_de, TV)
    por = {p: v["ingreso"] for p, v in out["por_plan"].items()}
    # Plan A: FAC1 25.000 − NC1 5.000 + FAC7 1.000 (anticipado) · Plan B: mitad de FAC2 20.000 + FAC3 3.000
    # Plan C: FAC3 1.000 + FAC4 5.000 · FAC6 sin plan
    assert por == {"Plan A": 21000, "Plan B": 13000, "Plan C": 6000}
    assert out["retirado"] == 2000 and out["total"] == 42000
    assert out["facturas"] == 7 and out["pagos"] == 7
    assert out["por_plan"]["Plan B"]["facturas"] == 2
    assert out["plan_segun"] == {"corte": 4, "suscripcion": 1, "historial": 1, "retirado": 1}
    assert list(out["por_plan"]) == ["Plan A", "Plan B", "Plan C"]  # de mayor a menor


# ---------------------------------------------------------------- de punta a punta
def test_ensure_saves_each_month_and_freezes_closed_months(workdir, monkeypatch):
    _at(monkeypatch, 2026, 10, 3)
    fake = FakeERP()
    res = comercial.ensure(client_factory=lambda: fake)
    assert res["error"] is None
    # Cortes del Excel de prueba: dic 2025, ene 2026, ago y sep 2026 → de ene 2025 a sep 2026
    assert res["calculados"][0] == "2025-01" and res["calculados"][-1] == "2026-09" and len(res["calculados"]) == 21
    sep = comercial.load("2026-09")
    assert sep["leads"]["convertidos"] == 3 and sep["leads"]["con_tv"] == 1
    assert sep["ingresos"]["por_plan"]["Plan A"]["ingreso"] == 21000  # SUS-0001 es Plan A en el corte (hoy Plan B)
    # Recaudo del mes, sin acumular: PE9 (pago del 30 de agosto) no entra en septiembre; PE10 (28 de septiembre, factura
    # emitida en octubre) sí, porque el dinero entró en septiembre; la factura VIEJA (2024) queda fuera de la ventana
    assert sep["ingresos"]["total"] == 42000
    assert sep["planes_segun"]["corte"]["archivo"] == "30SEP2026" and "detalle" not in sep["ingresos"]
    assert sep["definitivo"] is False  # calculado el 3 de octubre: aún puede recibir pagos con fecha de septiembre
    ago = comercial.load("2026-08")
    assert ago["leads"]["convertidos"] == 1 and ago["ingresos"]["total"] == pytest.approx(0.1)
    det = json.loads(comercial.detail_path("2026-09").read_text(encoding="utf-8"))
    assert det["consultas"]["leads"]["parametros"]["filters"][1] == ["custom_activation_date", ">=", "2026-09-01 00:00:00"]
    assert det["consultas"]["pagos"]["peticion_id"].startswith("37183144-")
    assert {d["plan_segun"] for d in det["ingresos"]["detalle"]} == {"corte", "suscripcion", "historial", "retirado"}
    inv_calls = [p for path, p in fake.calls if path == "/api/resource/Sales Invoice"]
    assert len(inv_calls) == 1 and json.loads(inv_calls[0]["filters"])[1] == ["posting_date", ">=", "2024-01-01"]

    # Días después: solo se recalcula septiembre (el único que no era definitivo) y queda fijo
    _at(monkeypatch, 2026, 10, 7)
    fake2 = FakeERP()
    res = comercial.ensure(client_factory=lambda: fake2)
    assert res["calculados"] == ["2026-09"] and comercial.load("2026-09")["definitivo"] is True
    assert comercial.ensure(client_factory=lambda: FakeERP())["calculados"] == []


def test_api_comercial(workdir, monkeypatch):
    from app.main import app
    _at(monkeypatch, 2026, 11, 4)
    comercial.ensure(["2026-09"], client_factory=lambda: FakeERP())
    with TestClient(app) as client:
        assert client.get("/api/comercial").status_code == 401
        assert client.post("/api/auth/dev-login", json={"email": "ana@gigafibra.co"}).status_code == 200
        body = client.get("/api/comercial").json()
        assert list(body["periodos"]) == ["2026-09"] and body["en_curso"] is False
        assert "detalle" not in json.dumps(body)
        d = client.get("/api/descargas/comercial/2026-09")
        assert d.status_code == 200 and d.json()["ingresos"]["detalle"]
        assert client.get("/api/descargas/comercial/2026-13").status_code == 400
        assert client.get("/api/descargas/comercial/2026-01").status_code == 404


# ---------------------------------------------------------------- Excel de cada card
def _xlsx(content):
    import io

    import openpyxl
    return openpyxl.load_workbook(io.BytesIO(content), read_only=True)


def _cells(ws):
    return [c for row in ws.iter_rows(values_only=True) for c in row if c is not None]


def test_card_downloads(workdir, monkeypatch):
    from app.main import app
    _at(monkeypatch, 2026, 11, 4)
    comercial.ensure(["2026-08", "2026-09"], client_factory=lambda: FakeERP())
    with TestClient(app) as client:
        assert client.get("/api/descargas/tarjeta/segmentos?periodo=2026-09").status_code == 401
        client.post("/api/auth/dev-login", json={"email": "ana@gigafibra.co"})

        # Mes del Excel inicial sin detalle (columna "dec"): se dice de dónde salen las cantidades
        r = client.get("/api/descargas/tarjeta/segmentos?periodo=2025-12")
        assert r.status_code == 200 and "Suscripciones%20por%20segmento%202025-12.xlsx" in r.headers["content-disposition"]
        wb = _xlsx(r.content)
        assert "Sin detalle" in wb.sheetnames and "Suscripciones del corte" not in wb.sheetnames
        assert any("Excel inicial del proyecto" in str(c) for c in _cells(wb["Resumen"]))

        # Mes con hoja cruda (30SEP2026): cada suscripción que cuenta; suma igual al total del corte
        wb = _xlsx(client.get("/api/descargas/tarjeta/lider?periodo=2026-09").content)
        det = list(wb["Suscripciones del corte"].iter_rows(min_row=4, values_only=True))
        assert len(det) == 10 and {d[1] for d in det} == {"Active", "Past Due Date"}
        assert any("Segmento con más suscripciones" in str(c) for c in _cells(wb["Resumen"]))

        # Recaudo: la hoja de pagos suma el total del mes
        wb = _xlsx(client.get("/api/descargas/tarjeta/recaudo?periodo=2026-09").content)
        pagos = list(wb["Pagos"].iter_rows(min_row=4, values_only=True))
        assert round(sum(p[9] for p in pagos)) == 42000
        assert "Recaudo por mes" in wb.sheetnames

        # Leads TV con el filtro de planes de la card
        r = client.get("/api/descargas/tarjeta/leads?periodo=2026-09&plan=Plan%20B")
        assert "filtrado" in r.headers["content-disposition"]
        wb = _xlsx(r.content)
        assert [x for x in wb["Leads TV"].iter_rows(min_row=4, values_only=True) if any(x)] == []  # sin leads con Plan B
        wb = _xlsx(client.get("/api/descargas/tarjeta/leads?periodo=2026-09").content)
        assert [row[0] for row in wb["Leads TV"].iter_rows(min_row=4, values_only=True)] == ["L1"]

        assert client.get("/api/descargas/tarjeta/otra?periodo=2026-09").status_code == 400
        assert client.get("/api/descargas/tarjeta/recaudo?periodo=2026-01").status_code == 404
        assert client.get("/api/descargas/tarjeta/segmentos?periodo=2026-05").status_code == 404  # mes sin corte
