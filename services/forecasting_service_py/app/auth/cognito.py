"""Cognito JWT validation + local-user resolution.

- Fetches and caches the User Pool's JWKS (public keys) for signature
  verification.
- Decodes and validates Bearer tokens (signature, issuer, audience, expiry).
- Resolves a local `User` row from the JWT's `sub` claim (Cognito user id),
  creating one on first sight using the `email` claim and (optional)
  `name` / `cognito:username` claims.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from app.utils.timeutil import utcnow
from typing import Any, Optional

from jose import jwk, jwt
from jose.utils import base64url_decode
from sqlmodel import Session, select

from app.db.models import User


logger = logging.getLogger(__name__)


# --- env-driven config -------------------------------------------------

def _cfg() -> dict[str, Optional[str]]:
    return {
        "region": os.getenv("COGNITO_REGION") or os.getenv("AWS_REGION"),
        "user_pool_id": os.getenv("COGNITO_USER_POOL_ID"),
        "app_client_id": os.getenv("COGNITO_APP_CLIENT_ID"),
    }


def is_cognito_configured() -> bool:
    c = _cfg()
    return bool(c["region"] and c["user_pool_id"])


def _issuer() -> str:
    c = _cfg()
    return f"https://cognito-idp.{c['region']}.amazonaws.com/{c['user_pool_id']}"


def _jwks_url() -> str:
    return f"{_issuer()}/.well-known/jwks.json"


# --- JWKS cache ---------------------------------------------------------

_JWKS_TTL_SECONDS = 3600  # refresh hourly
_jwks_lock = threading.Lock()
_jwks_cache: dict[str, Any] = {"keys": None, "fetched_at": 0.0}


def _fetch_jwks() -> dict[str, Any]:
    """Pull JWKS from Cognito (small JSON doc with public keys)."""
    import httpx
    url = _jwks_url()
    resp = httpx.get(url, timeout=10.0)
    resp.raise_for_status()
    return resp.json()


def _jwks_keys() -> list[dict[str, Any]]:
    now = time.time()
    with _jwks_lock:
        if (
            _jwks_cache["keys"] is None
            or now - _jwks_cache["fetched_at"] > _JWKS_TTL_SECONDS
        ):
            try:
                doc = _fetch_jwks()
                _jwks_cache["keys"] = doc.get("keys", [])
                _jwks_cache["fetched_at"] = now
            except Exception as exc:
                logger.warning("Failed to refresh Cognito JWKS: %s", exc)
                if _jwks_cache["keys"] is None:
                    raise
        return _jwks_cache["keys"]


# --- token verification -------------------------------------------------

class TokenError(Exception):
    """Raised when a JWT fails to verify."""


def verify_cognito_jwt(token: str) -> dict[str, Any]:
    """Verify a Cognito JWT and return its claims.

    Validates: signature (against JWKS), issuer, expiry. Audience is
    checked for ID tokens (`aud == app_client_id`); for access tokens
    Cognito uses `client_id` claim instead of `aud`.
    """
    if not is_cognito_configured():
        raise TokenError("Cognito is not configured on the server")

    headers = jwt.get_unverified_headers(token)
    kid = headers.get("kid")
    if not kid:
        raise TokenError("Token has no 'kid' header")

    keys = _jwks_keys()
    matching = next((k for k in keys if k.get("kid") == kid), None)
    if matching is None:
        # Could be a key rotation — refresh once
        with _jwks_lock:
            _jwks_cache["fetched_at"] = 0
        keys = _jwks_keys()
        matching = next((k for k in keys if k.get("kid") == kid), None)
    if matching is None:
        raise TokenError(f"No matching JWK for kid={kid}")

    public_key = jwk.construct(matching)
    message, signature_b64 = token.rsplit(".", 1)
    if not public_key.verify(message.encode("utf-8"), base64url_decode(signature_b64.encode("utf-8"))):
        raise TokenError("Token signature did not verify")

    # Decode without re-verifying signature (already done above) but with
    # issuer/audience/expiry checks. python-jose can do this in one go too;
    # here we verify manually so we can support both ID and access tokens.
    claims = jwt.get_unverified_claims(token)

    # Expiry
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or time.time() > float(exp):
        raise TokenError("Token expired")

    # Issuer
    if claims.get("iss") != _issuer():
        raise TokenError("Token issuer mismatch")

    # Audience: ID tokens have `aud`; access tokens have `client_id`.
    cfg_aud = _cfg()["app_client_id"]
    if cfg_aud:
        token_use = claims.get("token_use")
        if token_use == "id":
            if claims.get("aud") != cfg_aud:
                raise TokenError("Token audience mismatch (id token)")
        elif token_use == "access":
            if claims.get("client_id") != cfg_aud:
                raise TokenError("Token audience mismatch (access token)")
        else:
            raise TokenError(f"Unexpected token_use={token_use!r}")

    return claims


# --- user resolution ----------------------------------------------------

def find_or_create_user_for_claims(session: Session, claims: dict[str, Any]) -> User:
    """Resolve (or create) a local `User` row from validated JWT claims."""
    sub = str(claims.get("sub") or "").strip()
    email = str(claims.get("email") or "").strip().lower()
    name = (claims.get("name") or claims.get("cognito:username") or "").strip() or None

    if not sub:
        raise TokenError("Token missing 'sub' claim")

    # 1) match on cognito_sub
    user = session.exec(select(User).where(User.cognito_sub == sub)).first()
    if user:
        # Backfill email/name if changed (or were missing)
        if email and user.email != email:
            user.email = email
        if name and user.name != name:
            user.name = name
        user.updated_at = utcnow()
        session.add(user)
        session.commit()
        session.refresh(user)
        return user

    # 2) match on email (older account that pre-dates Cognito) — link it
    if email:
        user = session.exec(select(User).where(User.email == email)).first()
        if user:
            user.cognito_sub = sub
            if name and not user.name:
                user.name = name
            user.updated_at = utcnow()
            session.add(user)
            session.commit()
            session.refresh(user)
            return user

    # 3) create a new user
    if not email:
        # Cognito should always provide email since we configured it as a
        # required attribute; but defend against malformed tokens.
        raise TokenError("Token missing 'email' claim — cannot create user")

    user = User(
        email=email,
        cognito_sub=sub,
        name=name,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user
