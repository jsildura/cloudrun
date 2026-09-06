"""
REST API routes for the gamdl web server.
Refactored for stateless multi-user: no global singletons,
per-user DownloadManager instances keyed by hashed token,
in-memory per-IP rate limiting.
"""

import asyncio
import hashlib
import logging
import time
from collections import defaultdict

import psutil
psutil.cpu_percent()  # warm-up: first call always returns 0, prime for next calls
from dataclasses import asdict
import os
import sys
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse

from .config import ServerConfig, load_config, save_config
from .download_manager import DownloadManager
from .models import (
    AuthStatus,
    ConfigUpdate,
    DownloadJob,
    DownloadRequest,
    DownloadStage,
    PreviewResponse,
    ReserveAccountInfo,
    ReserveConnectResponse,
    ReserveContributeRequest,
    ReserveContributeResponse,
    ReserveUnlockRequest,
    ReserveUnlockResponse,
)
from .reserve_cookies import ReserveCookiesManager
from .storage import CloudStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# ── Per-user state (keyed by hashed token) ────────────────────────────────────
_user_managers: dict[str, DownloadManager] = {}
_user_last_access: dict[str, float] = {}  # key -> last access timestamp
_USER_MANAGER_TTL = 1800  # 30 minutes — evict idle user managers

# ── Cloud storage instance (set by main.py at startup when cloud_mode=True) ───
cloud_storage: CloudStorage | None = None

# ── Reserve cookies manager instance (set by main.py at startup) ──────────────
reserve_manager: ReserveCookiesManager | None = None

# ── Simple in-memory per-IP rate limiter ──────────────────────────────────────
_rate_limits: dict[str, list[float]] = defaultdict(list)
MAX_REQUESTS_PER_MINUTE = 120


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

    # Update access time for current user
    now = time.time()
    _user_last_access[key] = now

    # Evict stale user managers to free memory
    stale_keys = [
        k for k, ts in list(_user_last_access.items())
        if now - ts > _USER_MANAGER_TTL and k != key
    ]
    for k in stale_keys:
        dm = _user_managers.get(k)
        if dm:
            has_active = any(
                j.stage in (
                    DownloadStage.QUEUED,
                    DownloadStage.PARSING,
                    DownloadStage.PREPARING,
                    DownloadStage.DOWNLOADING,
                )
                for j in dm.jobs.values()
            )
            if has_active:
                # Update timestamp to prevent re-checking
                _user_last_access[k] = now + 300  # Extend by 5 min
                continue

            _user_managers.pop(k, None)
            _user_last_access.pop(k, None)

            # Cancel remaining tasks and clean up
            for task in dm._job_tasks.values():
                if task and not task.done():
                    task.cancel()
            for jid in list(dm._job_temp_dirs.keys()):
                dm._cleanup_job(jid)

            # Close HTTP clients if event loop is running
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    if hasattr(dm, "_apple_music_api") and hasattr(dm._apple_music_api, "http_client"):
                        loop.create_task(dm._apple_music_api.http_client.aclose())
                    if hasattr(dm, "_itunes_api") and hasattr(dm._itunes_api, "http_client"):
                        loop.create_task(dm._itunes_api.http_client.aclose())
            except Exception:
                pass
            logger.info("Evicted stale user manager: %s", k)

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


ALLOWED_USER_FIELDS = {
    "song_codec", "codec_fallback", "synced_lyrics_format", "no_synced_lyrics",
    "synced_lyrics_only", "save_synced_lyrics", "music_video_resolution",
    "exclude_videos", "cover_format", "cover_size", "save_cover",
    "save_animated_artwork", "save_playlist", "playlist_mode", "overwrite",
    "download_mode", "remux_mode",
    "language", "use_wrapper", "rate_limit_delay",
    "album_folder_template", "compilation_folder_template",
    "no_album_folder_template", "no_album_file_template",
    "single_disc_file_template", "multi_disc_file_template",
    "playlist_file_template", "date_tag_template", "exclude_tags",
    "truncate", "use_album_date", "fetch_extra_tags",
    "music_video_codec_priority", "music_video_remux_format",
    "uploaded_video_quality",
}

_SENSITIVE_CONFIG_KEYS = {
    "r2_access_key", "r2_secret_key", "r2_endpoint", "r2_bucket",
    "cookies_path", "wvd_path", "ffmpeg_path", "mp4decrypt_path",
    "mp4box_path", "nm3u8dlre_path",
}


