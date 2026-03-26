from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate local JWT for API auth testing")
    parser.add_argument("--sub", default="local-user")
    parser.add_argument("--tenant", action="append", dest="tenants", default=["org_demo"])
    parser.add_argument(
        "--perm",
        action="append",
        dest="perms",
        default=[
            "assist:decide",
            "assist:feedback",
            "assist:reindex",
            "assist:handoff:read",
            "assist:handoff:update",
        ],
    )
    parser.add_argument("--role", action="append", dest="roles", default=["support_agent"])
    parser.add_argument("--minutes", type=int, default=120)
    args = parser.parse_args()

    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": args.sub,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=args.minutes)).timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "roles": args.roles,
        "permissions": args.perms,
        "tenant_ids": args.tenants,
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    print(token)


if __name__ == "__main__":
    main()
