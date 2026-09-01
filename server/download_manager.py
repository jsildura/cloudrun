"""
Async download manager.
Wraps gamdl's AppleMusicDownloader to manage a queue of download jobs
with real-time progress tracking via SSE broadcast.
"""

import asyncio
import logging
import os
import shutil
import tempfile
import time
import traceback
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

from gamdl.api import AppleMusicApi, ItunesApi
from gamdl.downloader import (
    AppleMusicBaseDownloader,
    AppleMusicDownloader,
    AppleMusicMusicVideoDownloader,
    AppleMusicSongDownloader,
    AppleMusicUploadedVideoDownloader,
    DownloadItem,
    DownloadMode,
    RemuxFormatMusicVideo,
    RemuxMode,
)
from gamdl.interface import (
    AppleMusicInterface,
    AppleMusicMusicVideoInterface,
    AppleMusicSongInterface,
    AppleMusicUploadedVideoInterface,
    CoverFormat,
    MusicVideoCodec,
    MusicVideoResolution,
    SongCodec,
    SyncedLyricsFormat,
    UploadedVideoQuality,
)
from gamdl.downloader.exceptions import MediaFileExists
from gamdl.downloader.constants import (
    ALBUM_MEDIA_TYPE,
    PLAYLIST_MEDIA_TYPE,
    VALID_URL_PATTERN,
)
from gamdl.utils import GamdlError

from .config import ServerConfig
from .models import DownloadJob, DownloadStage, PreviewResponse, PreviewTrack, TrackProgress

logger = logging.getLogger(__name__)


# Global concurrency semaphore — max 2 download jobs running at once across all users
_download_semaphore = asyncio.Semaphore(2)

# Ordered list of (job_id, DownloadJob) tuples currently waiting for a slot
_waiting_jobs: list[tuple[str, object]] = []

# Minimum free disk space (bytes) required to start a download (1 GB emergency threshold)
_MIN_FREE_DISK_BYTES = 1024 * 1024 * 1024  # 1 GB

# How long to keep completed jobs in memory before eviction (safety net)
_STALE_JOB_TTL = 1800  # 30 minutes — primary cleanup is event-driven from frontend

# Tracks which jobs currently hold a semaphore slot and their progress
# Key = job_id, Value = timestamp when the slot was acquired
_active_jobs: dict[str, float] = {}

# Maximum idle time (seconds) with zero track activity before watchdog force-cancels
_MAX_JOB_IDLE_TIME = 300  # 5 minutes of complete inactivity


