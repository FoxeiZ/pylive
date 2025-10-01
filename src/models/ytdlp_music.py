from typing import List, NotRequired, TypedDict


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
    description: NotRequired[str]
    duration: float
    channel_id: str
    channel: str
    channel_url: str
    uploader: str
    uploader_id: NotRequired[str]
    uploader_url: NotRequired[str]
    thumbnails: List[ThumbnailDict]
    timestamp: NotRequired[int]
    release_timestamp: NotRequired[int]
    availability: NotRequired[str]
    view_count: NotRequired[int]
    live_status: NotRequired[str]
    channel_is_verified: NotRequired[bool]
    __x_forwarded_for_ip: NotRequired[str]


class YouTubeMusicPlaylistDict(TypedDict):
    id: str
    title: str
    _type: str
    entries: List[PlaylistEntryDict]
    webpage_url: str
    original_url: str
    webpage_url_basename: str
    webpage_url_domain: str
    extractor: str
    extractor_key: str
    release_year: NotRequired[int]
    requested_entries: List[int]
    playlist_count: NotRequired[int]
    epoch: int