def _merge_user_config(base: ServerConfig, overrides: ConfigUpdate | None) -> ServerConfig:
    """Apply per-user config overrides on top of the server base config.

    Only the fields that the frontend UI actually controls are applied.
    Server-infrastructure fields (paths, cloud mode, wrapper URLs, templates,
    tool paths) are never overridden — they always come from the server.
    """
    if overrides is None:
        return base

    from dataclasses import replace
    update_data = overrides.model_dump(exclude_none=True)
    safe_updates = {k: v for k, v in update_data.items() if k in ALLOWED_USER_FIELDS}

    if safe_updates:
        base = replace(base, **safe_updates)
    return base


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
        logger.error("connect_auth error: %s", e)
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
    import asyncio

    _check_rate_limit(request)
    token = _extract_token(request)
    dm = _get_user_dm(token)
    cfg = _merge_user_config(_get_current_config(), req.config)

    if not dm.is_authenticated:
        raise HTTPException(status_code=401, detail="Not authenticated. Connect auth first.")
    if not dm.has_subscription:
        raise HTTPException(status_code=403, detail="No active Apple Music subscription.")

    # Retry once on transient failure (handles cold-start / first-call issues
    # with the Apple Music API through the WARP proxy)
    last_error = None
    for attempt in range(2):
        try:
            return await dm.preview_url(req.url, cfg)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            last_error = e
            if attempt == 0:
                logger.warning("[Preview] First attempt failed (%s), retrying in 1s…", e)
                await asyncio.sleep(1)

    raise HTTPException(status_code=500, detail=f"Preview failed: {last_error}")


_convert_m3u8_semaphore = asyncio.Semaphore(3)
_ALLOWED_M3U8_HOSTS = (".mzstatic.com", ".apple.com", ".akamaized.net", ".apple-dns.net")


@router.get("/convert-m3u8")
async def convert_m3u8(url: str, request: Request, background_tasks: BackgroundTasks, quality: int = 720):
    """Convert an m3u8 stream to an mp4 file using yt-dlp to select resolution."""
    import asyncio
    import tempfile
    import urllib.parse

    _check_rate_limit(request)
    _extract_token(request)

    if not url.endswith('.m3u8'):
        raise HTTPException(status_code=400, detail="URL must be an m3u8 playlist")

    # Validate hostname against Apple CDN allowlist to prevent SSRF
    parsed = urllib.parse.urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if not any(hostname.endswith(allowed) or hostname == allowed.lstrip(".") for allowed in _ALLOWED_M3U8_HOSTS):
        raise HTTPException(status_code=400, detail="URL host is not an authorized media source")

    # Clamp quality to valid video heights
    safe_quality = min(max(int(quality), 360), 1080)

    temp_dir = tempfile.gettempdir()
    temp_file = os.path.join(temp_dir, f"artwork_{uuid.uuid4().hex}.mp4")

    cmd = [
        "yt-dlp",
        "-f", f"bestvideo[height<={safe_quality}]+bestaudio/best[height<={safe_quality}]/best",
        "--merge-output-format", "mp4",
        "-o", temp_file,
        url
    ]

    process = None
    try:
        async with _convert_m3u8_semaphore:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=45.0)
    except asyncio.TimeoutError:
        if process:
            try:
                process.kill()
            except Exception:
                pass
        if os.path.exists(temp_file):
            os.remove(temp_file)
        raise HTTPException(status_code=504, detail="Conversion timed out")
    except Exception as e:
        if process:
            try:
                process.kill()
            except Exception:
                pass
        if os.path.exists(temp_file):
            os.remove(temp_file)
        raise HTTPException(status_code=500, detail=f"Conversion failed: {e}")

    if process.returncode != 0:
        logger.error(f"yt-dlp failed to convert artwork: {stderr.decode(errors='ignore')}")
        if os.path.exists(temp_file):
            os.remove(temp_file)
        raise HTTPException(status_code=500, detail="Failed to convert animated artwork to MP4")

    def cleanup():
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception as e:
                logger.error(f"Failed to remove temp file {temp_file}: {e}")

    background_tasks.add_task(cleanup)

    return FileResponse(
        path=temp_file,
        filename="artwork.mp4",
        media_type="video/mp4"
    )



# ── Downloads ─────────────────────────────────────────────────────────────────


