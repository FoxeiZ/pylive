from collections.abc import Generator
from typing import (
    NotRequired,
    TypedDict,
)

__all__ = [
    "BaseExtractModel",
    "ExtractModel",
    "ProcessedExtractModel",
]


class BaseExtractModel(TypedDict):
    title: str
    id: str
    duration: float
    process: bool
    webpage_url: str
    is_live: NotRequired[bool]


class BaseExtractPlaylistModel(BaseExtractModel):
    entries: list[BaseExtractModel] | Generator[BaseExtractModel, None, None]


class ExtractModel(BaseExtractModel):
    channel: str
    channel_url: str
    extractor: str
    thumbnail: NotRequired[str]


class ProcessedExtractModel(ExtractModel):
    url: str
    format_duration: str
    thumbnail: NotRequired[str]
    expires_in: int

