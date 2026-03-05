"""
Async download manager.
Wraps gamdl's AppleMusicDownloader to manage a queue of download jobs
with real-time progress tracking via SSE broadcast.
"""

import asyncio
import logging
import tempfile
import time
import traceback
import uuid
from dataclasses import dataclass, field
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
from gamdl.utils import GamdlError

from .config import ServerConfig
from .models import DownloadJob, DownloadStage, PreviewResponse, PreviewTrack, TrackProgress

logger = logging.getLogger(__name__)


class DownloadManager:
    """Manages download jobs with progress tracking and SSE broadcast."""

    def __init__(self) -> None:
        self.jobs: dict[str, DownloadJob] = {}
        self._job_configs: dict[str, ServerConfig] = {}
        self._job_temp_dirs: dict[str, str] = {}  # job_id -> temp dir path
        self._job_tasks: dict[str, asyncio.Task] = {}  # job_id -> asyncio.Task
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

    def _build_downloader(self, config: ServerConfig, job_id: str | None = None) -> AppleMusicDownloader:
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
            # Reuse existing temp dir for retries, create new one for first download
            if job_id in self._job_temp_dirs:
                output_path = self._job_temp_dirs[job_id]
            else:
                temp_dir = tempfile.mkdtemp(prefix=f"gamdl_{job_id[:8]}_")
                self._job_temp_dirs[job_id] = temp_dir
                output_path = temp_dir
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
        )
        music_video_downloader = AppleMusicMusicVideoDownloader(
            base_downloader=base_downloader,
            interface=music_video_interface,
            codec_priority=[
                MusicVideoCodec(c) for c in config.music_video_codec_priority
            ],
            remux_format=RemuxFormatMusicVideo(config.music_video_remux_format),
            resolution=MusicVideoResolution(config.music_video_resolution),
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
            tracks.append(PreviewTrack(
                track_number=1,
                title=attrs.get("name", "Unknown"),
                artist=attrs.get("artistName", "Unknown"),
                duration_ms=duration,
                is_explicit=attrs.get("contentRating", "") == "explicit",
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
                tracks.append(PreviewTrack(
                    track_number=i + 1,
                    title=t_attrs.get("name", "Unknown"),
                    artist=t_attrs.get("artistName", "Unknown"),
                    duration_ms=duration,
                    is_explicit=t_attrs.get("contentRating", "") == "explicit",
                    is_video=track.get("type") == "music-videos",
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

    async def submit_download(self, url: str, config: ServerConfig) -> DownloadJob:
        """Submit a new download job. Returns the job immediately."""
        job_id = str(uuid.uuid4())[:8]
        job = DownloadJob(
            job_id=job_id,
            url=url,
            stage=DownloadStage.QUEUED,
        )
        self.jobs[job_id] = job
        self._job_configs[job_id] = config
        await self._broadcast({"type": "job_created", "data": job.model_dump()})

        # Start processing in the background and track the task
        task = asyncio.create_task(self._process_job(job_id, url, config))
        self._job_tasks[job_id] = task
        return job

    async def _process_job(
        self, job_id: str, url: str, config: ServerConfig
    ) -> None:
        """Process a single download job end-to-end."""
        job = self.jobs[job_id]
        try:
            # 1. Parse URL
            job.stage = DownloadStage.PARSING
            await self._broadcast_job(job)

            downloader = self._build_downloader(config, job_id=job_id)
            url_info = downloader.get_url_info(url)

            if not url_info:
                job.stage = DownloadStage.ERROR
                job.error_message = f'Could not parse URL: "{url}"'
                await self._broadcast_job(job)
                return

            # 2. Build download queue
            job.stage = DownloadStage.PREPARING
            await self._broadcast_job(job)

            download_queue = await downloader.get_download_queue(url_info)
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
                        stage=DownloadStage.QUEUED,
                    )
                )
            await self._broadcast_job(job)

            # 4. Download each track
            job.stage = DownloadStage.DOWNLOADING
            for i, download_item in enumerate(download_queue):
                if job.stage == DownloadStage.CANCELLED:
                    break

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

                for attempt in range(max_retries + 1):
                    try:
                        result_item = await downloader.download(download_item)
                        job.tracks[i].stage = DownloadStage.DONE
                        if hasattr(result_item, 'final_path') and result_item.final_path:
                            job.tracks[i].file_path = str(result_item.final_path)
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
                        success = True
                        break
                    except GamdlError as e:
                        error_msg = str(e)
                        if "429" in error_msg and attempt < max_retries:
                            delay = retry_delays[attempt]
                            logger.warning(
                                f"Rate limited on track {i+1}, retrying in {delay}s "
                                f"(attempt {attempt+1}/{max_retries})"
                            )
                            job.tracks[i].error_message = f"Rate limited, retrying in {delay}s..."
                            await self._broadcast_job(job)
                            await asyncio.sleep(delay)
                            job.tracks[i].error_message = None
                            continue
                        job.tracks[i].stage = DownloadStage.ERROR
                        job.tracks[i].error_message = error_msg
                        logger.warning(f"Track skipped: {e}")
                        break
                    except Exception as e:
                        error_msg = str(e)
                        if "429" in error_msg and attempt < max_retries:
                            delay = retry_delays[attempt]
                            logger.warning(
                                f"Rate limited on track {i+1}, retrying in {delay}s "
                                f"(attempt {attempt+1}/{max_retries})"
                            )
                            job.tracks[i].error_message = f"Rate limited, retrying in {delay}s..."
                            await self._broadcast_job(job)
                            await asyncio.sleep(delay)
                            job.tracks[i].error_message = None
                            continue
                        job.tracks[i].stage = DownloadStage.ERROR
                        job.tracks[i].error_message = error_msg
                        logger.error(f"Track error: {e}", exc_info=True)
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

        except asyncio.CancelledError:
            job.stage = DownloadStage.CANCELLED
            logger.info(f"Job {job_id} cancelled")
            await self._broadcast_job(job)
        except Exception as e:
            job.stage = DownloadStage.ERROR
            job.error_message = str(e)
            logger.error(f"Job {job_id} failed: {e}", exc_info=True)
            await self._broadcast_job(job)

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
            # Use cached download queue when available (avoids redundant API call)
            download_queue = self._job_download_queues.get(job_id)

            if download_queue and track_index < len(download_queue):
                logger.info("[Retry] Using cached queue for job %s track %d", job_id, track_index)
            else:
                # Cache miss — rebuild from API (fallback)
                logger.info("[Retry] Cache miss for job %s, rebuilding queue from API", job_id)
                downloader = self._build_downloader(config, job_id=job_id)
                url_info = downloader.get_url_info(job.url)
                if not url_info:
                    track.stage = DownloadStage.ERROR
                    track.error_message = "Could not parse URL for retry"
                    await self._broadcast_job(job)
                    return

                download_queue = await downloader.get_download_queue(url_info)
                if not download_queue or track_index >= len(download_queue):
                    track.stage = DownloadStage.ERROR
                    track.error_message = "Could not rebuild download queue"
                    await self._broadcast_job(job)
                    return

                # Update cache for future retries
                self._job_download_queues[job_id] = download_queue

            download_item = download_queue[track_index]

            # Retry with backoff for rate limiting
            max_retries = 3
            retry_delays = [10, 30, 60]

            for attempt in range(max_retries + 1):
                try:
                    result_item = await downloader.download(download_item)
                    track.stage = DownloadStage.DONE
                    if hasattr(result_item, 'final_path') and result_item.final_path:
                        track.file_path = str(result_item.final_path)
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
                except (GamdlError, Exception) as e:
                    error_msg = str(e)
                    if "429" in error_msg and attempt < max_retries:
                        delay = retry_delays[attempt]
                        track.error_message = f"Rate limited, retrying in {delay}s..."
                        await self._broadcast_job(job)
                        await asyncio.sleep(delay)
                        track.error_message = None
                        continue
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

            download_queue = await downloader.get_download_queue(url_info)
            if not download_queue:
                for i in failed_indices:
                    job.tracks[i].error_message = "Could not rebuild download queue"
                await self._broadcast_job(job)
                return

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
                max_retries = 3
                retry_delays = [10, 30, 60]

                for attempt in range(max_retries + 1):
                    try:
                        result_item = await downloader.download(download_item)
                        track.stage = DownloadStage.DONE
                        if hasattr(result_item, 'final_path') and result_item.final_path:
                            track.file_path = str(result_item.final_path)
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
                    except (GamdlError, Exception) as e:
                        error_msg = str(e)
                        if "429" in error_msg and attempt < max_retries:
                            delay = retry_delays[attempt]
                            track.error_message = f"Rate limited, retrying in {delay}s..."
                            await self._broadcast_job(job)
                            await asyncio.sleep(delay)
                            track.error_message = None
                            continue
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