@router.post("/download")
async def start_download(req: DownloadRequest, request: Request) -> DownloadJob:
    _check_rate_limit(request)
    token = _extract_token(request)
    dm = _get_user_dm(token)
    cfg = _merge_user_config(_get_current_config(), req.config)

    if not dm.is_authenticated:
        raise HTTPException(status_code=401, detail="Not authenticated. Connect auth first.")
    if not dm.has_subscription:
        raise HTTPException(status_code=403, detail="No active Apple Music subscription.")

    try:
        job = await dm.submit_download(req.url, cfg, selected_tracks=req.selected_tracks)
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


@router.post("/downloads/{job_id}/cleanup")
async def cleanup_job(job_id: str, request: Request) -> dict:
    """Frontend signals that saving is complete — safe to delete temp files."""
    token = _extract_token(request)
    dm = _get_user_dm(token)

    job = dm.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    dm._cleanup_job(job_id)
    logger.info("Cleanup signal received for job %s — temp files deleted", job_id)
    return {"status": "cleaned", "job_id": job_id}


@router.api_route("/download/latest", methods=["GET", "HEAD"])
async def get_latest_download(request: Request) -> dict:
    """Get metadata about the single most recent completed download file.
    Not locked to any IP address. Supports Bearer header, ?token= param, or active session.
    """
    _check_rate_limit(request)
    auth = request.headers.get("Authorization", "")
    token = ""
    if auth.startswith("Bearer "):
        token = auth.removeprefix("Bearer ").strip()
    if not token:
        token = request.query_params.get("token", "").strip()

    latest = None
    if token:
        dm = _get_user_dm(token)
        latest = dm.get_latest_download()

    # Fallback to search across active managers if no token or not found
    if not latest or not os.path.isfile(latest.get("file_path", "")):
        for dm in _user_managers.values():
            cand = dm.get_latest_download()
            if cand and os.path.isfile(cand.get("file_path", "")):
                latest = cand
                break

    if not latest or not os.path.isfile(latest.get("file_path", "")):
        return {"available": False}
    return {
        "available": True,
        "job_id": latest.get("job_id", ""),
        "filename": latest.get("filename", ""),
        "title": latest.get("title", ""),
        "artist": latest.get("artist", ""),
        "type": latest.get("type", ""),
        "size": latest.get("size", 0),
        "timestamp": latest.get("timestamp", 0),
    }


