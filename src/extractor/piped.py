from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from .base import BaseExtractor, ExtractedTrack, format_duration_seconds

logger = logging.getLogger(__name__)


def extract_youtube_video_id(url: str) -> str:
    """extract youtube 11-char video id from url."""
    parsed = urlparse(url)
    if parsed.hostname in ("youtu.be", "www.youtu.be"):
        return parsed.path.strip("/")
    if parsed.hostname in ("youtube.com", "www.youtube.com", "music.youtube.com", "m.youtube.com"):
        if parsed.path == "/watch":
            query = parse_qs(parsed.query)
            v_param = query.get("v")
            if v_param:
                return v_param[0]
        elif parsed.path.startswith(("/embed/", "/v/", "/shorts/")):
            return parsed.path.split("/")[2]

    # fallback regex for 11-char id
    match = re.search(r"([a-zA-Z0-9_-]{11})", url)
    if match:
        return match.group(1)
    raise ValueError(f"could not extract youtube video id from url: {url}")


class PipedExtractor(BaseExtractor):
    """extractor adapter using piped api for youtube stream extraction and search."""

    def __init__(self, instance_url: str = "https://pipedapi.kavin.rocks") -> None:
        self.instance_url = instance_url.rstrip("/")

    async def extract_stream(self, url: str) -> ExtractedTrack:
        video_id = extract_youtube_video_id(url)
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{self.instance_url}/streams/{video_id}")
            response.raise_for_status()
            data: dict[str, Any] = response.json()

            audio_streams: list[dict[str, Any]] = data.get("audioStreams", [])
            if not audio_streams:
                raise ValueError("no audio streams found in piped response")

            # prefer opus/webm, otherwise m4a/first available
            selected_stream = next(
                (s for s in audio_streams if s.get("format") in ("OPUS", "WEBMA_OPUS")),
                audio_streams[0],
            )

            stream_url = selected_stream.get("url")
            if not stream_url:
                raise ValueError("selected audio stream has no url")

            duration = float(data.get("duration", 0.0))
            title = str(data.get("title", "Unknown Track"))
            artist = str(data.get("uploader", "Unknown Artist"))
            artwork_url = str(data.get("thumbnailUrl", ""))

            return {
                "title": title,
                "artist": artist,
                "duration": duration,
                "stream_url": stream_url,
                "artwork_url": artwork_url,
                "source_url": url,
                "extractor": "piped",
                "format_duration": format_duration_seconds(duration),
            }

    async def search(self, query: str, limit: int = 5) -> list[ExtractedTrack]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            params = {"q": query, "filter": "music_songs"}
            response = await client.get(f"{self.instance_url}/search", params=params)
            response.raise_for_status()
            data: dict[str, Any] = response.json()

            items: list[dict[str, Any]] = data.get("items", [])
            results: list[ExtractedTrack] = []
            for item in items[:limit]:
                raw_url = str(item.get("url", ""))
                clean_url = f"https://www.youtube.com{raw_url}" if raw_url.startswith("/") else raw_url
                duration = float(item.get("duration", 0.0))
                results.append(
                    {
                        "title": str(item.get("title", "Unknown Track")),
                        "artist": str(item.get("uploaderName", "Unknown Artist")),
                        "duration": duration,
                        "stream_url": "",
                        "artwork_url": str(item.get("thumbnail", "")),
                        "source_url": clean_url,
                        "extractor": "piped",
                        "format_duration": format_duration_seconds(duration),
                    }
                )
            return results

    async def get_related_tracks(self, url: str, limit: int = 5) -> list[ExtractedTrack]:
        video_id = extract_youtube_video_id(url)
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{self.instance_url}/streams/{video_id}")
            response.raise_for_status()
            data: dict[str, Any] = response.json()

            related_streams: list[dict[str, Any]] = data.get("relatedStreams", [])
            results: list[ExtractedTrack] = []
            for item in related_streams[:limit]:
                raw_url = str(item.get("url", ""))
                clean_url = f"https://www.youtube.com{raw_url}" if raw_url.startswith("/") else raw_url
                duration = float(item.get("duration", 0.0))
                results.append(
                    {
                        "title": str(item.get("title", "Unknown Track")),
                        "artist": str(item.get("uploaderName", "Unknown Artist")),
                        "duration": duration,
                        "stream_url": "",
                        "artwork_url": str(item.get("thumbnail", "")),
                        "source_url": clean_url,
                        "extractor": "piped",
                        "format_duration": format_duration_seconds(duration),
                    }
                )
            return results
