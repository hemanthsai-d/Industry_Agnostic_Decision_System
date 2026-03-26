from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthContext:
    subject: str
    roles: set[str]
    permissions: set[str]
    tenant_ids: set[str]
    is_platform_admin: bool = False

