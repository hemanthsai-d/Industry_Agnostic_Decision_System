from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import jwt
from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

from app.core.config import Settings
from app.security.models import AuthContext


class AuthService:
    def __init__(self, settings: Settings):
        self._settings = settings

    def authenticate(self, credentials: HTTPAuthorizationCredentials | None) -> AuthContext:
        if not self._settings.auth_enabled:
            return AuthContext(
                subject="dev-local",
                roles={"platform_admin"},
                permissions={"*"},
                tenant_ids={"*"},
                is_platform_admin=True,
            )

        if credentials is None or not credentials.credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing bearer token.",
            )

        token = credentials.credentials
        payload = self._decode(token)
        return self._build_context(payload)

    def require_permission(self, ctx: AuthContext, permission: str) -> None:
        if ctx.is_platform_admin:
            return
        if "*" in ctx.permissions or permission in ctx.permissions:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission: {permission}",
        )

    def enforce_tenant_access(self, ctx: AuthContext, tenant_id: str) -> None:
        if ctx.is_platform_admin:
            return
        if "*" in ctx.tenant_ids or tenant_id in ctx.tenant_ids:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No access to tenant: {tenant_id}",
        )

    def _decode(self, token: str) -> dict[str, Any]:
        try:
            options = {
                "require": ["sub", "exp", "iat"],
            }
            kwargs: dict[str, Any] = {
                "algorithms": [self._settings.jwt_algorithm],
                "options": options,
            }
            if self._settings.jwt_audience:
                kwargs["audience"] = self._settings.jwt_audience
            if self._settings.jwt_issuer:
                kwargs["issuer"] = self._settings.jwt_issuer

            payload = jwt.decode(token, self._settings.jwt_secret_key, **kwargs)
            return payload
        except jwt.ExpiredSignatureError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired.",
            ) from exc
        except jwt.InvalidTokenError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token.",
            ) from exc

    @staticmethod
    def _normalize_set(value: Any) -> set[str]:
        if value is None:
            return set()
        if isinstance(value, str):
            if " " in value:
                return {v.strip() for v in value.split(" ") if v.strip()}
            return {value}
        if isinstance(value, list):
            return {str(v) for v in value if str(v)}
        return set()

    def _build_context(self, payload: dict[str, Any]) -> AuthContext:
        sub = str(payload.get("sub", ""))
        if not sub:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing subject.",
            )

        roles = self._normalize_set(payload.get("roles"))
        permissions = self._normalize_set(payload.get("permissions"))
        if not permissions and payload.get("scope"):
            permissions = self._normalize_set(payload.get("scope"))

        tenant_ids = self._normalize_set(payload.get("tenant_ids"))
        tenant_single = payload.get("tenant_id")
        if tenant_single:
            tenant_ids.add(str(tenant_single))

        is_platform_admin = "platform_admin" in roles or "*" in tenant_ids or "*" in permissions
        if is_platform_admin:
            tenant_ids.add("*")
            permissions.add("*")

        iat = payload.get("iat")
        if isinstance(iat, (int, float)):
            now = datetime.now(timezone.utc).timestamp()
            if iat > now + 120:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token iat.",
                )

        return AuthContext(
            subject=sub,
            roles=roles,
            permissions=permissions,
            tenant_ids=tenant_ids,
            is_platform_admin=is_platform_admin,
        )

