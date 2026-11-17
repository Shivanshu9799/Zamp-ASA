from __future__ import annotations

import base64
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config
from .bootstrap import init_db
from .routers import dashboard, demo, master_data, runs


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Invoice Processing Agent", version="1.0", lifespan=lifespan)


@app.middleware("http")
async def optional_password(request: Request, call_next):
    """If APP_PASSWORD is set, the whole site (UI + API + SSE) sits behind HTTP Basic auth (any username)."""
    if config.APP_PASSWORD and request.url.path != "/api/health":
        header = request.headers.get("authorization", "")
        ok = False
        if header.lower().startswith("basic "):
            try:
                _, _, pwd = base64.b64decode(header[6:]).decode().partition(":")
                ok = secrets.compare_digest(pwd, config.APP_PASSWORD)
            except Exception:
                ok = False
        if not ok:
            return Response("Authentication required", status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="Invoice Agent"'})
    return await call_next(request)


@app.get("/api/health")
def health():
    return {"ok": True}


for r in (runs.router, dashboard.router, master_data.router, demo.router):
    app.include_router(r)

# ---- serve the built React app (single-container deploy) ----
dist = config.FRONTEND_DIST
if dist.exists():
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")
