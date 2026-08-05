from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from .config import Settings


def _authorization_token(value: str | None) -> str | None:
    if not value:
        return None
    parts = value.strip().split(maxsplit=1)
    if len(parts) != 2 or parts[0].lower() not in {"bearer", "token"}:
        return None
    return parts[1].strip()


def build_auth_dependency(settings: Settings):
    async def verify_memory_key(
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    ) -> None:
        if not settings.require_auth:
            return
        supplied = x_api_key or _authorization_token(authorization)
        if not supplied or not hmac.compare_digest(supplied, settings.memory_api_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"reason": "invalid or missing Memory System Key"},
            )

    return verify_memory_key
