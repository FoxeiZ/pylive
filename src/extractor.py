# pyright: reportUnknownMemberType=false

from __future__ import annotations

import asyncio
import logging
from collections.abc import Generator, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast, overload
from urllib.parse import parse_qs, urlparse

import httpx
from yt_dlp import YoutubeDL

from .constants import MAX_DURATION_SECONDS, MAX_RELATED_TRACKS, YTDL_OPTIONS
from .errors import VideoIsUnavailableError
from .utils.general import (
    get_and_cast,
    human_readable_to_int,
    time_string_to_seconds,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping
    from typing import Any, Literal

    from .models.extract import BaseExtractModel, ExtractModel, ProcessedExtractModel

logger = logging.getLogger(__name__)


def _sync_extract_info(url: str, process: bool) -> Mapping[str, Any] | None:
    with YoutubeDL(YTDL_OPTIONS) as ytdl:  # type: ignore
        return ytdl.extract_info(url, download=False, process=process)


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


def _parser_video_info(
    data: Mapping[str, Any], url: str, process: bool = False
) -> ExtractModel | ProcessedExtractModel:
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
            "is_expired": lambda: (
                expires_in > 0 and datetime.now(tz=UTC).timestamp() >= expires_in
            ),
        }
        if thumbnail := get_and_cast(data, "thumbnail", None):
            processed_info["thumbnail"] = thumbnail
        return processed_info
    return extract_info


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
        "BaseExtractModel | ProcessedExtractModel | None",
        await asyncio.to_thread(_sync_extract_info, url, process),
    )
    if not data:
        logger.warning(f"no data extracted from url: {url}")
        raise VideoIsUnavailableError("the video is unavailable.")

    if data.get("entries"):
        logger.debug("Processing playlist entries")
        entries = data.get("entries", {})
        data = (
            next(entries)
            if isinstance(entries, Generator)
            else entries[0]
            if entries
            else None
        )

        if not data:
            logger.warning("No valid entries found in playlist")
            raise VideoIsUnavailableError("No valid playlist entries")

    if data.get("is_live"):
        logger.warning("live videos are not supported")
        raise VideoIsUnavailableError("live videos are not supported.")

    if is_video_too_long(data):
        logger.warning("video exceeds maximum allowed duration")
        raise VideoIsUnavailableError("video exceeds maximum allowed duration.")

    return _parser_video_info(data, url, process)


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


async def get_related_tracks(
    video_info: BaseExtractModel,
) -> Sequence[BaseExtractModel]:
    result = await get_youtube_music_related_tracks(video_info.get("id", ""))
    if result:
        return result

    logger.info("Falling back to standard YouTube related tracks")
    return await get_youtube_related_tracks(video_info)


def _process_related_entries(
    entries: Iterable[Mapping[str, Any]],
    parser: Callable[[Mapping[str, Any]], BaseExtractModel | None],
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


def _parser_youtube_related_tracks(item: Mapping[str, Any]) -> BaseExtractModel | None:
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
    if view_count < 2000:
        return None

    duration = time_string_to_seconds(
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
        )
    )
    if duration < 30 or duration > 540:
        return None

    return {
        "title": get_and_cast(
            lockup_view_model,
            ("metadata", "lockupMetadataViewModel", "title", "content"),
            "Unknown Title",
        ),
        "id": video_id,
        "duration": duration,
        "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
        "process": False,
    }


async def get_youtube_related_tracks(
    video_info: BaseExtractModel,
) -> Sequence[BaseExtractModel]:
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
    async with httpx.AsyncClient() as session:
        response = await session.post(
            "https://www.youtube.com/youtubei/v1/next?key=AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8",
            json=api_payload,
        )

        if response.status_code != 200:
            logger.error(
                f"failed to fetch related tracks, status code: {response.status_code}"
            )
            return []

        data: dict[str, Any] = response.json()
        try:
            secondary_results = get_and_cast(
                data,
                (
                    "contents",
                    "twoColumnWatchNextResults",
                    "secondaryResults",
                    "secondaryResults",
                    "results",
                ),
                [],
                strict=True,
            )
            # secondary_results
            # data["contents"]["twoColumnWatchNextResults"]["secondaryResults"]["secondaryResults"]["results"]
        except KeyError as e:
            logger.error(f"error parsing related tracks response: {e}")
            return []

        related_tracks: list[BaseExtractModel] = []
        for item in secondary_results:
            parsed = _parser_youtube_related_tracks(item)
            if parsed:
                logging.info(f"related track found: {parsed}")
                related_tracks.append(parsed)

        logging.info(f"fetched {len(related_tracks)} related tracks from youtube")
        return related_tracks


def _parser_youtube_music_related_tracks(
    item: Mapping[str, Any],
) -> BaseExtractModel | None:
    panel_renderer: dict[str, Any] | None = item.get("playlistPanelVideoRenderer", None)
    if not panel_renderer:
        return None

    video_id = panel_renderer.get("videoId")
    if not video_id:
        return None

    duration = time_string_to_seconds(
        get_and_cast(
            panel_renderer,
            (
                "lengthText",
                "runs",
                0,
                "text",
            ),
            "0:00",
        )
    )
    if duration < 30 or duration > 540:
        return None

    title = get_and_cast(
        panel_renderer,
        (
            "title",
            "runs",
            0,
            "text",
        ),
        "Unknown Title",
    )

    return {
        "title": title,
        "id": video_id,
        "duration": duration,
        "process": False,
        "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
    }


async def get_youtube_music_related_tracks(
    current_track_id: str,
) -> Sequence[BaseExtractModel]:
    body = {
        "context": {
            "client": {
                "hl": "en",
                "gl": "US",
                "clientName": "WEB_REMIX",
                "clientVersion": "1.20220918.01.00",
                "originalUrl": "https://www.youtube.com",
                "platform": "DESKTOP",
            },
        },
        "enablePersistentPlaylistPanel": True,
        "isAudioOnly": True,
        "tunerSettingValue": "AUTOMIX_SETTING_NORMAL",
        "playlistId": f"RDAMVM{current_track_id}",
        "params": "wAEB",
    }
    async with httpx.AsyncClient() as session:
        response = await session.post(
            "https://music.youtube.com/youtubei/v1/next?key=AIzaSyC9XL3ZjWddXya6X74dJoCTL-WEYFDNX30&alt=json",
            json=body,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:88.0) Gecko/20100101 Firefox/88.0",
            },
        )

        if response.status_code != 200:
            logging.error(
                f"failed to fetch related tracks, status code: {response.status_code}"
            )
            return []

        data: dict[str, Any] = response.json()
        try:
            sections = get_and_cast(
                data,
                (
                    "contents",
                    "singleColumnMusicWatchNextResultsRenderer",
                    "tabbedRenderer",
                    "watchNextTabbedResultsRenderer",
                    "tabs",
                    0,
                    "tabRenderer",
                    "content",
                    "musicQueueRenderer",
                    "content",
                    "playlistPanelRenderer",
                    "contents",
                ),
                [],
                strict=True,
            )
        except KeyError as e:
            logging.error(f"error parsing related tracks response: {e}")
            return []

        related_tracks: list[BaseExtractModel] = []
        for section in sections:
            parsed = _parser_youtube_music_related_tracks(section)
            if parsed:
                logging.info(f"related track found: {parsed}")
                related_tracks.append(parsed)

        logging.info(f"fetched {len(related_tracks)} related tracks from youtube music")
        return related_tracks
