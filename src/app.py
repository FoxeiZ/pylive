from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import secrets
import signal
from typing import TYPE_CHECKING, Any

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


async def not_found_error(_: HTTPException):
    """handle 404 errors."""
    return await create_error_response(message="Resource not found", status_code=404)


async def internal_server_error(error: HTTPException):
    """handle 500 errors."""
    return await create_error_response(
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

    app.register_error_handler(404, not_found_error)
    app.register_error_handler(500, internal_server_error)

    register_all_routes(app)

    @app.before_serving
    async def startup():
        logger.info("starting audio stream controller")
        loop = asyncio.get_running_loop()

        old_handlers: dict[int, Any] = {}

        def _signal_handler(sig_num: int, frame: Any) -> None:
            logger.info(
                f"received signal {sig_num}, initiating audio controller shutdown"
            )
            with contextlib.suppress(Exception):
                loop.call_soon_threadsafe(lambda: asyncio.create_task(asc.stop()))
            old = old_handlers.get(sig_num)
            if callable(old) and old not in (
                signal.SIG_DFL,
                signal.SIG_IGN,
                signal.default_int_handler,
            ):
                old(sig_num, frame)

        for sig in (
            getattr(signal, "SIGINT", None),
            getattr(signal, "SIGTERM", None),
            getattr(signal, "SIGBREAK", None),
        ):
            if sig is not None:
                try:
                    old_handlers[sig] = signal.getsignal(sig)
                    signal.signal(sig, _signal_handler)
                except (ValueError, OSError):
                    pass

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
    app.run(host="127.0.0.1", port=8000, debug=True, use_reloader=False)