class DownloadManager:
    """Manages download jobs with progress tracking and SSE broadcast."""

    def __init__(self) -> None:
        self.jobs: dict[str, DownloadJob] = {}
        self._job_configs: dict[str, ServerConfig] = {}
        self._job_temp_dirs: dict[str, str] = {}  # job_id -> temp dir path
        self._job_tasks: dict[str, asyncio.Task] = {}  # job_id -> asyncio.Task
        self._job_finish_times: dict[str, float] = {}  # job_id -> completion timestamp
        self._ws_clients: set[asyncio.Queue] = set()
        self._apple_music_api: AppleMusicApi | None = None
        self._itunes_api: ItunesApi | None = None
        self._config: ServerConfig | None = None
        self._task: asyncio.Task | None = None
        self._queue: asyncio.Queue = asyncio.Queue()
        self._storage = None  # CloudStorage instance (set when cloud_mode=True)
        self._current_token: str | None = None  # User's raw token for R2 key prefixing
        self._preview_cache: dict[str, tuple[float, PreviewResponse]] = {}
        self.PREVIEW_CACHE_TTL = 600  # 10 minutes
        self._job_download_queues: dict[str, list] = {}  # job_id -> cached download queue

    def set_storage(self, storage) -> None:
        """Set the CloudStorage instance for R2 uploads."""
        self._storage = storage

    def set_token(self, token: str) -> None:
        """Set the current user's raw token (used for R2 object key prefix)."""
        self._current_token = token

    @property
    def is_authenticated(self) -> bool:
        return self._apple_music_api is not None

    @property
    def has_subscription(self) -> bool:
        if self._apple_music_api is None:
            return False
        return self._apple_music_api.active_subscription

    @property
    def has_restrictions(self) -> dict | None:
        if self._apple_music_api is None:
            return None
        return self._apple_music_api.account_restrictions

    @property
    def storefront(self) -> str | None:
        if self._apple_music_api is None:
            return None
        return self._apple_music_api.storefront

    async def authenticate(self, config: ServerConfig) -> dict:
        """Initialize Apple Music API from cookies or wrapper."""
        self._config = config
        try:
            if config.use_wrapper:
                self._apple_music_api = await AppleMusicApi.create_from_wrapper(
                    wrapper_account_url=config.wrapper_account_url,
                    language=config.language,
                )
            else:
                self._apple_music_api = await AppleMusicApi.create_from_netscape_cookies(
                    cookies_path=config.cookies_path,
                    language=config.language,
                )

            self._itunes_api = ItunesApi(
                self._apple_music_api.storefront,
                self._apple_music_api.language,
            )

            return {
                "authenticated": True,
                "active_subscription": self._apple_music_api.active_subscription,
                "account_restrictions": self._apple_music_api.account_restrictions,
                "storefront": self._apple_music_api.storefront,
            }
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            self._apple_music_api = None
            self._itunes_api = None
            raise

    async def authenticate_from_token(self, token: str, language: str = "en-US") -> dict:
        """Authenticate using a raw media-user-token (from client-side cookie parsing).

        Instead of reading cookies from disk, this accepts the token directly
        as extracted by the browser-side AuthStorage module.
        """
        try:
            self._apple_music_api = await AppleMusicApi.create(
                media_user_token=token,
                language=language,
            )

            self._itunes_api = ItunesApi(
                self._apple_music_api.storefront,
                self._apple_music_api.language,
            )

            return {
                "authenticated": True,
                "active_subscription": self._apple_music_api.active_subscription,
                "account_restrictions": self._apple_music_api.account_restrictions,
                "storefront": self._apple_music_api.storefront,
            }
        except Exception as e:
            logger.error(f"Token authentication failed: {e}")
            self._apple_music_api = None
            self._itunes_api = None
            raise

    def _get_output_dir_for_job(self, job_id: str, url: str | None = None) -> str:
        """Get or create the output directory for a job.
        For collections (albums/playlists), uses a deterministic folder name based on
        storefront/media-id so retries and re-downloads can resume existing tracks.
        """
        if job_id in self._job_temp_dirs:
            return self._job_temp_dirs[job_id]

        if url:
            match = VALID_URL_PATTERN.match(url)
            if match:
                groups = match.groupdict()
                url_type = groups.get("type") or groups.get("library_type")
                # Single songs within album have sub_id -> keep per-job folder
                if not groups.get("sub_id") and (url_type in ALBUM_MEDIA_TYPE or url_type in PLAYLIST_MEDIA_TYPE):
                    media_id = groups.get("id") or groups.get("library_id") or "collection"
                    safe_id = "".join(c for c in media_id if c.isalnum() or c in ("-", "_"))[:40]
                    dir_path = Path(tempfile.gettempdir()) / f"gamdl_cache_{url_type}_{safe_id}"
                    dir_path.mkdir(parents=True, exist_ok=True)
                    self._job_temp_dirs[job_id] = str(dir_path)
                    logger.info("Using deterministic cache directory for %s %s: %s", url_type, media_id, dir_path)
                    return str(dir_path)

        temp_dir = tempfile.mkdtemp(prefix=f"gamdl_{job_id[:8]}_")
        self._job_temp_dirs[job_id] = temp_dir
        return temp_dir

    def _build_downloader(self, config: ServerConfig, job_id: str | None = None, url: str | None = None) -> AppleMusicDownloader:
        """Build a full gamdl downloader from the current config."""
        interface = AppleMusicInterface(
            self._apple_music_api,
            self._itunes_api,
        )
        song_interface = AppleMusicSongInterface(interface)
        music_video_interface = AppleMusicMusicVideoInterface(interface)
        uploaded_video_interface = AppleMusicUploadedVideoInterface(interface)

        # Use a temp directory so files aren't saved to the user's visible filesystem.
        # Files are served via the browser save dialog instead.
        if job_id:
            output_path = self._get_output_dir_for_job(job_id, url=url or (self.jobs.get(job_id).url if job_id in self.jobs else None))
        else:
            output_path = config.output_path

        # Only use wrapper for non-legacy codecs that actually need it.
        # Legacy codecs (aac-legacy, aac-he-legacy) always use mp4decrypt/ffmpeg
        # and don't benefit from the wrapper — passing use_wrapper=True for them
        # can cause the blob fetch / save dialog to fail silently.
        effective_use_wrapper = config.use_wrapper
        if config.song_codec in ("aac-legacy", "aac-he-legacy"):
            effective_use_wrapper = False
            if config.use_wrapper:
                logger.info(
                    "Legacy codec '%s' selected — overriding use_wrapper to False",
                    config.song_codec,
                )

        base_downloader = AppleMusicBaseDownloader(
            output_path=output_path,
            temp_path=config.temp_path,
            wvd_path=config.wvd_path,
            overwrite=config.overwrite,
            save_cover=config.save_cover,
            save_playlist=config.save_playlist,
            nm3u8dlre_path=config.nm3u8dlre_path,
            mp4decrypt_path=config.mp4decrypt_path,
            ffmpeg_path=config.ffmpeg_path,
            mp4box_path=config.mp4box_path,
            use_wrapper=effective_use_wrapper,
            wrapper_decrypt_ip=config.wrapper_decrypt_ip,
            download_mode=DownloadMode(config.download_mode),
            remux_mode=RemuxMode(config.remux_mode),
            cover_format=CoverFormat(config.cover_format),
            album_folder_template=config.album_folder_template,
            compilation_folder_template=config.compilation_folder_template,
            no_album_folder_template=config.no_album_folder_template,
            single_disc_file_template=config.single_disc_file_template,
            multi_disc_file_template=config.multi_disc_file_template,
            no_album_file_template=config.no_album_file_template,
            playlist_file_template=config.playlist_file_template,
            date_tag_template=config.date_tag_template,
            exclude_tags=config.exclude_tags if config.exclude_tags else None,
            cover_size=config.cover_size,
            truncate=config.truncate,
            silent=True,
            playlist_mode=config.playlist_mode,
        )
        song_downloader = AppleMusicSongDownloader(
            base_downloader=base_downloader,
            interface=song_interface,
            codec=SongCodec(config.song_codec),
            synced_lyrics_format=SyncedLyricsFormat(config.synced_lyrics_format),
            no_synced_lyrics=config.no_synced_lyrics,
            synced_lyrics_only=config.synced_lyrics_only,
            save_synced_lyrics=config.save_synced_lyrics,
            use_album_date=config.use_album_date,
            fetch_extra_tags=config.fetch_extra_tags,
            playlist_mode=config.playlist_mode,
        )
        music_video_downloader = AppleMusicMusicVideoDownloader(
            base_downloader=base_downloader,
            interface=music_video_interface,
            codec_priority=[
                MusicVideoCodec(c) for c in config.music_video_codec_priority
            ],
            remux_format=RemuxFormatMusicVideo(config.music_video_remux_format),
            resolution=MusicVideoResolution(config.music_video_resolution),
            playlist_mode=config.playlist_mode,
        )
        uploaded_video_downloader = AppleMusicUploadedVideoDownloader(
            base_downloader=base_downloader,
            interface=uploaded_video_interface,
            quality=UploadedVideoQuality(config.uploaded_video_quality),
        )
        downloader = AppleMusicDownloader(
            interface=interface,
            base_downloader=base_downloader,
            song_downloader=song_downloader,
            music_video_downloader=music_video_downloader,
            uploaded_video_downloader=uploaded_video_downloader,
        )
        return downloader

    def _is_collection_url(self, url: str) -> bool:
        """Return True if *url* points to an album or playlist (not a single song/video)."""
        from gamdl.downloader.constants import (
            ALBUM_MEDIA_TYPE,
            PLAYLIST_MEDIA_TYPE,
            VALID_URL_PATTERN,
        )
        match = VALID_URL_PATTERN.match(url)
        if not match:
            return False
        groups = match.groupdict()
        url_type = groups.get("type") or groups.get("library_type")
        # sub_id means a specific song inside an album URL
        if groups.get("sub_id"):
            return False
        return url_type in ALBUM_MEDIA_TYPE or url_type in PLAYLIST_MEDIA_TYPE

    async def preview_url(self, url: str, config: ServerConfig) -> PreviewResponse:
        """Fetch metadata for a URL without downloading. Returns preview info."""
        from gamdl.downloader.constants import (
            ALBUM_MEDIA_TYPE,
            MUSIC_VIDEO_MEDIA_TYPE,
            PLAYLIST_MEDIA_TYPE,
            SONG_MEDIA_TYPE,
            VALID_URL_PATTERN,
        )

        # --- Cache logic ---
        cache_key = f"{url}:{config.exclude_videos}"

        # Cleanup expired entries
        now = time.time()
        expired = [k for k, (ts, _) in self._preview_cache.items() if now - ts > self.PREVIEW_CACHE_TTL]
        for k in expired:
            del self._preview_cache[k]

        # Cache hit
        if cache_key in self._preview_cache:
            logger.info("[Preview] Cache hit for %s", url)
            return self._preview_cache[cache_key][1]

        logger.info("[Preview] Cache miss for %s — fetching from API", url)

        if not self._apple_music_api:
            raise ValueError("Not authenticated")

        # Parse URL
        match = VALID_URL_PATTERN.match(url)
        if not match:
            raise ValueError(f'Invalid Apple Music URL: "{url}"')

        groups = match.groupdict()
        url_type = groups.get("type") or groups.get("library_type")
        media_id = groups.get("sub_id") or groups.get("id") or groups.get("library_id")
        is_library = groups.get("library_id") is not None

        # If sub_id is present, it's a song within an album URL
        if groups.get("sub_id"):
            url_type = "song"

        api = self._apple_music_api
        response = None
        media_type = ""

        if url_type in SONG_MEDIA_TYPE:
            response = await api.get_song(media_id, extend="extendedAssetUrls,editorialVideo")
            media_type = "song"
        elif url_type in ALBUM_MEDIA_TYPE:
            if is_library:
                response = await api.get_library_album(media_id)
            else:
                response = await api.get_album(media_id, extend="extendedAssetUrls,editorialVideo")
            media_type = "album"
        elif url_type in PLAYLIST_MEDIA_TYPE:
            if is_library:
                response = await api.get_library_playlist(media_id)
            else:
                response = await api.get_playlist(media_id, extend="extendedAssetUrls,editorialVideo")
            media_type = "playlist"
        elif url_type in MUSIC_VIDEO_MEDIA_TYPE:
            response = await api.get_music_video(media_id)
            media_type = "music-video"
        else:
            raise ValueError(f'Unsupported URL type: "{url_type}"')

        if not response or not response.get("data"):
            raise ValueError(f'No metadata found for "{url}"')

        data = response["data"][0]
        attrs = data.get("attributes", {})

        # Extract artwork URL (600px for preview display)
        artwork = attrs.get("artwork", {})
        artwork_url = ""
        if artwork and artwork.get("url"):
            artwork_url = (
                artwork["url"]
                .replace("{w}", "600")
                .replace("{h}", "600")
            )

        # Extract genre and year
        genre_names = attrs.get("genreNames", [])
        genre = genre_names[0] if genre_names else ""
        release_date = attrs.get("releaseDate", "")
        year = release_date[:4] if release_date else ""

        # Extract animated artwork URL (HLS video) if available
        editorial_video = attrs.get("editorialVideo", {})
        animated_artwork_url = ""
        # Prefer square variant for our 1:1 artwork container
        for variant in ("motionSquareVideo1x1", "motionDetailSquare"):
            vid = editorial_video.get(variant, {})
            if vid.get("video"):
                animated_artwork_url = vid["video"]
                break

        # Build track list
        tracks = []
        total_duration_ms = 0

        # Dolby Atmos: use album-level audioTraits (matches Apple Music behaviour)
        album_audio_traits = attrs.get("audioTraits", [])
        has_dolby_atmos = "atmos" in album_audio_traits

        if media_type == "song":
            # Single song — one track
            duration = attrs.get("durationInMillis", 0)
            total_duration_ms = duration
            song_audio_traits = attrs.get("audioTraits", [])
            song_previews = attrs.get("previews", [])
            song_preview_url = song_previews[0].get("url", "") if song_previews else ""
            tracks.append(PreviewTrack(
                track_number=1,
                title=attrs.get("name", "Unknown"),
                artist=attrs.get("artistName", "Unknown"),
                duration_ms=duration,
                is_explicit=attrs.get("contentRating", "") == "explicit",
                has_dolby_atmos="atmos" in song_audio_traits,
                is_lossless="lossless" in song_audio_traits or "hi-res-lossless" in song_audio_traits,
                preview_url=song_preview_url,
            ))
        else:
            # Album or playlist — extract tracks from relationships
            relationships = data.get("relationships", {})
            tracks_data = relationships.get("tracks", {}).get("data", [])

            # Filter out music-video tracks when the setting is enabled
            if config.exclude_videos:
                tracks_data = [
                    t for t in tracks_data if t.get("type") != "music-videos"
                ]

            for i, track in enumerate(tracks_data):
                t_attrs = track.get("attributes", {})
                duration = t_attrs.get("durationInMillis", 0)
                total_duration_ms += duration
                t_audio_traits = t_attrs.get("audioTraits", [])
                t_previews = t_attrs.get("previews", [])
                t_preview_url = t_previews[0].get("url", "") if t_previews else ""
                tracks.append(PreviewTrack(
                    track_number=i + 1,
                    title=t_attrs.get("name", "Unknown"),
                    artist=t_attrs.get("artistName", "Unknown"),
                    duration_ms=duration,
                    is_explicit=t_attrs.get("contentRating", "") == "explicit",
                    is_video=track.get("type") == "music-videos",
                    has_dolby_atmos="atmos" in t_audio_traits,
                    is_lossless="lossless" in t_audio_traits or "hi-res-lossless" in t_audio_traits,
                    preview_url=t_preview_url,
                ))

        response = PreviewResponse(
            url=url,
            media_type=media_type,
            title=attrs.get("name", "Unknown"),
            artist=attrs.get("artistName", "Unknown"),
            genre=genre,
            year=year,
            release_date=release_date,
            track_count=len(tracks),
            total_duration_ms=total_duration_ms,
            copyright=attrs.get("copyright", ""),
            artwork_url=artwork_url,
            animated_artwork_url=animated_artwork_url,
            is_explicit=attrs.get("contentRating", "") == "explicit",
            has_dolby_atmos=has_dolby_atmos,
            tracks=tracks,
        )

        # Store in cache
        self._preview_cache[cache_key] = (time.time(), response)
        return response

    def _cleanup_job(self, job_id: str) -> None:
        """Remove temp directory and in-memory caches for a completed job."""
        # Remove temp directory from disk (preserve gamdl_cache_* deterministic directories for resumed downloads)
        temp_dir = self._job_temp_dirs.pop(job_id, None)
        if temp_dir:
            dir_name = Path(temp_dir).name
            if dir_name.startswith("gamdl_cache_"):
                logger.info("Preserving collection cache directory for job %s: %s", job_id, temp_dir)
            else:
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    logger.info("Cleaned up temp dir for job %s: %s", job_id, temp_dir)
                except Exception as e:
                    logger.warning("Failed to clean temp dir %s: %s", temp_dir, e)

        # Remove cached download queue (can be large)
        self._job_download_queues.pop(job_id, None)

        # Remove stored config
        self._job_configs.pop(job_id, None)

        # Remove task reference
        self._job_tasks.pop(job_id, None)

    def _evict_stale_jobs(self) -> None:
        """Remove completed/cancelled/errored jobs older than _STALE_JOB_TTL."""
        now = time.time()
        stale_ids = [
            jid for jid, ts in self._job_finish_times.items()
            if now - ts > _STALE_JOB_TTL
        ]
        for jid in stale_ids:
            self._cleanup_job(jid)
            self.jobs.pop(jid, None)
            self._job_finish_times.pop(jid, None)
            logger.info("Evicted stale job %s", jid)

    @classmethod
    def _emergency_cleanup_tmp(cls) -> None:
        """Emergency cleanup: remove orphaned gamdl temp directories older than 2 minutes in temp dir."""
        temp_dir = tempfile.gettempdir()
        logger.warning("Low disk space detected! Running emergency cleanup pass on %s...", temp_dir)
        now = time.time()

        # Collect temp directories belonging to active/in-flight jobs to prevent deleting them
        active_dirs: set[str] = set()
        try:
            from . import api_routes
            for dm in api_routes._user_managers.values():
                for jid, j in dm.jobs.items():
                    if j.stage in (
                        DownloadStage.QUEUED,
                        DownloadStage.PARSING,
                        DownloadStage.PREPARING,
                        DownloadStage.DOWNLOADING,
                    ):
                        td = dm._job_temp_dirs.get(jid)
                        if td:
                            active_dirs.add(os.path.abspath(td))
        except Exception:
            pass

        try:
            for item in Path(temp_dir).glob("gamdl_*"):
                try:
                    if os.path.abspath(str(item)) in active_dirs:
                        continue
                    if item.is_dir() and (now - item.stat().st_mtime > 120):
                        shutil.rmtree(item, ignore_errors=True)
                    elif item.is_file() and (now - item.stat().st_mtime > 120):
                        item.unlink(missing_ok=True)
                except Exception:
                    pass
            # Also clean orphan artwork files
            for item in Path(temp_dir).glob("artwork_*.mp4"):
                try:
                    if item.is_file() and (now - item.stat().st_mtime > 120):
                        item.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception as e:
            logger.error("Emergency cleanup error: %s", e)

    @classmethod
    def _check_disk_space(cls) -> bool:
        """Return True if there is at least 1GB of free space in temp dir.
        If space is low, automatically executes an immediate emergency cleanup pass
        to reclaim disk space before rejecting the job.
        """
        temp_dir = tempfile.gettempdir()
        try:
            usage = shutil.disk_usage(temp_dir)
            if usage.free < _MIN_FREE_DISK_BYTES:
                cls._emergency_cleanup_tmp()
                usage = shutil.disk_usage(temp_dir)
            return usage.free >= _MIN_FREE_DISK_BYTES
        except Exception:
            return True  # If we can't check, allow the download

    async def submit_download(self, url: str, config: ServerConfig, selected_tracks: list[int] | None = None) -> DownloadJob:
        """Submit a new download job. Returns the job immediately."""
        # Evict old completed jobs to free memory
        self._evict_stale_jobs()

        # Pre-check disk space (1GB emergency threshold)
        if not self._check_disk_space():
            free_mb = round(shutil.disk_usage('/tmp').free / 1048576)
            raise ValueError(
                f"Server disk space is critically low ({free_mb} MB available, 1024 MB required). "
                "An emergency cleanup pass was executed. Please wait for active downloads to finish and try again."
            )

        job_id = str(uuid.uuid4())[:8]
        job = DownloadJob(
            job_id=job_id,
            url=url,
            stage=DownloadStage.QUEUED,
            selected_tracks=selected_tracks,
        )
        self.jobs[job_id] = job
        self._job_configs[job_id] = config
        await self._broadcast({"type": "job_created", "data": job.model_dump()})

        # Start processing in the background and track the task
        task = asyncio.create_task(self._process_job(job_id, url, config))
        self._job_tasks[job_id] = task
        return job

    async def _probe_connectivity(self) -> bool:
        """Send a quick test request to Apple Music API to verify the
        WARP proxy tunnel is alive.

        Returns True if the network path works, False if all retries fail.
        The first attempt often 'wakes up' a sleeping WireGuard tunnel,
        so we retry up to 3 times with short delays.
        """
        import httpx as _httpx

        proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("ALL_PROXY")
        if not proxy_url:
            # No proxy configured — assume direct connectivity is fine
            return True

        target_url = "https://amp-api.music.apple.com"
        max_attempts = 3
        delay_between = 2  # seconds

        for attempt in range(1, max_attempts + 1):
            try:
                async with _httpx.AsyncClient(
                    proxy=proxy_url,
                    timeout=10.0,
                ) as client:
                    response = await client.head(target_url)
                    logger.info(
                        "Connectivity probe succeeded (attempt %d/%d, HTTP %s)",
                        attempt, max_attempts, response.status_code,
                    )
                    return True
            except Exception as e:
                logger.warning(
                    "Connectivity probe failed (attempt %d/%d): %s",
                    attempt, max_attempts, e,
                )
                if attempt < max_attempts:
                    await asyncio.sleep(delay_between)

        logger.error("Connectivity probe failed after %d attempts", max_attempts)
        return False

    async def _process_job(
        self, job_id: str, url: str, config: ServerConfig
    ) -> None:
        """Process a single download job end-to-end."""
        job = self.jobs[job_id]

        # Wait for a download slot (max 2 concurrent downloads globally)
        if _download_semaphore.locked():
            # Add to global waiting list for position tracking
            _waiting_jobs.append((job_id, job))
            job.stage = DownloadStage.QUEUED
            position = len(_waiting_jobs)
            job.error_message = (
                f"Position {position} in queue \u2014 "
                f"the server is currently processing other downloads. "
                f"Your download will start automatically in just a moment. "
                f"Please keep this page open."
            )
            await self._broadcast_job(job)

            # Update queue position every 3s while waiting
            async def _update_position():
                while (job_id, job) in _waiting_jobs:
                    await asyncio.sleep(3)
                    if (job_id, job) not in _waiting_jobs:
                        break
                    pos = _waiting_jobs.index((job_id, job)) + 1
                    job.error_message = (
                        f"Position {pos} in queue \u2014 "
                        f"the server is currently processing other downloads. "
                        f"Your download will start automatically in just a moment. "
                        f"Please keep this page open."
                    )
                    await self._broadcast_job(job)

            position_task = asyncio.create_task(_update_position())

        try:
            await _download_semaphore.acquire()
        except asyncio.CancelledError:
            # Cancelled while waiting for a slot — clean up waiting list
            if (job_id, job) in _waiting_jobs:
                _waiting_jobs.remove((job_id, job))
            try:
                position_task.cancel()
            except UnboundLocalError:
                pass
            job.stage = DownloadStage.CANCELLED
            logger.info("Job %s cancelled while waiting for semaphore slot", job_id)
            await self._broadcast_job(job)
            self._cleanup_job(job_id)
            return

        logger.info(
            "Job %s acquired semaphore slot (available: %s)",
            job_id, _download_semaphore._value,
        )
        _active_jobs[job_id] = time.time()  # Track when we acquired the slot

        # Remove from waiting list and cancel position updater
        if (job_id, job) in _waiting_jobs:
            _waiting_jobs.remove((job_id, job))
        try:
            position_task.cancel()
        except UnboundLocalError:
            pass  # Was never queued (semaphore was free)
        try:
            job.error_message = None  # Clear queue message
            job.last_active_time = time.time()
            # Dynamic timeout: collections with many tracks need ample time.
            # Base 1800s (30m) + up to 180s per track for rate limits and decryption.
            estimated_tracks = len(job.tracks) if job.tracks else 30
            job_timeout = max(1800, estimated_tracks * 180)
            await asyncio.wait_for(
                self._process_job_inner(job_id, url, config),
                timeout=job_timeout,
            )
        except asyncio.TimeoutError:
            job.stage = DownloadStage.ERROR
            job.error_message = (
                f"Download timed out after {int(job_timeout // 60)} minutes. "
                "The server may be experiencing network issues. Please try again."
            )
            logger.error("Job %s timed out after %ds", job_id, job_timeout)
            await self._broadcast_job(job)
            self._cleanup_job(job_id)
        finally:
            _download_semaphore.release()
            _active_jobs.pop(job_id, None)  # Stop tracking this job
            logger.info(
                "Job %s released semaphore slot (available: %s)",
                job_id, _download_semaphore._value,
            )
            # Record finish time for stale eviction
            self._job_finish_times[job_id] = time.time()
            # Only clean up immediately if files were actually uploaded to R2
            # (cloud_mode ON *and* storage client available).
            # If cloud_mode is on but R2 credentials are missing, files stay
            # on local disk and the frontend still needs to fetch them.
            if config.cloud_mode and self._storage:
                self._cleanup_job(job_id)

    async def _process_job_inner(
        self, job_id: str, url: str, config: ServerConfig
    ) -> None:
        """Inner download logic, called within the semaphore."""
        job = self.jobs[job_id]
        try:
            # 0. Verify network connectivity through WARP proxy
            #    This wakes up a sleeping WireGuard tunnel or fails fast
            if not await self._probe_connectivity():
                job.stage = DownloadStage.ERROR
                job.error_message = (
                    "Cannot reach Apple Music servers. "
                    "The network proxy may be down. Please try again in a few minutes."
                )
                await self._broadcast_job(job)
                return

            # 1. Parse URL
            job.stage = DownloadStage.PARSING
            await self._broadcast_job(job)
            logger.info("Job %s: PARSING — building downloader", job_id)

            downloader = self._build_downloader(config, job_id=job_id)
            url_info = downloader.get_url_info(url)
            logger.info("Job %s: URL parsed — type=%s", job_id, url_info)

            if not url_info:
                job.stage = DownloadStage.ERROR
                job.error_message = f'Could not parse URL: "{url}"'
                await self._broadcast_job(job)
                return

            # 2. Build download queue
            job.stage = DownloadStage.PREPARING
            await self._broadcast_job(job)
            logger.info("Job %s: PREPARING — fetching download queue from API", job_id)

            download_queue = await downloader.get_download_queue(url_info)
            logger.info("Job %s: download queue returned %d items", job_id, len(download_queue) if download_queue else 0)
            if not download_queue:
                job.stage = DownloadStage.ERROR
                job.error_message = f'No downloadable media found for "{url}"'
                await self._broadcast_job(job)
                return

            # Filter out music-video items for album/playlist downloads
            if config.exclude_videos and self._is_collection_url(url):
                download_queue = [
                    item for item in download_queue
                    if not (
                        isinstance(item, DownloadItem)
                        and item.media_metadata
                        and item.media_metadata.get("type") == "music-videos"
                    )
                ]
                if not download_queue:
                    job.stage = DownloadStage.ERROR
                    job.error_message = 'All tracks were music videos and excluded by settings'
                    await self._broadcast_job(job)
                    return

            # Filter to user-selected tracks (0-based indices from the preview)
            if job.selected_tracks is not None:
                valid_indices = [i for i in job.selected_tracks if 0 <= i < len(download_queue)]
                if not valid_indices:
                    job.stage = DownloadStage.ERROR
                    job.error_message = 'No valid tracks selected for download'
                    await self._broadcast_job(job)
                    return
                download_queue = [download_queue[i] for i in sorted(valid_indices)]
                logger.info(
                    "Track selection: downloading %d/%d tracks (indices: %s)",
                    len(download_queue), job.total_tracks or len(download_queue), valid_indices,
                )

            # 3. Populate track info
            # Cache the download queue for retries
            self._job_download_queues[job_id] = download_queue
            job.total_tracks = len(download_queue)
            job.tracks = []
            for i, item in enumerate(download_queue):
                attrs = {}
                if isinstance(item, DownloadItem) and item.media_metadata:
                    attrs = item.media_metadata.get("attributes", {})

                # Build cover URL from artwork
                cover_url = ""
                artwork = attrs.get("artwork", {})
                if artwork and artwork.get("url"):
                    cover_url = (
                        artwork["url"]
                        .replace("{w}", "300")
                        .replace("{h}", "300")
                    )

                job.tracks.append(
                    TrackProgress(
                        track_index=i + 1,
                        track_total=len(download_queue),
                        title=attrs.get("name", "Unknown"),
                        artist=attrs.get("artistName", "Unknown"),
                        album=attrs.get("albumName", ""),
                        cover_url=cover_url,
                        disc_number=attrs.get("discNumber", 1),
                        disc_total=attrs.get("discCount", 1),
                        stage=DownloadStage.QUEUED,
                    )
                )
            # Compute disc_total from actual track disc numbers
            # (discCount is album-level and may not be in per-track attrs)
            if job.tracks:
                actual_disc_total = max(t.disc_number for t in job.tracks)
                for t in job.tracks:
                    t.disc_total = actual_disc_total
            await self._broadcast_job(job)

            # 4. Download each track
            job.stage = DownloadStage.DOWNLOADING
            for i, download_item in enumerate(download_queue):
                if job.stage == DownloadStage.CANCELLED:
                    break

                job.last_active_time = time.time()

                # --- TRACK RESUMPTION PRE-CHECK ---
                # If track was already downloaded to disk previously (e.g. from an earlier cancelled run),
                # reuse it immediately and do not download again.
                final_p = Path(download_item.final_path) if getattr(download_item, "final_path", None) else None
                if final_p and final_p.exists() and final_p.stat().st_size > 1024:
                    logger.info(
                        "Track %d/%d already exists on disk (%d bytes): %s — reusing file",
                        i + 1, len(download_queue), final_p.stat().st_size, final_p,
                    )
                    job.current_track = i + 1
                    job.tracks[i].stage = DownloadStage.DONE
                    job.tracks[i].file_path = str(final_p)
                    try:
                        temp_dir = self._job_temp_dirs.get(job_id)
                        if temp_dir:
                            job.tracks[i].relative_path = str(
                                final_p.resolve().relative_to(Path(temp_dir).resolve())
                            )
                    except ValueError:
                        pass

                    # Check for existing synced lyrics and cover files
                    if getattr(download_item, "synced_lyrics_path", None):
                        lyrics_path = Path(download_item.synced_lyrics_path)
                        if lyrics_path.exists():
                            job.tracks[i].synced_lyrics_file_path = str(lyrics_path)
                    if getattr(download_item, "cover_path", None):
                        cover_path = Path(download_item.cover_path)
                        if cover_path.exists():
                            job.tracks[i].cover_file_path = str(cover_path)

                    await self._broadcast_job(job)
                    continue

                # Rate-limit delay before each track (except the first)
                if i > 0:
                    await asyncio.sleep(config.rate_limit_delay)

                job.current_track = i + 1
                job.tracks[i].stage = DownloadStage.DOWNLOADING
                await self._broadcast_job(job)

                # Retry with backoff for rate limiting (429)
                max_retries = 3
                retry_delays = [10, 30, 60]  # seconds
                success = False
                _used_fallback = False  # track whether we already tried the fallback

                for attempt in range(max_retries + 1):
                    job.last_active_time = time.time()
                    try:
                        result_item = await downloader.download(download_item)
                        job.tracks[i].stage = DownloadStage.DONE
                        if hasattr(result_item, 'final_path') and result_item.final_path:
                            job.tracks[i].file_path = str(result_item.final_path)
                            # Compute relative path from job temp dir for ZIP folder structure
                            try:
                                temp_dir = self._job_temp_dirs.get(job_id)
                                if temp_dir:
                                    job.tracks[i].relative_path = str(
                                        Path(result_item.final_path).resolve().relative_to(
                                            Path(temp_dir).resolve()
                                        )
                                    )
                            except ValueError:
                                pass
                            file_exists = Path(result_item.final_path).exists()
                            logger.info(
                                "Track %d/%d done: file_path=%s exists=%s",
                                i + 1, len(download_queue),
                                result_item.final_path, file_exists,
                            )
                            # Track synced lyrics file if it was saved
                            if hasattr(result_item, 'synced_lyrics_path') and result_item.synced_lyrics_path:
                                lyrics_path = Path(result_item.synced_lyrics_path)
                                if lyrics_path.exists():
                                    job.tracks[i].synced_lyrics_file_path = str(lyrics_path)
                                    logger.info(
                                        "Track %d/%d lyrics file: %s",
                                        i + 1, len(download_queue), lyrics_path,
                                    )
                            # Track cover file if it was saved
                            if hasattr(result_item, 'cover_path') and result_item.cover_path:
                                cover_path = Path(result_item.cover_path)
                                if cover_path.exists():
                                    job.tracks[i].cover_file_path = str(cover_path)
                                    logger.info(
                                        "Track %d/%d cover file: %s",
                                        i + 1, len(download_queue), cover_path,
                                    )
                            # Cloud mode: upload to R2, generate signed URL, clean up local
                            if config.cloud_mode and self._storage and self._current_token:
                                output_path = result_item.final_path
                                object_key = self._storage.object_key(
                                    user_token=self._current_token,
                                    job_id=job_id,
                                    filename=Path(output_path).name,
                                )
                                self._storage.upload_file(output_path, object_key)
                                job.tracks[i].download_url = self._storage.get_signed_url(object_key)
                                Path(output_path).unlink(missing_ok=True)
                        else:
                            logger.warning(
                                "Track %d/%d done but no final_path on result item",
                                i + 1, len(download_queue),
                            )
                    except MediaFileExists as e:
                        logger.info("Track %d/%d file already exists: %s — reusing file", i + 1, len(download_queue), e.media_path)
                        job.tracks[i].stage = DownloadStage.DONE
                        job.tracks[i].file_path = str(e.media_path)
                        try:
                            temp_dir = self._job_temp_dirs.get(job_id)
                            if temp_dir:
                                job.tracks[i].relative_path = str(
                                    Path(e.media_path).resolve().relative_to(Path(temp_dir).resolve())
                                )
                        except ValueError:
                            pass
                        success = True
                        break
                    except (GamdlError, Exception) as e:
                        error_msg = str(e)
                        # Retry on rate-limit (429) or transient connection errors
                        is_rate_limit = "429" in error_msg
                        is_conn_error = isinstance(e, (ConnectionResetError, ConnectionError, TimeoutError, OSError)) or isinstance(getattr(e, '__cause__', None), (ConnectionResetError, ConnectionError, TimeoutError, OSError))
                        if (is_rate_limit or is_conn_error) and attempt < max_retries:
                            delay = retry_delays[attempt] if is_rate_limit else [2, 5, 10][attempt]
                            reason = "Rate limited" if is_rate_limit else "Connection error"
                            logger.warning(
                                f"{reason} on track {i+1}, retrying in {delay}s "
                                f"(attempt {attempt+1}/{max_retries})"
                            )
                            job.tracks[i].error_message = f"{reason}, retrying in {delay}s..."
                            await self._broadcast_job(job)
                            await asyncio.sleep(delay)
                            job.tracks[i].error_message = None
                            continue

                        # ── Codec fallback: try once with the fallback codec ──
                        if (
                            not _used_fallback
                            and config.codec_fallback
                            and config.song_codec not in ("aac-legacy", "aac-he-legacy")
                        ):
                            _used_fallback = True
                            fallback_item = await self._execute_codec_fallback(
                                job=job,
                                track_index=i,
                                download_item=download_item,
                                config=config,
                                job_id=job_id,
                            )
                            if fallback_item:
                                success = True
                                download_queue[i] = fallback_item
                                break

                        job.tracks[i].stage = DownloadStage.ERROR
                        job.tracks[i].error_message = error_msg
                        logger.warning("Track %d failed: %s", i + 1, e)
                        break

                await self._broadcast_job(job)

            # 5. Download animated artwork (MP4) for albums/playlists
            if (
                config.save_animated_artwork
                and job.stage != DownloadStage.CANCELLED
                and url_info
            ):
                try:
                    await self._download_animated_artwork(job, url_info, config)
                except Exception as e:
                    logger.warning(f"Animated artwork download failed: {e}")

            # 6. Mark job done
            if job.stage != DownloadStage.CANCELLED:
                all_done = all(
                    t.stage in (DownloadStage.DONE, DownloadStage.ERROR)
                    for t in job.tracks
                )
                if all_done:
                    has_errors = any(
                        t.stage == DownloadStage.ERROR for t in job.tracks
                    )
                    job.stage = DownloadStage.DONE
                    if has_errors:
                        job.error_message = "Completed with errors"
            await self._broadcast_job(job)

            # Non-cloud mode: schedule cleanup after 15 minutes
            if not config.cloud_mode:
                asyncio.get_event_loop().call_later(
                    900,  # 15 minutes
                    lambda jid=job_id: self._cleanup_job(jid),
                )

        except asyncio.CancelledError:
            job.stage = DownloadStage.CANCELLED
            logger.info(f"Job {job_id} cancelled")
            await self._broadcast_job(job)
            # For non-collections (single tracks), clean up immediately.
            # For collections (albums/playlists), preserve files in deterministic cache
            # so redownloading or retrying resumes where it left off.
            if not self._is_collection_url(url):
                self._cleanup_job(job_id)
        except Exception as e:
            job.stage = DownloadStage.ERROR
            job.error_message = str(e)
            logger.error(f"Job {job_id} failed: {e}", exc_info=True)
            await self._broadcast_job(job)
            # For non-collections (single tracks), clean up immediately.
            # For collections, preserve files so retries can resume.
            if not self._is_collection_url(url):
                self._cleanup_job(job_id)

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job."""
        job = self.jobs.get(job_id)
        if not job:
            return False
        if job.stage in (DownloadStage.DONE, DownloadStage.ERROR, DownloadStage.CANCELLED):
            return False
        job.stage = DownloadStage.CANCELLED
        # Cancel the async task for immediate interruption
        task = self._job_tasks.get(job_id)
        if task and not task.done():
            task.cancel()
        return True

    async def _execute_codec_fallback(
        self,
        job: DownloadJob,
        track_index: int,
        download_item: DownloadItem,
        config: ServerConfig,
        job_id: str,
    ) -> DownloadItem | None:
        """Attempt to download a track using the fallback codec if configured.
        Returns the resulting DownloadItem on success, or None on failure."""
        if not config.codec_fallback or config.song_codec in ("aac-legacy", "aac-he-legacy"):
            return None

        track = job.tracks[track_index]
        original_codec = config.song_codec
        logger.warning(
            "Codec fallback: job %s track %d failed with '%s', retrying with '%s'",
            job_id, track_index + 1, original_codec, config.codec_fallback,
        )
        track.error_message = (
            f"Codec '{original_codec}' unavailable, falling back to "
            f"'{config.codec_fallback}'…"
        )
        track.stage = DownloadStage.DOWNLOADING
        await self._broadcast_job(job)

        fallback_cfg = replace(config, song_codec=config.codec_fallback)
        fallback_downloader = self._build_downloader(fallback_cfg, job_id=job_id)

        try:
            # Re-fetch/build the download item specifically for the fallback codec
            fallback_item = await fallback_downloader.get_single_download_item_no_filter(
                download_item.media_metadata,
                download_item.playlist_metadata,
            )
            if fallback_item.error:
                raise fallback_item.error

            try:
                result_item = await fallback_downloader.download(fallback_item)
            except MediaFileExists as e:
                logger.info(
                    "Codec fallback: track %d file already exists: %s — reusing file",
                    track_index + 1, e.media_path,
                )
                result_item = fallback_item
                result_item.final_path = e.media_path

            track.stage = DownloadStage.DONE
            track.error_message = None

            if hasattr(result_item, "final_path") and result_item.final_path:
                track.file_path = str(result_item.final_path)
                try:
                    temp_dir = self._job_temp_dirs.get(job_id)
                    if temp_dir:
                        track.relative_path = str(
                            Path(result_item.final_path).resolve().relative_to(Path(temp_dir).resolve())
                        )
                except ValueError:
                    pass

                if hasattr(result_item, "synced_lyrics_path") and result_item.synced_lyrics_path:
                    lyrics_path = Path(result_item.synced_lyrics_path)
                    if lyrics_path.exists():
                        track.synced_lyrics_file_path = str(lyrics_path)

                if hasattr(result_item, "cover_path") and result_item.cover_path:
                    cover_path = Path(result_item.cover_path)
                    if cover_path.exists():
                        track.cover_file_path = str(cover_path)

                if config.cloud_mode and self._storage and self._current_token:
                    output_path = result_item.final_path
                    object_key = self._storage.object_key(
                        user_token=self._current_token,
                        job_id=job_id,
                        filename=Path(output_path).name,
                    )
                    self._storage.upload_file(output_path, object_key)
                    track.download_url = self._storage.get_signed_url(object_key)
                    Path(output_path).unlink(missing_ok=True)

            logger.info("Codec fallback succeeded for job %s track %d", job_id, track_index + 1)
            return fallback_item

        except Exception as fallback_err:
            logger.error(
                "Codec fallback failed for job %s track %d: %s",
                job_id, track_index + 1, fallback_err,
            )
            track.stage = DownloadStage.ERROR
            track.error_message = (
                f"Fallback '{config.codec_fallback}' also failed: {fallback_err}"
            )
            return None

    async def _download_animated_artwork(
        self, job: DownloadJob, url_info, config: ServerConfig
    ) -> None:
        """Download animated artwork (MP4) for albums/playlists if available."""
        from gamdl.downloader.constants import (
            ALBUM_MEDIA_TYPE,
            PLAYLIST_MEDIA_TYPE,
        )

        url_type = url_info.type or url_info.library_type
        media_id = url_info.sub_id or url_info.id or url_info.library_id

        # Only for albums and playlists
        if url_type not in ALBUM_MEDIA_TYPE and url_type not in PLAYLIST_MEDIA_TYPE:
            return

        # Skip library albums/playlists (they don't have editorialVideo)
        if url_info.library_id:
            return

        if not self._apple_music_api:
            return

        # Fetch metadata with editorialVideo
        api = self._apple_music_api
        if url_type in ALBUM_MEDIA_TYPE:
            response = await api.get_album(media_id, extend="extendedAssetUrls,editorialVideo")
        else:
            response = await api.get_playlist(media_id, extend="extendedAssetUrls,editorialVideo")

        if not response or not response.get("data"):
            return

        attrs = response["data"][0].get("attributes", {})
        editorial_video = attrs.get("editorialVideo", {})
        if not editorial_video:
            logger.info("No animated artwork available for this %s", url_type)
            return

        # Collect HLS stream URLs for each variant
        variants = {
            "animated_cover_square": ("motionSquareVideo1x1", "motionDetailSquare"),
            "animated_cover_tall": ("motionTallVideo3x4", "motionDetailTall"),
        }

        hls_urls = {}  # name -> m3u8 url
        for name, keys in variants.items():
            for key in keys:
                vid = editorial_video.get(key, {})
                if vid.get("video"):
                    hls_urls[name] = vid["video"]
                    break

        if not hls_urls:
            logger.info("editorialVideo present but no usable HLS streams found")
            return

        # Determine output directory from the first successfully downloaded track
        output_dir = None
        for track in job.tracks:
            if track.file_path:
                output_dir = Path(track.file_path).parent
                break

        if not output_dir:
            # Fallback to temp dir
            output_dir = Path(tempfile.gettempdir())

        output_dir.mkdir(parents=True, exist_ok=True)

        # Download each variant using ffmpeg
        for name, m3u8_url in hls_urls.items():
            out_path = output_dir / f"{name}.mp4"
            logger.info("Downloading animated artwork: %s -> %s", name, out_path)

            try:
                proc = await asyncio.create_subprocess_exec(
                    config.ffmpeg_path,
                    "-y",
                    "-i", m3u8_url,
                    "-c", "copy",
                    "-bsf:a", "aac_adtstoasc",
                    "-movflags", "+faststart",
                    str(out_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await proc.communicate()

                if proc.returncode != 0:
                    logger.warning(
                        "ffmpeg failed for %s (exit %d): %s",
                        name, proc.returncode, stderr.decode()[:500],
                    )
                    continue

                if out_path.exists() and out_path.stat().st_size > 0:
                    job.animated_artwork_paths.append(str(out_path))
                    logger.info("Animated artwork saved: %s (%d bytes)", out_path, out_path.stat().st_size)

                    # Cloud mode: upload to R2
                    if config.cloud_mode and self._storage and self._current_token:
                        object_key = self._storage.object_key(
                            user_token=self._current_token,
                            job_id=job.job_id,
                            filename=out_path.name,
                        )
                        self._storage.upload_file(str(out_path), object_key)
                        job.animated_artwork_urls.append(
                            self._storage.get_signed_url(object_key)
                        )
                        out_path.unlink(missing_ok=True)
                else:
                    logger.warning("ffmpeg produced empty file for %s", name)

            except FileNotFoundError:
                logger.warning("ffmpeg not found at '%s', skipping animated artwork", config.ffmpeg_path)
                return
            except Exception as e:
                logger.warning("Failed to download animated artwork %s: %s", name, e)

        if job.animated_artwork_paths or job.animated_artwork_urls:
            await self._broadcast_job(job)

    async def retry_track(
        self, job_id: str, track_index: int, config: ServerConfig
    ) -> None:
        """Retry a single errored track in a completed job."""
        job = self.jobs.get(job_id)
        if not job:
            raise ValueError("Job not found")
        if track_index < 0 or track_index >= len(job.tracks):
            raise ValueError("Track index out of range")
        track = job.tracks[track_index]
        if track.stage != DownloadStage.ERROR:
            raise ValueError("Track is not in error state")

        asyncio.create_task(
            self._retry_track_task(job_id, track_index, config)
        )

    async def _retry_track_task(
        self, job_id: str, track_index: int, config: ServerConfig
    ) -> None:
        """Background task that re-downloads a single track."""
        job = self.jobs[job_id]
        track = job.tracks[track_index]

        # Reset track state
        track.stage = DownloadStage.DOWNLOADING
        track.error_message = None
        job.stage = DownloadStage.DOWNLOADING
        job.error_message = None
        await self._broadcast_job(job)

        try:
            downloader = self._build_downloader(config, job_id=job_id)

            # Use cached download queue when available (avoids redundant API call)
            download_queue = self._job_download_queues.get(job_id)

            if download_queue and track_index < len(download_queue):
                logger.info("[Retry] Using cached queue for job %s track %d", job_id, track_index)
            else:
                # Cache miss — rebuild from API (fallback)
                logger.info("[Retry] Cache miss for job %s, rebuilding queue from API", job_id)
                url_info = downloader.get_url_info(job.url)
                if not url_info:
                    track.stage = DownloadStage.ERROR
                    track.error_message = "Could not parse URL for retry"
                    await self._broadcast_job(job)
                    return

                download_queue = await downloader.get_download_queue(url_info)
                if not download_queue:
                    track.stage = DownloadStage.ERROR
                    track.error_message = "Could not rebuild download queue"
                    await self._broadcast_job(job)
                    return

                # Re-apply exclude_videos filter if applicable
                if config.exclude_videos:
                    download_queue = [
                        item for item in download_queue
                        if getattr(item, 'media_metadata', {}).get('type') != 'music-videos'
                    ]

                if track_index >= len(download_queue):
                    track.stage = DownloadStage.ERROR
                    track.error_message = "Track index out of range in rebuilt queue"
                    await self._broadcast_job(job)
                    return

                # Update cache for future retries
                self._job_download_queues[job_id] = download_queue

            download_item = download_queue[track_index]

            # Pre-check if already on disk
            final_p = Path(download_item.final_path) if getattr(download_item, "final_path", None) else None
            if final_p and final_p.exists() and final_p.stat().st_size > 1024:
                logger.info("[Retry] Track %d already on disk (%d bytes): %s", track_index, final_p.stat().st_size, final_p)
                track.stage = DownloadStage.DONE
                track.file_path = str(final_p)
                try:
                    _td = self._job_temp_dirs.get(job_id)
                    if _td:
                        track.relative_path = str(final_p.resolve().relative_to(Path(_td).resolve()))
                except ValueError:
                    pass
                if getattr(download_item, "synced_lyrics_path", None) and Path(download_item.synced_lyrics_path).exists():
                    track.synced_lyrics_file_path = str(download_item.synced_lyrics_path)
                if getattr(download_item, "cover_path", None) and Path(download_item.cover_path).exists():
                    track.cover_file_path = str(download_item.cover_path)
                job.last_active_time = time.time()
                await self._broadcast_job(job)
            else:
                # Retry with backoff for rate limiting
                max_retries = 3
                retry_delays = [10, 30, 60]

                for attempt in range(max_retries + 1):
                    job.last_active_time = time.time()
                    try:
                        result_item = await downloader.download(download_item)
                        track.stage = DownloadStage.DONE
                        if hasattr(result_item, 'final_path') and result_item.final_path:
                            track.file_path = str(result_item.final_path)
                            try:
                                _td = self._job_temp_dirs.get(job_id)
                                if _td:
                                    track.relative_path = str(
                                        Path(result_item.final_path).resolve().relative_to(Path(_td).resolve())
                                    )
                            except ValueError:
                                pass
                            # Track synced lyrics file if it was saved
                            if hasattr(result_item, 'synced_lyrics_path') and result_item.synced_lyrics_path:
                                lyrics_path = Path(result_item.synced_lyrics_path)
                                if lyrics_path.exists():
                                    track.synced_lyrics_file_path = str(lyrics_path)
                            # Track cover file if it was saved
                            if hasattr(result_item, 'cover_path') and result_item.cover_path:
                                cover_path = Path(result_item.cover_path)
                                if cover_path.exists():
                                    track.cover_file_path = str(cover_path)
                            # Cloud mode: upload to R2, generate signed URL, clean up local
                            cfg = self._job_configs.get(job_id)
                            if cfg and cfg.cloud_mode and self._storage and self._current_token:
                                output_path = result_item.final_path
                                object_key = self._storage.object_key(
                                    user_token=self._current_token,
                                    job_id=job_id,
                                    filename=Path(output_path).name,
                                    )
                                self._storage.upload_file(output_path, object_key)
                                track.download_url = self._storage.get_signed_url(object_key)
                                Path(output_path).unlink(missing_ok=True)
                        break
                    except MediaFileExists as e:
                        logger.info("[Retry] Track %d MediaFileExists: %s", track_index, e.media_path)
                        track.stage = DownloadStage.DONE
                        track.file_path = str(e.media_path)
                        try:
                            _td = self._job_temp_dirs.get(job_id)
                            if _td:
                                track.relative_path = str(Path(e.media_path).resolve().relative_to(Path(_td).resolve()))
                        except ValueError:
                            pass
                        break
                    except (GamdlError, Exception) as e:
                        error_msg = str(e)
                        if "429" in error_msg and attempt < max_retries:
                            delay = retry_delays[attempt]
                            track.error_message = f"Rate limited, retrying in {delay}s..."
                            await self._broadcast_job(job)
                            await asyncio.sleep(delay)
                            track.error_message = None
                            continue

                        # ── Codec fallback: try once with the fallback codec ──
                        cfg = self._job_configs.get(job_id) or config
                        if cfg.codec_fallback and cfg.song_codec not in ("aac-legacy", "aac-he-legacy"):
                            fallback_item = await self._execute_codec_fallback(
                                job=job,
                                track_index=track_index,
                                download_item=download_item,
                                config=cfg,
                                job_id=job_id,
                            )
                            if fallback_item:
                                if download_queue and track_index < len(download_queue):
                                    download_queue[track_index] = fallback_item
                                break

                        track.stage = DownloadStage.ERROR
                        track.error_message = error_msg
                        break

        except Exception as e:
            track.stage = DownloadStage.ERROR
            track.error_message = str(e)
            logger.error(f"Retry failed for job {job_id} track {track_index}: {e}", exc_info=True)

        # Re-evaluate job status
        all_done = all(
            t.stage in (DownloadStage.DONE, DownloadStage.ERROR)
            for t in job.tracks
        )
        if all_done:
            has_errors = any(t.stage == DownloadStage.ERROR for t in job.tracks)
            job.stage = DownloadStage.DONE
            if has_errors:
                job.error_message = "Completed with errors"
            else:
                job.error_message = None
        await self._broadcast_job(job)

    async def retry_all_failed(
        self, job_id: str, config: ServerConfig
    ) -> int:
        """Retry all errored tracks in a job. Returns count of retried tracks."""
        job = self.jobs.get(job_id)
        if not job:
            raise ValueError("Job not found")

        failed_indices = [
            i for i, t in enumerate(job.tracks)
            if t.stage == DownloadStage.ERROR
        ]
        if not failed_indices:
            raise ValueError("No failed tracks to retry")

        asyncio.create_task(
            self._retry_all_failed_task(job_id, failed_indices, config)
        )
        return len(failed_indices)

    async def _retry_all_failed_task(
        self, job_id: str, failed_indices: list[int], config: ServerConfig
    ) -> None:
        """Background task that re-downloads all failed tracks serially."""
        job = self.jobs[job_id]
        job.stage = DownloadStage.DOWNLOADING
        job.error_message = None
        await self._broadcast_job(job)

        try:
            downloader = self._build_downloader(config, job_id=job_id)
            url_info = downloader.get_url_info(job.url)
            if not url_info:
                for i in failed_indices:
                    job.tracks[i].error_message = "Could not parse URL for retry"
                await self._broadcast_job(job)
                return

            download_queue = self._job_download_queues.get(job_id)
            if not download_queue:
                download_queue = await downloader.get_download_queue(url_info)
                if not download_queue:
                    for i in failed_indices:
                        job.tracks[i].error_message = "Could not rebuild download queue"
                    await self._broadcast_job(job)
                    return

                if config.exclude_videos:
                    download_queue = [
                        item for item in download_queue
                        if getattr(item, 'media_metadata', {}).get('type') != 'music-videos'
                    ]
                self._job_download_queues[job_id] = download_queue

            for idx, track_index in enumerate(failed_indices):
                if track_index >= len(download_queue):
                    continue
                track = job.tracks[track_index]

                # Rate-limit delay between retries (except the first)
                if idx > 0:
                    await asyncio.sleep(config.rate_limit_delay)

                track.stage = DownloadStage.DOWNLOADING
                track.error_message = None
                await self._broadcast_job(job)

                download_item = download_queue[track_index]

                # Pre-check if already on disk
                final_p = Path(download_item.final_path) if getattr(download_item, "final_path", None) else None
                if final_p and final_p.exists() and final_p.stat().st_size > 1024:
                    logger.info("[RetryAll] Track %d already on disk (%d bytes): %s", track_index, final_p.stat().st_size, final_p)
                    track.stage = DownloadStage.DONE
                    track.file_path = str(final_p)
                    try:
                        _td = self._job_temp_dirs.get(job_id)
                        if _td:
                            track.relative_path = str(final_p.resolve().relative_to(Path(_td).resolve()))
                    except ValueError:
                        pass
                    if getattr(download_item, "synced_lyrics_path", None) and Path(download_item.synced_lyrics_path).exists():
                        track.synced_lyrics_file_path = str(download_item.synced_lyrics_path)
                    if getattr(download_item, "cover_path", None) and Path(download_item.cover_path).exists():
                        track.cover_file_path = str(download_item.cover_path)
                    job.last_active_time = time.time()
                    await self._broadcast_job(job)
                    continue

                max_retries = 3
                retry_delays = [10, 30, 60]

                for attempt in range(max_retries + 1):
                    job.last_active_time = time.time()
                    try:
                        result_item = await downloader.download(download_item)
                        track.stage = DownloadStage.DONE
                        if hasattr(result_item, 'final_path') and result_item.final_path:
                            track.file_path = str(result_item.final_path)
                            try:
                                _td = self._job_temp_dirs.get(job_id)
                                if _td:
                                    track.relative_path = str(
                                        Path(result_item.final_path).resolve().relative_to(Path(_td).resolve())
                                    )
                            except ValueError:
                                pass
                            # Track synced lyrics file if it was saved
                            if hasattr(result_item, 'synced_lyrics_path') and result_item.synced_lyrics_path:
                                lyrics_path = Path(result_item.synced_lyrics_path)
                                if lyrics_path.exists():
                                    track.synced_lyrics_file_path = str(lyrics_path)
                            # Track cover file if it was saved
                            if hasattr(result_item, 'cover_path') and result_item.cover_path:
                                cover_path = Path(result_item.cover_path)
                                if cover_path.exists():
                                    track.cover_file_path = str(cover_path)
                            # Cloud mode: upload to R2, generate signed URL, clean up local
                            if config.cloud_mode and self._storage and self._current_token:
                                output_path = result_item.final_path
                                object_key = self._storage.object_key(
                                    user_token=self._current_token,
                                    job_id=job_id,
                                    filename=Path(output_path).name,
                                )
                                self._storage.upload_file(output_path, object_key)
                                track.download_url = self._storage.get_signed_url(object_key)
                                Path(output_path).unlink(missing_ok=True)
                        break
                    except MediaFileExists as e:
                        logger.info("[RetryAll] Track %d MediaFileExists: %s", track_index, e.media_path)
                        track.stage = DownloadStage.DONE
                        track.file_path = str(e.media_path)
                        try:
                            _td = self._job_temp_dirs.get(job_id)
                            if _td:
                                track.relative_path = str(Path(e.media_path).resolve().relative_to(Path(_td).resolve()))
                        except ValueError:
                            pass
                        break
                    except (GamdlError, Exception) as e:
                        error_msg = str(e)
                        if "429" in error_msg and attempt < max_retries:
                            delay = retry_delays[attempt]
                            track.error_message = f"Rate limited, retrying in {delay}s..."
                            await self._broadcast_job(job)
                            await asyncio.sleep(delay)
                            track.error_message = None
                            continue

                        # ── Codec fallback: try once with the fallback codec ──
                        if config.codec_fallback and config.song_codec not in ("aac-legacy", "aac-he-legacy"):
                            fallback_item = await self._execute_codec_fallback(
                                job=job,
                                track_index=track_index,
                                download_item=download_item,
                                config=config,
                                job_id=job_id,
                            )
                            if fallback_item:
                                if download_queue and track_index < len(download_queue):
                                    download_queue[track_index] = fallback_item
                                break

                        track.stage = DownloadStage.ERROR
                        track.error_message = error_msg
                        break

                await self._broadcast_job(job)

        except Exception as e:
            logger.error(f"Retry-all failed for job {job_id}: {e}", exc_info=True)

        # Re-evaluate job status
        all_done = all(
            t.stage in (DownloadStage.DONE, DownloadStage.ERROR)
            for t in job.tracks
        )
        if all_done:
            has_errors = any(t.stage == DownloadStage.ERROR for t in job.tracks)
            job.stage = DownloadStage.DONE
            if has_errors:
                job.error_message = "Completed with errors"
            else:
                job.error_message = None
        await self._broadcast_job(job)

    # ── SSE broadcast ─────────────────────────────────────────────────────────

    def register_ws(self, queue: asyncio.Queue) -> None:
        self._ws_clients.add(queue)

    def unregister_ws(self, queue: asyncio.Queue) -> None:
        self._ws_clients.discard(queue)

    async def _broadcast(self, message: dict) -> None:
        for q in self._ws_clients:
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                pass

    async def _broadcast_job(self, job: DownloadJob) -> None:
        await self._broadcast({"type": "job_update", "data": job.model_dump()})

def check_semaphore_health() -> None:
    """Watchdog: force-cancel any download job that has been inactive/stalled
    with zero track activity for longer than _MAX_JOB_IDLE_TIME (5 minutes).

    Called every 60 seconds from the periodic cleanup loop in main.py.
    Active downloads completing tracks will never be prematurely cancelled.
    """
    from . import api_routes

    now = time.time()
    stuck_jobs = []

    for job_id, acquire_time in list(_active_jobs.items()):
        # Look up job's last_active_time from user managers
        last_active = acquire_time
        for dm in api_routes._user_managers.values():
            job = dm.jobs.get(job_id)
            if job and job.last_active_time:
                last_active = max(last_active, job.last_active_time)
                break

        idle_seconds = now - last_active
        if idle_seconds > _MAX_JOB_IDLE_TIME:
            stuck_jobs.append((job_id, idle_seconds))

    for job_id, idle_seconds in stuck_jobs:
        logger.error(
            "Watchdog: force-cancelling zombie job %s (idle with zero activity for %ds)",
            job_id, int(idle_seconds),
        )

        # Find the asyncio Task for this job across all user managers
        # and cancel it — the CancelledError will propagate through
        # _process_job_inner's except block, which sets the job to
        # CANCELLED state and releases the semaphore in the finally block
        from . import api_routes
        for dm in api_routes._user_managers.values():
            task = dm._job_tasks.get(job_id)
            if task and not task.done():
                task.cancel()
                logger.info("Watchdog: sent cancel signal to job %s task", job_id)
                break
        else:
            # Task not found — force-release semaphore only if this job was actually tracked as holding a slot
            if _active_jobs.pop(job_id, None) is not None:
                logger.warning(
                    "Watchdog: job %s task not found, force-releasing semaphore slot",
                    job_id,
                )
                _download_semaphore.release()
