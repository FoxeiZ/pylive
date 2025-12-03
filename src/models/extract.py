from typing import (
    Any,
    Callable,
    Literal,
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
    entries: NotRequired[dict[Any, Any]]


class ExtractModel(BaseExtractModel):
    channel: str
    channel_url: str
    extractor: str
    thumbnail: NotRequired[str]


class ProcessedExtractModel(ExtractModel):
    url: str
    format_duration: str
    thumbnail: NotRequired[str]
    expires_in: int | Literal[0]
    is_expired: Callable[[], bool]
