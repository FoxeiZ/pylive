from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import AsyncGenerator

    from ..models.extract import BaseExtractModel

logger = logging.getLogger(__name__)


class EventManager:
    """
    Manages Server-Sent Events (SSE) for real-time client updates.

    This class handles:
    - Client connection management with configurable limits
    - Event broadcasting to all connected clients
    - Graceful shutdown with client notification
    """

    NEXT_TRACK = "next"
    QUEUE_ADD = "queueadd"
    NOW_PLAYING = "nowplaying"
    SHUTDOWN = "shutdown"

    __slots__ = (
        "_shutdown_requested",
        "_user_queues",
        "_user_queues_lock",
        "_max_connections",
    )

    def __init__(self, max_connections: int = 1000) -> None:
        logger.info("initializing EventManager")

        self._shutdown_requested: bool = False
        self._user_queues: set[asyncio.Queue[str]] = set()
        self._user_queues_lock = asyncio.Lock()
        self._max_connections = max_connections

        logger.debug("eventManager initialized successfully")

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown_requested

    @property
    def connection_count(self) -> int:
        return len(self._user_queues)

    async def watch(self) -> AsyncGenerator[str, None]:
        """
        Async generator that yields SSE events for a connected client.

        Yields:
            SSE-formatted event strings.
        """
        logger.debug("client connected to event stream")

        async with self._user_queues_lock:
            if len(self._user_queues) >= self._max_connections:
                logger.warning("max SSE connections reached, rejecting client")
                return

        event_queue: asyncio.Queue[str] = asyncio.Queue()
        async with self._user_queues_lock:
            self._user_queues.add(event_queue)

        try:
            while not self._shutdown_requested:
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                    if event == EventManager.SHUTDOWN:
                        break
                    yield event
                except asyncio.TimeoutError:
                    continue

        except asyncio.CancelledError:
            logger.debug("client disconnected from event stream")

        finally:
            async with self._user_queues_lock:
                self._user_queues.discard(event_queue)

    async def _broadcast_event(self, event_data: str) -> None:
        """broadcast an event to all connected clients."""
        async with self._user_queues_lock:
            queues = list(self._user_queues)

        for user_queue in queues:
            try:
                user_queue.put_nowait(event_data)
            except asyncio.QueueFull:
                logger.warning("client queue full, dropping event")
            except Exception as e:
                logger.warning(f"failed to queue event for client: {e}")

    async def add_event(self, event_type: str, data: BaseExtractModel) -> None:
        """
        Add and broadcast an event to all connected clients.

        Args:
            event_type: The type of event (e.g., QUEUE_ADD, NOW_PLAYING).
            data: The event data to broadcast.
        """
        if self._shutdown_requested:
            return

        try:
            event_data = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
            await self._broadcast_event(event_data)
            logger.debug(f"broadcast event: {event_type}")
        except Exception as e:
            logger.error(f"failed to add event: {e}", exc_info=True)

    async def shutdown(self) -> None:
        """gracefully shutdown the event manager and notify all clients."""
        logger.info("shutting down EventManager")
        self._shutdown_requested = True

        shutdown_data = f"event: {EventManager.SHUTDOWN}\ndata: null\n\n"
        await self._broadcast_event(shutdown_data)

        async with self._user_queues_lock:
            self._user_queues.clear()
