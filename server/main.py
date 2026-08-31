"""
FastAPI application entry point for the gamdl web server.
Serves both the REST API and the static frontend.
"""

import asyncio
import logging
import os
import httpx
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

_WARP_KEEPALIVE_INTERVAL = 300  # 5 minutes


async def _warp_keepalive_loop() -> None:
    """Send a lightweight request through the WARP proxy every 5 minutes
    to prevent the WireGuard tunnel from dropping its encryption keys.

    Without this, the tunnel dies after ~9 minutes of inactivity, causing
    all subsequent download requests to hang silently.
    """
    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("ALL_PROXY")
    if not proxy_url:
        logger.info("WARP keepalive: no proxy configured, skipping")
        return

    # Target: Apple Music API origin — lightweight HEAD request
    target_url = "https://amp-api.music.apple.com"

    while True:
        await asyncio.sleep(_WARP_KEEPALIVE_INTERVAL)
        try:
            async with httpx.AsyncClient(
                proxy=proxy_url,
                timeout=10.0,
            ) as client:
                start = asyncio.get_event_loop().time()
                response = await client.head(target_url)
                elapsed_ms = int((asyncio.get_event_loop().time() - start) * 1000)
                logger.info(
                    "WARP keepalive: tunnel alive (HTTP %s, %dms)",
                    response.status_code, elapsed_ms,
                )
        except Exception as e:
            logger.warning("WARP keepalive: tunnel unreachable (%s) — will retry in %ds", e, _WARP_KEEPALIVE_INTERVAL)


_WRAPPER_WATCHDOG_INTERVAL = 60  # Check wrapper health every 60 seconds
_WRAPPER_WATCHDOG_FAILURE_THRESHOLD = 2  # 2 consecutive failed health checks trigger auto-restart


async def _wrapper_watchdog_loop() -> None:
    """Background watchdog: monitors Wrapper ports 10020 and 30020.
    If the wrapper daemon crashes, hangs, or enters a dead socket state,
    it automatically recycles the process to maintain zero-touch reliability.
    """
    # Wait 30 seconds after server startup before running health checks
    await asyncio.sleep(30)
    consecutive_failures = 0

    while True:
        await asyncio.sleep(_WRAPPER_WATCHDOG_INTERVAL)
        try:
            # Check if wrapper binary exists on disk before attempting watchdog checks
            wrapper_bin = "/app/Wrapper/wrapper"
            if not os.path.isfile(wrapper_bin):
                continue

            # Run synchronous health check in thread executor
            is_healthy = await asyncio.get_event_loop().run_in_executor(
                None, api_routes.check_wrapper_healthy
            )

            if is_healthy:
                if consecutive_failures > 0:
                    logger.info("Wrapper watchdog: Wrapper returned to healthy state")
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                logger.warning(
                    "Wrapper watchdog: Wrapper health check failed (%d/%d)",
                    consecutive_failures,
                    _WRAPPER_WATCHDOG_FAILURE_THRESHOLD,
                )

                if consecutive_failures >= _WRAPPER_WATCHDOG_FAILURE_THRESHOLD:
                    logger.error(
                        "Wrapper watchdog: Health check failed %d times in a row. "
                        "Auto-restarting Wrapper daemon...",
                        consecutive_failures,
                    )
                    restart_res = await asyncio.get_event_loop().run_in_executor(
                        None, api_routes.do_wrapper_restart
                    )
                    logger.info("Wrapper watchdog restart result: %s", restart_res)
                    consecutive_failures = 0
                    # Give it extra time to stabilize before next check
                    await asyncio.sleep(15)
        except Exception:
            logger.exception("Wrapper watchdog error (non-fatal)")


async def _periodic_cleanup_loop() -> None:
    """Background loop: runs every 60s to evict stale jobs and free disk/RAM."""
    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL)
        try:
            await api_routes.run_periodic_cleanup()
            # Check for zombie jobs holding semaphore slots
            from .download_manager import check_semaphore_health
            check_semaphore_health()
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

    # Start WARP tunnel keep-alive heartbeat
    keepalive_task = asyncio.create_task(_warp_keepalive_loop())
    logger.info("WARP keepalive loop started (every %ds)", _WARP_KEEPALIVE_INTERVAL)

    # Start Wrapper auto-restart watchdog
    wrapper_watchdog_task = asyncio.create_task(_wrapper_watchdog_loop())
    logger.info(
        "Wrapper watchdog loop started (every %ds, threshold: %d)",
        _WRAPPER_WATCHDOG_INTERVAL,
        _WRAPPER_WATCHDOG_FAILURE_THRESHOLD,
    )

    yield

    # Cancel background tasks
    cleanup_task.cancel()
    keepalive_task.cancel()
    wrapper_watchdog_task.cancel()
    for task in (cleanup_task, keepalive_task, wrapper_watchdog_task):
        try:
            await task
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
