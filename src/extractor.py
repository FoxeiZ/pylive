# pyright: reportArgumentType=false
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Callable, Generator, Iterable, Literal, cast, overload

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from .errors import (
    PlaylistNotFoundException,
    VideoIsLiveException,
    VideoIsOverLengthException,
    VideoIsUnavailableException,
)
from .utils.general import (
    HTTPRequestManager,
    get_and_cast,
    human_readable_to_int,
    time_string_to_seconds,
)

if TYPE_CHECKING:
    from .models.extract import BaseExtractModel, ExtractModel, ProcessedExtractModel
    from .models.youtube import YouTubeRelatedVideosResponse
    from .models.ytdlp_music import YouTubeMusicPlaylistDict
else:
    YouTubeMusicPlaylistDict = dict


logger = logging.getLogger(__name__)

MAX_DURATION_SECONDS = 8 * 60  # 8 minutes
MAX_PLAYLIST_ENTRIES = 25
MAX_RELATED_TRACKS = 25

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


def is_video_too_long(video_info: BaseExtractModel) -> bool:
    duration = video_info.get("duration", -1.0)
    if not duration or duration < 0:
        return True  # assume too long if no info
    return duration > MAX_DURATION_SECONDS


@overload
def extract_video_info(url: str, process: Literal[True]) -> ProcessedExtractModel: ...
@overload
def extract_video_info(url: str, process: Literal[False]) -> ExtractModel: ...
@overload
def extract_video_info(url: str) -> ProcessedExtractModel: ...


def extract_video_info(
    url: str, process: bool = True
) -> ProcessedExtractModel | ExtractModel:
    logger.info(f"Extracting video information from URL: {url}")

    with YoutubeDL(YTDL_OPTIONS) as ytdl:
        try:
            data = ytdl.extract_info(url=url, download=False, process=process)

            if not data:
                logger.warning(f"No data extracted from URL: {url}")
                raise VideoIsUnavailableException("No video data available")

            if data.get("entries"):
                logger.debug("Processing playlist entries")
                entries = data["entries"]  # pyright: ignore[reportGeneralTypeIssues]
                if isinstance(entries, Generator):
                    data = next(entries)
                else:
                    data = entries[0] if entries else None

                if not data:
                    logger.warning("No valid entries found in playlist")
                    raise VideoIsUnavailableException("No valid playlist entries")

            if data.get("is_live", False):
                logger.warning(f"Video is live stream: {url}")
                raise VideoIsLiveException("Live streams are not supported")

            if is_video_too_long(data):
                duration = data.get("duration", 0)
                logger.warning(f"Video too long ({duration}s): {url}")
                raise VideoIsOverLengthException(
                    f"Video duration {duration}s exceeds limit"
                )

            needs_reencoding = _check_audio_requirements(data)
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
                "need_reencode": needs_reencoding,
            }

            if process:
                processed_info: ProcessedExtractModel = {
                    **extract_info,
                    "url": get_and_cast(data, "url", ""),
                    "format_duration": get_and_cast(data, "duration_string", "0:00"),
                }
                return processed_info

            return extract_info

        except DownloadError as e:
            logger.error(f"Download error for URL {url}: {e}")
            raise VideoIsUnavailableException(f"Download error: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error extracting video info: {e}")
            raise


def _check_audio_requirements(video_data: dict) -> bool:
    sample_rate = get_and_cast(video_data, "asr", 0)
    audio_codec = get_and_cast(video_data, "acodec", "none")

    needs_reencoding = False

    if sample_rate != 48000:
        logger.debug(f"Audio sample rate {sample_rate} != 48000, re-encoding needed")
        needs_reencoding = True

    if audio_codec != "opus":
        logger.debug(f"Audio codec {audio_codec} != opus, re-encoding needed")
        needs_reencoding = True

    return needs_reencoding


