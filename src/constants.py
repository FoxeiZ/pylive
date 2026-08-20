from __future__ import annotations

import os
from typing import TYPE_CHECKING

from src.config import Config

if TYPE_CHECKING:
    from typing import Any

IS_WINDOWS = os.name == "nt"
YTDL_OPTIONS: dict[str, Any] = {
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "format": "bestaudio[ext=webm]/bestaudio[acodec=opus]/bestaudio[ext=m4a]/bestaudio/best/b",
    "restrictfilenames": True,
    # "source_address": "0.0.0.0",
    "playlist_items": f"1-{Config.get('MAX_PLAYLIST_ENTRIES', 100)}",
    "extract_flat": "in_playlist",
    # "lazy_playlist": True,
    "compat_opts": ["no-youtube-unavailable-videos"],
    "playlistend": Config.get("MAX_PLAYLIST_ENTRIES", 100),
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
