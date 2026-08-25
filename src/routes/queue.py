from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from quart import Blueprint, Quart, Response

from ..auth import Permission, require_permission
from ..services import room_manager
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
    "music.youtube.com",
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
                logger.exception(f"error in {func.__name__}: {e}")
                return await create_error_response(message=message)

        wrapper.__name__ = func.__name__
        return wrapper

    return decorator


@bp.route("/")
@on_error_decorator("Failed to get queue information")
@validate_request_args(
    required_args=[],
    optional_args=[("page", int), ("use_autoplay", bool)],
)
async def get_queue_info(page: int = 0, use_autoplay: bool = False) -> Response:
    queue_data = await room_manager.get_queue("main", page=page, page_size=5)
    response_data: dict[str, Any] = {
        "queue": queue_data["queue"],
        "page": page,
        "total_items": queue_data["total"],
    }
    if use_autoplay:
        response_data["auto_queue"] = queue_data["auto_queue"]

    return await create_response(data=response_data)


@bp.route("/auto", methods=["GET"])
@on_error_decorator("Failed to get auto queue information")
async def get_auto_queue() -> Response:
    queue_data = await room_manager.get_queue("main", page=0, page_size=10)
    return await create_response(data=queue_data["auto_queue"])


@bp.route("/add", methods=["POST"])
@require_permission(Permission.QUEUE_ADD)
@on_error_decorator("Failed to add track to queue")
@validate_request_args(required_args=[("url", str)])
async def add_track_to_queue(url: str) -> Response:
    logger.info(f"adding track to queue: {url}")
    if not _is_valid_youtube_url(url):
        logger.warning(f"rejected invalid url: {url}")
        return await create_error_response(
            message="Invalid YouTube URL provided",
            status_code=400,
        )

    track = await room_manager.extractor.extract_stream(url)
    res = await room_manager.add_to_queue("main", track)
    return await create_response(data=res, message="Track added to queue successfully")


@bp.route("/skip", methods=["POST"])
@require_permission(Permission.QUEUE_SKIP_VOTE)
@on_error_decorator("Failed to skip current track")
async def skip_current_track() -> Response:
    logger.info("skipping current track")
    res = await room_manager.skip_track("main")
    return await create_response(data=res, message="Track skipped successfully")


@bp.route("/autoplay/refresh", methods=["POST"])
@require_permission(Permission.QUEUE_AUTOPLAY_REFRESH)
@on_error_decorator("Failed to refresh autoplay queue")
async def refresh_autoplay_queue() -> Response:
    logger.info("refreshing autoplay queue")
    queue_data = await room_manager.get_queue("main", page=0, page_size=10)
    return await create_response(data=queue_data["auto_queue"], message="Autoplay queue refreshed successfully")


@bp.route("/remove", methods=["POST"])
@require_permission(Permission.QUEUE_ADD)
@on_error_decorator("Failed to remove track from queue")
@validate_request_args(required_args=[("index", int)])
async def remove_track(index: int) -> Response:
    success = await room_manager.remove_queue_item("main", index)
    if not success:
        return await create_error_response(message="Invalid queue index", status_code=400)
    return await create_response(message="Track removed successfully")


@bp.route("/clear", methods=["POST"])
@require_permission(Permission.QUEUE_ADD)
@on_error_decorator("Failed to clear queue")
async def clear_queue() -> Response:
    await room_manager.clear_queue("main")
    return await create_response(message="Queue cleared successfully")


def register_routes(app: Quart) -> None:
    app.register_blueprint(bp, url_prefix="/queue")
