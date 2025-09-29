from .queue import register_routes as queue_bp
from .root import register_routes as root_bp


def register_all_routes(app):
    queue_bp(app)
    root_bp(app)
