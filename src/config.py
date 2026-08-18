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
