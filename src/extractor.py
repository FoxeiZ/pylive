# pyright: reportArgumentType=false

import json
import logging
from typing import Generator

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from .errors import (
    PlaylistNotFoundException,
    VideoIsLiveException,
    VideoIsOverLengthException,
    VideoIsUnavailableException,
)
from .utils.general import HTTPRequestManager

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
    "playlist_items": "1-10",
    "extract_flat": True,
    "compat_opts": ["no-youtube-unavailable-videos"],
    "playlistend": 10,
    "playlistrandom": True,
    "cookiesfrombrowser": ("firefox",),
}

MAX_DURATION_SECONDS = 900.0  # 15 minutes
MAX_PLAYLIST_ENTRIES = 25
MAX_RELATED_TRACKS = 5


def is_video_too_long(video_info: dict) -> bool:
    duration = video_info.get("duration", MAX_DURATION_SECONDS + 1)
    return duration > MAX_DURATION_SECONDS


def extract_video_info(url: str, process: bool = True) -> dict:
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
            video_info = {
                "title": data.get("title", "Unknown Title"),
                "id": data.get("id", "unknown"),
                "webpage_url": (
                    data.get("webpage_url")
                    or data.get("original_url")
                    or data.get("url", url)
                ),
                "duration": data.get("duration", 0.0),
                "channel": data.get("uploader", "Unknown Channel"),
                "channel_url": (
                    data.get("uploader_url") or data.get("channel_url", "")
                ),
                "process": False,
                "extractor": data.get("extractor", "unknown"),
                "need_reencode": needs_reencoding,
            }

            if process:
                video_info.update(
                    {
                        "url": data.get("url"),
                        "process": True,
                        "format_duration": data.get("duration_string", "0:00"),
                    }
                )
                logger.debug(f"Video processed for streaming: {video_info['title']}")

            logger.info(f"Successfully extracted video info: {video_info['title']}")
            return video_info

        except DownloadError as e:
            logger.error(f"Download error for URL {url}: {e}")
            raise VideoIsUnavailableException(f"Download error: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error extracting video info: {e}")
            raise


def _check_audio_requirements(video_data: dict) -> bool:
    sample_rate = video_data.get("asr", 0)
    audio_codec = video_data.get("acodec", "none")

    needs_reencoding = False

    if sample_rate != 48000:
        logger.debug(f"Audio sample rate {sample_rate} != 48000, re-encoding needed")
        needs_reencoding = True

    if audio_codec != "opus":
        logger.debug(f"Audio codec {audio_codec} != opus, re-encoding needed")
        needs_reencoding = True

    return needs_reencoding


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


def get_youtube_music_related_tracks(current_track: dict) -> list:
    logger.debug("Getting YouTube Music related tracks")

    video_id = current_track.get("id")
    if not video_id:
        logger.warning("No video ID available for YouTube Music API")
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
            "videoId": video_id,
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
            logger.warning("No response from YouTube Music API")
            return []

        response_data = json.loads(response.read())

        try:
            secondary_results = response_data["contents"]["twoColumnWatchNextResults"][
                "secondaryResults"
            ]["secondaryResults"]["results"]
        except KeyError as e:
            logger.warning(f"Unexpected API response structure: {e}")
            return []

        related_urls = []
        for count, item in enumerate(secondary_results):
            if count >= MAX_RELATED_TRACKS:
                break

            compact_video = item.get("compactVideoRenderer")
            if not compact_video:
                continue

            video_id = compact_video.get("videoId")
            if video_id:
                related_urls.append(f"https://www.youtube.com/watch?v={video_id}")

        logger.debug(f"Found {len(related_urls)} related tracks from YouTube Music")
        return related_urls

    except Exception as e:
        logger.error(f"Error getting YouTube Music related tracks: {e}")
        return []


def get_youtube_related_tracks(current_track: dict) -> list:
    logger.debug("Getting YouTube related tracks")

    video_id = current_track.get("id")
    if not video_id:
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
            "videoId": video_id,
            "racyCheckOk": True,
            "contentCheckOk": True,
        }

        # Make API request
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

        try:
            secondary_results = response_data["contents"]["twoColumnWatchNextResults"][
                "secondaryResults"
            ]["secondaryResults"]["results"]
        except KeyError as e:
            logger.warning(f"Unexpected YouTube API response structure: {e}")
            return []

        related_urls = []
        for item in secondary_results:
            if len(related_urls) >= MAX_RELATED_TRACKS:
                break

            lockup_view_model = item.get("lockupViewModel")
            if not lockup_view_model:
                continue

            if lockup_view_model.get("contentType") != "LOCKUP_CONTENT_TYPE_VIDEO":
                continue

            video_id = lockup_view_model.get("contentId")
            if video_id:
                related_urls.append(f"https://www.youtube.com/watch?v={video_id}")

        logger.debug(f"Found {len(related_urls)} related tracks from YouTube")
        return related_urls

    except Exception as e:
        logger.error(f"Error getting YouTube related tracks: {e}")
        return []
