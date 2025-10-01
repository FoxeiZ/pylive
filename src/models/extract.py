from typing import NotRequired, TypedDict


class BaseExtractModel(TypedDict):
    title: str
    id: str
    duration: float
    process: bool
    webpage_url: str


class ExtractModel(BaseExtractModel):
    channel: str
    channel_url: str
    extractor: str
    need_reencode: bool
    thumbnail: NotRequired[str]


class ProcessedExtractModel(ExtractModel):
    url: str
    format_duration: str
