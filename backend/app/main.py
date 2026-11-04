"""API del reporte mensual de suscripciones de TV + frontend compilado (un solo proceso)."""
from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import auth, comercial, descargas, report, scheduler
from .config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tva.main")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.APP_ENV == "production" and settings.SECRET_KEY in ("dev-only-change-me", "cambia-esta-clave", ""):
        raise RuntimeError("SECRET_KEY de producción sin definir en backend/.env")
    report.report_dir()
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

if settings.APP_ENV != "production" and settings.CORS_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    if request.url.path.startswith(f"{settings.BASE_PATH}/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


api = APIRouter(prefix=f"{settings.BASE_PATH}/api")


def current_user(request: Request) -> dict:
    return auth.require_user(request)


# ------------------------------------------------------------------ sesión
@api.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "time": report.now().isoformat()}


@api.get("/auth/config")
def auth_config() -> dict[str, Any]:
    return {"mode": settings.AUTH_MODE, "oauth_configured": auth.oauth_configured(),
            "allowed_domains": settings.ALLOWED_EMAIL_DOMAINS, "env_label": settings.ENV_LABEL}


@api.get("/auth/me")
def me(request: Request) -> dict[str, Any]:
    user = auth.read_session(request)
    return {"authenticated": bool(user), "user": user}


