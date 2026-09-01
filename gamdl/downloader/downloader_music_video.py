from pathlib import Path

from ..interface.enums import MusicVideoCodec, MusicVideoResolution
from ..interface.interface_music_video import AppleMusicMusicVideoInterface
from ..interface.types import DecryptionKeyAv, StreamInfoAv
from ..utils import async_subprocess
from .constants import PLAYLIST_MEDIA_TYPE
from .downloader_base import AppleMusicBaseDownloader
from .enums import RemuxFormatMusicVideo, RemuxMode
from .types import DownloadItem


class AppleMusicMusicVideoDownloader(AppleMusicBaseDownloader):
    def __init__(
        self,
        base_downloader: AppleMusicBaseDownloader,
        interface: AppleMusicMusicVideoInterface,
        codec_priority: list[MusicVideoCodec] = [
            MusicVideoCodec.H264,
            MusicVideoCodec.H265,
        ],
        remux_format: RemuxFormatMusicVideo = RemuxFormatMusicVideo.M4V,
        resolution: MusicVideoResolution = MusicVideoResolution.R1080P,
        playlist_mode: bool = False,
    ):
        self.__dict__.update(base_downloader.__dict__)
        self.interface = interface
        self.codec_priority = codec_priority
        self.remux_format = remux_format
        self.resolution = resolution
        self.playlist_mode = playlist_mode or getattr(base_downloader, "playlist_mode", False)

    async def remux_mp4box(
        self,
        input_path_video: str,
        input_path_audio: str,
        output_path: str,
    ):
        await async_subprocess(
            self.full_mp4box_path,
            "-quiet",
            "-add",
            input_path_audio,
            "-add",
            input_path_video,
            output_path,
            silent=self.silent,
        )

    async def remux_ffmpeg(
        self,
        input_path_video: str,
        input_path_audio: str,
        output_path: str,
    ):
        await async_subprocess(
            self.full_ffmpeg_path,
            "-loglevel",
            "error",
            "-y",
            "-i",
            input_path_video,
            "-i",
            input_path_audio,
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            output_path,
            silent=self.silent,
        )

    async def get_decryption_key(
        self,
        stream_info: StreamInfoAv,
    ) -> DecryptionKeyAv:
        return await self.interface.get_decryption_key(
            stream_info,
            self.cdm,
        )

    async def decrypt_mp4decrypt(
        self,
        input_path: str,
        output_path: str,
        decryption_key: str,
    ):
        await async_subprocess(
            self.full_mp4decrypt_path,
            "--key",
            f"1:{decryption_key}",
            input_path,
            output_path,
            silent=self.silent,
        )

    async def stage(
        self,
        encrypted_path_video: str,
        encrypted_path_audio: str,
        decrypted_path_video: str,
        decrypted_path_audio: str,
        staged_path: str,
        decryption_key: DecryptionKeyAv,
    ):
        await self.decrypt_mp4decrypt(
            encrypted_path_video,
            decrypted_path_video,
            decryption_key.video_track.key,
        )
        await self.decrypt_mp4decrypt(
            encrypted_path_audio,
            decrypted_path_audio,
            decryption_key.audio_track.key,
        )

        if self.remux_mode == RemuxMode.MP4BOX:
            await self.remux_mp4box(
                decrypted_path_video,
                decrypted_path_audio,
                staged_path,
            )
        else:
            await self.remux_ffmpeg(
                decrypted_path_video,
                decrypted_path_audio,
                staged_path,
            )

    def get_cover_path(
        self,
        final_path: str,
        file_extension: str,
    ) -> str:
        return str(Path(final_path).with_suffix(file_extension))

    async def get_download_item(
        self,
        music_video_metadata: dict,
        playlist_metadata: dict = None,
    ) -> DownloadItem:
        download_item = DownloadItem()

        download_item.media_metadata = music_video_metadata
        download_item.playlist_metadata = playlist_metadata

        music_video_id = self.interface.get_media_id_of_library_media(
            music_video_metadata,
        )

        itunes_page_metadata = await self.interface.get_itunes_page_metadata(
            music_video_metadata,
        )
        download_item.media_tags = await self.interface.get_tags(
            music_video_metadata,
            itunes_page_metadata,
        )

        is_catalog_playlist = (
            playlist_metadata is not None
            and playlist_metadata.get("type") in PLAYLIST_MEDIA_TYPE
            and not playlist_metadata.get("type", "").startswith("library")
            and str(playlist_metadata.get("id", "")).startswith("pl.")
        )

        if playlist_metadata:
            download_item.playlist_tags = self.get_playlist_tags(
                playlist_metadata,
                music_video_metadata,
            )
            download_item.playlist_file_path = self.get_playlist_file_path(
                download_item.playlist_tags,
            )

        if self.playlist_mode and is_catalog_playlist:
            playlist_attrs = playlist_metadata.get("attributes", {})
            playlist_name = playlist_attrs.get("name")
            if playlist_name:
                download_item.media_tags.album = playlist_name

            playlist_artist = playlist_attrs.get("artistName") or playlist_attrs.get("curatorName")
            if playlist_artist:
                download_item.media_tags.album_artist = playlist_artist

            download_item.media_tags.disc = 1
            download_item.media_tags.disc_total = 1

            if download_item.playlist_tags and download_item.playlist_tags.playlist_track:
                download_item.media_tags.track = download_item.playlist_tags.playlist_track

            tracks_list = playlist_metadata.get("relationships", {}).get("tracks", {}).get("data", [])
            total_tracks = playlist_attrs.get("trackCount") or len(tracks_list) or download_item.media_tags.track_total
            if total_tracks:
                download_item.media_tags.track_total = int(total_tracks)

        download_item.stream_info = await self.interface.get_stream_info(
            music_video_metadata,
            itunes_page_metadata,
            self.codec_priority,
            self.resolution,
        )

        download_item.decryption_key = await self.get_decryption_key(
            download_item.stream_info,
        )

        download_item.random_uuid = self.get_random_uuid()
        download_item.staged_path = self.get_temp_path(
            music_video_id,
            download_item.random_uuid,
            "staged",
            (
                "."
                + (
                    "mp4"
                    if self.remux_format == RemuxFormatMusicVideo.MP4
                    else download_item.stream_info.file_format.value
                )
            ),
        )
        download_item.final_path = self.get_final_path(
            download_item.media_tags,
            Path(download_item.staged_path).suffix,
            download_item.playlist_tags,
        )

        cover_source_metadata = (
            playlist_metadata
            if (self.playlist_mode and is_catalog_playlist and playlist_metadata.get("attributes", {}).get("artwork"))
            else music_video_metadata
        )

        download_item.cover_url_template = self.interface.get_cover_url_template(
            cover_source_metadata,
            self.cover_format,
        )
        download_item.cover_url = self.interface.get_cover_url(
            download_item.cover_url_template,
            self.cover_size,
            self.cover_format,
        )

        cover_file_extension = await self.interface.get_cover_file_extension(
            download_item.cover_url,
            self.cover_format,
        )
        if cover_file_extension:
            download_item.cover_path = self.get_cover_path(
                download_item.final_path,
                cover_file_extension,
            )

        return download_item

    async def download(
        self,
        download_item: DownloadItem,
    ) -> None:
        encrypted_path_video = self.get_temp_path(
            download_item.media_metadata["id"],
            download_item.random_uuid,
            "encrypted_video",
            ".mp4",
        )
        encrypted_path_audio = self.get_temp_path(
            download_item.media_metadata["id"],
            download_item.random_uuid,
            "encrypted_audio",
            ".m4a",
        )

        await self.download_stream(
            download_item.stream_info.video_track.stream_url,
            encrypted_path_video,
        )
        await self.download_stream(
            download_item.stream_info.audio_track.stream_url,
            encrypted_path_audio,
        )

        decrypted_path_video = self.get_temp_path(
            download_item.media_metadata["id"],
            download_item.random_uuid,
            "decrypted_video",
            ".mp4",
        )
        decrypted_path_audio = self.get_temp_path(
            download_item.media_metadata["id"],
            download_item.random_uuid,
            "decrypted_audio",
            ".m4a",
        )

        await self.stage(
            encrypted_path_video,
            encrypted_path_audio,
            decrypted_path_video,
            decrypted_path_audio,
            download_item.staged_path,
            download_item.decryption_key,
        )

        cover_bytes = await self.interface.get_cover_bytes(download_item.cover_url)
        await self.apply_tags(
            download_item.staged_path,
            download_item.media_tags,
            cover_bytes,
        )