@router.api_route("/download/latest/file", methods=["GET", "HEAD"])
async def get_latest_download_file(request: Request):
    """Directly download the single most recent completed download file.
    Not locked to any IP address. Supports remote uploads, cloud transfers, range requests, and HEAD probes.
    """
    _check_rate_limit(request)
    try:
        auth = request.headers.get("Authorization", "")
        token = ""
        if auth.startswith("Bearer "):
            token = auth.removeprefix("Bearer ").strip()
        if not token:
            token = request.query_params.get("token", "").strip()

        latest = None
        if token:
            dm = _get_user_dm(token)
            latest = dm.get_latest_download()

        # Fallback to search across active managers if no token or not found
        if not latest or not os.path.isfile(latest.get("file_path", "")):
            for dm in _user_managers.values():
                cand = dm.get_latest_download()
                if cand and os.path.isfile(cand.get("file_path", "")):
                    latest = cand
                    break

        if not latest or not os.path.isfile(latest.get("file_path", "")):
            raise HTTPException(status_code=404, detail="No recent download file available")

        file_path = latest["file_path"]
        filename = latest["filename"]
        ext = os.path.splitext(filename)[1].lower()
        if ext == ".zip":
            media_type = "application/zip"
        elif ext in (".m4a", ".aac"):
            media_type = "audio/mp4"
        elif ext in (".m4v", ".mp4"):
            media_type = "video/mp4"
        elif ext in (".flac",):
            media_type = "audio/flac"
        else:
            media_type = "application/octet-stream"

        return FileResponse(
            path=file_path,
            filename=filename,
            media_type=media_type,
            content_disposition_type="attachment",
            headers={
                "Accept-Ranges": "bytes",
                "Access-Control-Expose-Headers": "Content-Disposition, Content-Length, Content-Type, Accept-Ranges",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to serve latest download file: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to serve latest file: {e}")


async def run_periodic_cleanup() -> None:
    """Proactive cleanup: evict stale jobs and user managers.

    Called by the background loop in main.py every 60 seconds.
    """
    now = time.time()

    # 1. Evict stale jobs across all user managers
    for key, dm in list(_user_managers.items()):
        dm._evict_stale_jobs()

    # 2. Evict stale user managers (no API activity for 30+ min)
    stale_keys = [
        k for k, ts in _user_last_access.items()
        if now - ts > _USER_MANAGER_TTL
    ]
    for k in stale_keys:
        dm = _user_managers.pop(k, None)
        if dm:
            for jid in list(dm._job_temp_dirs.keys()):
                dm._cleanup_job(jid)
            logger.info("Periodic cleanup: evicted stale user manager %s", k)
        _user_last_access.pop(k, None)

# ── Config ────────────────────────────────────────────────────────────────────


@router.get("/system/stats")
async def system_stats(request: Request) -> dict:
    """Return host CPU, RAM, and Swap usage. No auth required."""
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    return {
        "cpu_percent": psutil.cpu_percent(interval=0),
        "ram_used_mb": round(vm.used / 1048576),
        "ram_total_mb": round(vm.total / 1048576),
        "ram_percent": vm.percent,
        "swap_used_mb": round(sw.used / 1048576),
        "swap_total_mb": round(sw.total / 1048576),
        "swap_percent": sw.percent,
    }


def do_wrapper_restart() -> dict:
    """Kill any existing wrapper processes reliably via psutil and start a fresh daemon."""
    import subprocess
    import urllib.request
    import urllib.error

    wrapper_bin = "/app/Wrapper/wrapper"
    if not os.path.isfile(wrapper_bin):
        local_wrapper = os.path.join(os.getcwd(), "Wrapper", "wrapper.exe" if sys.platform == "win32" else "wrapper")
        if os.path.isfile(local_wrapper):
            wrapper_bin = local_wrapper

    # 1. Kill only processes belonging specifically to the wrapper binary/process name
    try:
        current_pid = os.getpid()
        for p in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
            try:
                if p.pid == current_pid:
                    continue
                name = (p.info.get("name") or "").lower()
                exe = (p.info.get("exe") or "").lower()
                cmdline = [c.lower() for c in (p.info.get("cmdline") or [])]

                is_wrapper = (
                    name in ("wrapper", "wrapper.exe")
                    or (exe and os.path.basename(exe) in ("wrapper", "wrapper.exe"))
                    or any("wrapper" in c and ("./wrapper" in c or "/wrapper" in c or "\\wrapper" in c) for c in cmdline)
                )

                if is_wrapper:
                    try:
                        p.terminate()
                    except Exception:
                        pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Wait up to 1 second for graceful termination, then escalate if needed
        time.sleep(1)
        for p in psutil.process_iter(["pid", "name", "exe"]):
            try:
                if p.pid == current_pid:
                    continue
                name = (p.info.get("name") or "").lower()
                if name in ("wrapper", "wrapper.exe"):
                    try:
                        p.kill()
                    except Exception:
                        pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception as e:
        logger.warning(f"Error terminating old wrapper processes: {e}")

    # Reap zombies on Unix if uvicorn is PID 1
    if hasattr(os, "waitpid") and hasattr(os, "WNOHANG"):
        try:
            while True:
                pid, status = os.waitpid(-1, os.WNOHANG)
                if pid <= 0:
                    break
        except Exception:
            pass

    time.sleep(1)

    # 2. Check if the wrapper binary exists
    if not os.path.isfile(wrapper_bin):
        return {"success": False, "message": "Wrapper binary not found"}

    try:
        os.chmod(wrapper_bin, 0o755)
    except Exception:
        pass

    # 3. Start the wrapper in the background
    try:
        wrapper_dir = os.path.dirname(os.path.abspath(wrapper_bin))
        subprocess.Popen(
            [wrapper_bin, "-H", "0.0.0.0"],
            cwd=wrapper_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True if sys.platform != "win32" else False,
        )
    except Exception as e:
        return {"success": False, "message": f"Failed to start: {e}"}

    # 4. Poll for wrapper readiness with a retry loop (up to 10 seconds)
    for _ in range(20):
        time.sleep(0.5)
        if check_wrapper_healthy():
            return {"success": True, "message": "Wrapper restarted successfully"}

    return {"success": False, "message": "Wrapper started but taking longer to initialize"}


def check_wrapper_healthy() -> bool:
    """Check if the Wrapper service is reachable on account URL and decrypt port 10020 is responsive."""
    import socket
    import urllib.request
    import urllib.error

    cfg = _get_current_config()
    # 1. Test HTTP port (30020)
    try:
        req = urllib.request.Request(cfg.wrapper_account_url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            pass
    except urllib.error.HTTPError:
        # Any HTTP status code (200, 404, 400, etc.) means port 30020 is active and responding
        pass
    except Exception:
        return False

    # 2. Test TCP Decrypt port (10020)
    try:
        host, port_str = cfg.wrapper_decrypt_ip.split(":")
        with socket.create_connection((host, int(port_str)), timeout=3):
            pass
    except Exception:
        return False

    return True


@router.get("/wrapper/status")
async def wrapper_status(request: Request) -> dict:
    """Check if the Wrapper service is reachable and decrypt port 10020 is responsive."""
    import asyncio
    _check_rate_limit(request)
    available = await asyncio.get_event_loop().run_in_executor(None, check_wrapper_healthy)
    return {"available": available}


_last_wrapper_restart: float = 0.0
_WRAPPER_RESTART_COOLDOWN = 60  # Reduced cooldown to 60s for better user experience


@router.post("/wrapper/restart")
async def wrapper_restart(request: Request) -> dict:
    """Kill existing Wrapper process using psutil and start a new one."""
    import asyncio

    _check_rate_limit(request)
    _extract_token(request)

    global _last_wrapper_restart
    now = time.time()
    if now - _last_wrapper_restart < _WRAPPER_RESTART_COOLDOWN:
        remaining = int(_WRAPPER_RESTART_COOLDOWN - (now - _last_wrapper_restart))
        return {"success": False, "message": f"Please wait {remaining}s before restarting again"}
    _last_wrapper_restart = now

    result = await asyncio.get_event_loop().run_in_executor(None, do_wrapper_restart)
    return result


@router.get("/config")
async def get_config(request: Request) -> dict:
    _check_rate_limit(request)
    _extract_token(request)
    cfg = _get_current_config()
    cfg_dict = asdict(cfg)
    for secret in _SENSITIVE_CONFIG_KEYS:
        cfg_dict.pop(secret, None)
    return cfg_dict


@router.put("/config")
async def update_config(update: ConfigUpdate, request: Request) -> dict:
    _check_rate_limit(request)
    _extract_token(request)
    cfg = _get_current_config()

    # Apply only allowed non-sensitive user-preference fields from the update
    update_data = update.model_dump(exclude_none=True)
    safe_updates = {k: v for k, v in update_data.items() if k in ALLOWED_USER_FIELDS}
    for key, value in safe_updates.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)

    save_config(cfg)
    cfg_dict = asdict(cfg)
    for secret in _SENSITIVE_CONFIG_KEYS:
        cfg_dict.pop(secret, None)
    return cfg_dict


# ── Files ─────────────────────────────────────────────────────────────────────


@router.get("/files")
async def list_files(request: Request) -> list[dict]:
    _check_rate_limit(request)
    _extract_token(request)
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
    _extract_token(request)
    cfg = _get_current_config()

    if cfg.cloud_mode:
        raise HTTPException(status_code=404, detail="File serving disabled in cloud mode. Use download_url from track progress.")

    root = Path(cfg.output_path).resolve()
    full_path = (root / file_path).resolve()

    # Security: check containment before checking existence (prevents path existence oracle)
    try:
        full_path.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

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

    # Compute relative path from output_path for ZIP folder structure
    if track.relative_path:
        relative_path = track.relative_path
    else:
        try:
            temp_dir = dm._job_temp_dirs.get(job_id) or cfg.output_path
            relative_path = str(file_path.resolve().relative_to(Path(temp_dir).resolve()))
        except ValueError:
            relative_path = file_path.name

    # Stream file without Content-Disposition to prevent download manager
    # extensions (IDM, etc.) from intercepting JavaScript fetch() calls.
    # The filename is passed via X-Filename header for our JS code to read.
    # X-Relative-Path preserves folder structure for ZIP assembly.
    def file_iterator():
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        file_iterator(),
        media_type="application/octet-stream",
        headers={
            "X-Filename": file_path.name,
            "X-Relative-Path": relative_path,
        },
    )


@router.get("/save/{job_id}/{track_index}/lyrics")
async def save_track_lyrics(job_id: str, track_index: int, request: Request):
    """Serve the synced lyrics file for a completed track."""
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


# ── Reserve Cookies ───────────────────────────────────────────────────────────


def _check_reserve_passcode(request: Request) -> None:
    """Verify X-Reserve-Passcode header against configured passcode."""
    passcode = request.headers.get("X-Reserve-Passcode", "")
    cfg = _get_current_config()
    if not reserve_manager or not reserve_manager.verify_passcode(passcode, cfg):
        raise HTTPException(status_code=401, detail="Invalid reserve passcode")


@router.post("/reserve-cookies/contribute", response_model=ReserveContributeResponse)
async def contribute_reserve_cookie(
    req: ReserveContributeRequest,
    request: Request,
) -> ReserveContributeResponse:
    """Contribute a verified Apple Music token to the reserve pool.
    The token is extracted from the Authorization: Bearer <token> header.
    """
    _check_rate_limit(request)
    try:
        token = _extract_token(request)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    if not reserve_manager:
        return ReserveContributeResponse(id="", storefront=req.storefront, is_new=False)

    result = reserve_manager.contribute(
        token=token,
        storefront=req.storefront,
        has_subscription=req.has_subscription,
    )
    return ReserveContributeResponse(**result)


@router.post("/reserve-cookies/unlock", response_model=ReserveUnlockResponse)
async def unlock_reserve_cookies(
    req: ReserveUnlockRequest,
    request: Request,
) -> ReserveUnlockResponse:
    """Validate passcode and return list of reserve accounts (without tokens)."""
    _check_rate_limit(request)
    cfg = _get_current_config()
    if not reserve_manager or not reserve_manager.verify_passcode(req.passcode, cfg):
        raise HTTPException(status_code=401, detail="Invalid reserve passcode")

    accounts = reserve_manager.list_accounts()
    return ReserveUnlockResponse(
        success=True,
        accounts=[ReserveAccountInfo(**a) for a in accounts],
    )


@router.get("/reserve-cookies", response_model=list[ReserveAccountInfo])
async def list_reserve_cookies(request: Request) -> list[ReserveAccountInfo]:
    """List available reserve accounts (requires X-Reserve-Passcode header)."""
    _check_rate_limit(request)
    _check_reserve_passcode(request)
    accounts = reserve_manager.list_accounts() if reserve_manager else []
    return [ReserveAccountInfo(**a) for a in accounts]


@router.post("/reserve-cookies/connect/{account_id}", response_model=ReserveConnectResponse)
async def connect_reserve_cookie(
    account_id: str,
    request: Request,
) -> ReserveConnectResponse:
    """Connect to a reserve account by ID.
    Looks up token internally, authenticates with Apple Music, and returns the token and status.
    """
    _check_rate_limit(request)
    _check_reserve_passcode(request)

    if not reserve_manager:
        raise HTTPException(status_code=500, detail="Reserve manager not initialized")

    token = reserve_manager.get_token_by_id(account_id)
    if not token:
        raise HTTPException(status_code=404, detail="Account not found in reserve pool")

    dm = _get_user_dm(token)
    cfg = _get_current_config()

    try:
        if dm.is_authenticated:
            auth_status = AuthStatus(
                authenticated=True,
                active_subscription=dm.has_subscription,
                account_restrictions=dm.has_restrictions,
                storefront=dm.storefront,
            )
        else:
            result = await dm.authenticate_from_token(token, cfg.language)
            auth_status = AuthStatus(
                authenticated=result["authenticated"],
                active_subscription=result["active_subscription"],
                account_restrictions=result["account_restrictions"],
                storefront=result["storefront"],
            )

        reserve_manager.update_account_status(
            account_id,
            storefront=auth_status.storefront,
            has_subscription=auth_status.active_subscription,
        )
        return ReserveConnectResponse(token=token, auth_status=auth_status)
    except Exception as e:
        logger.error("Failed to authenticate reserve account %s: %s", account_id, e)
        raise HTTPException(
            status_code=400,
            detail=f"Failed to authenticate reserve account: {e}",
        )


@router.delete("/reserve-cookies/{account_id}")
async def delete_reserve_cookie(
    account_id: str,
    request: Request,
) -> dict[str, bool]:
    """Delete a reserve account from the pool by ID."""
    _check_rate_limit(request)
    _check_reserve_passcode(request)

    if not reserve_manager:
        raise HTTPException(status_code=500, detail="Reserve manager not initialized")

    success = reserve_manager.delete_account(account_id)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")

    return {"success": True}
