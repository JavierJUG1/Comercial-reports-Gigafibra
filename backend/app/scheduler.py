"""Corte automático: último día de cada mes a SYNC_HOUR:SYNC_MINUTE (America/Bogota), desde REPORT_START.

- Es la única forma de generar cortes desde el portal (no hay botón manual).
- Si falla por un error transitorio, se reintenta cada SYNC_RETRY_MINUTES (hasta SYNC_RETRY_MAX).
- Al arrancar: si el servidor estuvo apagado al cierre de un mes, toma ese corte pendiente con la fecha real.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from . import report
from .config import settings

log = logging.getLogger("tva.scheduler")
_scheduler: BackgroundScheduler | None = None
JOB_ID = "corte_mensual"


def _cron() -> CronTrigger:
    if settings.SYNC_DAY != "LAST_DAY_OF_MONTH":
        log.warning("SYNC_DAY=%s no es compatible; se usa LAST_DAY_OF_MONTH.", settings.SYNC_DAY)
    return CronTrigger(day="last", hour=settings.SYNC_HOUR, minute=settings.SYNC_MINUTE,
                       timezone=settings.TIMEZONE, start_date=report.start_month().isoformat())


def _run(trigger: str, retry: int = 0) -> None:
    if not settings.erp_configured:
        log.warning("Corte omitido: faltan credenciales de ERPNext.")
        return
    pending = report.pending_cut()
    if pending is None:
        log.info("Corte (%s): no hay corte pendiente.", trigger)
        return
    fecha, periodo, _motivo = pending
    try:
        res = report.take_cut(trigger, fecha=fecha, periodo=periodo)
        log.info("Corte (%s): %s", trigger, res.get("mensaje"))
    except report.ReportError as exc:
        log.warning("Corte (%s) falló: %s", trigger, exc.message)
        if exc.code in ("retryable", "error", "locked", "excel") and retry < settings.SYNC_RETRY_MAX and _scheduler:
            when = report.now() + timedelta(minutes=settings.SYNC_RETRY_MINUTES)
            _scheduler.add_job(_run, DateTrigger(run_date=when), args=["retry", retry + 1], id="reintento",
                               replace_existing=True, misfire_grace_time=3600)
            log.info("Reintento %s/%s programado para %s", retry + 1, settings.SYNC_RETRY_MAX, when.isoformat())


def _monthly_job() -> None:
    _run("schedule")


def catch_up() -> None:
    """Al arrancar: corte de un mes cerrado que quedó sin tomar, o el de hoy si ya pasó la hora programada."""
    pending = report.pending_cut()
    if pending is None:
        return
    _fecha, _periodo, reason = pending
    t = report.now()
    if reason == "recuperacion" or (t.hour, t.minute) >= (settings.SYNC_HOUR, settings.SYNC_MINUTE):
        log.info("Recuperación: corte pendiente (%s); se toma ahora.", reason)
        _run("catch_up")


def start() -> BackgroundScheduler | None:
    global _scheduler
    if not settings.SCHEDULER_ENABLED or _scheduler is not None:
        return _scheduler
    sched = BackgroundScheduler(timezone=settings.TIMEZONE)
    sched.add_job(_monthly_job, _cron(), id=JOB_ID, replace_existing=True, misfire_grace_time=6 * 3600,
                  coalesce=True, max_instances=1)
    sched.start()
    _scheduler = sched
    log.info("Corte mensual programado; próxima ejecución: %s", next_run())
    if settings.CATCH_UP_ON_START and report.has_workbook():
        sched.add_job(catch_up, DateTrigger(run_date=report.now() + timedelta(seconds=10)), id="recuperacion",
                      replace_existing=True)
    return sched


def next_run() -> str | None:
    if _scheduler is not None:
        job = _scheduler.get_job(JOB_ID)
        if job and job.next_run_time:
            return job.next_run_time.isoformat()
    nxt = _cron().get_next_fire_time(None, report.now())
    return nxt.isoformat() if nxt else None


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
