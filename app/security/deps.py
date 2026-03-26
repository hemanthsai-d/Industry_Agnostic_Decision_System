from __future__ import annotations

from typing import Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.security.auth import AuthService
from app.security.models import AuthContext

bearer_scheme = HTTPBearer(auto_error=False)


def get_auth_service() -> AuthService:
    return AuthService(get_settings())


def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthContext:
    return auth_service.authenticate(credentials)


def require_permission(permission: str) -> Callable[[AuthContext, AuthService], AuthContext]:
    def _dependency(
        ctx: AuthContext = Depends(get_auth_context),
        auth_service: AuthService = Depends(get_auth_service),
    ) -> AuthContext:
        auth_service.require_permission(ctx, permission)
        return ctx

    return _dependency

