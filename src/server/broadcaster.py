from __future__ import annotations

import asyncio
import enum
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Mapping
    from typing import Any

logger = logging.getLogger(__name__)


class EventType(enum.StrEnum):
    NEXT_TRACK = "next"
    QUEUE_ADD = "queueadd"
    NOW_PLAYING = "nowplaying"
    SHUTDOWN = "shutdown"


class EventManager:
    """
    Manages Server-Sent Events (SSE) for real-time client updates.

    This class handles:
    - Client connection management with configurable limits
    - Event broadcasting to all connected clients
    - Graceful shutdown with client notification
    """

    __slots__ = (
        "_max_connections",
        "_shutdown_requested",
        "_user_queues",
        "_user_queues_lock",
    )

    def __init__(self, max_connections: int = 1000) -> None:
        logger.info("initializing EventManager")

        self._shutdown_requested: bool = False
        self._user_queues: set[asyncio.Queue[str]] = set()
        self._user_queues_lock: asyncio.Lock | None = None
        self._max_connections = max_connections

        logger.debug("eventManager initialized successfully")

    def _get_lock(self) -> asyncio.Lock:
        if self._user_queues_lock is None:
            self._user_queues_lock = asyncio.Lock()
        return self._user_queues_lock

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown_requested

    @property
    def connection_count(self) -> int:
        return len(self._user_queues)

    def _craft_event(
        self, event_type: EventType, data: Mapping[str, Any] | None = None
    ) -> str:
        data_str = json.dumps(data) if data is not None else "null"
        return f"event: {event_type}\ndata: {data_str}\n\n"

    async def watch(self) -> AsyncGenerator[str, None]:
        logger.debug("client connected to event stream")

        event_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
        async with self._get_lock():
            if len(self._user_queues) >= self._max_connections:
                logger.warning("max SSE connections reached, rejecting client")
                return
            self._user_queues.add(event_queue)

        try:
            while not self._shutdown_requested:
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                    if event.startswith(f"event: {EventType.SHUTDOWN}") or self._shutdown_requested:
                        break
                    yield event
                except TimeoutError:
                    continue

        except asyncio.CancelledError:
            logger.debug("client disconnected from event stream")

        finally:
            async with self._get_lock():
                self._user_queues.discard(event_queue)

    async def _broadcast_event(self, event_data: str) -> None:
        """broadcast an event to all connected clients."""
        async with self._get_lock():
            queues = list(self._user_queues)

        for user_queue in queues:
            try:
                user_queue.put_nowait(event_data)
            except asyncio.QueueFull:
                logger.warning("client queue full, dropping event")
            except Exception as e:
                logger.warning(f"failed to queue event for client: {e}")

    async def add_event(
        self, event_type: EventType, data: Mapping[str, Any] | None = None
    ) -> None:
        if self._shutdown_requested:
            return

        try:
            await self._broadcast_event(self._craft_event(event_type, data))
            logger.debug(f"broadcast event: {event_type}")
        except Exception as e:
            logger.error(f"failed to add event: {e}", exc_info=True)

    async def shutdown(self) -> None:
        """gracefully shutdown the event manager and notify all clients."""
        logger.info("shutting down EventManager")
        self._shutdown_requested = True

        await self._broadcast_event(self._craft_event(EventType.SHUTDOWN))
        async with self._get_lock():
            self._user_queues.clear()

