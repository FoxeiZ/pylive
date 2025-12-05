from collections.abc import Iterator
from typing import NotRequired, TypedDict


class ThumbnailDict(TypedDict):
    url: str
    height: int
    width: int


class PlaylistEntryDict(TypedDict):
    _type: str
    ie_key: str
    id: str
    url: str
    title: str
    description: str | None
    duration: float
    channel_id: str
    channel: str
    channel_url: str
    uploader: str
    uploader_id: str | None
    uploader_url: str | None
    thumbnails: list[ThumbnailDict]
    timestamp: int | None
    release_timestamp: int | None
    availability: str | None
    view_count: int | None
    live_status: str | None
    channel_is_verified: bool | None
    __x_forwarded_for_ip: NotRequired[str]


class YouTubeMusicPlaylistDict(TypedDict):
    id: str
    title: str
    _type: str
    entries: Iterator[PlaylistEntryDict]
    webpage_url: str
    original_url: str
    webpage_url_basename: str
    webpage_url_domain: str
    extractor: str
    extractor_key: str
    release_year: NotRequired[int]
    requested_entries: NotRequired[list[int]]
    playlist_count: NotRequired[int]
    epoch: NotRequired[int]
