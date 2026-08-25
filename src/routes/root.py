from __future__ import annotations

import logging
from typing import Any

from quart import Blueprint, Quart, render_template

from ..auth import get_current_user
from ..config import Config
from ..services import room_manager
from ..utils.handlers import create_response

logger = logging.getLogger(__name__)

__all__ = ("register_routes",)

bp = Blueprint("root", __name__)


@bp.route("/")
async def index_page() -> Any:
    try:
        user = await get_current_user()
        user_data = user.to_public_dict() if user else None

        room_state = await room_manager.get_room_state("main")
        queue_data = await room_manager.get_queue("main", page=0, page_size=10)

        supabase_url = str(Config.get("SUPABASE_URL", ""))
        supabase_key = str(Config.get("SUPABASE_KEY", ""))

        return await render_template(
            "index.html",
            np=room_state.get("now_playing") or {},
            queue=queue_data.get("queue", []),
            auto_queue=queue_data.get("auto_queue", []),
            user=user_data,
            supabase_url=supabase_url,
            supabase_key=supabase_key,
        )
    except Exception as e:
        logger.error(f"error rendering index page: {e}")
        return await render_template(
            "index.html",
            np={},
            queue=[],
            auto_queue=[],
            user=None,
            supabase_url="",
            supabase_key="",
        )


@bp.route("/health")
async def health_check() -> Any:
    return await create_response(data={"status": "ok"})


def register_routes(app: Quart) -> None:
    app.register_blueprint(bp)
