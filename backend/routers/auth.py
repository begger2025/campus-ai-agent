"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.admin_models import User
from backend.database import get_db
from backend.schemas import ok
from backend.services.auth_service import (
    authenticate_user,
    create_access_token,
    get_current_user,
    user_to_dict,
)

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, payload.username, payload.password)
    token = create_access_token(user)
    db.commit()
    return ok(
        {
            "access_token": token,
            "token_type": "bearer",
            "user": user_to_dict(user),
        }
    )


@router.get("/auth/me")
def me(current_user: User = Depends(get_current_user)):
    return ok(user_to_dict(current_user))
