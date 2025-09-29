import logging

from flask import Flask

from .routes import register_all_routes
from .utils.handlers import create_error_response

logger = logging.getLogger(__name__)


def not_found_error(error):
    """Handle 404 errors."""
    return create_error_response(message="Resource not found", status_code=404)


def internal_server_error(error):
    """Handle 500 errors."""
    return create_error_response(message="Internal server error", status_code=500)


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = "huhu"
    app.config.update(
        TEMPLATES_AUTO_RELOAD=True,
        SESSION_COOKIE_SAMESITE="None",
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=False,
    )

    app.register_error_handler(404, not_found_error)
    app.register_error_handler(500, internal_server_error)

    register_all_routes(app)

    if app.debug:
        app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
