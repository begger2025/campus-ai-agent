"""Minimal authentication and authorization helpers for the admin backend."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime
from typing import Any

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from backend.admin_models import User
from backend.database import get_db

HASH_ALGORITHM = "pbkdf2_sha256"
HASH_ITERATIONS = 120_000
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123456"
DEFAULT_JWT_SECRET = "campus-ai-agent-week2-dev-secret"


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("ascii"))


def _jwt_secret() -> str:
    return os.getenv("JWT_SECRET_KEY") or DEFAULT_JWT_SECRET


def _token_expire_seconds() -> int:
    try:
        minutes = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))
    except ValueError:
        minutes = 1440
    return max(minutes, 1) * 60


def hash_password(password: str, *, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        HASH_ITERATIONS,
    ).hex()
    return f"{HASH_ALGORITHM}${HASH_ITERATIONS}${salt}${digest}"


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    parts = password_hash.split("$")
    if len(parts) != 4 or parts[0] != HASH_ALGORITHM:
        return False
    _, raw_iterations, salt, expected = parts
    try:
        iterations = int(raw_iterations)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return hmac.compare_digest(digest, expected)


def user_to_dict(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "display_name": user.display_name,
        "status": user.status,
    }


def create_access_token(user: User) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "iat": now,
        "exp": now + _token_expire_seconds(),
    }
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = ".".join(
        [
            _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8")),
            _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
    )
    signature = hmac.new(
        _jwt_secret().encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        header_part, payload_part, signature_part = token.split(".")
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc

    signing_input = f"{header_part}.{payload_part}"
    expected_signature = hmac.new(
        _jwt_secret().encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        provided_signature = _b64url_decode(signature_part)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc
    if not hmac.compare_digest(expected_signature, provided_signature):
        raise HTTPException(status_code=401, detail="invalid token")

    try:
        payload = json.loads(_b64url_decode(payload_part).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc
    if int(payload.get("exp") or 0) < int(time.time()):
        raise HTTPException(status_code=401, detail="token expired")
    return payload


def ensure_user(
    db: Session,
    *,
    username: str,
    password: str,
    role: str,
    display_name: str = "",
    status: str = "active",
) -> User:
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            display_name=display_name or username,
            status=status,
            is_active=status == "active",
        )
        db.add(user)
        db.flush()
        return user

    user.role = role
    user.display_name = display_name or user.display_name or username
    user.status = status
    user.is_active = status == "active"
    if not user.password_hash:
        user.password_hash = hash_password(password)
    db.flush()
    return user


def ensure_default_admin(db: Session) -> User:
    username = os.getenv("ADMIN_USERNAME") or DEFAULT_ADMIN_USERNAME
    password = os.getenv("ADMIN_PASSWORD") or DEFAULT_ADMIN_PASSWORD
    display_name = os.getenv("ADMIN_DISPLAY_NAME") or "管理员"
    return ensure_user(
        db,
        username=username,
        password=password,
        role="admin",
        display_name=display_name,
        status="active",
    )


def authenticate_user(db: Session, username: str, password: str) -> User:
    user = db.query(User).filter(User.username == username).first()
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid username or password")
    if user.status != "active" or not user.is_active:
        raise HTTPException(status_code=403, detail="user disabled")
    user.last_login_at = datetime.utcnow()
    db.flush()
    return user


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization:
        raise HTTPException(status_code=401, detail="missing bearer token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="invalid authorization header")

    payload = decode_access_token(token)
    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == int(user_id)).first() if str(user_id).isdigit() else None
    if user is None:
        raise HTTPException(status_code=401, detail="user not found")
    if user.status != "active" or not user.is_active:
        raise HTTPException(status_code=403, detail="user disabled")
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return current_user
