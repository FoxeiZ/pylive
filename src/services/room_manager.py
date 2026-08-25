from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any, cast

from ..extractor import ExtractedTrack, ExtractorService
from .redis_client import get_redis_client
from .supabase_client import broadcast_realtime_event

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class RoomManager:
    """manages room playback state, queue manipulation, and atomic track advancement."""

    def __init__(self, extractor_service: ExtractorService | None = None) -> None:
        self.redis: aioredis.Redis = get_redis_client()
        self.extractor: ExtractorService = extractor_service or ExtractorService(redis_client=self.redis)

    def _get_state_key(self, room_id: str) -> str:
        return f"room:{room_id}:state"

    def _get_queue_key(self, room_id: str) -> str:
        return f"room:{room_id}:queue"

    def _get_auto_queue_key(self, room_id: str) -> str:
        return f"room:{room_id}:auto_queue"

    def _get_history_key(self, room_id: str) -> str:
        return f"room:{room_id}:history"

    def _get_lock_key(self, room_id: str) -> str:
        return f"room:{room_id}:advance_lock"

    async def get_room_state(self, room_id: str = "main") -> dict[str, Any]:
        """retrieve full room state with computed playback timestamp."""
        raw_res = await self.redis.hgetall(self._get_state_key(room_id))
        state_raw: dict[str, str] = {str(k): str(v) for k, v in raw_res.items()}
        queue_len = int(await self.redis.llen(self._get_queue_key(room_id)))
        auto_queue_len = int(await self.redis.llen(self._get_auto_queue_key(room_id)))
        now_ms = int(time.time() * 1000)

        if not state_raw:
            return {
                "is_active": False,
                "server_time": now_ms,
                "now_playing": None,
                "queue_length": queue_len,
                "auto_queue_length": auto_queue_len,
            }

        started_at = int(state_raw.get("started_at", "0"))
        duration = float(state_raw.get("duration", "0"))
        is_paused = state_raw.get("is_paused", "0") == "1"
        pause_offset = float(state_raw.get("pause_offset", "0.0"))

        if is_paused:
            current_position = pause_offset
        else:
            elapsed = (now_ms - started_at) / 1000.0 if started_at > 0 else 0.0
            current_position = min(duration, max(0.0, elapsed + pause_offset)) if duration > 0 else elapsed

        now_playing = {
            "title": state_raw.get("title", "Unknown"),
            "artist": state_raw.get("artist", "Unknown"),
            "duration": duration,
            "stream_url": state_raw.get("stream_url", ""),
            "artwork_url": state_raw.get("artwork_url", ""),
            "source_url": state_raw.get("source_url", ""),
            "started_at": started_at,
            "is_paused": is_paused,
            "current_position": current_position,
        }

        return {
            "is_active": bool(state_raw.get("stream_url")),
            "server_time": now_ms,
            "now_playing": now_playing,
            "queue_length": queue_len,
            "auto_queue_length": auto_queue_len,
        }

    async def add_to_queue(self, room_id: str, track: ExtractedTrack) -> dict[str, Any]:
        """add track to queue or play immediately if idle."""
        state = await self.get_room_state(room_id)
        if not state.get("is_active"):
            # room idle, start track immediately
            return await self._play_track(room_id, track)

        # push to queue
        await self.redis.rpush(self._get_queue_key(room_id), json.dumps(track))
        queue_len = int(await self.redis.llen(self._get_queue_key(room_id)))

        await broadcast_realtime_event(room_id, "queue_update", {"queue_length": queue_len, "added_track": track})
        # pre-resolve stream if next in line
        if queue_len == 1:
            await self.pre_resolve_next_track(room_id)

        return {"status": "queued", "position": queue_len, "track": track}

    async def _play_track(self, room_id: str, track: ExtractedTrack) -> dict[str, Any]:
        """set room state to playing given track."""
        now_ms = int(time.time() * 1000)

        # ensure direct stream url is resolved
        if not track.get("stream_url"):
            resolved = await self.extractor.extract_stream(track["source_url"])
            track = resolved

        room_state: dict[str, Any] = {
            "track_id": track["source_url"],
            "title": track["title"],
            "artist": track["artist"],
            "duration": str(track["duration"]),
            "stream_url": track["stream_url"],
            "artwork_url": track["artwork_url"],
            "source_url": track["source_url"],
            "started_at": str(now_ms),
            "is_paused": "0",
            "paused_at": "0",
            "pause_offset": "0.0",
        }

        await cast("Any", self.redis).hset(self._get_state_key(room_id), mapping=room_state)
        await self.redis.lpush(self._get_history_key(room_id), json.dumps(track))
        await self.redis.ltrim(self._get_history_key(room_id), 0, 49)

        payload = {**track, "started_at": now_ms, "is_paused": False, "server_time": now_ms}
        await broadcast_realtime_event(room_id, "track_change", payload)

        # populate auto queue recommendations asynchronously
        await self._refresh_auto_queue(room_id, track["source_url"])
        await self.pre_resolve_next_track(room_id)

        return {"status": "playing", "track": track, "started_at": now_ms}

    async def advance_track(self, room_id: str = "main", force: bool = False) -> dict[str, Any] | None:
        """advance to next track in queue with atomic distributed lock."""
        lock_key = self._get_lock_key(room_id)
        acquired = await self.redis.set(lock_key, "1", nx=True, ex=5)

        if not acquired and not force:
            logger.debug(f"advance for room {room_id} already locked by another request")
            return None

        try:
            next_raw = await self.redis.lpop(self._get_queue_key(room_id))
            if not next_raw:
                next_raw = await self.redis.lpop(self._get_auto_queue_key(room_id))

            if not next_raw or not isinstance(next_raw, str):
                # no more tracks, clear state
                await self.redis.delete(self._get_state_key(room_id))
                now_ms = int(time.time() * 1000)
                await broadcast_realtime_event(
                    room_id, "track_change", {"stream_url": "", "title": "Waiting for stream...", "server_time": now_ms}
                )
                return {"status": "idle"}

            track_dict: ExtractedTrack = json.loads(next_raw)
            return await self._play_track(room_id, track_dict)
        finally:
            await self.redis.delete(lock_key)

    async def skip_track(self, room_id: str = "main") -> dict[str, Any] | None:
        """force skip current track."""
        return await self.advance_track(room_id=room_id, force=True)

    async def pause_track(self, room_id: str = "main") -> dict[str, Any]:
        """pause current room playback."""
        state = await self.get_room_state(room_id)
        now_ms = int(time.time() * 1000)
        curr_pos = state.get("now_playing", {}).get("current_position", 0.0)

        await cast("Any", self.redis).hset(
            self._get_state_key(room_id),
            mapping={
                "is_paused": "1",
                "paused_at": str(now_ms),
                "pause_offset": str(curr_pos),
            },
        )
        payload = {"is_paused": True, "position": curr_pos, "server_time": now_ms}
        await broadcast_realtime_event(room_id, "playback_sync", payload)
        return {"status": "paused", "position": curr_pos}

    async def resume_track(self, room_id: str = "main") -> dict[str, Any]:
        """resume current room playback."""
        now_ms = int(time.time() * 1000)
        raw_res = await self.redis.hgetall(self._get_state_key(room_id))
        state_raw: dict[str, str] = {str(k): str(v) for k, v in raw_res.items()}
        pause_offset = float(state_raw.get("pause_offset", "0.0"))

        await cast("Any", self.redis).hset(
            self._get_state_key(room_id),
            mapping={
                "is_paused": "0",
                "started_at": str(now_ms),
                "paused_at": "0",
            },
        )
        payload = {"is_paused": False, "position": pause_offset, "server_time": now_ms}
        await broadcast_realtime_event(room_id, "playback_sync", payload)
        return {"status": "resumed", "position": pause_offset}

    async def get_queue(self, room_id: str = "main", page: int = 0, page_size: int = 10) -> dict[str, Any]:
        """get paginated queue entries."""
        queue_key = self._get_queue_key(room_id)
        total = int(await self.redis.llen(queue_key))
        start = max(0, page) * page_size
        end = start + page_size - 1

        items_raw: list[Any] = await self.redis.lrange(queue_key, start, end)
        items = [json.loads(str(item)) for item in items_raw if item]

        auto_queue_raw: list[Any] = await self.redis.lrange(self._get_auto_queue_key(room_id), 0, 9)
        auto_items = [json.loads(str(item)) for item in auto_queue_raw if item]

        return {
            "queue": items,
            "auto_queue": auto_items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def remove_queue_item(self, room_id: str = "main", index: int = 0) -> bool:
        """remove track at specific queue index."""
        queue_key = self._get_queue_key(room_id)
        items_raw: list[Any] = await self.redis.lrange(queue_key, 0, -1)
        if index < 0 or index >= len(items_raw):
            return False

        item_to_remove = str(items_raw[index])
        await self.redis.lrem(queue_key, 1, item_to_remove)
        queue_len = int(await self.redis.llen(queue_key))
        await broadcast_realtime_event(room_id, "queue_update", {"queue_length": queue_len})
        return True

    async def clear_queue(self, room_id: str = "main") -> bool:
        """clear all queue items."""
        await self.redis.delete(self._get_queue_key(room_id))
        await broadcast_realtime_event(room_id, "queue_update", {"queue_length": 0})
        return True

    async def pre_resolve_next_track(self, room_id: str = "main") -> None:
        """pre-resolve stream url for the next queued track in redis."""
        next_raw = await self.redis.lindex(self._get_queue_key(room_id), 0)
        if not next_raw:
            next_raw = await self.redis.lindex(self._get_auto_queue_key(room_id), 0)

        if next_raw and isinstance(next_raw, str):
            try:
                track = json.loads(next_raw)
                source_url = track.get("source_url")
                if source_url:
                    await self.extractor.extract_stream(source_url, use_cache=True)
            except Exception as e:
                logger.warning(f"failed to pre-resolve next track: {e}")

    async def _refresh_auto_queue(self, room_id: str, source_url: str) -> None:
        """populate auto-queue with recommended tracks."""
        auto_key = self._get_auto_queue_key(room_id)
        existing_len = int(await self.redis.llen(auto_key))
        if existing_len >= 5:
            return

        try:
            related = await self.extractor.get_related_tracks(source_url, limit=5)
            for track in related:
                await self.redis.rpush(auto_key, json.dumps(track))
        except Exception as e:
            logger.warning(f"failed to refresh auto-queue: {e}")


room_manager = RoomManager()
