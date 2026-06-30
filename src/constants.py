from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

IS_WINDOWS = os.name == "nt"

# audio streaming constants
POLL_INTERVAL = 0.1  # seconds between FFmpeg stdin writes
AUDIO_BUFFER_SIZE = 4096  # bytes per audio read chunk

# queue limits
QUEUE_MAX_SIZE = 50
TRACK_HISTORY_SIZE = 50
MAX_SSE_CONNECTIONS = 1000

# video duration limits
MAX_DURATION_SECONDS = 8 * 60  # 8 minutes (480 seconds)

# playlist and related tracks limits
MAX_PLAYLIST_ENTRIES = 25
MAX_RELATED_TRACKS = 25

# cache configuration
VIDEO_INFO_CACHE_TTL = 30 * 60  # 30 minutes
VIDEO_INFO_CACHE_MAXSIZE = 500
RELATED_TRACKS_CACHE_TTL = 15 * 60  # 15 minutes
RELATED_TRACKS_CACHE_MAXSIZE = 200


YTDL_OPTIONS: dict[str, Any] = {
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "format": "bestaudio[ext=webm]/bestaudio[acodec=opus]/bestaudio[ext=m4a]/bestaudio/best/b",
    "restrictfilenames": True,
    # "source_address": "0.0.0.0",
    "playlist_items": f"1-{MAX_PLAYLIST_ENTRIES}",
    "extract_flat": "in_playlist",
    # "lazy_playlist": True,
    "compat_opts": ["no-youtube-unavailable-videos"],
    "playlistend": MAX_PLAYLIST_ENTRIES,
    "playlistrandom": True,
    "extractor_args": {
        "youtube": {
            "lang": ["en"],
            "player_client": ["mweb"],
            "formats": "missing_pot",
            "player_js_variant": ("tv",),
        },
        "youtubepot-bgutilhttp": {
            "base_url": ["https://bgutil-ytdlp-pot-vercal.vercel.app"]
        },
    },
    "js_runtimes": {"node": {}, "deno": {}},
    "remote_components": {"ejs:github"},
    "allowed_extractors": [r"^[yY].*[tT].*e?$"],
    "retries": 10,
}

if IS_WINDOWS:
    YTDL_OPTIONS.update(
        {
            "cookiesfrombrowser": ("firefox",),
        }
    )
