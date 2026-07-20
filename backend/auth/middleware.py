"""Auth middleware: extract JWT user, require login for API routes."""

from __future__ import annotations

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.auth.database import get_user_by_id
from backend.auth.jwt_handler import verify_token

PUBLIC_PATHS = {
    "/",
    "/index.html",
    "/dashboard.html",
    "/robots.txt",
    "/sitemap.xml",
    "/favicon.svg",
    "/favicon.ico",
    "/api/health",
    "/api/auth/register",
    "/api/auth/login",
    "/api/auth/magic-link",
    "/api/auth/verify",
    "/api/auth/google",
    "/api/auth/google/callback",
    "/api/v1/health",
    "/openapi.json",
    "/docs",
    "/redoc",
}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Allow static files and public paths
        if path.startswith("/ui/") or path.startswith("/static/") or path in PUBLIC_PATHS:
            return await call_next(request)

        # Allow API docs paths
        if any(path.startswith(p) for p in ("/docs", "/redoc", "/openapi")):
            return await call_next(request)

        # Require authentication for all other API routes
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
        return await call_next(request)
