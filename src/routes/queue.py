from __future__ import annotations

import logging

from flask import Blueprint, Flask, request

from ..extensions import audio_manager
from ..utils.handlers import (
    create_error_response,
    create_response,
    validate_request_args,
)

logger = logging.getLogger(__name__)

__all__ = ("register_routes",)


bp = Blueprint("queue", __name__)


@bp.route("/")
def get_queue_info():
    try:
        if not audio_manager:
            return create_error_response(
                message="Audio manager not available", status_code=503
            )

        queue = audio_manager.queue.copy()
        auto_queue = audio_manager.auto_queue.copy() if audio_manager.auto_queue else []

        # Parse request parameters
        page_index = int(request.args.get("index", request.args.get("page", 0)))
        use_autoplay = request.args.get("use_autoplay", "0") == "1"

        # Calculate pagination
        items_per_page = 5
        end_offset = min((page_index + 1) * items_per_page, len(queue))
        start_offset = max(end_offset - items_per_page, 0)

        response_data = {
            "queue": queue[start_offset:end_offset],
        }

        if use_autoplay and auto_queue:
            response_data.update({"auto_queue": auto_queue})

        return create_response(data=response_data)

    except Exception as e:
        logger.error(f"Error getting queue info: {e}")
        return create_error_response(message="Failed to retrieve queue information")


@bp.route("/add", methods=["POST"])
@validate_request_args(["url"])
def add_track_to_queue(url):
    try:
        if not audio_manager:
            logger.error("Audio manager not available")
            return create_error_response(
                message="Audio manager not available", status_code=503
            )

        logger.info(f"Adding track to queue: {url}")
        audio_manager.add_track(url)
        return create_response(message="Track added to queue successfully")

    except Exception as err:
        logger.error(f"Failed to add track to queue: {err}")
        return create_error_response(message=f"{err.__class__.__name__}: {str(err)}")


@bp.route("/skip", methods=["POST"])
def skip_current_track():
    try:
        if not audio_manager:
            return create_error_response(
                message="Audio manager not available", status_code=503
            )

        logger.info("Skipping current track")
        audio_manager.skip_track()
        return create_response(message="Track skipped successfully")

    except Exception as e:
        logger.error(f"Error skipping track: {e}")
        return create_error_response(message="Failed to skip track")


def register_routes(app: Flask):
    app.register_blueprint(bp, url_prefix="/queue")
