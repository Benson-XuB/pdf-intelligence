import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api.auth import usage_tracker
from backend.api.v1.routes import router as v1_router
from backend.api import legacy_routes
from backend.api import auth_routes
from backend.api import stripe_routes
from backend.auth.middleware import AuthMiddleware

app = FastAPI(
    title="PDF Intelligence API",
    version="2.0.0",
    description="Dual-engine PDF table extraction · Docling + pdfplumber · SaaS API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth middleware — extracts JWT, enforces tier limits
app.add_middleware(AuthMiddleware)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    if request.url.path.startswith("/api/"):
        from backend.api.auth import RequestLogEntry

        usage_tracker.record(
            RequestLogEntry(
                timestamp=time.time(),
                method=request.method,
                path=request.url.path,
                key_id=getattr(request.state, "api_key_id", "public"),
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
        )
    return response


app.include_router(v1_router)
app.include_router(auth_routes.router)
app.include_router(stripe_routes.router)
legacy_routes.register(app)

_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if _FRONTEND_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="ui")


@app.get("/")
def root():
    return FileResponse(str(_FRONTEND_DIR / "dashboard.html")) if (_FRONTEND_DIR / "dashboard.html").exists() else {"ok": True}


@app.get("/index.html")
def extraction_page():
    target = _FRONTEND_DIR / "index.html"
    if target.exists():
        return FileResponse(str(target))
    return {"ok": True}


@app.get("/dashboard.html")
def dashboard_page():
    target = _FRONTEND_DIR / "dashboard.html"
    if target.exists():
        return FileResponse(str(target))
    return {"ok": True}
