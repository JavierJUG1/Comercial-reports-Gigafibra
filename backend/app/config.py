"""Configuración (variables de entorno + backend/.env)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
PROJECT_DIR = BASE_DIR.parent

load_dotenv(os.environ.get("TVA_ENV_FILE") or (BASE_DIR / ".env"))


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _bool(name: str, default: bool) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "si", "sí", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)) or default)
    except ValueError:
        return default


def _list(name: str, default: str = "") -> list[str]:
    raw = _env(name, default) or ""
    return [x.strip() for x in raw.split(",") if x.strip()]


def _path(name: str, default: Path) -> Path:
    value = _env(name)
    if not value:
        return default
    p = Path(value)
    return p if p.is_absolute() else (BASE_DIR / p).resolve()


def _base_path(value: str | None) -> str:
    clean = (value or "").strip().strip("/")
    return f"/{clean}" if clean else ""


class Settings:
    APP_NAME = "Gigafibra TV Analytics"
    APP_ENV = _env("APP_ENV", "development")
    ENV_LABEL = _env("ENV_LABEL", "" if APP_ENV == "production" else "DESARROLLO")
    SECRET_KEY = _env("SECRET_KEY", "dev-only-change-me")
    # Cookie de sesión solo por HTTPS. Por defecto en producción; COOKIE_SECURE=false si el servidor publica por HTTP.
    COOKIE_SECURE = _bool("COOKIE_SECURE", APP_ENV == "production")
    TIMEZONE = _env("TIMEZONE", "America/Bogota")
    BASE_PATH = _base_path(_env("BASE_PATH", ""))
    CORS_ORIGINS = _list("CORS_ORIGINS", "http://localhost:5174,http://127.0.0.1:5174")
    FRONTEND_DIST = _path("FRONTEND_DIST", PROJECT_DIR / "frontend" / "dist")

    # ERPNext (la consulta es la petición de Postman definida en config/consulta_postman.json)
    ERPNEXT_URL = (_env("ERPNEXT_URL", "https://next.gigafibra.co") or "").rstrip("/")
    ERPNEXT_API_KEY = _env("ERPNEXT_API_KEY")
    ERPNEXT_API_SECRET = _env("ERPNEXT_API_SECRET")
    ERPNEXT_TIMEOUT = float(_env("ERPNEXT_TIMEOUT", "300") or 300)
    CONSULTA_FILE = _path("CONSULTA_FILE", BASE_DIR / "config" / "consulta_postman.json")

    # Reporte
    REPORT_DIR = _path("REPORT_DIR", BASE_DIR / "data" / "reporte")
    # Un libro por año: el de 2026 es el Excel recibido; el 31 de enero de 2027 se crea el de 2027, y así cada año.
    EXCEL_FILE_PATTERN = _env("EXCEL_FILE_PATTERN", "planes TV {anio}.xlsx")
    EXCEL_SHEET_PATTERN = _env("EXCEL_SHEET_PATTERN", "Planes TV mensual {anio}")
    EXCEL_TABLE = _env("EXCEL_TABLE", "Tabla2")
    # Nombre de la descarga: "Planes tv corte AAAA-MM" (año-mes del último corte del libro)
    EXCEL_DOWNLOAD_PATTERN = _env("EXCEL_DOWNLOAD_PATTERN", "Planes tv corte {periodo}.xlsx")
    # Respaldos del Excel previos a cada corte que se conservan (el original recibido se guarda siempre)
    EXCEL_BACKUPS_KEEP = _int("EXCEL_BACKUPS_KEEP", 3)
    COUNT_STATUSES = _list("COUNT_STATUSES", "Active,Past Due Date")

    # Programación: último día de cada mes a SYNC_HOUR:SYNC_MINUTE (desde REPORT_START)
    SCHEDULER_ENABLED = _bool("SCHEDULER_ENABLED", True)
    SYNC_DAY = (_env("SYNC_DAY", "LAST_DAY_OF_MONTH") or "LAST_DAY_OF_MONTH").upper()
    SYNC_HOUR = _int("SYNC_HOUR", 23)
    SYNC_MINUTE = _int("SYNC_MINUTE", 50)
    REPORT_START = _env("REPORT_START", "2026-11")  # primer mes con corte automático (AAAA-MM)
    CATCH_UP_ON_START = _bool("CATCH_UP_ON_START", True)
    SYNC_MAX_ATTEMPTS = _int("SYNC_MAX_ATTEMPTS", 3)
    SYNC_RETRY_BACKOFF_SECONDS = float(_env("SYNC_RETRY_BACKOFF_SECONDS", "5") or 5)
    SYNC_RETRY_MINUTES = _int("SYNC_RETRY_MINUTES", 30)
    SYNC_RETRY_MAX = _int("SYNC_RETRY_MAX", 3)

    # Autenticación: debug (formulario local) | erpnext (SSO OAuth2 de ERPNext → Office 365)
    AUTH_MODE = (_env("AUTH_MODE", "debug") or "debug").lower()
    SESSION_HOURS = _int("SESSION_HOURS", 12)
    OAUTH_CLIENT_ID = _env("OAUTH_CLIENT_ID")
    OAUTH_CLIENT_SECRET = _env("OAUTH_CLIENT_SECRET")
    OAUTH_REDIRECT_URI = _env("OAUTH_REDIRECT_URI", "http://localhost:8010/api/auth/callback")
    OAUTH_SCOPES = _env("OAUTH_SCOPES", "openid all")
    ALLOWED_EMAIL_DOMAINS = _list("ALLOWED_EMAIL_DOMAINS", "gigafibra.co")
    ALLOWED_ROLES = _list("ALLOWED_ROLES", "")

    @property
    def erp_configured(self) -> bool:
        return bool(self.ERPNEXT_API_KEY and self.ERPNEXT_API_SECRET)



settings = Settings()
