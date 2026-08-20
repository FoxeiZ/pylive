from __future__ import annotations

import logging
from functools import wraps
from typing import TYPE_CHECKING, Any

from quart import Response, session

from ..utils.handlers import create_error_response
from .permissions import Permission, Role, has_permission

if TYPE_CHECKING:
    from collections.abc import Callable

    from .manager import AuthManager
    from .models import User

logger = logging.getLogger(__name__)

_global_auth_manager: AuthManager | None = None


def set_auth_manager(manager: AuthManager) -> None:
    global _global_auth_manager
    _global_auth_manager = manager


def get_auth_manager() -> AuthManager:
    if _global_auth_manager is None:
        raise RuntimeError("AuthManager has not been initialized")
    return _global_auth_manager


async def get_current_user() -> User | None:
    username = session.get("username")
    if not username or not isinstance(username, str):
        return None
    manager = get_auth_manager()
    return await manager.get_user(username)


def require_auth():
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Response:
            user = await get_current_user()
            if not user:
                return await create_error_response(
                    message="Authentication required",
                    status_code=401,
                )
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def require_permission(required_permission: Permission | str):
    perm_str = (
        required_permission.value
        if isinstance(required_permission, Permission)
        else required_permission
    )

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Response:
            user = await get_current_user()
            if not user:
                return await create_error_response(
                    message="Authentication required",
                    status_code=401,
                )
            if not has_permission(user.role, user.permissions, perm_str):
                logger.warning(
                    "permission denied for user '%s': requires '%s'",
                    user.username,
                    perm_str,
                )
                return await create_error_response(
                    message=f"Permission denied: {perm_str} required",
                    status_code=403,
                )
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def require_admin():
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Response:
            user = await get_current_user()
            if not user:
                return await create_error_response(
                    message="Authentication required",
                    status_code=401,
                )
            if user.role != Role.ADMIN.value:
                return await create_error_response(
                    message="Admin privileges required",
                    status_code=403,
                )
            return await func(*args, **kwargs)

        return wrapper

    return decorator
