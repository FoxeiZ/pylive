from __future__ import annotations

import logging
from typing import Any

from quart import Blueprint, Quart, request, session

from ..auth import (
    ALL_PERMISSIONS,
    get_auth_manager,
    get_current_user,
    require_admin,
    require_auth,
)
from ..utils.handlers import create_error_response, create_response

logger = logging.getLogger(__name__)

bp = Blueprint("auth", __name__)


@bp.route("/status", methods=["GET"])
async def get_auth_status():
    user = await get_current_user()
    if not user:
        return await create_response(
            data={
                "authenticated": False,
                "user": None,
                "available_permissions": [p.value for p in ALL_PERMISSIONS],
            }
        )
    return await create_response(
        data={
            "authenticated": True,
            "user": user.to_public_dict(),
            "available_permissions": [p.value for p in ALL_PERMISSIONS],
        }
    )


@bp.route("/login", methods=["POST"])
async def login():
    data: dict[str, Any] | None = await request.get_json()
    if not data or "username" not in data or "password" not in data:
        return await create_error_response(
            message="Username and password are required",
            status_code=400,
        )

    username = str(data["username"]).strip()
    password = str(data["password"])

    manager = get_auth_manager()
    user = await manager.authenticate(username, password)
    if not user:
        logger.warning("failed login attempt for username: %s", username)
        return await create_error_response(
            message="Invalid username or password",
            status_code=401,
        )

    session["username"] = user.username
    logger.info("user '%s' logged in successfully", user.username)
    return await create_response(
        data=user.to_public_dict(),
        message="Login successful",
    )


@bp.route("/logout", methods=["POST"])
async def logout():
    username = session.pop("username", None)
    if username:
        logger.info("user '%s' logged out", username)
    return await create_response(message="Logout successful")


@bp.route("/change-password", methods=["POST"])
@require_auth()
async def change_password():
    user = await get_current_user()
    if not user:
        return await create_error_response(message="Authentication required", status_code=401)

    data: dict[str, Any] | None = await request.get_json()
    if not data or "current_password" not in data or "new_password" not in data:
        return await create_error_response(
            message="Current password and new password are required",
            status_code=400,
        )

    current_password = str(data["current_password"])
    new_password = str(data["new_password"])

    manager = get_auth_manager()
    authenticated = await manager.authenticate(user.username, current_password)
    if not authenticated:
        return await create_error_response(
            message="Current password is incorrect",
            status_code=400,
        )

    try:
        await manager.update_password(user.username, new_password)
        return await create_response(message="Password changed successfully")
    except ValueError as e:
        return await create_error_response(message=str(e), status_code=400)


@bp.route("/users", methods=["GET"])
@require_admin()
async def list_users():
    manager = get_auth_manager()
    users = await manager.list_users()
    return await create_response(
        data={
            "users": [u.to_public_dict() for u in users],
            "all_permissions": [p.value for p in ALL_PERMISSIONS],
        }
    )


@bp.route("/users", methods=["POST"])
@require_admin()
async def create_user():
    data: dict[str, Any] | None = await request.get_json()
    if not data or "username" not in data or "password" not in data:
        return await create_error_response(
            message="Username and password are required",
            status_code=400,
        )

    username = str(data["username"]).strip()
    password = str(data["password"])
    role = str(data.get("role", "user"))
    permissions_raw = data.get("permissions")
    permissions: list[str] | None = None
    if isinstance(permissions_raw, list):
        permissions = [str(p) for p in permissions_raw if p is not None]

    manager = get_auth_manager()
    try:
        new_user = await manager.create_user(
            username=username,
            password=password,
            role=role,
            permissions=permissions,
        )
        return await create_response(
            data=new_user.to_public_dict(),
            message="User created successfully",
            status_code=201,
        )
    except ValueError as e:
        return await create_error_response(message=str(e), status_code=400)


@bp.route("/users/<username>", methods=["DELETE"])
@require_admin()
async def delete_user(username: str):
    manager = get_auth_manager()
    try:
        deleted = await manager.delete_user(username)
        if not deleted:
            return await create_error_response(message="User not found", status_code=404)
        return await create_response(message=f"User '{username}' deleted successfully")
    except ValueError as e:
        return await create_error_response(message=str(e), status_code=400)


@bp.route("/users/<username>/permissions", methods=["PUT"])
@require_admin()
async def update_user_permissions(username: str):
    data: dict[str, Any] | None = await request.get_json()
    if not data or "permissions" not in data:
        return await create_error_response(
            message="A list of permissions is required",
            status_code=400,
        )

    raw_perms = data.get("permissions")
    if not isinstance(raw_perms, list):
        return await create_error_response(
            message="A list of permissions is required",
            status_code=400,
        )

    permissions: list[str] = [str(p) for p in raw_perms if p is not None]
    manager = get_auth_manager()
    success = await manager.update_permissions(username, permissions)
    if not success:
        return await create_error_response(message="User not found", status_code=404)

    return await create_response(message=f"Permissions for '{username}' updated successfully")


@bp.route("/users/<username>/reset-password", methods=["POST"])
@require_admin()
async def reset_user_password(username: str):
    data: dict[str, Any] | None = await request.get_json()
    if not data or "new_password" not in data:
        return await create_error_response(
            message="new_password is required",
            status_code=400,
        )

    new_password = str(data["new_password"])
    manager = get_auth_manager()
    try:
        success = await manager.update_password(username, new_password)
        if not success:
            return await create_error_response(message="User not found", status_code=404)
        return await create_response(message=f"Password for '{username}' reset successfully")
    except ValueError as e:
        return await create_error_response(message=str(e), status_code=400)


def register_routes(app: Quart) -> None:
    app.register_blueprint(bp, url_prefix="/auth")
