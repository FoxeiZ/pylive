from __future__ import annotations

import logging

from flask import Blueprint, Flask

from ..extensions import audio_controller
from ..utils.handlers import (
    create_error_response,
    create_response,
    validate_request_args,
)

logger = logging.getLogger(__name__)

__all__ = ("register_routes",)


bp = Blueprint("queue", __name__)


def on_error_decorator(message: str):
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.exception(f"Error in {func.__name__}: {e}")
                return create_error_response(message=message)

        wrapper.__name__ = func.__name__
        return wrapper

    return decorator


@bp.route("/")
@on_error_decorator("Failed to get queue information")
@validate_request_args(
    required_args=[],
    optional_args=[("index", int), ("page", int), ("use_autoplay", bool)],
)
def get_queue_info(page=0, use_autoplay=False):
    queue = audio_controller.queue
    auto_queue = audio_controller.auto_queue

    items_per_page = 5
    end_offset = min((page + 1) * items_per_page, len(queue))
    start_offset = max(end_offset - items_per_page, 0)

    response_data = {
        "queue": queue[start_offset:end_offset],
    }

    if use_autoplay and auto_queue:
        response_data.update({"auto_queue": auto_queue})

    return create_response(data=response_data)


@bp.route("/auto", methods=["GET"])
@on_error_decorator("Failed to get auto queue information")
def get_auto_queue():
    return create_response(data=audio_controller.auto_queue)


@bp.route("/add", methods=["POST"])
@on_error_decorator("Failed to add track to queue")
@validate_request_args(required_args=[("url", str)])
def add_track_to_queue(url):
    logger.info(f"Adding track to queue: {url}")
    audio_controller.add_track(url)
    return create_response(message="Track added to queue successfully")


@bp.route("/skip", methods=["POST"])
@on_error_decorator("Failed to skip current track")
def skip_current_track():
    logger.info("Skipping current track")
    audio_controller.skip_track()
    return create_response(message="Track skipped successfully")


def register_routes(app: Flask):
    app.register_blueprint(bp, url_prefix="/queue")
