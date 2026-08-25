from __future__ import annotations

import logging
from typing import Any

from quart import Blueprint, Response

from ..auth import Permission, require_permission
from ..services import room_manager
from ..utils.handlers import (
    create_error_response,
    create_response,
)

logger = logging.getLogger(__name__)

bp = Blueprint("room", __name__, url_prefix="/api/room")


@bp.route("/state", methods=["GET"])
async def get_state() -> Response:
    """get current room playback state, active track, and sync timestamps."""
    try:
        state = await room_manager.get_room_state("main")
        return await create_response(data=state)
    except Exception as e:
        logger.exception(f"failed to get room state: {e}")
        return await create_error_response(message="failed to get room state")


@bp.route("/advance", methods=["POST"])
async def advance() -> Response:
    """atomically advance to next track when client completes song playback."""
    try:
        res = await room_manager.advance_track("main")
        return await create_response(data=res or {"status": "already_advanced"})
    except Exception as e:
        logger.exception(f"failed to advance room track: {e}")
        return await create_error_response(message="failed to advance track")


@bp.route("/skip", methods=["POST"])
@require_permission(Permission.QUEUE_SKIP_FORCE)
async def skip() -> Response:
    """force skip the currently playing track."""
    try:
        res = await room_manager.skip_track("main")
        return await create_response(data=res or {"status": "idle"})
    except Exception as e:
        logger.exception(f"failed to skip track: {e}")
        return await create_error_response(message="failed to skip track")


@bp.route("/pause", methods=["POST"])
@require_permission(Permission.PLAYER_CONTROL)
async def pause() -> Response:
    """pause room playback."""
    try:
        res = await room_manager.pause_track("main")
        return await create_response(data=res)
    except Exception as e:
        logger.exception(f"failed to pause track: {e}")
        return await create_error_response(message="failed to pause track")


@bp.route("/resume", methods=["POST"])
@require_permission(Permission.PLAYER_CONTROL)
async def resume() -> Response:
    """resume room playback."""
    try:
        res = await room_manager.resume_track("main")
        return await create_response(data=res)
    except Exception as e:
        logger.exception(f"failed to resume track: {e}")
        return await create_error_response(message="failed to resume track")


def register_routes(app: Any) -> None:
    app.register_blueprint(bp)
