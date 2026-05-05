"""Auth-side endpoints (currently just /me)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db.database import engine
from app.db.models import User


auth_router = APIRouter()


class MeResponse(BaseModel):
    id: int
    email: str
    name: Optional[str] = None
    cognito_sub: Optional[str] = None


@auth_router.get("/me", response_model=MeResponse)
def me(
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    """Return the currently-authenticated user.

    The middleware has already validated the Cognito token and set
    `X-User-Id` on the request scope; this endpoint just looks up the row.
    """
    uid = user_id if user_id is not None else x_user_id
    if uid is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    with Session(engine) as session:
        user = session.exec(select(User).where(User.id == uid)).first()
        if not user or not user.is_active:
            raise HTTPException(status_code=404, detail="User not found")
        return MeResponse(
            id=int(user.id),
            email=user.email,
            name=user.name,
            cognito_sub=user.cognito_sub,
        )
