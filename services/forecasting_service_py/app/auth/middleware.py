"""Cognito auth middleware.

For every incoming request:
- If `Authorization: Bearer <jwt>` is present, validate the JWT against
  Cognito JWKS, resolve the local `User`, and rewrite `X-User-Id` on the
  request scope so existing handlers' `Header(alias="X-User-Id")` params
  pick up the authenticated user id automatically.
- If no Bearer token, the request passes through with any client-supplied
  `X-User-Id` stripped (so it cannot be spoofed). Handlers see `None`.
- If a Bearer token is present but invalid, return 401.

The middleware is a no-op when Cognito is not configured (e.g. local dev
without Cognito env vars) — it simply does not touch incoming requests,
so the legacy `X-User-Id` flow keeps working for `python main.py` + curl.
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

from sqlmodel import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.auth.cognito import (
    TokenError,
    find_or_create_user_for_claims,
    is_cognito_configured,
    verify_cognito_jwt,
)
from app.db.database import engine


logger = logging.getLogger(__name__)


class CognitoAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Skip entirely when Cognito isn't configured (local dev, tests).
        if not is_cognito_configured():
            return await call_next(request)

        # Strip any client-supplied X-User-Id immediately. Anything below
        # that re-injects it must do so from a verified Cognito claim.
        _strip_header(request, "x-user-id")

        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.lower().startswith("bearer "):
            # No Bearer token: handlers will see x_user_id=None and decide
            # whether to 401 (via `_require_user`) or serve a public response.
            return await call_next(request)

        token = auth_header[7:].strip()
        try:
            claims = verify_cognito_jwt(token)
        except TokenError as exc:
            logger.info("Auth: rejected Bearer token (%s)", exc)
            return JSONResponse({"detail": str(exc)}, status_code=401)
        except Exception as exc:
            logger.warning("Auth: unexpected JWT error: %s", exc)
            return JSONResponse({"detail": "Invalid token"}, status_code=401)

        try:
            with Session(engine) as session:
                user = find_or_create_user_for_claims(session, claims)
                user_id = int(user.id)
        except TokenError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=401)
        except Exception as exc:
            logger.exception("Auth: failed to resolve user from claims: %s", exc)
            return JSONResponse({"detail": "User resolution failed"}, status_code=500)

        # Inject X-User-Id and the resolved user onto the request scope so
        # both the legacy header path and any future Depends() can see it.
        _set_header(request, "x-user-id", str(user_id))
        request.state.user_id = user_id
        request.state.cognito_claims = claims

        return await call_next(request)


def _set_header(request: Request, name: str, value: str) -> None:
    """Replace (or add) a header on the live request scope.

    Starlette stores headers as a list of (bytes, bytes) tuples in
    `request.scope['headers']`. We mutate that list so downstream code
    (FastAPI's `Header(...)` resolver included) sees the new value.
    """
    name_b = name.lower().encode("latin-1")
    value_b = value.encode("latin-1")
    headers = [(k, v) for (k, v) in request.scope.get("headers", []) if k.lower() != name_b]
    headers.append((name_b, value_b))
    request.scope["headers"] = headers


def _strip_header(request: Request, name: str) -> None:
    """Remove a header from the live request scope (if present)."""
    name_b = name.lower().encode("latin-1")
    headers = [(k, v) for (k, v) in request.scope.get("headers", []) if k.lower() != name_b]
    request.scope["headers"] = headers
