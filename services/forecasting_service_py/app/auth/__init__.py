"""Cognito JWT auth.

Strategy: a FastAPI middleware (`CognitoAuthMiddleware`) inspects the
`Authorization: Bearer <jwt>` header on each request. If a valid Cognito
access/ID token is present, it resolves (or creates) a local `User` row
and writes that user's id into `X-User-Id` on the request scope.

This keeps every existing handler that reads `X-User-Id: int` working
without code changes — the middleware just makes the header trustworthy.

When `COGNITO_USER_POOL_ID` is unset (e.g. local dev), the middleware is
a no-op and the legacy `X-User-Id` header is still honored.
"""
from app.auth.middleware import CognitoAuthMiddleware  # noqa: F401
from app.auth.router import auth_router  # noqa: F401
