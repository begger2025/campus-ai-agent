from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from backend.admin_models import User
from backend.main import app
from backend.services.auth_service import get_current_user


class UsageEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.addCleanup(app.dependency_overrides.clear)

    def login_as(self, role: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: User(
            id=1, username=f"test_{role}", role=role
        )

    def test_requires_token(self) -> None:
        response = self.client.get("/api/agent/public/usage")

        self.assertEqual(response.status_code, 401)

    def test_normal_user_is_forbidden(self) -> None:
        self.login_as("user")
        response = self.client.get("/api/agent/public/usage")

        self.assertEqual(response.status_code, 403)

    def test_admin_gets_usage_payload(self) -> None:
        self.login_as("admin")
        response = self.client.get("/api/agent/public/usage")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["code"], 0)
        data = body["data"]
        self.assertEqual(data["scope"], "process")
        self.assertIn("model", data)
        self.assertIn("llm_enabled", data)
        for key in ("calls", "cache_hits", "errors", "total_tokens", "duration_ms"):
            self.assertIn(key, data["usage"])
        self.assertIn("enabled", data["cache"])
        self.assertIn("entries", data["cache"])


if __name__ == "__main__":
    unittest.main()
