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
DEFAULT_DEMO_USERNAME = "user"

# 未配置 JWT_SECRET_KEY 时的进程级随机密钥。绝不能退回可预测的硬编码字符串——
# 公开仓库里的固定密钥等于任何人都能伪造管理员 token。
_runtime_jwt_secret: str | None = None


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("ascii"))


def _jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET_KEY")
    if secret:
        return secret
    global _runtime_jwt_secret
    if _runtime_jwt_secret is None:
        _runtime_jwt_secret = secrets.token_urlsafe(48)
        print(
            "[auth] 警告：未配置 JWT_SECRET_KEY，已生成进程级随机密钥；"
            "服务重启后所有已登录用户需要重新登录。请在 .env 中配置 JWT_SECRET_KEY。"
        )
    return _runtime_jwt_secret


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


def _resolve_bootstrap_password(db: Session, *, username: str, env_key: str, label: str) -> str:
    """env 优先；账号已有密码则无需默认值；新建且未配置时生成随机密码并打印一次。"""

    password = os.getenv(env_key)
    if password:
        return password
    existing = db.query(User).filter(User.username == username).first()
    if existing is not None and existing.password_hash:
        return ""  # ensure_user 对已有密码的账号不会改密
    password = secrets.token_urlsafe(12)
    print(
        f"[auth] 未配置 {env_key}，已为新建{label} {username} 生成随机密码：{password}"
        "（仅本次打印，请立即记录或在 .env 中固定密码后重启）"
    )
    return password


def ensure_default_admin(db: Session) -> User:
    username = os.getenv("ADMIN_USERNAME") or DEFAULT_ADMIN_USERNAME
    password = _resolve_bootstrap_password(
        db, username=username, env_key="ADMIN_PASSWORD", label="管理员"
    )
    display_name = os.getenv("ADMIN_DISPLAY_NAME") or "管理员"
    return ensure_user(
        db,
        username=username,
        password=password,
        role="admin",
        display_name=display_name,
        status="active",
    )


def ensure_default_demo_user(db: Session) -> User | None:
    """本地新库保证有一个可登录的普通用户；ENSURE_DEMO_USER=false 可关闭。"""

    if (os.getenv("ENSURE_DEMO_USER") or "true").lower() in {"0", "false", "no"}:
        return None
    username = os.getenv("DEMO_USER_USERNAME") or DEFAULT_DEMO_USERNAME
    password = _resolve_bootstrap_password(
        db, username=username, env_key="DEMO_USER_PASSWORD", label="演示用户"
    )
    return ensure_user(
        db,
        username=username,
        password=password,
        role="user",
        display_name="",
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
