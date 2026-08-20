from __future__ import annotations

from .decorators import (
    get_auth_manager,
    get_current_user,
    require_admin,
    require_auth,
    require_permission,
    set_auth_manager,
)
from .manager import AuthManager
from .models import User
from .permissions import (
    ALL_PERMISSIONS,
    DEFAULT_USER_PERMISSIONS,
    Permission,
    Role,
    has_permission,
)

auth_manager = AuthManager()
set_auth_manager(auth_manager)

__all__ = [
    "ALL_PERMISSIONS",
    "DEFAULT_USER_PERMISSIONS",
    "AuthManager",
    "Permission",
    "Role",
    "User",
    "auth_manager",
    "get_auth_manager",
    "get_current_user",
    "has_permission",
    "require_admin",
    "require_auth",
    "require_permission",
    "set_auth_manager",
]
