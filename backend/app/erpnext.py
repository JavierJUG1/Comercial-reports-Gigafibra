"""Cliente de ERPNext (solo backend). Ejecuta la petición de Postman del reporte y consulta roles.

La petición está definida en config/consulta_postman.json, copiada de la colección "ERPNext API" de Postman:
"GET Lista Subscriptions (vista reporte: lead, estrato, ciudad, PPPoE, plan, precio)".
"""
from __future__ import annotations

import json
import logging
import time
from functools import lru_cache
from typing import Any, Callable
from urllib.parse import quote

import httpx

from .config import settings

log = logging.getLogger("tva.erpnext")


class ERPNextError(Exception):
    """Error con mensaje apto para mostrar (sin trazas). `retryable` indica fallas transitorias."""

    def __init__(self, user_message: str, detail: str = "", retryable: bool = False, status: int | None = None):
        super().__init__(user_message)
        self.user_message = user_message
        self.detail = detail or user_message
        self.retryable = retryable
        self.status = status


@lru_cache(maxsize=1)
def consulta() -> dict[str, Any]:
    with open(settings.CONSULTA_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def _error_text(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        return resp.text[:400]
    if isinstance(data, dict):
        for key in ("exception", "exc_type", "message", "_server_messages"):
            if data.get(key):
                return str(data[key])[:400]
    return str(data)[:400]


class ERPNextClient:
    def __init__(self, transport: httpx.BaseTransport | None = None, sleep: Callable[[float], None] = time.sleep):
        if not settings.erp_configured:
            raise ERPNextError("La plataforma no tiene credenciales de ERPNext configuradas.",
                               "Faltan ERPNEXT_API_KEY / ERPNEXT_API_SECRET en backend/.env")
        self.http = httpx.Client(
            base_url=settings.ERPNEXT_URL,
            headers={"Authorization": f"token {settings.ERPNEXT_API_KEY}:{settings.ERPNEXT_API_SECRET}",
                     "Accept": "application/json"},
            timeout=httpx.Timeout(settings.ERPNEXT_TIMEOUT, connect=20),
            transport=transport,
        )
        self._sleep = sleep
        self.attempts = 0

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> "ERPNextClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _once(self, path: str, params: dict[str, Any] | None) -> Any:
        self.attempts += 1
        try:
            resp = self.http.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise ERPNextError("ERPNext tardó demasiado en responder.", repr(exc), retryable=True)
        except httpx.HTTPError as exc:
            raise ERPNextError("No fue posible conectarse con ERPNext.", repr(exc), retryable=True)
        if resp.status_code in (401, 403):
            raise ERPNextError("ERPNext rechazó la consulta (credenciales o permisos insuficientes).",
                               f"{resp.status_code} {path}: {_error_text(resp)}", status=resp.status_code)
        if resp.status_code == 404:
            raise ERPNextError("ERPNext no encontró el recurso solicitado.", f"404 {path}: {_error_text(resp)}", status=404)
        if resp.status_code == 429 or resp.status_code >= 500:
            raise ERPNextError("ERPNext no está disponible en este momento.",
                               f"{resp.status_code} {path}: {_error_text(resp)}", retryable=True, status=resp.status_code)
        if resp.status_code >= 400:
            raise ERPNextError("ERPNext devolvió un error.", f"{resp.status_code} {path}: {_error_text(resp)}",
                               status=resp.status_code)
        try:
            return resp.json()
        except ValueError as exc:
            raise ERPNextError("ERPNext devolvió una respuesta inválida.", resp.text[:300]) from exc

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET con reintentos y espera creciente ante fallas transitorias."""
        tries = max(1, settings.SYNC_MAX_ATTEMPTS)
        for attempt in range(1, tries + 1):
            try:
                return self._once(path, params)
            except ERPNextError as exc:
                if not exc.retryable or attempt == tries:
                    raise
                wait = settings.SYNC_RETRY_BACKOFF_SECONDS * (3 ** (attempt - 1))
                log.warning("ERPNext %s (intento %s/%s), nuevo intento en %.0fs: %s", path, attempt, tries, wait, exc.detail)
                self._sleep(wait)
        raise AssertionError("unreachable")  # pragma: no cover

    def report_rows(self) -> list[dict[str, Any]]:
        """Ejecuta la petición de Postman del reporte: todas las suscripciones, una fila por plan."""
        c = consulta()
        p = c["parametros"]
        params = {"fields": json.dumps(p["fields"]), "limit_page_length": p["limit_page_length"],
                  "order_by": p["order_by"]}
        data = self.get(c["ruta"], params)
        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise ERPNextError("La consulta de suscripciones devolvió un formato inesperado.", str(data)[:300])
        return rows

    def user_roles(self, email: str) -> tuple[bool, list[str]]:
        try:
            data = self.get(f"/api/resource/User/{quote(email, safe='@')}")
        except ERPNextError as exc:
            if exc.status == 404:
                return False, []
            raise
        doc = (data or {}).get("data") or {}
        roles = [r.get("role") for r in doc.get("roles") or [] if isinstance(r, dict) and r.get("role")]
        return bool(doc.get("enabled")), roles


def get_client() -> ERPNextClient:
    return ERPNextClient()
