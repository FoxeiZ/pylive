from __future__ import annotations

import logging
from typing import Any

import httpx
from supabase import Client, create_client

from ..config import Config

logger = logging.getLogger(__name__)

_supabase_client: Client | None = None


def get_supabase_client() -> Client | None:
    """get or initialize supabase client singleton."""
    global _supabase_client
    url = str(Config.get("SUPABASE_URL", "")).strip()
    key = str(Config.get("SUPABASE_KEY", "")).strip()
    if not url or not key:
        return None

    if _supabase_client is None:
        try:
            _supabase_client = create_client(url, key)
        except Exception as e:
            logger.error(f"failed to initialize supabase client: {e}")
            return None
    return _supabase_client


async def broadcast_realtime_event(channel_name: str, event_name: str, payload: dict[str, Any]) -> bool:
    """broadcast event to supabase realtime subscribers via rest api."""
    url = str(Config.get("SUPABASE_URL", "")).strip().rstrip("/")
    key = str(Config.get("SUPABASE_KEY", "")).strip()

    if not url or not key:
        logger.debug(f"supabase credentials not set, skipping realtime broadcast: {event_name}")
        return False

    endpoint = f"{url}/realtime/v1/api/broadcast"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    data = {
        "messages": [
            {
                "topic": f"realtime:{channel_name}",
                "event": event_name,
                "payload": payload,
            }
        ]
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(endpoint, json=data, headers=headers)
            if response.status_code in (200, 202):
                logger.debug(f"realtime event '{event_name}' broadcasted to channel '{channel_name}'")
                return True
            logger.warning(f"realtime broadcast returned status {response.status_code}: {response.text}")
            return False
    except Exception as e:
        logger.warning(f"failed to broadcast realtime event '{event_name}': {e}")
        return False
