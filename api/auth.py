"""Shared API authentication dependency.

Centralized here so that routers (``api.whatsapp_routes`` and
``api.integration_routes``) do not have to import ``api.app``, which would
otherwise create a circular import.
"""

import os
import secrets

from fastapi import Header, HTTPException, status


def _ui_token() -> str:
    return os.getenv("UI_ACCESS_TOKEN", "")


def require_ui_access(authorization: str | None = Header(default=None)) -> None:
    """Reject unauthenticated requests.

    Fails closed when ``UI_ACCESS_TOKEN`` is empty (protected endpoints must
    never be reachable without a configured token). Accepts
    ``Authorization: Bearer <token>`` and compares with a constant-time check.
    """
    token = _ui_token()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="UI access not configured.",
        )

    presented = (authorization or "")
    if presented.lower().startswith("bearer "):
        presented = presented[7:].strip()

    if not presented or not secrets.compare_digest(presented, token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized.",
        )
