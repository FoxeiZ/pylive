from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from quart import Blueprint, Quart, make_response, render_template, request

from ..extensions import asc
from ..utils.handlers import (
    create_error_response,
    create_response,
    validate_request_args,
)

if TYPE_CHECKING:
    from typing import Any

logger = logging.getLogger(__name__)

__all__ = ("register_routes",)


bp = Blueprint("root", __name__)


@bp.route("/")
async def index():
    try:
        if not asc:
            return await render_template("stream.html", np={}, queue=[])
        return await render_template("stream.html", np=asc.now_playing, queue=asc.queue)

    except Exception as e:
        logger.error(f"error rendering index page: {e}")
        raise


@bp.route("/watch_event")
async def watch_events():
    try:
        if not asc:
            logger.error("Audio manager not available for events")
            return await create_error_response(
                message="Event streaming not available", status_code=503
            )

        logger.debug("Client connected to event stream")
        response = await make_response(
            asc.event_queue.watch(),
            {
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
            },
        )
        response.timeout = None  # type: ignore
        return response

    except Exception as e:
        logger.error(f"error in event stream: {e}")
        return await create_error_response(
            message="failed to start event stream", status_code=500
        )


@bp.route("/stream")
async def get_stream():
    try:
        if not asc:
            logger.error("audio manager not available for streaming")
            return await create_error_response(
                message="audio streaming not available", status_code=503
            )

        logger.debug("starting audio stream for client %s", request.remote_addr)
        response = await make_response(
            asc.stream(),
            {
                "Transfer-Encoding": "chunked",
                "Content-Type": "audio/ogg",
                "Cache-Control": "no-cache",
            },
        )
        response.timeout = None  # type: ignore
        return response

    except Exception as e:
        logger.error(f"error getting audio stream: {e}")
        return await create_error_response(
            message="failed to start audio stream", status_code=500
        )


@bp.route("/np")
@bp.route("/nowplaying")
async def get_now_playing():
    try:
        if not asc:
            return await create_error_response(
                message="audio manager not available", status_code=503
            )

        response_data: dict[str, Any] = {"now_playing": asc.now_playing}
        if asc.queue:
            response_data.update({"next_up": asc.queue[0]})

        return await create_response(data=response_data)

    except Exception as e:
        logger.error(f"Error getting now playing info: {e}")
        return await create_error_response(
            message="Failed to retrieve now playing information"
        )


def register_routes(app: Quart):
    app.register_blueprint(bp, url_prefix="/")


@bp.route("/test")
@validate_request_args(required_args=[("param1", int)], optional_args=[("param2", str)])
async def test_endpoint(param1: int, param2: str | None = None):
    try:
        logger.debug(f"Test endpoint called with param1={param1}, param2={param2}")
        data = {"param1": param1, "param2": param2}
        return await create_response(data=data, message="Test endpoint successful")
    except Exception as e:
        logger.error(f"Error in test endpoint: {e}")
        return await create_error_response(message="Test endpoint failed")
