from __future__ import annotations

import argparse
import contextlib
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, TypedDict

from dotenv import find_dotenv, load_dotenv

logger = logging.getLogger(__name__)


class ConfigT(TypedDict):
    LOG_LEVEL: str
    SUPABASE_URL: str
    SUPABASE_KEY: str
    REDIS_URL: str
    UPSTASH_REDIS_REST_URL: str
    UPSTASH_REDIS_REST_TOKEN: str
    COBALT_API_URL: str
    COBALT_API_KEY: str
    PIPED_API_URL: str
    DEFAULT_EXTRACTOR: str
    STREAM_CACHE_TTL: int
    QUEUE_MAX_SIZE: int
    TRACK_HISTORY_SIZE: int


class BaseConfigLoader[T: ConfigT](ABC):
    _config: dict[str, Any]

    def __init__(self) -> None:
        self._config = dict(self.get_defaults())

    @abstractmethod
    def get_defaults(self) -> T: ...


class ConfigLoader(BaseConfigLoader[ConfigT]):
    _instance: ConfigLoader | None = None

    @classmethod
    def get_instance(cls) -> ConfigLoader:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        if self._instance is not None:
            import warnings  # noqa: PLC0415

            warnings.warn(
                "ConfigSingleton instance already exists. Use get_instance() to access it.",
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
        """get default configuration values."""
        return {
            "LOG_LEVEL": "INFO",
            "SUPABASE_URL": "",
            "SUPABASE_KEY": "",
            "REDIS_URL": "redis://localhost:6379",
            "UPSTASH_REDIS_REST_URL": "",
            "UPSTASH_REDIS_REST_TOKEN": "",
            "COBALT_API_URL": "https://api.cobalt.tools",
            "COBALT_API_KEY": "",
            "PIPED_API_URL": "https://pipedapi.kavin.rocks",
            "DEFAULT_EXTRACTOR": "cobalt",
            "STREAM_CACHE_TTL": 7200,
            "QUEUE_MAX_SIZE": 50,
            "TRACK_HISTORY_SIZE": 50,
        }

    def _parse_args(self) -> None:
        parser = argparse.ArgumentParser(add_help=True, exit_on_error=False)
        parser.add_argument(
            "--log-level",
            dest="LOG_LEVEL",
            choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            default=None,
            help="Set the logging level",
        )
        parser.add_argument(
            "--debug",
            dest="LOG_LEVEL",
            action="store_const",
            const="DEBUG",
            help="Enable debug mode",
        )
        parser.add_argument(
            "--redis-url",
            dest="REDIS_URL",
            default=None,
            help="Redis connection URL",
        )
        parser.add_argument(
            "--cobalt-url",
            dest="COBALT_API_URL",
            default=None,
            help="Cobalt API URL",
        )

        try:
            args, _ = parser.parse_known_args()
            for key, value in vars(args).items():
                if value is not None:
                    self._config[key] = value
        except Exception as e:
            logger.debug(f"cli args parsing error: {e}")

    def _load_from_env(self) -> None:
        """load configuration from environment variables."""
        defaults = self.get_defaults()
        for key in defaults:
            env_val = os.environ.get(key)
            if env_val is not None:
                default_val = defaults.get(key)
                if isinstance(default_val, int):
                    with contextlib.suppress(ValueError):
                        self._config[key] = int(env_val)
                elif isinstance(default_val, bool):
                    self._config[key] = env_val.lower() in ("1", "true", "yes")
                else:
                    self._config[key] = env_val

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def __getattr__(self, key: str) -> Any:
        if key in self._config:
            return self.get(key)
        defaults = self.get_defaults()
        if key in defaults:
            return defaults.get(key)
        raise AttributeError(f"Config has no attribute '{key}'")

    def get(self, key: str, default: Any = None) -> Any:
        """get configuration value by key."""
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """set configuration value."""
        self._config[key] = value


Config = ConfigLoader.get_instance()
