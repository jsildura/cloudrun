"""
FastAPI application entry point for the gamdl web server.
Serves both the REST API and the static frontend.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from . import api_routes, sse_routes
from .config import load_config, save_config, ServerConfig
from .storage import CloudStorage

logger = logging.getLogger(__name__)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)

_CLEANUP_INTERVAL = 60  # seconds


async def _periodic_cleanup_loop() -> None:
    """Background loop: runs every 60s to evict stale jobs and free disk/RAM."""
    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL)
        try:
            await api_routes.run_periodic_cleanup()
        except Exception:
            logger.exception("Periodic cleanup error (non-fatal)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize on startup, cleanup on shutdown."""
    logger.info("Starting gamdl web server...")

    # Load config
    config = load_config()
    save_config(config)  # Ensure file exists with defaults

    # Initialize cloud storage if cloud_mode is enabled
    if config.cloud_mode and config.r2_endpoint and config.r2_access_key:
        storage = CloudStorage(
            endpoint=config.r2_endpoint,
            access_key=config.r2_access_key,
            secret_key=config.r2_secret_key,
            bucket=config.r2_bucket,
        )
        api_routes.cloud_storage = storage
        logger.info(f"Cloud storage initialized (bucket: {config.r2_bucket})")
    else:
        api_routes.cloud_storage = None
        if config.cloud_mode:
            logger.warning(
                "cloud_mode=True but R2 credentials are incomplete. "
                "Cloud storage disabled."
            )

    # SSE routes import per-user DMs from api_routes directly — no injection needed.

    # Start background cleanup loop (safety net for abandoned sessions)
    cleanup_task = asyncio.create_task(_periodic_cleanup_loop())
    logger.info("Background cleanup loop started (every %ds)", _CLEANUP_INTERVAL)

    yield

    # Cancel background cleanup loop
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    logger.info("Shutting down gamdl web server...")


app = FastAPI(
    title="Gamdl Web",
    description="Web interface for Gamdl — Apple Music Downloader",
    version="1.0.0",
    lifespan=lifespan,
)

import os

# Base origins
origins = [
    "http://localhost:8080",        # Local dev
    "http://localhost:3000",        # Local dev (alt port)
    "http://127.0.0.1:8080",       # Local dev
    "https://gamdl.pages.dev",      # Production Cloudflare Pages default
    "https://amdlxd.stormygenesis.workers.dev",  # Cloudflare Workers
]

# Add custom origins from environment (for Cloudflare Pages custom domains)
if os.environ.get("CORS_ORIGINS"):
    custom_origins = [o.strip() for o in os.environ["CORS_ORIGINS"].split(",")]
    origins.extend(custom_origins)

# CORS — allow specific origins for cross-origin frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https://.*\.(gamdl\.pages\.dev|workers\.dev|trycloudflare\.com|hf\.space|koyeb\.app)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Mount API routes
app.include_router(api_routes.router)
app.include_router(sse_routes.router)

# Determine paths
_server_dir = Path(__file__).parent
_web_dir = _server_dir.parent / "web"


# Serve frontend
if _web_dir.exists():
    app.mount(
        "/css",
        StaticFiles(directory=str(_web_dir / "css")),
        name="css",
    )
    app.mount(
        "/js",
        StaticFiles(directory=str(_web_dir / "js")),
        name="js",
    )


@app.get("/")
async def serve_index():
    index_path = _web_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path), media_type="text/html")
    return {"message": "Gamdl Web API is running. Frontend not found."}


@app.get("/favicon.ico")
async def favicon():
    favicon_path = _web_dir / "favicon.ico"
    if favicon_path.exists():
        return FileResponse(str(favicon_path))
    return FileResponse(
        str(_web_dir / "index.html"),
        status_code=204,
    )
