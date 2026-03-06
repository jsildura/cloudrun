"""
REST API routes for the gamdl web server.
Refactored for stateless multi-user: no global singletons,
per-user DownloadManager instances keyed by hashed token,
in-memory per-IP rate limiting.
"""

import hashlib
import logging
import time
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from .config import ServerConfig, load_config, save_config
from .download_manager import DownloadManager
from .models import AuthStatus, ConfigUpdate, DownloadJob, DownloadRequest, PreviewResponse
from .storage import CloudStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# ── Per-user state (keyed by hashed token) ────────────────────────────────────
_user_managers: dict[str, DownloadManager] = {}

# ── Cloud storage instance (set by main.py at startup when cloud_mode=True) ───
cloud_storage: CloudStorage | None = None

# ── Simple in-memory per-IP rate limiter ──────────────────────────────────────
_rate_limits: dict[str, list[float]] = defaultdict(list)
MAX_REQUESTS_PER_MINUTE = 30


# ── Helpers ───────────────────────────────────────────────────────────────────


def _extract_token(request: Request) -> str:
    """Extract and validate the Bearer token from the request."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization header")
    token = auth.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "Empty token in Authorization header")
    return token


def _get_user_dm(token: str) -> DownloadManager:
    """Get or create a per-user DownloadManager."""
    key = hashlib.sha256(token.encode()).hexdigest()[:16]
    if key not in _user_managers:
        dm = DownloadManager()
        if cloud_storage:
            dm.set_storage(cloud_storage)
        dm.set_token(token)
        _user_managers[key] = dm
    return _user_managers[key]


def _get_current_config() -> ServerConfig:
    """Load config from disk (no global state)."""
    return load_config()


def _check_rate_limit(request: Request) -> None:
    """Enforce per-IP rate limiting."""
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    _rate_limits[ip] = [t for t in _rate_limits[ip] if now - t < 60]
    if len(_rate_limits[ip]) >= MAX_REQUESTS_PER_MINUTE:
        raise HTTPException(429, "Rate limit exceeded")
    _rate_limits[ip].append(now)


# ── Auth ──────────────────────────────────────────────────────────────────────


@router.get("/auth/status")
async def auth_status(request: Request) -> AuthStatus:
    _check_rate_limit(request)
    token = _extract_token(request)
    dm = _get_user_dm(token)
    return AuthStatus(
        authenticated=dm.is_authenticated,
        active_subscription=dm.has_subscription,
        account_restrictions=dm.has_restrictions,
        storefront=dm.storefront,
    )


@router.post("/auth/connect")
async def connect_auth(request: Request) -> AuthStatus:
    """Authenticate using the media-user-token from the Authorization header.

    The client parses cookies.txt in the browser, extracts the
    media-user-token, and sends it as: Authorization: Bearer <token>
    """
    _check_rate_limit(request)
    token = _extract_token(request)
    dm = _get_user_dm(token)
    cfg = _get_current_config()

    # If already authenticated, just return current status
    if dm.is_authenticated:
        return AuthStatus(
            authenticated=True,
            active_subscription=dm.has_subscription,
            account_restrictions=dm.has_restrictions,
            storefront=dm.storefront,
        )

    try:
        result = await dm.authenticate_from_token(token, cfg.language)
        return AuthStatus(
            authenticated=result["authenticated"],
            active_subscription=result["active_subscription"],
            account_restrictions=result["account_restrictions"],
            storefront=result["storefront"],
        )
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg:
            raise HTTPException(
                status_code=429,
                detail="Apple Music API rate limit reached. Please wait a moment and try again.",
            )
        raise HTTPException(status_code=401, detail=f"Authentication failed: {e}")


# ── Preview ───────────────────────────────────────────────────────────────────


@router.post("/preview")
async def preview_url(req: DownloadRequest, request: Request) -> PreviewResponse:
    """Fetch metadata for a URL without starting a download."""
    _check_rate_limit(request)
    token = _extract_token(request)
    dm = _get_user_dm(token)
    cfg = _get_current_config()

    if not dm.is_authenticated:
        raise HTTPException(status_code=401, detail="Not authenticated. Connect auth first.")
    if not dm.has_subscription:
        raise HTTPException(status_code=403, detail="No active Apple Music subscription.")

    try:
        return await dm.preview_url(req.url, cfg)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Preview failed: {e}")


# ── Downloads ─────────────────────────────────────────────────────────────────


@router.post("/download")
async def start_download(req: DownloadRequest, request: Request) -> DownloadJob:
    _check_rate_limit(request)
    token = _extract_token(request)
    dm = _get_user_dm(token)
    cfg = _get_current_config()

    if not dm.is_authenticated:
        raise HTTPException(status_code=401, detail="Not authenticated. Connect auth first.")
    if not dm.has_subscription:
        raise HTTPException(status_code=403, detail="No active Apple Music subscription.")

    try:
        job = await dm.submit_download(req.url, cfg)
        return job
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/downloads")
async def list_downloads(request: Request) -> list[DownloadJob]:
    _check_rate_limit(request)
    token = _extract_token(request)
    dm = _get_user_dm(token)
    # Return jobs in reverse order (newest first)
    return list(reversed(dm.jobs.values()))


@router.get("/downloads/{job_id}")
async def get_download(job_id: str, request: Request) -> DownloadJob:
    _check_rate_limit(request)
    token = _extract_token(request)
    dm = _get_user_dm(token)
    job = dm.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/downloads/{job_id}/cancel")
async def cancel_download(job_id: str, request: Request) -> dict:
    _check_rate_limit(request)
    token = _extract_token(request)
    dm = _get_user_dm(token)
    success = dm.cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot cancel job")
    return {"status": "cancelled", "job_id": job_id}


@router.post("/downloads/{job_id}/retry/{track_index}")
async def retry_track(job_id: str, track_index: int, request: Request) -> dict:
    _check_rate_limit(request)
    token = _extract_token(request)
    dm = _get_user_dm(token)
    cfg = _get_current_config()

    # Use stored job config if available, otherwise current config
    job_cfg = dm._job_configs.get(job_id, cfg)

    try:
        await dm.retry_track(job_id, track_index, job_cfg)
        return {"status": "retrying", "job_id": job_id, "track_index": track_index}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/downloads/{job_id}/retry-all")
async def retry_all_failed(job_id: str, request: Request) -> dict:
    _check_rate_limit(request)
    token = _extract_token(request)
    dm = _get_user_dm(token)
    cfg = _get_current_config()

    job_cfg = dm._job_configs.get(job_id, cfg)

    try:
        count = await dm.retry_all_failed(job_id, job_cfg)
        return {"status": "retrying", "job_id": job_id, "count": count}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Config ────────────────────────────────────────────────────────────────────


@router.get("/wrapper/status")
async def wrapper_status() -> dict:
    """Check if the Wrapper service is reachable."""
    import asyncio
    import urllib.request
    import urllib.error

    cfg = _get_current_config()
    url = cfg.wrapper_account_url  # e.g. http://127.0.0.1:30020/

    def _ping():
        try:
            req = urllib.request.Request(url, method="GET")
            urllib.request.urlopen(req, timeout=2)
            return True
        except Exception:
            return False

    available = await asyncio.get_event_loop().run_in_executor(None, _ping)
    return {"available": available}


@router.post("/wrapper/restart")
async def wrapper_restart() -> dict:
    """Kill existing Wrapper process and start a new one."""
    import asyncio
    import subprocess
    import urllib.request
    import urllib.error

    wrapper_bin = "/app/Wrapper/wrapper"

    def _do_restart():
        # 1. Kill any existing wrapper processes
        try:
            subprocess.run(
                ["pkill", "-f", "wrapper"],
                timeout=5,
                capture_output=True,
            )
        except Exception:
            pass

        import time
        time.sleep(1)

        # 2. Check if the wrapper binary exists
        import os
        if not os.path.isfile(wrapper_bin):
            return {"success": False, "message": "Wrapper binary not found"}

        # 3. Start the wrapper in the background
        try:
            subprocess.Popen(
                ["./wrapper", "-H", "0.0.0.0"],
                cwd="/app/Wrapper",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            return {"success": False, "message": f"Failed to start: {e}"}

        # 4. Wait and then ping to verify it started
        time.sleep(3)

        cfg = _get_current_config()
        url = cfg.wrapper_account_url
        try:
            req = urllib.request.Request(url, method="GET")
            urllib.request.urlopen(req, timeout=3)
            return {"success": True, "message": "Wrapper restarted successfully"}
        except Exception:
            return {"success": False, "message": "Wrapper started but not responding yet, try to refresh the page"}

    result = await asyncio.get_event_loop().run_in_executor(None, _do_restart)
    return result


@router.get("/config")
async def get_config(request: Request) -> dict:
    _check_rate_limit(request)
    cfg = _get_current_config()
    return asdict(cfg)


@router.put("/config")
async def update_config(update: ConfigUpdate, request: Request) -> dict:
    _check_rate_limit(request)
    cfg = _get_current_config()

    # Apply non-None fields from the update
    update_data = update.model_dump(exclude_none=True)
    for key, value in update_data.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)

    save_config(cfg)
    return asdict(cfg)


# ── Files ─────────────────────────────────────────────────────────────────────


@router.get("/files")
async def list_files(request: Request) -> list[dict]:
    _check_rate_limit(request)
    cfg = _get_current_config()

    # In cloud mode, files are in R2 — not on local disk
    if cfg.cloud_mode:
        return []

    output_path = Path(cfg.output_path)

    if not output_path.exists():
        return []

    files = []
    for f in sorted(output_path.rglob("*")):
        if f.is_file() and not f.name.startswith("."):
            try:
                stat = f.stat()
                files.append({
                    "path": str(f.relative_to(output_path)),
                    "name": f.name,
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                    "extension": f.suffix.lower(),
                })
            except OSError:
                continue

    return files


@router.get("/files/{file_path:path}")
async def serve_file(file_path: str, request: Request):
    _check_rate_limit(request)
    cfg = _get_current_config()

    if cfg.cloud_mode:
        raise HTTPException(status_code=404, detail="File serving disabled in cloud mode. Use download_url from track progress.")

    full_path = Path(cfg.output_path) / file_path

    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # Security: prevent path traversal
    try:
        full_path.resolve().relative_to(Path(cfg.output_path).resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(
        path=str(full_path),
        filename=full_path.name,
        media_type="application/octet-stream",
    )


# ── Save to device ────────────────────────────────────────────────────────────
# ZIP compression is now handled client-side via JSZip.
# Only the individual track endpoint is needed.



@router.get("/save/{job_id}/{track_index}")
async def save_track_to_device(job_id: str, track_index: int, request: Request):
    """Serve a completed track file for browser download (save to device)."""
    from fastapi.responses import RedirectResponse

    _check_rate_limit(request)
    token = _extract_token(request)
    dm = _get_user_dm(token)
    cfg = _get_current_config()

    job = dm.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if track_index < 0 or track_index >= len(job.tracks):
        raise HTTPException(status_code=404, detail="Track not found")

    track = job.tracks[track_index]

    # Cloud mode: redirect to signed R2 URL
    if cfg.cloud_mode and track.download_url:
        return RedirectResponse(url=track.download_url)

    # Local mode: serve from disk
    if not track.file_path:
        logger.warning("Save request for job=%s track=%d: no file_path set", job_id, track_index)
        raise HTTPException(status_code=404, detail="File not available")

    file_path = Path(track.file_path)
    if not file_path.exists() or not file_path.is_file():
        logger.warning(
            "Save request for job=%s track=%d: file not found at %s",
            job_id, track_index, file_path,
        )
        raise HTTPException(status_code=404, detail="File not found on disk")

    logger.info("Serving file for job=%s track=%d: %s (%d bytes)", job_id, track_index, file_path.name, file_path.stat().st_size)

    # Stream file without Content-Disposition to prevent download manager
    # extensions (IDM, etc.) from intercepting JavaScript fetch() calls.
    # The filename is passed via X-Filename header for our JS code to read.
    def file_iterator():
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        file_iterator(),
        media_type="application/octet-stream",
        headers={"X-Filename": file_path.name},
    )


@router.get("/save/{job_id}/{track_index}/lyrics")
async def save_track_lyrics(job_id: str, track_index: int, request: Request):
    """Serve the synced lyrics file for a completed track."""
    _check_rate_limit(request)
    token = _extract_token(request)
    dm = _get_user_dm(token)

    job = dm.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if track_index < 0 or track_index >= len(job.tracks):
        raise HTTPException(status_code=404, detail="Track not found")

    track = job.tracks[track_index]

    if not track.synced_lyrics_file_path:
        raise HTTPException(status_code=404, detail="No lyrics file available")

    file_path = Path(track.synced_lyrics_file_path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Lyrics file not found on disk")

    def file_iterator():
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        file_iterator(),
        media_type="text/plain; charset=utf-8",
        headers={"X-Filename": file_path.name},
    )


@router.get("/save/{job_id}/{track_index}/cover")
async def save_track_cover(job_id: str, track_index: int, request: Request):
    """Serve the cover image file for a completed track."""
    _check_rate_limit(request)
    token = _extract_token(request)
    dm = _get_user_dm(token)

    job = dm.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if track_index < 0 or track_index >= len(job.tracks):
        raise HTTPException(status_code=404, detail="Track not found")

    track = job.tracks[track_index]

    if not track.cover_file_path:
        raise HTTPException(status_code=404, detail="No cover file available")

    file_path = Path(track.cover_file_path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Cover file not found on disk")

    def file_iterator():
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        file_iterator(),
        media_type="application/octet-stream",
        headers={"X-Filename": file_path.name},
    )


@router.get("/save/{job_id}/animated-artwork/{index}")
async def save_animated_artwork(job_id: str, index: int, request: Request):
    """Serve an animated artwork MP4 file for a completed job."""
    _check_rate_limit(request)
    token = _extract_token(request)
    dm = _get_user_dm(token)

    job = dm.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if index < 0 or index >= len(job.animated_artwork_paths):
        raise HTTPException(status_code=404, detail="Animated artwork not found")

    file_path = Path(job.animated_artwork_paths[index])
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Animated artwork file not found on disk")

    def file_iterator():
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        file_iterator(),
        media_type="video/mp4",
        headers={"X-Filename": file_path.name},
    )
