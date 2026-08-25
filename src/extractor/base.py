from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypedDict


class ExtractedTrack(TypedDict):
    title: str
    artist: str
    duration: float
    stream_url: str
    artwork_url: str
    source_url: str
    extractor: str
    format_duration: str


def format_duration_seconds(seconds: float) -> str:
    """format seconds into mm:ss or hh:mm:ss."""
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class BaseExtractor(ABC):
    """abstract base class for audio stream extractors."""

    @abstractmethod
    async def extract_stream(self, url: str) -> ExtractedTrack:
        """extract direct audio stream url and metadata."""
        ...

    @abstractmethod
    async def search(self, query: str, limit: int = 5) -> list[ExtractedTrack]:
        """search for tracks matching query."""
        ...

    @abstractmethod
    async def get_related_tracks(self, url: str, limit: int = 5) -> list[ExtractedTrack]:
        """get related/recommended tracks for autoplay."""
        ...
