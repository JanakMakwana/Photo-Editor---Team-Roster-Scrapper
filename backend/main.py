"""
VeloRoster AI - Modern SaaS Backend Application
FastAPI + Python Media/AI Services + Multi-Tenant RBAC Database
Developed by Ecstaticloud Technologies
"""

import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import uvicorn

import saas_db
import studio
from backend.config import settings
from backend.api.auth import router as auth_router
from backend.api.admin import router as admin_router
from backend.api.roster import router as roster_router
from backend.api.studio import router as studio_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup sequence
    print("=" * 66)
    print(f"[{settings.APP_NAME}] Initializing {settings.COMPANY} backend suite...")
    print("=" * 66)

    # 1. Clean temporary files & RAM
    try:
        startup_clean = studio.clean_server_storage(max_age_minutes=0)
        print(f"[Studio] Startup cleanup: freed {startup_clean.get('freed_mb', 0)} MB disk cache.")
    except Exception as e:
        print(f"[Studio] Cleanup note: {e}")

    # 2. Initialize database
    try:
        saas_db.init_db()
    except Exception as e:
        print(f"[Studio] Database init error: {e}")

    # 3. Start Keep-Alive daemon if on cloud
    if settings.KEEP_ALIVE_ENABLED:
        studio.KeepAliveService.start()

    yield

    # Shutdown sequence
    print(f"[{settings.APP_NAME}] Shutting down services...")


app = FastAPI(
    title=f"{settings.APP_NAME} Commercial Studio API",
    description=f"Standardized 180×180 Athletic Roster & Headshot Platform by {settings.COMPANY}.",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Enable CORS for Vite frontend development and external embeds
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Domain API Routers
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(roster_router)
app.include_router(studio_router)


@app.get("/healthz")
@app.get("/health")
async def health_check():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}


@app.get("/api/keep_alive/status")
async def keep_alive_status():
    return studio.KeepAliveService.get_status()


# Static bundle mounting for production deployment (Render / Cloud)
frontend_dist = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist")

if os.path.exists(frontend_dist) and os.path.isdir(frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Don't intercept API routes
        if full_path.startswith("api/") or full_path in ("healthz", "health", "docs", "redoc", "openapi.json"):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        target = os.path.join(frontend_dist, full_path)
        if os.path.isfile(target):
            return FileResponse(target)
        return FileResponse(os.path.join(frontend_dist, "index.html"))
else:
    @app.get("/")
    async def index_fallback():
        return {
            "status": "VeloRoster AI Backend is running.",
            "api_docs": "/docs",
            "frontend": "Run 'npm run dev' inside 'frontend/' for Vite hot-reloading or 'npm run build' for production.",
            "company": settings.COMPANY
        }


def start():
    raw_port = os.environ.get("PORT", "").strip()
    try:
        port = int(raw_port) if raw_port else settings.PORT
    except ValueError:
        port = 8000
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"[{settings.APP_NAME}] Binding server to {host}:{port} (PORT env: '{raw_port}')")
    uvicorn.run("backend.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    start()
