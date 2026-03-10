"""
Pydantic models for API request/response schemas.
"""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


# ── Auth ──────────────────────────────────────────────────────────────────────

class AuthStatus(BaseModel):
    authenticated: bool = False
    active_subscription: bool = False
    account_restrictions: dict | None = None
    storefront: str | None = None


# ── Download ──────────────────────────────────────────────────────────────────

class DownloadRequest(BaseModel):
    url: str = Field(..., description="Apple Music URL to download")
    config: "ConfigUpdate | None" = Field(None, description="Optional per-user config overrides")


class DownloadStage(str, Enum):
    QUEUED = "queued"
    PARSING = "parsing"
    PREPARING = "preparing"
    DOWNLOADING = "downloading"
    DECRYPTING = "decrypting"
    TAGGING = "tagging"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


class TrackProgress(BaseModel):
    track_index: int = 0
    track_total: int = 0
    title: str = ""
    artist: str = ""
    album: str = ""
    cover_url: str = ""
    disc_number: int = 0
    disc_total: int = 0
    stage: DownloadStage = DownloadStage.QUEUED
    error_message: str | None = None
    file_path: str | None = None
    synced_lyrics_file_path: str | None = None
    cover_file_path: str | None = None
    relative_path: str | None = None    # path relative to job temp dir (for ZIP folder structure)
    download_url: str | None = None    # signed R2 URL for cloud mode


class DownloadJob(BaseModel):
    job_id: str
    url: str
    stage: DownloadStage = DownloadStage.QUEUED
    tracks: list[TrackProgress] = []
    current_track: int = 0
    total_tracks: int = 0
    error_message: str | None = None
    animated_artwork_paths: list[str] = []
    animated_artwork_urls: list[str] = []


# ── Preview ──────────────────────────────────────────────────────────────────

class PreviewTrack(BaseModel):
    track_number: int = 0
    title: str = ""
    artist: str = ""
    duration_ms: int = 0
    is_explicit: bool = False
    is_video: bool = False
    has_dolby_atmos: bool = False
    is_lossless: bool = False
    preview_url: str = ""

class PreviewResponse(BaseModel):
    url: str
    media_type: str = ""          # "song", "album", "playlist"
    title: str = ""
    artist: str = ""
    genre: str = ""
    year: str = ""
    release_date: str = ""
    track_count: int = 0
    total_duration_ms: int = 0
    copyright: str = ""
    artwork_url: str = ""         # high-res for display
    animated_artwork_url: str = "" # HLS video URL for animated artwork
    is_explicit: bool = False
    has_dolby_atmos: bool = False
    tracks: list[PreviewTrack] = []


# ── Config ────────────────────────────────────────────────────────────────────

class ConfigUpdate(BaseModel):
    """Partial config update — only include fields you want to change."""
    cookies_path: str | None = None
    language: str | None = None
    output_path: str | None = None
    temp_path: str | None = None
    wvd_path: str | None = None
    overwrite: bool | None = None
    save_cover: bool | None = None
    save_animated_artwork: bool | None = None
    save_playlist: bool | None = None
    cover_format: str | None = None
    cover_size: int | None = None
    rate_limit_delay: float | None = None
    download_mode: str | None = None
    remux_mode: str | None = None
    use_wrapper: bool | None = None
    wrapper_account_url: str | None = None
    wrapper_decrypt_ip: str | None = None
    nm3u8dlre_path: str | None = None
    mp4decrypt_path: str | None = None
    ffmpeg_path: str | None = None
    mp4box_path: str | None = None
    album_folder_template: str | None = None
    compilation_folder_template: str | None = None
    no_album_folder_template: str | None = None
    single_disc_file_template: str | None = None
    multi_disc_file_template: str | None = None
    no_album_file_template: str | None = None
    playlist_file_template: str | None = None
    date_tag_template: str | None = None
    exclude_tags: list[str] | None = None
    truncate: int | None = None
    song_codec: str | None = None
    codec_fallback: str | None = None
    synced_lyrics_format: str | None = None
    no_synced_lyrics: bool | None = None
    synced_lyrics_only: bool | None = None
    save_synced_lyrics: bool | None = None
    use_album_date: bool | None = None
    fetch_extra_tags: bool | None = None
    music_video_codec_priority: list[str] | None = None
    music_video_remux_format: str | None = None
    music_video_resolution: str | None = None
    uploaded_video_quality: str | None = None
    exclude_videos: bool | None = None


# ── SSE messages ──────────────────────────────────────────────────────────────

class WSMessage(BaseModel):
    type: str
    data: dict = {}
