from __future__ import annotations

from enum import StrEnum
from typing import Final


class Role(StrEnum):
    ADMIN = "admin"
    USER = "user"
    GUEST = "guest"


class Permission(StrEnum):
    QUEUE_ADD = "queue:add"
    QUEUE_REMOVE = "queue:remove"
    QUEUE_SKIP_VOTE = "queue:skip_vote"
    QUEUE_SKIP_FORCE = "queue:skip_force"
    QUEUE_CLEAR = "queue:clear"
    QUEUE_AUTOPLAY_REFRESH = "queue:autoplay_refresh"
    ADMIN_MANAGE_USERS = "admin:manage_users"


ALL_PERMISSIONS: Final[list[Permission]] = [
    Permission.QUEUE_ADD,
    Permission.QUEUE_REMOVE,
    Permission.QUEUE_SKIP_VOTE,
    Permission.QUEUE_SKIP_FORCE,
    Permission.QUEUE_CLEAR,
    Permission.QUEUE_AUTOPLAY_REFRESH,
    Permission.ADMIN_MANAGE_USERS,
]

DEFAULT_USER_PERMISSIONS: Final[list[Permission]] = [
    Permission.QUEUE_ADD,
    Permission.QUEUE_SKIP_VOTE,
]


def has_permission(
    role: str, user_permissions: list[str], required_permission: str
) -> bool:
    if role == Role.ADMIN.value:
        return True
    if role == Role.GUEST.value:
        return False
    return required_permission in user_permissions
