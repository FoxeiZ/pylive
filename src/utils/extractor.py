import json
from random import randint
from typing import Generator

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from .errors import (
    VideoIsLiveException,
    VideoIsUnavailableException,
    VideoIsOverLengthException,
    PlaylistNotFoundException,
)

from ..utils.general import URLRequest

globopts = {
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
}


def check_length(item: dict) -> bool:
    """Check if length > 15min"""
    return item.get("duration", 901) > 900.0


def create(url, process=True) -> dict[str, str | bool | float]:
    """
    Retrieves information about a video from a given URL.

    Parameters:
        url (str): The URL of the video.
        process (bool, optional): Whether to process the video or not. Defaults to True.

    Returns:
        Union[dict, None]: A dictionary containing information about the video, or None if the video could not be retrieved.
    """
    with YoutubeDL(globopts) as ytdl:
        try:
            data = ytdl.extract_info(url=url, download=False, process=process)
            if not data:
                raise VideoIsUnavailableException

            if data.get("entries", False):
                if isinstance(data["entries"], Generator):
                    data = next(data["entries"])
                else:
                    data = data["entries"][0]

            if data.get("is_live", False):
                raise VideoIsLiveException

            if check_length(data):
                raise VideoIsOverLengthException

            need_reencode = False
            if data.get("asr", 0) != 48000:
                need_reencode = True

            if data.get("acodec", "none") != "opus":
                need_reencode = True

            ret = {
                "title": data.get("title", "NA"),
                "id": data.get("id", "NA"),
                "webpage_url": data.get("webpage_url")
                or data.get("original_url")
                or data.get("url", "NA"),
                "duration": data.get("duration", 0.0),
                "channel": data.get("uploader", "NA"),
                "channel_url": data.get("uploader_url")
                or data.get("channel_url", "NA"),
                "process": False,
                "extractor": data.get("extractor", "None"),
                "need_reencode": need_reencode,
            }

            if process:
                ret.update(
                    {
                        "url": data.get("url"),
                        "process": True,
                        "format_duration": data.get("duration_string", "0:00"),
                    }
                )

            return ret
        except DownloadError:
            raise VideoIsUnavailableException


def fetch_playlist(url_playlist) -> list:
    item: dict
    max_entries = globopts.get("playlistend", 25)

    playlist = []
    with YoutubeDL(globopts) as ytdl:
        data = ytdl.extract_info(url=url_playlist, download=False, process=False)

        if not data:
            raise PlaylistNotFoundException

        for count, item in enumerate(data.get("entries", [])):
            try:
                if count >= max_entries:
                    return playlist

                if not item:
                    return playlist

                if check_length(item):
                    continue

                playlist.append(item["url"])
            except TypeError:
                print(f"{item['url']} is private")

    return playlist


def legacy_get_related_tracks(data):
    if "youtube" not in data["extractor"]:
        data = create(f"ytsearch1:{data['title']}", process=False)
        if not data:
            return

    related_video: dict = json.loads(
        URLRequest.request(
            f'https://vid.puffyan.us/api/v1/videos/{data["id"]}?fields=recommendedVideos'
        ).read()
    )

    if related_video.get("recommendedVideos", False):
        related_video = related_video["recommendedVideos"]

    return create(
        f"https://www.youtube.com/watch?v={related_video[randint(0, len(related_video) - 1)]['videoId']}",
        process=False,
    )



def youtube_music_get_related_tracks(now_playing: dict) -> list:
    videoId = now_playing.get("id")
    data = URLRequest.request(
        "https://www.youtube.com/youtubei/v1/next?key=AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8",
        method="POST",
        data={
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
            "videoId": videoId,
            "racyCheckOk": True,
            "contentCheckOk": True,
        },
        headers={
            "Origin": "https://www.youtube.com",
            "Referer": "https://www.youtube.com/",
            "Content-Type": "application/json; charset=utf-8",
        },
    )

    if not data:
        return []

    data_json = json.loads(data.read())

    related: list[dict] = []
    try:
        related = data_json["contents"]["twoColumnWatchNextResults"][
            "secondaryResults"
        ]["secondaryResults"]["results"]
    except Exception:
        return []

    # for item in related:
    #     res = item.get("compactRadioRenderer", False)

    #     if not res:
    #         continue

    #     playlist = extractor.fetch_playlist(res["shareUrl"])
    #     # remove the first entry; it usually is the same as the now-play one.
    #     return playlist[1:]

    playlist = []
    for count, item in enumerate(related):
        if count > 4:
            break

        res = item.get("compactVideoRenderer", False)
        if not res:
            continue
        playlist.append(f"https://www.youtube.com/watch?v={res['videoId']}")

    return playlist


def youtube_get_related_tracks(now_playing: dict) -> list:
    videoId = now_playing.get("id")
    data = URLRequest.request(
        "https://www.youtube.com/youtubei/v1/next?key=AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8",
        method="POST",
        data={
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
            "videoId": videoId,
            "racyCheckOk": True,
            "contentCheckOk": True,
        },
        headers={
            "Origin": "https://www.youtube.com",
            "Referer": "https://www.youtube.com/",
            "Content-Type": "application/json; charset=utf-8",
        },
    )

    if not data:
        return []

    data_json = json.loads(data.read())

    related: list[dict] = []
    try:
        related = data_json["contents"]["twoColumnWatchNextResults"][
            "secondaryResults"
        ]["secondaryResults"]["results"]
    except Exception:
        return []

    playlist = []
    for count, item in enumerate(related):
        if count > 4:
            break

        res = item.get("compactVideoRenderer", False)
        if not res:
            continue
        playlist.append(f"https://www.youtube.com/watch?v={res['videoId']}")

    return playlist
