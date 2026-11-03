"""Reporte mensual de suscripciones de TV desde la consola (desde backend/).

El corte es AUTOMÁTICO (último día de cada mes, 23:50). Estos comandos son para instalación y soporte:

    .venv\\Scripts\\python -m scripts.reporte inicializar "C:\\...\\planes TV 2026 (actualizado septiembre).xlsx"
    .venv\\Scripts\\python -m scripts.reporte probar      # ejecuta la consulta y muestra los conteos (no guarda nada)
    .venv\\Scripts\\python -m scripts.reporte pendiente   # toma el corte solo si hay uno pendiente (p. ej. servidor apagado)
    .venv\\Scripts\\python -m scripts.reporte resumen     # recalcula la tabla del portal desde los libros
    .venv\\Scripts\\python -m scripts.reporte desarrollo  # corte de prueba con observación (no toca el Excel oficial)
    .venv\\Scripts\\python -m scripts.reporte incluir 2026-11-03-desarrollo.json --periodo 2026-10 --observacion "…"
                                                        # incluye un .json ya guardado como corte de ese mes
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from app import report, scheduler
from app.config import settings
from app.erpnext import ERPNextError, get_client


def _fmt(n: int | None) -> str:
    return "—" if n is None else f"{n:,}".replace(",", ".")


def cmd_inicializar(args: argparse.Namespace) -> int:
    dest = report.import_excel(Path(args.excel), args.anio, replace=args.reemplazar)
    print(f"Excel copiado a {dest} (el original queda en respaldos/)")
    return cmd_resumen(args)


def cmd_probar(_args: argparse.Namespace) -> int:
    print(f"Origen: ERPNext API Gigafibra ({settings.ERPNEXT_URL}) · consulta de suscripciones (vista reporte)")
    t = time.monotonic()
    try:
        with get_client() as client:
            rows = client.report_rows()
    except ERPNextError as exc:
        print(f"✘ {exc.user_message}\n  {exc.detail}", file=sys.stderr)
        return 1
    plans = [p["plan"] for p in report.summary()["planes"]] if report.has_workbook() else []
    cur = report.curation(rows, plans)
    print(f"✔ {_fmt(len(rows))} filas ({_fmt(len({r.get('name') for r in rows}))} suscripciones) en {time.monotonic() - t:.1f}s")
    print("Filas por estado (todas se guardan en el .json):")
    for st, n in cur["filas_por_estado"].items():
        print(f"  {_fmt(n):>7}  {st}")
    print(f"Reporte ({' + '.join(settings.COUNT_STATUSES)}, filas por plan como COUNTIFS):")
    for p, n in cur["reporte"]["por_plan"].items():
        print(f"  {_fmt(n):>7}  {p}")
    print(f"  {_fmt(cur['reporte']['total']):>7}  TOTAL")
    return 0


def cmd_pendiente(args: argparse.Namespace) -> int:
    pending = report.pending_cut()
    if pending is None and not args.rehacer:
        print(f"No hay corte pendiente. Próximo corte automático: {scheduler.next_run()}")
        return 0
    if args.rehacer:
        last = sorted(report.registry())
        if not last:
            print("No hay cortes automáticos para rehacer.")
            return 1
        fecha, periodo = report.now().date(), last[-1]
    else:
        fecha, periodo, _ = pending
    try:
        res = report.take_cut("cli", "consola", fecha=fecha, periodo=periodo, force=args.rehacer)
    except report.ReportError as exc:
        print(f"✘ {exc.message}\n  {exc.detail}", file=sys.stderr)
        return 1
    print(("✔ " if res["estado"] == "exitosa" else "• ") + res.get("mensaje", res["estado"]))
    return 0


def cmd_resumen(_args: argparse.Namespace) -> int:
    s = report.build_summary()
    cols = s["columnas"]
    print(f"{'Plan':<50}" + "".join(f"{c['etiqueta'][:3] + ' ' + str(c['anio'])[2:]:>9}" for c in cols))
    for p in s["planes"]:
        print(f"{p['plan'][:49]:<50}" + "".join(f"{_fmt(v):>9}" for v in p["valores"]))
    print(f"{'TOTAL':<50}" + "".join(f"{_fmt(v):>9}" for v in s["totales"]))
    for lb in s["libros"]:
        print(f"Libro {lb['anio']}: descarga '{lb['descarga']}'")
    return 0


def cmd_desarrollo(_args: argparse.Namespace) -> int:
    try:
        res = report.take_dev_cut()
    except (report.ReportError, ERPNextError) as exc:
        print(f"✘ {getattr(exc, 'message', None) or exc.user_message}", file=sys.stderr)
        return 1
    print("✔ " + res["mensaje"])
    return 0


def cmd_incluir(args: argparse.Namespace) -> int:
    try:
        res = report.include_snapshot(args.snapshot, args.periodo, args.observacion)
    except report.ReportError as exc:
        print(f"✘ {exc.message}\n  {exc.detail}", file=sys.stderr)
        return 1
    print(("✔ " if res["estado"] == "exitosa" else "• ") + res.get("mensaje", res["estado"]))
    if res.get("reemplaza"):
        print(f"  Reemplaza el corte de desarrollo {', '.join(res['reemplaza'])} (mismas filas).")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("inicializar", help="Carga el Excel de referencia como libro de un año")
    p.add_argument("excel")
    p.add_argument("--anio", type=int, default=2026, help="Año del libro (por defecto 2026)")
    p.add_argument("--reemplazar", action="store_true")
    p.set_defaults(fn=cmd_inicializar)
    sub.add_parser("probar", help="Ejecuta la consulta y muestra los conteos sin guardar").set_defaults(fn=cmd_probar)
    g = sub.add_parser("pendiente", help="Toma el corte solo si hay uno pendiente")
    g.add_argument("--rehacer", action="store_true", help="Rehace el último corte (restaura el libro previo)")
    g.set_defaults(fn=cmd_pendiente)
    sub.add_parser("resumen", help="Recalcula la tabla del portal desde los libros").set_defaults(fn=cmd_resumen)
    sub.add_parser("desarrollo", help="Corte de prueba con observación (no toca el Excel oficial)").set_defaults(fn=cmd_desarrollo)
    i = sub.add_parser("incluir", help="Incluye un .json ya guardado como corte de un mes (sin consultar ERPNext)")
    i.add_argument("snapshot", help="Nombre del archivo en snapshots/, p. ej. 2026-11-03-desarrollo.json")
    i.add_argument("--periodo", required=True, help="Mes del reporte, AAAA-MM")
    i.add_argument("--observacion", required=True, help="Nota visible en Cortes generados")
    i.set_defaults(fn=cmd_incluir)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
