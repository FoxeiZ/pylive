from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast, overload
from urllib.parse import parse_qs, urlparse

from curl_cffi import AsyncSession, Response
from yt_dlp import YoutubeDL

from .constants import MAX_DURATION_SECONDS, MAX_PLAYLIST_ENTRIES, MAX_RELATED_TRACKS
from .errors import VideoIsUnavailableException
from .models.ytdlp_music import YouTubeMusicPlaylistDict
from .utils.general import (
    get_and_cast,
    human_readable_to_int,
    time_string_to_seconds,
)
from .utils.validator import validate_typed_dict

if TYPE_CHECKING:
    from typing import Callable, Generator, Iterable, Literal, Mapping

    from .models.extract import BaseExtractModel, ExtractModel, ProcessedExtractModel

logger = logging.getLogger(__name__)

YTDL_OPTIONS = {
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "format": "bestaudio[ext=webm]/bestaudio/best",
    "restrictfilenames": True,
    "source_address": "0.0.0.0",
    "playlist_items": f"1-{MAX_PLAYLIST_ENTRIES}",
    "extract_flat": "in_playlist",
    # "lazy_playlist": True,
    "compat_opts": ["no-youtube-unavailable-videos"],
    "playlistend": MAX_PLAYLIST_ENTRIES,
    "playlistrandom": True,
    "cookiesfrombrowser": ("firefox",),
}


_YtdlInstance = YoutubeDL(YTDL_OPTIONS)  # type: ignore


def is_video_too_long(video_info: BaseExtractModel) -> bool:
    duration = video_info.get("duration", -1.0)
    if not duration or duration < 0:
        return True  # assume too long if no info
    return duration > MAX_DURATION_SECONDS


@overload
async def extract_video_info(
    url: str, process: Literal[True]
) -> ProcessedExtractModel: ...
@overload
async def extract_video_info(url: str, process: Literal[False]) -> ExtractModel: ...
@overload
async def extract_video_info(url: str) -> ProcessedExtractModel: ...


async def extract_video_info(
    url: str, process: bool = True
) -> ExtractModel | ProcessedExtractModel:
    logger.info(f"extracting video info from url: {url}")

    data = cast(
        "BaseExtractModel | None",
        await asyncio.to_thread(
            _YtdlInstance.extract_info, url, download=False, process=process
        ),
    )
    if not data:
        logger.warning(f"No data extracted from URL: {url}")
        raise VideoIsUnavailableException("The video is unavailable.")

    if data.get("entries"):
        logger.debug("Processing playlist entries")
        entries = data.get("entries", {})
        if isinstance(entries, Generator):
            data = next(entries)
        else:
            data = entries[0] if entries else None

        if not data:
            logger.warning("No valid entries found in playlist")
            raise VideoIsUnavailableException("No valid playlist entries")

    if data.get("is_live"):
        logger.warning("live videos are not supported")
        raise VideoIsUnavailableException("live videos are not supported.")

    if is_video_too_long(data):
        logger.warning("video exceeds maximum allowed duration")
        raise VideoIsUnavailableException("video exceeds maximum allowed duration.")

    extract_info: ExtractModel = {
        "title": get_and_cast(data, "title", "Unknown Title"),
        "id": get_and_cast(data, "id", "unknown"),
        "webpage_url": (
            get_and_cast(data, "webpage_url", None)
            or get_and_cast(data, "original_url", None)
            or get_and_cast(data, "url", url)
        ),
        "duration": get_and_cast(data, "duration", 0.0),
        "channel": get_and_cast(data, "uploader", "Unknown Channel"),
        "channel_url": (
            get_and_cast(data, "uploader_url", "")
            or get_and_cast(data, "channel_url", "")
        ),
        "process": False,
        "extractor": get_and_cast(data, "extractor", "unknown"),
    }

    if process:
        url = get_and_cast(data, "url", "")
        expires_in = int(parse_qs(urlparse(url).query).get("expire", [None])[0] or 0)
        processed_info: ProcessedExtractModel = {
            **extract_info,
            "url": url,
            "format_duration": get_and_cast(data, "duration_string", "0:00"),
            "expires_in": expires_in,
            "is_expired": lambda: expires_in != 0
            and expires_in <= 0
            or datetime.now(tz=timezone.utc).timestamp() >= expires_in,
        }
        if thumbnail := get_and_cast(data, "thumbnail", None):
            processed_info["thumbnail"] = thumbnail
        return processed_info
    return extract_info


# unused, not ported yet
# def fetch_playlist_tracks(playlist_url: str) -> list:
#     logger.info(f"Fetching playlist tracks from: {playlist_url}")

#     max_entries = YTDL_OPTIONS.get("playlistend", MAX_PLAYLIST_ENTRIES)
#     playlist_tracks = []

#     try:
#         with YoutubeDL(YTDL_OPTIONS) as ytdl:
#             data = ytdl.extract_info(url=playlist_url, download=False, process=False)

#             if not data:
#                 logger.warning(f"No playlist data found for: {playlist_url}")
#                 raise PlaylistNotFoundException("Playlist data not available")

#             entries = data.get("entries", [])
#             logger.debug(f"Found {len(entries)} entries in playlist")

#             for count, item in enumerate(entries):
#                 try:
#                     if count >= max_entries:
#                         logger.debug(f"Reached maximum entries limit: {max_entries}")
#                         break

#                     if not item:
#                         logger.debug(
#                             "Empty item encountered, stopping playlist processing"
#                         )
#                         break

