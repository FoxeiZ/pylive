from __future__ import annotations

import argparse
import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, TypedDict

from dotenv import find_dotenv, load_dotenv

if TYPE_CHECKING:
    from typing import Any


class ConfigT(TypedDict):
    LOG_LEVEL: str


class BaseConfigLoader[T: ConfigT](ABC):
    _config: T

    def __init__(self) -> None:
        self._config = self.get_defaults()

    @abstractmethod
    def get_defaults(self) -> T: ...


class ConfigLoader(BaseConfigLoader[ConfigT]):
    _instance: ConfigLoader | None = None

    @classmethod
    def get_instance(cls) -> ConfigLoader:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        if self._instance is not None:
            import warnings  # noqa: PLC0415

            warnings.warn(
                "ConfigSingleton instance already exists. Use get_instance() to access it. "
                "Making a new instance is probably not what you want.",
                UserWarning,
                stacklevel=2,
            )

        super().__init__()

        load_dotenv()
        load_dotenv(find_dotenv(usecwd=True))
        load_dotenv(find_dotenv(filename=".env.local"))
        load_dotenv(find_dotenv(usecwd=True, filename=".env.local"))

        self._parse_args()
        self._load_from_env()

    def get_defaults(self) -> ConfigT:
        """Get the default configuration values."""
        return {
            "LOG_LEVEL": "INFO",
        }

    def _parse_args(self):
        parser = argparse.ArgumentParser(add_help=True, exit_on_error=True)
        # parser.add_argument(
        #     "--webhook-url",
        #     dest="WEBHOOK_URL",
        #     help="Webhook URL for notifications",
        # )
        parser.add_argument(
            "--log-level",
            dest="LOG_LEVEL",
            choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            default="INFO",
            help="Set the logging level",
        )
        parser.add_argument(
            "--debug",
            dest="LOG_LEVEL",
            action="store_const",
            const="DEBUG",
            help="Enable debug mode, short for --log-level=DEBUG",
        )
        queue_args = parser.add_argument_group("Internal Size Limits")
        queue_args.add_argument(
            "--queue-max-size",
            dest="QUEUE_MAX_SIZE",
            type=int,
            default=50,
            help="Maximum number of tracks in the queue",
        )
        queue_args.add_argument(
            "--track-history-size",
            dest="TRACK_HISTORY_SIZE",
            type=int,
            default=50,
            help="Maximum number of tracks in the history",
        )
        queue_args.add_argument(
            "--max-sse-connections",
            dest="MAX_SSE_CONNECTIONS",
            type=int,
            default=1000,
            help="Maximum number of concurrent SSE connections",
        )
        extractor_args = parser.add_argument_group("Extractor Options")
        extractor_args.add_argument(
            "--max-playlist-entries",
            dest="MAX_PLAYLIST_ENTRIES",
            type=int,
            default=25,
            help="Maximum number of entries to extract from a playlist",
        )
        extractor_args.add_argument(
            "--max-related-tracks",
            dest="MAX_RELATED_TRACKS",
            type=int,
            default=10,
            help="Maximum number of related tracks to extract",
        )
        extractor_args.add_argument(
            "--video-info-cache-ttl",
            dest="VIDEO_INFO_CACHE_TTL",
            type=int,
            default=30 * 60,
            help="Time-to-live (TTL) for video info cache in seconds",
        )
        extractor_args.add_argument(
            "--video-info-cache-maxsize",
            dest="VIDEO_INFO_CACHE_MAXSIZE",
            type=int,
            default=500,
            help="Maximum size of the video info cache",
        )
        extractor_args.add_argument(
            "--related-tracks-cache-ttl",
            dest="RELATED_TRACKS_CACHE_TTL",
            type=int,
            default=15 * 60,
            help="Time-to-live (TTL) for related tracks cache in seconds",
        )
        extractor_args.add_argument(
            "--related-tracks-cache-maxsize",
            dest="RELATED_TRACKS_CACHE_MAXSIZE",
            type=int,
            default=200,
            help="Maximum size of the related tracks cache",
        )
        audio_args = parser.add_argument_group("Audio Streaming Options")
        audio_args.add_argument(
            "--audio-buffer-size",
            dest="AUDIO_BUFFER_SIZE",
            type=int,
            default=4096,
            help="Size of the audio buffer in bytes",
        )
        audio_args.add_argument(
            "--poll-interval",
            dest="POLL_INTERVAL",
            type=float,
            default=0.1,
            help="Interval in seconds between FFmpeg stdin writes",
        )

        args, _ = parser.parse_known_args()
        for key, value in vars(args).items():
            if value is not None:
                self._config[key] = value

    def _load_from_env(self) -> None:
        """Load configuration from environment variables (if not already set by args)."""
        for key, default in self.get_defaults().items():
            # skip if already set by command line args (value differs from default)
            if self._config.get(key) != default:
                continue
            env_value = os.environ.get(key)
            if env_value is not None:
                if isinstance(default, bool):
                    self._config[key] = self.str_to_bool(env_value)
                else:
                    self._config[key] = env_value

    def str_to_bool(self, value: str | bool) -> bool:
        if isinstance(value, bool):
            return value
        return value.lower() in ("1", "true", "yes")

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def __getattr__(self, key: str) -> Any:
        if key in self._config:
            return self.get(key)
        defaults = self.get_defaults()
        if key in defaults:
            return defaults[key]  # type: ignore  # last resort
        raise AttributeError(f"Config has no attribute '{key}'")

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value by key."""
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value."""
        self._config[key] = value


Config = ConfigLoader.get_instance()
