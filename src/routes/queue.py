from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from quart import Blueprint, Quart, Response

from ..extensions import asc
from ..utils.handlers import (
    create_error_response,
    create_response,
    validate_request_args,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

__all__ = ("register_routes",)


bp = Blueprint("queue", __name__)

_YOUTUBE_ALLOWED_HOSTS = (
    "youtube.com",
    "youtu.be",
)


def _is_valid_youtube_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False

    hostname = parsed.hostname or ""
    return any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in _YOUTUBE_ALLOWED_HOSTS
    )


def on_error_decorator(message: str):
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        async def wrapper(*args: Any, **kwargs: Any) -> Response:
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logger.exception(f"Error in {func.__name__}: {e}")
                return await create_error_response(message=message)

        wrapper.__name__ = func.__name__
        return wrapper

    return decorator


@bp.route("/")
@on_error_decorator("Failed to get queue information")
@validate_request_args(
    required_args=[],
    optional_args=[("index", int), ("page", int), ("use_autoplay", bool)],
)
async def get_queue_info(page: int = 0, use_autoplay: bool = False):
    queue = asc.queue
    auto_queue = asc.auto_queue

    items_per_page = 5
    end_offset = min((page + 1) * items_per_page, len(queue))
    start_offset = max(end_offset - items_per_page, 0)

    response_data = {
        "queue": queue[start_offset:end_offset],
    }

    if use_autoplay and auto_queue:
        response_data.update({"auto_queue": auto_queue})

    return await create_response(data=response_data)


@bp.route("/auto", methods=["GET"])
@on_error_decorator("Failed to get auto queue information")
async def get_auto_queue():
    return await create_response(data=asc.auto_queue)


@bp.route("/add", methods=["POST"])
@on_error_decorator("Failed to add track to queue")
@validate_request_args(required_args=[("url", str)])
async def add_track_to_queue(url: str):
    logger.info(f"Adding track to queue: {url}")
    if not _is_valid_youtube_url(url):
        logger.warning(f"Rejected non-YouTube URL: {url}")
        return await create_error_response(
            message="Invalid YouTube URL provided",
            status_code=400,
        )
    await asc.add_track(url)
    return await create_response(message="Track added to queue successfully")


@bp.route("/skip", methods=["POST"])
@on_error_decorator("Failed to skip current track")
async def skip_current_track():
    logger.info("Skipping current track")
    await asc.skip_track()
    return await create_response(message="Track skipped successfully")


def register_routes(app: Quart):
    app.register_blueprint(bp, url_prefix="/queue")
