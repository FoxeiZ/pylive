from __future__ import annotations

from typing import TYPE_CHECKING

from .auth import register_routes as auth_bp
from .queue import register_routes as queue_bp
from .room import register_routes as room_bp
from .root import register_routes as root_bp

if TYPE_CHECKING:
    from quart import Quart


def register_all_routes(app: Quart) -> None:
    auth_bp(app)
    queue_bp(app)
    room_bp(app)
    root_bp(app)
