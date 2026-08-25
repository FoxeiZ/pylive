from __future__ import annotations

import logging
import os
import secrets
from typing import TYPE_CHECKING

from quart import Quart

from .auth import auth_manager
from .routes import register_all_routes
from .services import close_redis_client
from .utils.handlers import create_error_response

if TYPE_CHECKING:
    from werkzeug.exceptions import HTTPException

logger = logging.getLogger(__name__)


def _resolve_secret_key() -> str:
    env_key = os.environ.get("PYLIVE_SECRET_KEY") or os.environ.get("SECRET_KEY")
    if env_key:
        return env_key

    return secrets.token_hex(32)


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
        SESSION_COOKIE_NAME="pylive_session",
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=False,
        SESSION_COOKIE_HTTPONLY=True,
    )

    app.register_error_handler(404, not_found_error)
    app.register_error_handler(500, internal_server_error)

    register_all_routes(app)

    @app.before_serving
    async def startup():
        logger.info("initializing authentication manager")
        await auth_manager.initialize()

    @app.after_serving
    async def shutdown():
        logger.info("closing redis connection pool")
        await close_redis_client()

    if app.debug:
        app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="127.0.0.1", port=8000, debug=True, use_reloader=False)
