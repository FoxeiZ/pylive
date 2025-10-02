from __future__ import annotations

import logging

from flask import Blueprint, Flask, Response, render_template

from ..extensions import audio_controller
from ..server import AudioStreamController
from ..utils.general import MISSING_TYPE
from ..utils.handlers import (
    create_error_response,
    create_response,
    validate_request_args,
)

logger = logging.getLogger(__name__)
MISSING = MISSING_TYPE()

__all__ = ("register_routes",)


bp = Blueprint("root", __name__)


def generate_audio_stream(audio_manager: AudioStreamController):
    logger.debug("Starting audio stream generation")

    try:
        yield audio_manager.wait_for_header()
        while audio_manager.is_alive():
            audio_manager.event.wait()
            yield audio_manager.buffer
    except InterruptedError:
        logger.info("Audio stream generation interrupted")
        return

    except Exception as e:
        logger.error(f"Error in audio stream generation: {e}")
    finally:
        logger.debug("Audio stream generation ended")


@bp.route("/")
def index():
    try:
        if not audio_controller:
            # Render with empty data if audio manager is not available
            return render_template("stream.html", np={}, queue=[])

        return render_template(
            "stream.html", np=audio_controller.now_playing, queue=audio_controller.queue
        )

    except Exception as e:
        logger.error(f"Error rendering index page: {e}")
        return "Internal Server Error", 500


@bp.route("/watch_event")
def watch_events():
    try:
        if not audio_controller:
            logger.error("Audio manager not available for events")
            return create_error_response(
                message="Event streaming not available", status_code=503
            )

        logger.debug("Client connected to event stream")
        return Response(
            audio_controller.event_queue.watch(), content_type="text/event-stream"
        )

    except Exception as e:
        logger.error(f"Error in event stream: {e}")
        return create_error_response(
            message="Failed to start event stream", status_code=500
        )


@bp.route("/stream")
def get_stream():
    try:
        if not audio_controller:
            logger.error("Audio manager not available for streaming")
            return create_error_response(
                message="Audio streaming not available", status_code=503
            )

        if (
            not hasattr(audio_controller, "_ffmpeg_process")
            or audio_controller._ffmpeg_process == MISSING
        ):
            logger.error("FFmpeg process not available")
            return create_error_response(
                message="Audio stream not available", status_code=404
            )

        logger.debug("Starting audio stream")
        return Response(
            generate_audio_stream(audio_controller),
            content_type="audio/ogg",
            status=200,
        )

    except Exception as e:
        logger.error(f"Error getting audio stream: {e}")
        return create_error_response(
            message="Failed to start audio stream", status_code=500
        )


@bp.route("/np")
@bp.route("/nowplaying")
def get_now_playing():
    try:
        if not audio_controller:
            return create_error_response(
                message="Audio manager not available", status_code=503
            )

        response_data = {"now_playing": audio_controller.now_playing}

        if audio_controller.queue:
            response_data.update({"next_up": audio_controller.queue[0]})

        return create_response(data=response_data)

    except Exception as e:
        logger.error(f"Error getting now playing info: {e}")
        return create_error_response(
            message="Failed to retrieve now playing information"
        )


def register_routes(app: Flask):
    app.register_blueprint(bp, url_prefix="/")


@bp.route("/test")
@validate_request_args(required_args=[("param1", int)], optional_args=[("param2", str)])
def test_endpoint(param1, param2=None):
    try:
        logger.debug(f"Test endpoint called with param1={param1}, param2={param2}")
        data = {"param1": param1, "param2": param2}
        return create_response(data=data, message="Test endpoint successful")
    except Exception as e:
        logger.error(f"Error in test endpoint: {e}")
        return create_error_response(message="Test endpoint failed")
