from __future__ import annotations

import logging
import os
import secrets
from typing import TYPE_CHECKING

from quart import Quart

from .extensions import asc
from .routes import register_all_routes
from .utils.handlers import create_error_response

if TYPE_CHECKING:
    from werkzeug.exceptions import HTTPException

logger = logging.getLogger(__name__)


def _resolve_secret_key() -> str:
    env_key = os.environ.get("PYLIVE_SECRET_KEY") or os.environ.get("SECRET_KEY")
    if env_key:
        logger.info("using secret key from environment")
        return env_key

    generated_key = secrets.token_hex(32)
    logger.warning("environment secret key missing; generated ephemeral key")
    return generated_key


def not_found_error(_: HTTPException):
    """Handle 404 errors."""
    return create_error_response(message="Resource not found", status_code=404)


def internal_server_error(error: HTTPException):
    """Handle 500 errors."""
    return create_error_response(
        message=error.description or "Internal Server Error",
        status_code=error.code or 500,
    )


def create_app() -> Quart:
    app = Quart(__name__, template_folder="templates", static_folder="static")
    app.secret_key = _resolve_secret_key()
    app.config.update(
        TEMPLATES_AUTO_RELOAD=True,
        SESSION_COOKIE_SAMESITE="None",
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=False,
    )

    # app.register_error_handler(404, not_found_error)
    # app.register_error_handler(500, internal_server_error)

    register_all_routes(app)

    @app.before_serving
    async def startup():
        logger.info("starting audio stream controller")
        # old_handler = signal.getsignal(signal.SIGINT)

        # def handle_sigint(signum: int, frame: Any) -> None:
        #     loop = asyncio.get_running_loop()
        #     loop.call_soon_threadsafe(lambda: asyncio.create_task(asc.stop()))
        #     if callable(old_handler):
        #         old_handler(signum, frame)

        # signal.signal(signal.SIGINT, handle_sigint)
        await asc.start()

    @app.after_serving
    async def shutdown():
        logger.info("stopping audio stream controller")
        await asc.stop()

    if app.debug:
        app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
