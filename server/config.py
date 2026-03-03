"""
Server configuration management.
Wraps gamdl's configuration options with JSON persistence.
"""

import json
import logging
import os
from pathlib import Path
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / ".gamdl" / "web_config.json"


@dataclass
class ServerConfig:
    # Authentication
    cookies_path: str = "./cookies.txt"

    # Apple Music options
    language: str = "en-US"

    # Output options
    output_path: str = "./Apple Music"
    temp_path: str = "."
    wvd_path: str | None = None
    overwrite: bool = False
    save_cover: bool = False
    save_playlist: bool = False
    cover_format: str = "jpg"
    cover_size: int = 1200

    # Rate limiting
    rate_limit_delay: float = 7.0  # seconds between track downloads

    # Download options
    download_mode: str = "ytdlp"
    remux_mode: str = "ffmpeg"
    use_wrapper: bool = False
    wrapper_account_url: str = "http://127.0.0.1:30020/"
    wrapper_decrypt_ip: str = "127.0.0.1:10020"
    nm3u8dlre_path: str = "N_m3u8DL-RE"
    mp4decrypt_path: str = "mp4decrypt"
    ffmpeg_path: str = "ffmpeg"
    mp4box_path: str = "MP4Box"

    # Template options
    album_folder_template: str = "{album_artist}/{album}"
    compilation_folder_template: str = "Compilations/{album}"
    no_album_folder_template: str = "{artist}/Unknown Album"
    single_disc_file_template: str = "{track:02d} {title}"
    multi_disc_file_template: str = "{disc}-{track:02d} {title}"
    no_album_file_template: str = "{title}"
    playlist_file_template: str = "Playlists/{playlist_artist}/{playlist_title}"
    date_tag_template: str = "%Y-%m-%dT%H:%M:%SZ"
    exclude_tags: list[str] = field(default_factory=list)
    truncate: int | None = None

    # Song options
    song_codec: str = "aac-legacy"
    synced_lyrics_format: str = "lrc"
    no_synced_lyrics: bool = False
    synced_lyrics_only: bool = False
    save_synced_lyrics: bool = False
    use_album_date: bool = False
    fetch_extra_tags: bool = False

    # Music video options
    music_video_codec_priority: list[str] = field(
        default_factory=lambda: ["h264", "h265"]
    )
    music_video_remux_format: str = "m4v"
    music_video_resolution: str = "1080p"

    # Post video options
    uploaded_video_quality: str = "best"

    # ── Cloud / Serverless ────────────────────────────────────────────────────
    cloud_mode: bool = False           # True when deployed to Cloud Run
    r2_endpoint: str = ""              # e.g. https://<account_id>.r2.cloudflarestorage.com
    r2_access_key: str = ""
    r2_secret_key: str = ""
    r2_bucket: str = "gamdl-files"


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> ServerConfig:
    """Load config from JSON file, or return defaults if not found."""
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            config = ServerConfig(**data)
        except Exception as e:
            logger.warning(f"Failed to load config from {config_path}: {e}")
            config = ServerConfig()
    else:
        config = ServerConfig()

    # Override with environment variables if present (for Cloud Run)
    if os.environ.get("CLOUD_MODE", "").lower() == "true":
        config.cloud_mode = True
    if os.environ.get("R2_ENDPOINT"):
        config.r2_endpoint = os.environ["R2_ENDPOINT"]
    if os.environ.get("R2_ACCESS_KEY"):
        config.r2_access_key = os.environ["R2_ACCESS_KEY"]
    if os.environ.get("R2_SECRET_KEY"):
        config.r2_secret_key = os.environ["R2_SECRET_KEY"]
    if os.environ.get("R2_BUCKET"):
        config.r2_bucket = os.environ["R2_BUCKET"]
    if os.environ.get("WRAPPER_ACCOUNT_URL"):
        config.wrapper_account_url = os.environ["WRAPPER_ACCOUNT_URL"]
    if os.environ.get("WRAPPER_DECRYPT_IP"):
        config.wrapper_decrypt_ip = os.environ["WRAPPER_DECRYPT_IP"]

    return config


def save_config(config: ServerConfig, config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Save config to JSON file."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(config)
    config_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(f"Config saved to {config_path}")
