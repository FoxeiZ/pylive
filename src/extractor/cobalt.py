from __future__ import annotations

import logging
from typing import Any

import httpx

from .base import BaseExtractor, ExtractedTrack, format_duration_seconds

logger = logging.getLogger(__name__)


class CobaltExtractor(BaseExtractor):
    """extractor adapter using cobalt api for cors-friendly audio extraction."""

    def __init__(self, api_url: str = "https://api.cobalt.tools", api_key: str | None = None) -> None:
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key

    async def extract_stream(self, url: str) -> ExtractedTrack:
        """extract direct audio stream url and metadata via cobalt."""
        headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Api-Key {self.api_key}"

        payload: dict[str, Any] = {
            "url": url,
            "downloadMode": "audio",
            "audioFormat": "opus",
            "audioBitrate": "128",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(f"{self.api_url}/", json=payload, headers=headers)
            response.raise_for_status()
            data: dict[str, Any] = response.json()

            status = data.get("status")
            if status == "error":
                error_msg = data.get("error", {}).get("code", "unknown error")
                raise ValueError(f"cobalt extraction failed: {error_msg}")

            stream_url = data.get("url")
            if not stream_url:
                raise ValueError("cobalt response missing stream url")

            filename = data.get("filename", "Audio Track")
            # extract basic title from filename if present
            title = filename.rsplit(".", 1)[0] if "." in filename else filename

            duration = float(data.get("duration", 0.0))

            return {
                "title": title,
                "artist": "YouTube",
                "duration": duration,
                "stream_url": stream_url,
                "artwork_url": data.get("thumbnail", ""),
                "source_url": url,
                "extractor": "cobalt",
                "format_duration": format_duration_seconds(duration),
            }

    async def search(self, query: str, limit: int = 5) -> list[ExtractedTrack]:
        """fallback search using public piped instance."""
        return []

    async def get_related_tracks(self, url: str, limit: int = 5) -> list[ExtractedTrack]:
        """fallback related tracks using public piped instance."""
        return []
