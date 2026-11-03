"""Sesión de la plataforma (mismo esquema del portal de reportes regulatorios).

AUTH_MODE=debug   → formulario local con correo del dominio (solo desarrollo).
AUTH_MODE=erpnext → SSO con ERPNext como proveedor OAuth2 (login de ERPNext con Office 365), con PKCE.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import settings

log = logging.getLogger("tva.auth")

SESSION_COOKIE = "tva_session"
OAUTH_COOKIE = "tva_oauth"
_serializer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="tva-session")
_oauth_serializer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="tva-oauth")

AUTHORIZE_PATH = "/api/method/frappe.integrations.oauth2.authorize"
TOKEN_PATH = "/api/method/frappe.integrations.oauth2.get_token"
PROFILE_PATH = "/api/method/frappe.integrations.oauth2.openid_profile"


def initials(name: str) -> str:
    parts = [p for p in name.replace(".", " ").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _cookie_kwargs() -> dict[str, Any]:
    return {"httponly": True, "samesite": "lax", "secure": settings.COOKIE_SECURE,
            "path": settings.BASE_PATH or "/"}


def make_user(email: str, name: str, roles: list[str] | None = None, source: str = "debug") -> dict:
    name = (name or "").strip() or email.split("@")[0].replace(".", " ").title()
    return {"email": email.strip().lower(), "name": name, "initials": initials(name), "roles": roles or [],
            "source": source}


def set_session(response: Response, user: dict) -> None:
    response.set_cookie(SESSION_COOKIE, _serializer.dumps(user), max_age=settings.SESSION_HOURS * 3600,
                        **_cookie_kwargs())


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path=settings.BASE_PATH or "/")


def read_session(request: Request) -> dict | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        return _serializer.loads(token, max_age=settings.SESSION_HOURS * 3600)
    except (BadSignature, SignatureExpired):
        return None


def require_user(request: Request) -> dict:
    user = read_session(request)
    if not user:
        raise HTTPException(status_code=401, detail="Sesión no iniciada")
    return user


def email_allowed(email: str) -> bool:
    if not settings.ALLOWED_EMAIL_DOMAINS:
        return True
    return email.lower().split("@")[-1] in [d.lower() for d in settings.ALLOWED_EMAIL_DOMAINS]


def safe_next(path: str | None) -> str | None:
    """Solo rutas internas (evita redirecciones abiertas)."""
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path:
        return None
    if path.startswith("/api/") or path.startswith("/login"):
        return None
    return path


# ------------------------------------------------------------------ OAuth ERPNext
def oauth_configured() -> bool:
    return bool(settings.OAUTH_CLIENT_ID)


def oauth_start_url(response: Response, next_path: str | None = None) -> str:
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    saved = {"state": state, "verifier": verifier, "next": safe_next(next_path)}
    response.set_cookie(OAUTH_COOKIE, _oauth_serializer.dumps(saved), max_age=600, **_cookie_kwargs())
    params = {
        "client_id": settings.OAUTH_CLIENT_ID, "response_type": "code", "scope": settings.OAUTH_SCOPES,
        "redirect_uri": settings.OAUTH_REDIRECT_URI, "state": state, "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{settings.ERPNEXT_URL}{AUTHORIZE_PATH}?{urlencode(params)}"


def oauth_next(request: Request) -> str | None:
    try:
        saved = _oauth_serializer.loads(request.cookies.get(OAUTH_COOKIE) or "", max_age=600)
    except (BadSignature, SignatureExpired):
        return None
    return safe_next(saved.get("next"))


def oauth_finish(request: Request, code: str, state: str) -> dict:
    try:
        saved = _oauth_serializer.loads(request.cookies.get(OAUTH_COOKIE) or "", max_age=600)
    except (BadSignature, SignatureExpired):
        raise HTTPException(status_code=400, detail="La solicitud de inicio de sesión expiró. Intenta de nuevo.")
    if not secrets.compare_digest(saved.get("state", ""), state or ""):
        raise HTTPException(status_code=400, detail="Estado de inicio de sesión inválido.")
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": settings.OAUTH_REDIRECT_URI,
            "client_id": settings.OAUTH_CLIENT_ID, "code_verifier": saved["verifier"]}
    if settings.OAUTH_CLIENT_SECRET:
        data["client_secret"] = settings.OAUTH_CLIENT_SECRET
    with httpx.Client(base_url=settings.ERPNEXT_URL, timeout=30) as http:
        token_resp = http.post(TOKEN_PATH, data=data)
        if token_resp.status_code >= 400:
            log.warning("Fallo canje de código OAuth: %s", token_resp.status_code)
            raise HTTPException(status_code=401, detail="ERPNext no autorizó el inicio de sesión.")
        access_token = token_resp.json().get("access_token")
        profile_resp = http.get(PROFILE_PATH, headers={"Authorization": f"Bearer {access_token}"})
        if profile_resp.status_code >= 400:
            raise HTTPException(status_code=401, detail="No fue posible leer el perfil de ERPNext.")
    profile = profile_resp.json()
    profile = profile.get("message", profile) if isinstance(profile, dict) else {}
    email = (profile.get("email") or profile.get("sub") or "").lower()
    roles = profile.get("roles") or []
    if not email or not email_allowed(email):
        raise HTTPException(status_code=403, detail="Tu cuenta no tiene acceso a la plataforma.")
    if settings.ALLOWED_ROLES and not set(settings.ALLOWED_ROLES) & set(roles):
        raise HTTPException(status_code=403, detail="Tu usuario de ERPNext no tiene un rol habilitado.")
    return make_user(email, profile.get("name") or profile.get("given_name") or email, roles, "erpnext")