# unused
def fetch_playlist_tracks(playlist_url: str) -> list:
    logger.info(f"Fetching playlist tracks from: {playlist_url}")

    max_entries = YTDL_OPTIONS.get("playlistend", MAX_PLAYLIST_ENTRIES)
    playlist_tracks = []

    try:
        with YoutubeDL(YTDL_OPTIONS) as ytdl:
            data = ytdl.extract_info(url=playlist_url, download=False, process=False)

            if not data:
                logger.warning(f"No playlist data found for: {playlist_url}")
                raise PlaylistNotFoundException("Playlist data not available")

            entries = data.get("entries", [])
            logger.debug(f"Found {len(entries)} entries in playlist")

            for count, item in enumerate(entries):
                try:
                    if count >= max_entries:
                        logger.debug(f"Reached maximum entries limit: {max_entries}")
                        break

                    if not item:
                        logger.debug(
                            "Empty item encountered, stopping playlist processing"
                        )
                        break

                    if is_video_too_long(item):
                        logger.debug(
                            f"Skipping long video: {item.get('title', 'unknown')}"
                        )
                        continue

                    playlist_tracks.append(item["url"])

                except (TypeError, KeyError) as e:
                    logger.warning(f"Error processing playlist item: {e}")
                    if item and item.get("url"):
                        logger.warning(f"Private or unavailable video: {item['url']}")

        logger.info(
            f"Successfully extracted {len(playlist_tracks)} tracks from playlist"
        )
        return playlist_tracks

    except Exception as e:
        logger.error(f"Error fetching playlist tracks: {e}")
        raise PlaylistNotFoundException(f"Failed to process playlist: {str(e)}")


def _process_related_entries(
    entries: Iterable[dict],
    parser: Callable[[dict], BaseExtractModel | None],
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
            logger.warning(f"Error processing related track item: {e}")
            if item and item.get("url"):
                logger.warning(f"Private or unavailable video: {item.get('url')}")

    return related_tracks


def get_youtube_related_tracks(
    current_track: BaseExtractModel,
) -> list[BaseExtractModel]:
    logger.debug("Getting YouTube related tracks")
    current_track_id = current_track.get("id")
    if not current_track_id:
        logger.warning("No video ID available for YouTube API")
        return []

    try:
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
        response = HTTPRequestManager.make_request(
            "https://www.youtube.com/youtubei/v1/next?key=AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8",
            method="POST",
            data=api_payload,
            headers={
                "Origin": "https://www.youtube.com",
                "Referer": "https://www.youtube.com/",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        if not response:
            logger.warning("No response from YouTube API")
            return []

        response_data = json.loads(response.read())
        secondary_results: YouTubeRelatedVideosResponse = response_data["contents"][
            "twoColumnWatchNextResults"
        ]["secondaryResults"]["secondaryResults"]["results"]

        def _parser(item: dict) -> BaseExtractModel | None:
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

        related_tracks = _process_related_entries(
            secondary_results, _parser, current_track_id
        )
        logger.debug(f"Found {len(related_tracks)} related tracks from YouTube")
        return related_tracks

    except Exception as e:
        logger.error(f"Error getting YouTube related tracks: {e}", exc_info=True)
        return []


def get_youtube_music_related_tracks(
    current_track: BaseExtractModel,
) -> list[BaseExtractModel]:
    logger.debug("Getting YouTube Music related tracks")
    video_id = current_track.get("id")
    if not video_id:
        logger.warning("No video ID available for YouTube Music API")
        return []

    pl_id = f"RDAMVM{video_id}"
    with YoutubeDL(YTDL_OPTIONS) as ytdl:
        try:
            data = cast(
                YouTubeMusicPlaylistDict,
                ytdl.extract_info(
                    url=f"https://music.youtube.com/watch?v={video_id}&list={pl_id}",
                    download=False,
                    process=False,
                ),
            )
            if not data:
                logger.warning("No data extracted from YouTube Music playlist")
                return []

            entries = data.get("entries", [])

            def _parser(item: dict) -> BaseExtractModel | None:
                return {
                    "title": get_and_cast(item, "title", "Unknown Title"),
                    "id": get_and_cast(item, "id", "unknown"),
                    "webpage_url": get_and_cast(item, "url", ""),
                    "duration": get_and_cast(item, "duration", 0.0),
                    "process": False,
                }

            related_tracks = _process_related_entries(
                entries, _parser, current_track.get("id")
            )
            logger.debug(
                f"Successfully extracted {len(related_tracks)} related tracks from YouTube Music"
            )
            return related_tracks

        except Exception as e:
            logger.error(
                f"Error fetching YouTube Music related tracks: {e}", exc_info=True
            )
            return []


if __name__ == "__main__":
    # youtube_related_tracks = get_youtube_related_tracks({"id": "wg0G0FOoCI8"})
    music_related_tracks = get_youtube_music_related_tracks({"id": "wg0G0FOoCI8"})
