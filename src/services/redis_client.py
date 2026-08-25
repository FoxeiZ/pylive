from __future__ import annotations

import logging

import redis.asyncio as aioredis

from ..config import Config

logger = logging.getLogger(__name__)

_redis_pool: aioredis.ConnectionPool | None = None
_redis_client: aioredis.Redis | None = None


def get_redis_client() -> aioredis.Redis:
    """get or initialize async redis client singleton."""
    global _redis_pool, _redis_client
    if _redis_client is None:
        redis_url = str(Config.get("REDIS_URL", "redis://localhost:6379"))
        logger.info(f"initializing redis client with url {redis_url.rsplit('@', 1)[-1]}")
        _redis_pool = aioredis.ConnectionPool.from_url(
            redis_url,
            decode_responses=True,
            max_connections=20,
        )
        _redis_client = aioredis.Redis(connection_pool=_redis_pool)
    return _redis_client


async def close_redis_client() -> None:
    """close redis client and connection pool."""
    global _redis_pool, _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
    if _redis_pool is not None:
        await _redis_pool.disconnect()
        _redis_pool = None
