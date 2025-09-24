import json
import logging

from flask import Flask, Response, abort, jsonify, render_template, request

from src.general import MISSING_TYPE, HTTPRequestManager, execute_in_thread
from src.server import AudioQueueManager

MISSING = MISSING_TYPE()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

WEBHOOK_URL = None

app = Flask(__name__, static_url_path="/static")
previous_client_ip = None

try:
    audio_manager = AudioQueueManager()
    logger.info("Audio manager initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize audio manager: {e}")
    audio_manager = None


def send_webhook(func):
    def webhook(response: Response, webhook_url=None, func_name=""):
        """Send webhook notification with response data."""
        if not webhook_url:
            return

        try:
            res = HTTPRequestManager.make_request(
                webhook_url,
                method="POST",
                data={
                    "content": f"`/{func_name}`\n```{json.dumps(response.json, indent=2)}\n```",
                    "username": "debug radio",
                },
                headers={
                    "Content-Type": "application/json",
                },
            )

            if res.getcode() != 204:
                logger.warning("Failed to send webhook")
                logger.debug(f"Webhook response: {res.read().decode('utf-8')}")

        except Exception as e:
            logger.error(f"Error sending webhook: {e}")

    def wrapper(*args, **kwargs):
        ret = func(*args, **kwargs)
        execute_in_thread(
            webhook,
            wait_for_result=False,
            response=ret[0],
            func_name=func.__name__,
            webhook_url=WEBHOOK_URL,
        )
        return ret

    wrapper.__name__ = func.__name__
    return wrapper


def is_value_present(arg) -> bool:
    if arg is None:
        return False

    # Handle different types appropriately
    if isinstance(arg, (list, dict, str)):
        return len(arg) > 0

    return bool(arg)


def create_response(
    data=None,
    message: str = "success",
    is_error: bool = False,
    status_code: int = 200,
    additional_data=None,
) -> tuple[Response, int]:
    response_body = {
        "msg": message,
        "error": is_error,
        "data": data if is_value_present(data) else None,
    }

    if additional_data:
        response_body.update({"additional_data": additional_data})

    return jsonify(response_body), status_code


def create_error_response(*args, **kwargs):
    return create_response(*args, is_error=True, **kwargs)


def generate_audio_stream(audio_manager: AudioQueueManager):
    logger.debug("Starting audio stream generation")

    try:
        # Send header data first
        yield audio_manager.wait_for_header()

        # Stream audio data while alive
        while audio_manager.is_alive():
            yield audio_manager.buffer
            audio_manager.event.wait()

    except Exception as e:
        logger.error(f"Error in audio stream generation: {e}")
    finally:
        logger.debug("Audio stream generation ended")


def validate_request_args(required_args: list):
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                # Get data based on request method
                if request.method == "GET":
                    data = request.args
                elif request.method == "POST":
                    if request.is_json:
                        data = request.json
                    else:
                        data = request.form
                else:
                    logger.warning(f"Unsupported request method: {request.method}")
                    return abort(500)

                # Validate required arguments
                if data is None:
                    logger.warning("No data provided in request")
                    return abort(400)

                for arg in required_args:
                    if arg not in data:
                        logger.warning(f"Missing required argument: {arg}")
                        return abort(400)
                    else:
                        kwargs[arg] = data.get(arg)

                return func(*args, **kwargs)

            except Exception as e:
                logger.error(f"Error validating request arguments: {e}")
                return abort(500)

        wrapper.__name__ = func.__name__
        return wrapper

    return decorator


def check_rate_limit(func):
    def wrapper(*args, **kwargs):
        global previous_client_ip

        client_ip = request.remote_addr

        if previous_client_ip == client_ip:
            logger.warning(f"Rate limit hit for IP: {client_ip}")
            return create_error_response(
                message="Rate limit exceeded. Please wait before making another request.",
                status_code=429,
            )

        previous_client_ip = client_ip
        return func(*args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


# Flask Routes


@app.route("/add", methods=["POST"])
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


@app.route("/queue")
def get_queue_info():
    try:
        if not audio_manager:
            return create_error_response(
                message="Audio manager not available", status_code=503
            )

        # Parse request parameters
        page_index = int(request.args.get("index", request.args.get("page", 0)))
        use_autoqueue = request.args.get("use_autoqueue", "0") == "1"

        # Calculate pagination
        items_per_page = 5
        end_offset = min((page_index + 1) * items_per_page, len(audio_manager.queue))
        start_offset = max(end_offset - items_per_page, 0)

        response_data = {
            "queue": audio_manager.queue[start_offset:end_offset],
        }

        if use_autoqueue and audio_manager.auto_queue:
            response_data.update({"auto_queue": audio_manager.auto_queue})

        return create_response(data=response_data)

    except Exception as e:
        logger.error(f"Error getting queue info: {e}")
        return create_error_response(message="Failed to retrieve queue information")


@app.route("/np")
@app.route("/nowplaying")
def get_now_playing():
    try:
        if not audio_manager:
            return create_error_response(
                message="Audio manager not available", status_code=503
            )

        response_data = {"now_playing": audio_manager.now_playing}

        if audio_manager.queue:
            response_data.update({"next_up": audio_manager.queue[0]})

        return create_response(data=response_data)

    except Exception as e:
        logger.error(f"Error getting now playing info: {e}")
        return create_error_response(
            message="Failed to retrieve now playing information"
        )


@app.route("/skip", methods=["POST"])
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


@app.route("/stream")
def get_audio_stream():
    try:
        if not audio_manager:
            logger.error("Audio manager not available for streaming")
            return create_error_response(
                message="Audio streaming not available", status_code=503
            )

        if (
            not hasattr(audio_manager, "_ffmpeg_process")
            or audio_manager._ffmpeg_process == MISSING
        ):
            logger.error("FFmpeg process not available")
            return create_error_response(
                message="Audio stream not available", status_code=404
            )

        logger.debug("Starting audio stream")
        return Response(
            generate_audio_stream(audio_manager), content_type="audio/ogg", status=200
        )

    except Exception as e:
        logger.error(f"Error getting audio stream: {e}")
        return create_error_response(
            message="Failed to start audio stream", status_code=500
        )


@app.route("/")
def index():
    try:
        if not audio_manager:
            # Render with empty data if audio manager is not available
            return render_template("stream.html", np={}, queue=[])

        return render_template(
            "stream.html", np=audio_manager.now_playing, queue=audio_manager.queue
        )

    except Exception as e:
        logger.error(f"Error rendering index page: {e}")
        return "Internal Server Error", 500


@app.route("/watch_event")
def watch_events():
    try:
        if not audio_manager:
            logger.error("Audio manager not available for events")
            return create_error_response(
                message="Event streaming not available", status_code=503
            )

        logger.debug("Client connected to event stream")
        return Response(
            audio_manager.event_queue.watch(), content_type="text/event-stream"
        )

    except Exception as e:
        logger.error(f"Error in event stream: {e}")
        return create_error_response(
            message="Failed to start event stream", status_code=500
        )


# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 errors."""
    logger.warning(f"404 error: {request.url}")
    return create_error_response(message="Resource not found", status_code=404)


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    logger.error(f"500 error: {error}")
    return create_error_response(message="Internal server error", status_code=500)


if __name__ == "__main__":
    logger.info("Starting PyLive server")

    if not audio_manager:
        logger.warning("Starting server without audio manager - limited functionality")

    try:
        app.run("0.0.0.0", port=5000, threaded=True)
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
    finally:
        logger.info("PyLive server stopped")
