from __future__ import annotations

import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.main import app
from backend.services.auth_service import create_access_token, ensure_user


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


class UserApiTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.session_factory = make_session_factory()
        db = self.session_factory()
        self.admin = ensure_user(db, username="boss", password="admin-pass-8", role="admin")
        self.normal = ensure_user(db, username="member", password="member-pass-8", role="user")
        db.commit()
        self.admin_id, self.normal_id = self.admin.id, self.normal.id
        db.close()

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def auth(self, username: str, role: str, user_id: int) -> dict:
        db = self.session_factory()
        user = ensure_user(db, username=username, password="x" * 8, role=role)
        db.commit()
        token = create_access_token(user)
        db.close()
        return {"Authorization": f"Bearer {token}"}

    def admin_headers(self) -> dict:
        return self.auth("boss", "admin", self.admin_id)

    def user_headers(self) -> dict:
        return self.auth("member", "user", self.normal_id)


class RegisterTest(UserApiTestBase):
    def register(self, payload: dict):
        return self.client.post("/api/auth/register", json=payload)

    def test_register_creates_user_and_returns_token(self) -> None:
        response = self.register(
            {"username": "newbie", "password": "password-8", "display_name": "新同学"}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertTrue(data["access_token"])
        self.assertEqual(data["user"]["username"], "newbie")
        self.assertEqual(data["user"]["role"], "user")
        self.assertEqual(data["user"]["display_name"], "新同学")

    def test_registered_account_can_login(self) -> None:
        self.register({"username": "newbie", "password": "password-8"})

        response = self.client.post(
            "/api/auth/login", json={"username": "newbie", "password": "password-8"}
        )

        self.assertEqual(response.status_code, 200)

    def test_register_never_grants_admin_role(self) -> None:
        response = self.register(
            {"username": "sneaky", "password": "password-8", "role": "admin"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["user"]["role"], "user")

    def test_duplicate_username_is_409(self) -> None:
        self.register({"username": "newbie", "password": "password-8"})

        response = self.register({"username": "newbie", "password": "password-9"})

        self.assertEqual(response.status_code, 409)

    def test_short_password_is_422(self) -> None:
        response = self.register({"username": "newbie", "password": "short"})

        self.assertEqual(response.status_code, 422)

    def test_invalid_username_is_422(self) -> None:
        response = self.register({"username": "a b!", "password": "password-8"})

        self.assertEqual(response.status_code, 422)


class AdminUsersListTest(UserApiTestBase):
    def test_requires_admin(self) -> None:
        response = self.client.get("/api/admin/users", headers=self.user_headers())

        self.assertEqual(response.status_code, 403)

    def test_lists_users_with_pagination_shape(self) -> None:
        response = self.client.get("/api/admin/users", headers=self.admin_headers())

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertGreaterEqual(data["total"], 2)
        usernames = {item["username"] for item in data["items"]}
        self.assertIn("boss", usernames)
        self.assertIn("member", usernames)
        item = data["items"][0]
        for key in ("id", "username", "role", "display_name", "status", "created_at", "last_login_at"):
            self.assertIn(key, item)
        self.assertNotIn("password_hash", item)

    def test_keyword_filter(self) -> None:
        response = self.client.get(
            "/api/admin/users", params={"keyword": "memb"}, headers=self.admin_headers()
        )

        data = response.json()["data"]
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["username"], "member")


class AdminUserStatusTest(UserApiTestBase):
    def patch_status(self, user_id: int, status: str, headers: dict):
        return self.client.patch(
            f"/api/admin/users/{user_id}/status", json={"status": status}, headers=headers
        )

    def test_disable_then_login_is_403(self) -> None:
        response = self.patch_status(self.normal_id, "disabled", self.admin_headers())

        self.assertEqual(response.status_code, 200)
        login = self.client.post(
            "/api/auth/login", json={"username": "member", "password": "member-pass-8"}
        )
        self.assertEqual(login.status_code, 403)

    def test_reenable_restores_login(self) -> None:
        self.patch_status(self.normal_id, "disabled", self.admin_headers())
        self.patch_status(self.normal_id, "active", self.admin_headers())

        login = self.client.post(
            "/api/auth/login", json={"username": "member", "password": "member-pass-8"}
        )
        self.assertEqual(login.status_code, 200)

    def test_cannot_disable_self(self) -> None:
        response = self.patch_status(self.admin_id, "disabled", self.admin_headers())

        self.assertEqual(response.status_code, 400)

    def test_invalid_status_is_400(self) -> None:
        response = self.patch_status(self.normal_id, "banned", self.admin_headers())

        self.assertEqual(response.status_code, 400)

    def test_unknown_user_is_404(self) -> None:
        response = self.patch_status(99999, "disabled", self.admin_headers())

        self.assertEqual(response.status_code, 404)

    def test_normal_user_cannot_manage(self) -> None:
        response = self.patch_status(self.normal_id, "disabled", self.user_headers())

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
