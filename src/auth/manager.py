from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config import Config
from .models import User
from .permissions import ALL_PERMISSIONS, DEFAULT_USER_PERMISSIONS, Role, has_permission

logger = logging.getLogger(__name__)

# DEFAULT_DATA_DIR = Path("data")
# DEFAULT_USERS_FILE = DEFAULT_DATA_DIR / "users.json"


def _hash_password(password: str, salt_hex: str) -> str:
    salt_bytes = bytes.fromhex(salt_hex)
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=salt_bytes, n=16384, r=8, p=1
    )
    return derived.hex()


def _verify_password(password: str, salt_hex: str, expected_hash_hex: str) -> bool:
    computed_hash = _hash_password(password, salt_hex)
    return hmac.compare_digest(computed_hash, expected_hash_hex)


class AuthManager:
    def __init__(self, file_path: Path | str | None = None) -> None:
        if file_path is None:
            file_path = Path(Config.get_instance().get("USERS_FILE", "data/users.json"))
        self.file_path = Path(file_path)
        self._users: dict[str, User] = {}
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        async with self._lock:
            if self._initialized:
                return
            await self._ensure_data_loaded()
            self._initialized = True

    async def _ensure_data_loaded(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if self.file_path.exists():
            try:
                content = await asyncio.to_thread(
                    self.file_path.read_text, encoding="utf-8"
                )
                raw_data: Any = json.loads(content)
                if isinstance(raw_data, dict) and "users" in raw_data:
                    raw_users = raw_data.get("users")
                    if isinstance(raw_users, list):
                        loaded_users: dict[str, User] = {}
                        for item in raw_users:
                            if isinstance(item, dict) and "username" in item:
                                user_obj = User.from_dict(item)
                                loaded_users[user_obj.username] = user_obj
                        self._users = loaded_users
                        logger.info(
                            "loaded %d user(s) from %s",
                            len(self._users),
                            self.file_path,
                        )
            except Exception as e:
                logger.error(
                    "failed to load users database from %s: %s", self.file_path, e
                )
                self._users = {}

        if not self._users or "admin" not in self._users:
            await self._bootstrap_admin_user()

    async def _bootstrap_admin_user(self) -> None:
        admin_password = secrets.token_urlsafe(16)
        salt_hex = secrets.token_hex(16)
        hash_hex = _hash_password(admin_password, salt_hex)
        now = datetime.now(UTC).isoformat()

        admin_user = User(
            username="admin",
            password_hash=hash_hex,
            salt=salt_hex,
            role=Role.ADMIN.value,
            permissions=[p.value for p in ALL_PERMISSIONS],
            created_at=now,
            updated_at=now,
        )
        self._users["admin"] = admin_user
        await self._save_to_disk()

        logger.info("=" * 64)
        logger.info("[AUTH INITIALIZATION] generated initial admin credentials:")
        logger.info("username: admin")
        logger.info("password: %s", admin_password)
        logger.info("please save these credentials or change password upon login.")
        logger.info("=" * 64)

    async def _save_to_disk(self) -> None:
        data = {
            "users": [user.to_dict() for user in self._users.values()],
        }
        json_content = json.dumps(data, indent=2)

        def _atomic_write() -> None:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                dir=self.file_path.parent,
                delete=False,
                encoding="utf-8",
            ) as temp_file:
                temp_file.write(json_content)
                temp_file.flush()
                temp_path = Path(temp_file.name)

            try:
                shutil.move(str(temp_path), str(self.file_path))
            except Exception:
                if temp_path.exists():
                    temp_path.unlink(missing_ok=True)
                raise

        await asyncio.to_thread(_atomic_write)

    async def authenticate(self, username: str, password: str) -> User | None:
        async with self._lock:
            user = self._users.get(username)
            if not user:
                return None
            if not _verify_password(password, user.salt, user.password_hash):
                return None
            return user

    async def get_user(self, username: str) -> User | None:
        async with self._lock:
            return self._users.get(username)

    async def list_users(self) -> list[User]:
        async with self._lock:
            return list(self._users.values())

    async def create_user(
        self,
        username: str,
        password: str,
        role: str = Role.USER.value,
        permissions: list[str] | None = None,
    ) -> User:
        username = username.strip()
        if not username:
            raise ValueError("username cannot be empty")
        if len(username) < 3:
            raise ValueError("username must be at least 3 characters long")
        if len(password) < 6:
            raise ValueError("password must be at least 6 characters long")

        async with self._lock:
            if username in self._users:
                raise ValueError(f"user '{username}' already exists")

            salt_hex = secrets.token_hex(16)
            hash_hex = _hash_password(password, salt_hex)
            now = datetime.now(UTC).isoformat()

            if permissions is None:
                perms = [p.value for p in DEFAULT_USER_PERMISSIONS]
            else:
                perms = [str(p) for p in permissions]

            new_user = User(
                username=username,
                password_hash=hash_hex,
                salt=salt_hex,
                role=role,
                permissions=perms,
                created_at=now,
                updated_at=now,
            )
            self._users[username] = new_user
            await self._save_to_disk()
            logger.info("created new user: %s (role=%s)", username, role)
            return new_user

    async def update_password(self, username: str, new_password: str) -> bool:
        if len(new_password) < 6:
            raise ValueError("new password must be at least 6 characters long")

        async with self._lock:
            user = self._users.get(username)
            if not user:
                return False

            salt_hex = secrets.token_hex(16)
            hash_hex = _hash_password(new_password, salt_hex)
            user.salt = salt_hex
            user.password_hash = hash_hex
            user.updated_at = datetime.now(UTC).isoformat()
            await self._save_to_disk()
            logger.info("updated password for user: %s", username)
            return True

    async def update_permissions(self, username: str, permissions: list[str]) -> bool:
        async with self._lock:
            user = self._users.get(username)
            if not user:
                return False
            user.permissions = [str(p) for p in permissions]
            user.updated_at = datetime.now(UTC).isoformat()
            await self._save_to_disk()
            logger.info("updated permissions for user: %s", username)
            return True

    async def update_role(self, username: str, role: str) -> bool:
        if username == "admin" and role != Role.ADMIN.value:
            raise ValueError("cannot change root admin role")

        async with self._lock:
            user = self._users.get(username)
            if not user:
                return False
            user.role = role
            user.updated_at = datetime.now(UTC).isoformat()
            await self._save_to_disk()
            logger.info("updated role for user: %s to %s", username, role)
            return True

    async def delete_user(self, username: str) -> bool:
        if username == "admin":
            raise ValueError("cannot delete root admin user")

        async with self._lock:
            if username not in self._users:
                return False
            del self._users[username]
            await self._save_to_disk()
            logger.info("deleted user: %s", username)
            return True

    async def check_user_permission(
        self, username: str, required_permission: str
    ) -> bool:
        async with self._lock:
            user = self._users.get(username)
            if not user:
                return False
            return has_permission(user.role, user.permissions, required_permission)
