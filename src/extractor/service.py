from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING, cast

from ..config import Config
from .cobalt import CobaltExtractor
from .piped import PipedExtractor

if TYPE_CHECKING:
    import redis.asyncio as aioredis

    from .base import BaseExtractor, ExtractedTrack

logger = logging.getLogger(__name__)


def hash_url(url: str) -> str:
    """generate sha256 hash of url for redis cache keys."""
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:16]


class ExtractorService:
    """pluggable extractor service coordinating multiple extraction backends and caching."""

    def __init__(
        self,
        primary_extractor: str | None = None,
        redis_client: aioredis.Redis | None = None,
    ) -> None:
        cobalt_url = str(Config.get("COBALT_API_URL", "https://api.cobalt.tools"))
        cobalt_key = Config.get("COBALT_API_KEY") or None
        piped_url = str(Config.get("PIPED_API_URL", "https://pipedapi.kavin.rocks"))

        self.cobalt = CobaltExtractor(api_url=cobalt_url, api_key=cobalt_key)
        self.piped = PipedExtractor(instance_url=piped_url)
        self.primary_name = primary_extractor or str(Config.get("DEFAULT_EXTRACTOR", "cobalt"))
        self.redis = redis_client
        self.cache_ttl = int(Config.get("STREAM_CACHE_TTL", 7200))

    def _get_primary_and_fallback(self) -> tuple[BaseExtractor, BaseExtractor]:
        if self.primary_name == "piped":
            return self.piped, self.cobalt
        return self.cobalt, self.piped

    async def extract_stream(self, url: str, use_cache: bool = True) -> ExtractedTrack:
        """extract stream url and metadata with redis cache and adapter fallback."""
        url_key = f"cache:track:{hash_url(url)}"

        # check redis cache
        if use_cache and self.redis:
            try:
                cached_data = await self.redis.get(url_key)
                if cached_data and isinstance(cached_data, str):
                    logger.debug(f"cache hit for url {url}")
                    return cast("ExtractedTrack", json.loads(cached_data))
            except Exception as e:
                logger.warning(f"redis cache read error: {e}")

        primary, fallback = self._get_primary_and_fallback()

        track: ExtractedTrack | None = None
        try:
            track = await primary.extract_stream(url)
        except Exception as primary_err:
            logger.warning(f"primary extractor ({self.primary_name}) failed: {primary_err}; trying fallback")
            try:
                track = await fallback.extract_stream(url)
            except Exception as fallback_err:
                logger.error(f"all extractors failed for url {url}: primary={primary_err}, fallback={fallback_err}")
                raise ValueError(f"failed to extract stream for url: {url}") from fallback_err

        # write to redis cache
        if self.redis and track:
            try:
                await self.redis.set(url_key, json.dumps(track), ex=self.cache_ttl)
            except Exception as e:
                logger.warning(f"redis cache write error: {e}")

        return track

    async def search(self, query: str, limit: int = 5) -> list[ExtractedTrack]:
        """search for tracks using piped backend."""
        try:
            return await self.piped.search(query, limit=limit)
        except Exception as e:
            logger.error(f"search failed for query '{query}': {e}")
            return []

    async def get_related_tracks(self, url: str, limit: int = 5) -> list[ExtractedTrack]:
        """get related recommended tracks."""
        try:
            return await self.piped.get_related_tracks(url, limit=limit)
        except Exception as e:
            logger.error(f"related tracks lookup failed for url '{url}': {e}")
            return []