class DevLogin(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    name: str | None = Field(default=None, max_length=200)


@api.post("/auth/dev-login")
def dev_login(body: DevLogin, response: Response) -> dict[str, Any]:
    if settings.AUTH_MODE != "debug":
        raise HTTPException(status_code=404)
    email = body.email.strip().lower()
    if "@" not in email or not auth.email_allowed(email):
        raise HTTPException(status_code=403, detail="Usa tu correo corporativo de Gigafibra.")
    user = auth.make_user(email, body.name or "", [], "debug")
    auth.set_session(response, user)
    return {"user": user}


@api.get("/auth/login")
def login(next: str | None = None) -> RedirectResponse:  # noqa: A002
    if settings.AUTH_MODE != "erpnext" or not auth.oauth_configured():
        return RedirectResponse(f"{settings.BASE_PATH}/login")
    resp = RedirectResponse("/", status_code=302)
    resp.headers["location"] = auth.oauth_start_url(resp, next)
    return resp


@api.get("/auth/callback")
def callback(request: Request, code: str = "", state: str = "") -> RedirectResponse:
    try:
        user = auth.oauth_finish(request, code, state)
    except HTTPException as exc:
        return RedirectResponse(f"{settings.BASE_PATH}/login?error={quote(str(exc.detail))}")
    target = auth.oauth_next(request) or "/"
    resp = RedirectResponse(f"{settings.BASE_PATH}{target}" if target != "/" else f"{settings.BASE_PATH}/")
    auth.set_session(resp, user)
    resp.delete_cookie(auth.OAUTH_COOKIE, path=settings.BASE_PATH or "/")
    return resp


@api.post("/auth/logout")
def logout(response: Response) -> dict[str, bool]:
    auth.clear_session(response)
    return {"ok": True}


# ------------------------------------------------------------------ reporte
@api.get("/meta")
def meta(user: dict = Depends(current_user)) -> dict[str, Any]:
    runs = report.runs()
    last = next((r for r in runs if r.get("estado") in ("exitosa", "fallida")), None)
    books = report.workbooks()
    return {
        "app": {"name": settings.APP_NAME, "env_label": settings.ENV_LABEL, "timezone": settings.TIMEZONE},
        "user": user,
        "erp": {"configured": settings.erp_configured},
        "origen": "ERPNext API Gigafibra",
        "estados": settings.COUNT_STATUSES,
        "programacion": {"activa": settings.SCHEDULER_ENABLED, "proxima": scheduler.next_run(),
                         "regla": f"Último día de cada mes, {settings.SYNC_HOUR:02d}:{settings.SYNC_MINUTE:02d}",
                         "desde": settings.REPORT_START},
        "excel": {"existe": bool(books), "nombre": report.download_name(books[-1][0]) if books else None},
        "en_curso": report.running(),
        "ultima": last,
    }


@api.get("/reporte")
def get_report(_: dict = Depends(current_user)) -> dict[str, Any]:
    try:
        return report.summary()
    except report.ReportError as exc:
        raise HTTPException(status_code=404, detail=exc.message)


@api.get("/cortes")
def get_runs(_: dict = Depends(current_user)) -> dict[str, Any]:
    return {"cortes": report.runs()[:100]}


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@api.get("/descargas/excel")
def download_excel(anio: int | None = None, corte: str | None = None, _: dict = Depends(current_user)) -> FileResponse:
    """Libro del año indicado (por defecto el más reciente) o el Excel de un corte del historial."""
    books = dict(report.workbooks())
    if corte:
        run = report.find_run(corte)
        if run is None:
            raise HTTPException(status_code=404, detail="Corte no encontrado.")
        if run.get("excel"):  # Excel propio (corte de desarrollo)
            path = (report.report_dir() / run["excel"]).resolve()
            if report.report_dir().resolve() not in path.parents or not path.is_file():
                raise HTTPException(status_code=404, detail="Excel del corte no encontrado.")
            return FileResponse(path, filename=path.name, media_type=XLSX)
        anio = int(run.get("libro") or run["fecha_corte"][:4])
    if not books:
        raise HTTPException(status_code=404, detail="Aún no hay Excel del reporte.")
    year = anio if anio in books else max(books)
    return FileResponse(books[year], filename=report.download_name(year), media_type=XLSX)


@api.get("/comercial")
def get_comercial(_: dict = Depends(current_user)) -> dict[str, Any]:
    """Cards comerciales por mes: leads convertidos e ingresos por plan de TV (sin el detalle de filas)."""
    st = comercial.state()
    return {"periodos": comercial.summaries(), "en_curso": st["en_curso"], "error": st["error"],
            "regla_dias": settings.COMERCIAL_REFRESH_DAYS}


_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@api.get("/descargas/comercial/{periodo}")
def download_comercial(periodo: str, _: dict = Depends(current_user)) -> FileResponse:
    """Detalle del cálculo de un mes (.json): peticiones usadas, leads y pagos con su parte de TV."""
    if not _PERIOD_RE.match(periodo):
        raise HTTPException(status_code=400, detail="Periodo inválido.")
    path = comercial.detail_path(periodo)
    if path is None:
        raise HTTPException(status_code=404, detail="Aún no hay indicadores para ese mes.")
    return FileResponse(path, filename=f"Comercial {periodo}.json", media_type="application/json")


@api.get("/descargas/tarjeta/{tarjeta}")
def download_card(tarjeta: str, periodo: str, plan: list[str] | None = Query(default=None),
                  _: dict = Depends(current_user)) -> Response:
    """Excel de una card del portal (segmentos, lider, recaudo, leads) para el mes elegido, con su detalle."""
    if not _PERIOD_RE.match(periodo):
        raise HTTPException(status_code=400, detail="Periodo inválido.")
    try:
        data, name = descargas.build(tarjeta, periodo, plan)
    except descargas.DownloadError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)
    except report.ReportError as exc:
        raise HTTPException(status_code=404, detail=exc.message)
    return Response(data, media_type=XLSX, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


_SNAPSHOT_RE = re.compile(r"^[A-Za-z0-9_\-]+\.json$")


@api.get("/descargas/snapshots/{name}")
def download_snapshot(name: str, _: dict = Depends(current_user)) -> FileResponse:
    if not _SNAPSHOT_RE.match(name):
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido.")
    path = report.report_dir() / "snapshots" / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Snapshot no encontrado.")
    return FileResponse(path, filename=name, media_type="application/json")


app.include_router(api)


@app.exception_handler(Exception)
async def unhandled(_request: Request, exc: Exception) -> JSONResponse:  # pragma: no cover
    log.exception("Error no controlado: %s", exc)
    return JSONResponse({"detail": "Error interno del servidor."}, status_code=500)


# ------------------------------------------------------------------ frontend (SPA)
@app.api_route(f"{settings.BASE_PATH}/{{path:path}}", methods=["GET", "HEAD"], include_in_schema=False)
def spa(path: str) -> Response:
    dist = settings.FRONTEND_DIST
    if path.startswith("api/"):
        raise HTTPException(status_code=404)
    target = (dist / path).resolve() if path else None
    if target and target.is_file() and dist.resolve() in target.parents:
        headers = {"Cache-Control": "public, max-age=31536000, immutable"} if path.startswith("assets/") else {}
        return FileResponse(target, headers=headers)
    index = dist / "index.html"
    if index.exists():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return JSONResponse({"detail": "Frontend sin compilar: ejecuta `npm run build` en frontend/."}, status_code=404)