#                     if is_video_too_long(item):
#                         logger.debug(
#                             f"Skipping long video: {item.get('title', 'unknown')}"
#                         )
#                         continue

#                     playlist_tracks.append(item["url"])

#                 except (TypeError, KeyError) as e:
#                     logger.warning(f"Error processing playlist item: {e}")
#                     if item and item.get("url"):
#                         logger.warning(f"Private or unavailable video: {item['url']}")

#         logger.info(
#             f"Successfully extracted {len(playlist_tracks)} tracks from playlist"
#         )
#         return playlist_tracks

#     except Exception as e:
#         logger.error(f"Error fetching playlist tracks: {e}")
#         raise PlaylistNotFoundException(f"Failed to process playlist: {str(e)}")


def _process_related_entries(
    entries: Iterable[Mapping],
    parser: Callable[[Mapping], BaseExtractModel | None],
    current_track_id: str | None,
) -> list[BaseExtractModel]:
    related_tracks: list[BaseExtractModel] = []
    for item in entries:
        if len(related_tracks) >= MAX_RELATED_TRACKS:
            break
        if not item:
            continue

        try:
            track_info = parser(item)
            if not track_info:
                continue

            # skip if the track is too long or is the current track
            if is_video_too_long(track_info):
                continue
            if track_info.get("id") == current_track_id:
                continue

            related_tracks.append(track_info)
        except (TypeError, KeyError) as e:
            logger.warning(f"error processing related track item: {e}")
            if item and item.get("url"):
                logger.warning(f"private or unavailable video: {item.get('url')}")

    return related_tracks


def _parser_youtube_related_tracks(item: Mapping) -> BaseExtractModel | None:
    lockup_view_model = item.get("lockupViewModel")
    if not (
        lockup_view_model
        and lockup_view_model.get("contentType") == "LOCKUP_CONTENT_TYPE_VIDEO"
    ):
        return None

    video_id = lockup_view_model.get("contentId")
    if not video_id:
        return None

    view_count = human_readable_to_int(
        get_and_cast(
            lockup_view_model,
            (
                "metadata",
                "lockupMetadataViewModel",
                "metadata",
                "contentMetadataViewModel",
                "metadataRows",
                1,
                "metadataParts",
                0,
                "text",
                "content",
            ),
            "0 views",
        )
    )
    if view_count < 5000:
        return None

    return {
        "title": get_and_cast(
            lockup_view_model,
            ("metadata", "lockupMetadataViewModel", "title", "content"),
            "Unknown Title",
        ),
        "id": video_id,
        "duration": time_string_to_seconds(
            get_and_cast(
                lockup_view_model,
                (
                    "contentImage",
                    "thumbnailViewModel",
                    "overlays",
                    0,
                    "thumbnailOverlayBadgeViewModel",
                    "thumbnailBadges",
                    0,
                    "thumbnailBadgeViewModel",
                    "text",
                ),
                "0:00",
            ),
        ),
        "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
        "process": False,
    }


async def get_youtube_related_tracks(
    video_info: BaseExtractModel,
):
    current_track_id = video_info.get("id", None)
    if not current_track_id:
        logger.warning("current track ID is missing, cannot fetch related tracks")
        return []

    api_payload = {
        "context": {
            "client": {
                "hl": "en",
                "gl": "US",
                "clientName": "WEB",
                "clientVersion": "2.20220809.02.00",
                "originalUrl": "https://www.youtube.com",
                "platform": "DESKTOP",
            },
        },
        "videoId": current_track_id,
        "racyCheckOk": True,
        "contentCheckOk": True,
    }
    async with AsyncSession[Response]() as session:
        response = await session.post(
            "https://www.youtube.com/youtubei/v1/next?key=AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8",
            json=api_payload,
        )

        if response.status_code != 200:
            logger.error(
                f"failed to fetch related tracks, status code: {response.status_code}"
            )
            return []

        data = response.json()
        try:
            secondary_results = data["contents"]["twoColumnWatchNextResults"][
                "secondaryResults"
            ]["secondaryResults"]["results"]
        except KeyError as e:
            logger.error(f"error parsing related tracks response: {e}")
            return []

        related_tracks = _process_related_entries(
            secondary_results, _parser_youtube_related_tracks, current_track_id
        )
        logger.info(f"fetched {len(related_tracks)} related tracks from youtube")
        return related_tracks


def _parser_youtube_music_related_tracks(item: Mapping) -> BaseExtractModel | None:
    return {
        "title": get_and_cast(item, "title", "Unknown Title"),
        "id": get_and_cast(item, "id", "unknown"),
        "webpage_url": get_and_cast(item, "url", ""),
        "duration": get_and_cast(item, "duration", 0.0),
        "process": False,
    }


async def get_youtube_music_related_tracks(
    video_info: BaseExtractModel,
) -> list[BaseExtractModel]:
    current_track_id = video_info.get("id", None)
    if not current_track_id:
        logger.warning("current track ID is missing, cannot fetch related tracks")
        return []

    pl_id = f"RDAMVM{current_track_id}"
    data = validate_typed_dict(
        _YtdlInstance.extract_info(
            url=f"https://music.youtube.com/watch?v={current_track_id}&list={pl_id}",
            download=False,
            process=False,
        ),
        YouTubeMusicPlaylistDict,
    )
    if not data:
        logger.warning("no data extracted from youtube music")
        return []

    entries = data.get("entries", [])
    related_tracks = _process_related_entries(
        entries, _parser_youtube_music_related_tracks, current_track_id
    )
    logger.info(f"fetched {len(related_tracks)} related tracks from youtube music")
    return related_tracks
