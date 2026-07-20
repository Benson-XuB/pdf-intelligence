"""Auth endpoints: Google OAuth, magic-link, profile."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from pydantic import BaseModel

from backend.auth.database import (
    consume_verification_token,
    create_user,
    create_verification_token,
    get_user_by_email,
    get_user_by_id,
    init_db,
    log_usage,
)
from backend.auth.jwt_handler import create_token, verify_token
from backend.auth.mailer import send_magic_link
from backend.config import settings

import bcrypt

router = APIRouter(prefix="/api/auth", tags=["auth"])

init_db()


# ── Models ─────────────────────────────────────────────────────────

class MagicLinkRequest(BaseModel):
    email: str
    name: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    token: str
    user: dict


# ── Google OAuth (primary auth flow) ───────────────────────────────

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPES = "openid email profile"


def _google_configured() -> bool:
    return bool(settings.google_client_id) and bool(settings.google_client_secret)


def _build_callback_uri(request: Request) -> str:
    scheme = request.headers.get("X-Forwarded-Proto", request.url.scheme or "https")
    host = request.headers.get("X-Forwarded-Host", request.headers.get("Host", "localhost"))
    return f"{scheme}://{host}/api/auth/google/callback"


@router.get("/google")
def google_login(request: Request):
    if not _google_configured():
        raise HTTPException(400, "Google Sign-In is not configured. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to .env")

    redirect_uri = _build_callback_uri(request)
    params = (
        f"client_id={settings.google_client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope={_SCOPES.replace(' ', '+')}"
        f"&access_type=online"
        f"&prompt=select_account"
    )
    return RedirectResponse(f"{_GOOGLE_AUTH_URL}?{params}")


@router.get("/google/callback")
def google_callback(request: Request, code: str = Query(...)):
    if not _google_configured():
        return HTMLResponse("<h2>Google Sign-In is not configured</h2>", status_code=400)

    import requests as sync_requests

    redirect_uri = _build_callback_uri(request)
    token_resp = sync_requests.post(_GOOGLE_TOKEN_URL, data={
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }, timeout=15)
    if token_resp.status_code != 200:
        return HTMLResponse("<h2>Failed to verify with Google</h2><p>Please try again.</p>", status_code=400)

    tokens = token_resp.json()
    id_token_str = tokens.get("id_token")
    if not id_token_str:
        return HTMLResponse("<h2>No identity token received from Google</h2>", status_code=400)

    try:
        info = id_token.verify_oauth2_token(
            id_token_str,
            google_requests.Request(),
            settings.google_client_id,
        )
    except ValueError:
        return HTMLResponse("<h2>Invalid Google token</h2><p>Please try signing in again.</p>", status_code=400)

    email = (info.get("email") or "").lower().strip()
    if not email:
        return HTMLResponse("<h2>Google account has no email</h2>", status_code=400)

    name = info.get("name", info.get("given_name", email.split("@")[0]))

    user = get_user_by_email(email)
    if not user:
        user = create_user(email, password_hash="", name=name)
    elif not user.get("name"):
        from backend.auth.database import _get_conn
        conn = _get_conn()
        conn.execute("UPDATE users SET name = ? WHERE id = ?", (name, user["id"]))
        conn.commit()
        user["name"] = name

    jwt_token = create_token(user["id"], user["email"], user["tier"])
    log_usage(user["id"], "login")

    return HTMLResponse(
        content=f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Signed in</title></head><body>
<script>
  localStorage.setItem('pi_token', '{jwt_token}');
  localStorage.setItem('pi_user', JSON.stringify({{
    id: {user['id']},
    email: '{user['email']}',
    name: '{user.get('name', '')}',
    tier: '{user['tier']}'
  }}));
  window.location.href = '/ui/index.html';
</script>
<p>Signed in as {user['email']}. Redirecting…</p>
</body></html>""",
        status_code=200,
    )


# ── Magic Link (backup auth) ───────────────────────────────────────

@router.post("/magic-link")
def request_magic_link(body: MagicLinkRequest):
    if len(body.email) < 5 or "@" not in body.email:
        raise HTTPException(400, "Please enter a valid email address")

    email = body.email.lower().strip()
    name = body.name.strip()

    token = create_verification_token(email, name)

    user = get_user_by_email(email)
    if not user:
        create_user(email, password_hash="", name=name)

    sent = send_magic_link(email, token, display_name=name)

    return {
        "message": "If that email is registered, a sign-in link has been sent.",
        "sent": sent,
    }


@router.get("/verify")
def verify_magic_link(token: str = Query(...)):
    data = consume_verification_token(token)
    if not data:
        return HTMLResponse(
            content="<h2>Link expired or already used</h2><p>Please request a new sign-in link.</p>",
            status_code=400,
        )

    user = get_user_by_email(data["email"])
    if not user:
        raise HTTPException(500, "User not found — please try again")

    jwt_token = create_token(user["id"], user["email"], user["tier"])
    log_usage(user["id"], "login")

    return HTMLResponse(
        content=f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Signed in</title></head><body>
<script>
  localStorage.setItem('pi_token', '{jwt_token}');
  localStorage.setItem('pi_user', JSON.stringify({{
    id: {user['id']},
    email: '{user['email']}',
    name: '{user.get('name', '')}',
    tier: '{user['tier']}'
  }}));
  window.location.href = '/ui/index.html';
</script>
<p>Signed in as {user['email']}. Redirecting…</p>
</body></html>""",
        status_code=200,
    )


# ── Legacy password login / register (kept for API users) ──────────

class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str = ""


@router.post("/register")
def register(body: RegisterRequest):
    if len(body.email) < 5 or "@" not in body.email:
        raise HTTPException(400, "Invalid email address")
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    if get_user_by_email(body.email):
        raise HTTPException(409, "Email already registered")

    pw_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    user = create_user(body.email, pw_hash, body.name)
    token = create_token(user["id"], user["email"], user["tier"])

    return AuthResponse(
        token=token,
        user={"id": user["id"], "email": user["email"], "name": user["name"], "tier": user["tier"]},
    )


@router.post("/login")
def login(body: LoginRequest):
    user = get_user_by_email(body.email)
    if not user:
        raise HTTPException(401, "Invalid email or password")
    if not user.get("password_hash"):
        raise HTTPException(401, "This account uses passwordless sign-in. Use Google or check your email for a magic link.")

    if not bcrypt.checkpw(body.password.encode(), user["password_hash"].encode()):
        raise HTTPException(401, "Invalid email or password")

    token = create_token(user["id"], user["email"], user["tier"])
    return AuthResponse(
        token=token,
        user={"id": user["id"], "email": user["email"], "name": user["name"], "tier": user["tier"]},
    )


# ── Profile ────────────────────────────────────────────────────────

@router.get("/me")
def me(request: Request):
    user = request.state.user
    if not user:
        raise HTTPException(401, "Not authenticated")

    return {
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "tier": user["tier"],
        },
    }
