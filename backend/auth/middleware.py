"""Auth middleware: extract JWT user, enforce tier limits."""
from __future__ import annotations

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.auth.database import (
    get_lifetime_usage_count,
    get_tier_limits,
    get_usage_count,
    get_user_by_id,
)
from backend.auth.jwt_handler import verify_token

PUBLIC_PATHS = {
    "/",
    "/index.html",
    "/dashboard.html",
    "/api/health",
    "/api/auth/register",
    "/api/auth/login",
    "/api/auth/magic-link",
    "/api/auth/verify",
    "/api/auth/google",
    "/api/auth/google/callback",
    "/api/stripe/webhook",
    "/api/v1/health",
    "/openapi.json",
    "/docs",
    "/redoc",
}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Allow static files and docs
        if path.startswith("/ui/") or path.startswith("/static/") or path in PUBLIC_PATHS:
            return await call_next(request)

        # Also allow API docs paths
        if any(path.startswith(p) for p in ("/docs", "/redoc", "/openapi")):
            return await call_next(request)

        # ── No token? Guest mode for upload, 401 for everything else ──
        auth_header = request.headers.get("Authorization", "")
        token = None
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

        if not token:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Sign in to continue.",
                    "code": "auth_required",
                },
            )

        # ── Authenticated user ──
        payload = verify_token(token)
        if not payload:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token. Please sign in again."},
            )

        user_id = int(payload["sub"])
        user = get_user_by_id(user_id)
        if not user:
            return JSONResponse(status_code=401, content={"detail": "User not found"})

        request.state.user = user
        request.state.token_payload = payload
        request.state.is_guest = False

        # Enforce tier limits on upload endpoints
        if path == "/api/upload" and request.method == "POST":
            limits = get_tier_limits(user["tier"])

            # Free tier: lifetime limit
            if user["tier"] == "free" and "max_pdfs_lifetime" in limits:
                lifetime_uploads = get_lifetime_usage_count(user["id"], "upload")
                if lifetime_uploads >= limits["max_pdfs_lifetime"]:
                    return JSONResponse(
                        status_code=429,
                        content={
                            "detail": f"Free tier limit reached ({limits['max_pdfs_lifetime']} PDFs total). Upgrade to Pro for $29/mo — 200 PDFs/day + Docling + DeepSeek + Qwen.",
                            "tier": user["tier"],
                            "limit": limits["max_pdfs_lifetime"],
                            "used": lifetime_uploads,
                            "upgrade_url": "/api/auth/upgrade",
                        },
                    )

            # All tiers: daily limit
            today_uploads = get_usage_count(user["id"], "upload")
            if today_uploads >= limits.get("max_pdfs_per_day", 9999):
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": f"Daily limit reached ({limits['max_pdfs_per_day']} PDFs/day on {user['tier']} tier).",
                        "tier": user["tier"],
                        "limit": limits["max_pdfs_per_day"],
                        "used": today_uploads,
                    },
                )

        return await call_next(request)
