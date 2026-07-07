from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.main import app
from backend.services import auth_service
from backend.services.auth_service import ensure_default_admin, ensure_user, verify_password


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


class AuthDbTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.session_factory = make_session_factory()

    def make_db(self):
        return self.session_factory()


class LoginApiTest(AuthDbTestBase):
    def setUp(self) -> None:
        super().setUp()
        db = self.make_db()
        ensure_user(db, username="alice", password="secret123", role="user", display_name="Alice")
        ensure_user(db, username="frozen", password="secret123", role="user", status="disabled")
        db.commit()
        db.close()

        def override_get_db():
            db = self.make_db()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def login(self, username: str, password: str):
        return self.client.post("/api/auth/login", json={"username": username, "password": password})

    def test_login_success_returns_token_and_user(self) -> None:
        response = self.login("alice", "secret123")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertTrue(data["access_token"])
        self.assertEqual(data["token_type"], "bearer")
        self.assertEqual(data["user"]["username"], "alice")
        self.assertEqual(data["user"]["role"], "user")

    def test_wrong_password_is_401(self) -> None:
        response = self.login("alice", "wrong-password")

        self.assertEqual(response.status_code, 401)

    def test_disabled_user_is_403(self) -> None:
        response = self.login("frozen", "secret123")

        self.assertEqual(response.status_code, 403)

    def test_me_roundtrip_with_issued_token(self) -> None:
        token = self.login("alice", "secret123").json()["data"]["access_token"]

        response = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["username"], "alice")


class JwtSecretHardeningTest(unittest.TestCase):
    """JWT 密钥治理：env 优先；未配置时不允许退回可预测的硬编码密钥。"""

    def test_env_secret_wins(self) -> None:
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "unit-test-secret"}):
            self.assertEqual(auth_service._jwt_secret(), "unit-test-secret")

    def test_missing_env_uses_random_process_secret(self) -> None:
        with patch.dict(os.environ, {"JWT_SECRET_KEY": ""}):
            first = auth_service._jwt_secret()
            second = auth_service._jwt_secret()

        # 进程内稳定（token 能自洽签验），但绝不能是公开仓库里的固定字符串。
        self.assertEqual(first, second)
        self.assertNotEqual(first, "campus-ai-agent-week2-dev-secret")
        self.assertGreaterEqual(len(first), 32)

    def test_token_roundtrip_without_env_secret(self) -> None:
        from backend.admin_models import User

        user = User(id=7, username="alice", role="user")
        with patch.dict(os.environ, {"JWT_SECRET_KEY": ""}):
            token = auth_service.create_access_token(user)
            payload = auth_service.decode_access_token(token)

        self.assertEqual(payload["sub"], "7")


class DefaultAdminHardeningTest(AuthDbTestBase):
    """默认管理员密码治理：env 优先；新库无配置时生成随机密码，绝不落回 admin123456。"""

    def test_fresh_admin_without_env_never_gets_known_default(self) -> None:
        db = self.make_db()
        with patch.dict(os.environ, {"ADMIN_PASSWORD": "", "ADMIN_USERNAME": ""}):
            admin = ensure_default_admin(db)

        self.assertFalse(verify_password("admin123456", admin.password_hash))
        self.assertTrue(admin.password_hash)
        db.close()

    def test_env_password_is_used_for_fresh_admin(self) -> None:
        db = self.make_db()
        with patch.dict(os.environ, {"ADMIN_PASSWORD": "env-pass-9", "ADMIN_USERNAME": ""}):
            admin = ensure_default_admin(db)

        self.assertTrue(verify_password("env-pass-9", admin.password_hash))
        db.close()

    def test_existing_admin_password_is_untouched(self) -> None:
        db = self.make_db()
        ensure_user(db, username="admin", password="original-pass", role="admin")
        db.commit()

        with patch.dict(os.environ, {"ADMIN_PASSWORD": "another-pass", "ADMIN_USERNAME": ""}):
            admin = ensure_default_admin(db)

        self.assertTrue(verify_password("original-pass", admin.password_hash))
        db.close()


class DemoUserTest(AuthDbTestBase):
    """演示普通用户：本地新库要有可登录的 user 角色账号；已有账号不被改密。"""

    def test_demo_user_created_with_env_password(self) -> None:
        db = self.make_db()
        with patch.dict(os.environ, {"DEMO_USER_PASSWORD": "demo-pass-1"}):
            user = auth_service.ensure_default_demo_user(db)

        self.assertEqual(user.username, "user")
        self.assertEqual(user.role, "user")
        self.assertTrue(verify_password("demo-pass-1", user.password_hash))
        db.close()

    def test_existing_demo_user_keeps_password_and_display_name(self) -> None:
        db = self.make_db()
        ensure_user(db, username="user", password="old-pass", role="user", display_name="测试用户")
        db.commit()

        with patch.dict(os.environ, {"DEMO_USER_PASSWORD": "new-pass"}):
            user = auth_service.ensure_default_demo_user(db)

        self.assertTrue(verify_password("old-pass", user.password_hash))
        self.assertEqual(user.display_name, "测试用户")
        db.close()

    def test_disabled_via_env(self) -> None:
        db = self.make_db()
        with patch.dict(os.environ, {"ENSURE_DEMO_USER": "false"}):
            user = auth_service.ensure_default_demo_user(db)

        self.assertIsNone(user)
        db.close()


if __name__ == "__main__":
    unittest.main()
