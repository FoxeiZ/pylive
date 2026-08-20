from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass
class User:
    username: str
    password_hash: str
    salt: str
    role: str
    permissions: list[str] = field(default_factory=list["str"])
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "role": self.role,
            "permissions": self.permissions,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> User:
        raw_perms: Iterable[str] | None = data.get("permissions")
        perms_list: list[str] = (
            [str(p) for p in raw_perms] if isinstance(raw_perms, list) else []
        )
        return cls(
            username=str(data["username"]),
            password_hash=str(data["password_hash"]),
            salt=str(data["salt"]),
            role=str(data.get("role", "user")),
            permissions=perms_list,
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )
