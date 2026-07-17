"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.admin_models import User
from backend.database import get_db
from backend.schemas import ok
from backend.services.auth_service import (
    authenticate_user,
    create_access_token,
    get_current_user,
    hash_password,
    user_to_dict,
)

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    # 角色不接受请求方指定：公开注册一律 user，防止提权。
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_\-]+$")
    password: str = Field(min_length=8, max_length=64)
    display_name: str = Field(default="", max_length=64)


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


@router.post("/auth/register")
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="用户名已被占用")
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role="user",
        display_name=payload.display_name or payload.username,
        status="active",
        is_active=True,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        # check-then-insert 竞态：两个并发同名注册都过了 .first() 判重，靠 username
        # 唯一约束兜底。裸抛会 500；翻成预期的 409。
        db.rollback()
        raise HTTPException(status_code=409, detail="用户名已被占用")
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
