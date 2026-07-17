from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.admin_models import SystemLog
from backend.database import Base, get_db
from backend.main import app


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def broken_get_db():
    class Boom:
        def __getattr__(self, name):
            raise RuntimeError("boom-test-internal")

    yield Boom()


class GlobalExceptionHandlerTest(unittest.TestCase):
    """未捕获异常必须返回统一 JSON 500，不泄露堆栈，并落 system_logs。"""

    def setUp(self) -> None:
        self.session_factory = make_session_factory()
        app.dependency_overrides[get_db] = broken_get_db
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_unhandled_error_returns_uniform_json_500(self) -> None:
        with patch("backend.main.SessionLocal", self.session_factory):
            response = self.client.get("/api/events")

        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertEqual(body["code"], 500)
        self.assertIn("服务器内部错误", body["message"])
        self.assertIsNone(body["data"])
        # 不把异常类型/堆栈泄露给前端
        self.assertNotIn("boom-test-internal", response.text)
        self.assertNotIn("RuntimeError", response.text)

    def test_unhandled_error_is_recorded_to_system_logs(self) -> None:
        with patch("backend.main.SessionLocal", self.session_factory):
            self.client.get("/api/events")

        db = self.session_factory()
        rows = db.query(SystemLog).filter(SystemLog.level == "error").all()
        db.close()
        self.assertEqual(len(rows), 1)
        self.assertIn("RuntimeError", rows[0].message)

    def test_http_exceptions_are_not_swallowed(self) -> None:
        # 业务 HTTPException（如 401）不应被全局兜底改写成 500。
        # 用内存库替换 get_db：本测试验证的是"异常处理器不吞 HTTPException"，
        # 不应依赖真实数据库可达（曾因共享 RDS 抖动假红，违反零网络纪律）。
        def good_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = good_db
        response = self.client.post("/api/auth/login", json={"username": "x", "password": "y"})

        self.assertEqual(response.status_code, 401)


class LoggingSetupTest(unittest.TestCase):
    def test_setup_is_idempotent_and_adds_file_handler(self) -> None:
        from backend.logging_setup import setup_logging

        setup_logging()
        setup_logging()

        root = logging.getLogger("campus")
        file_handlers = [
            h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        self.assertEqual(len(file_handlers), 1)


if __name__ == "__main__":
    unittest.main()
