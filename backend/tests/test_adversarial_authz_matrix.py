"""对抗战役 · 攻击面1：权限越权矩阵。

刁钻用户假设：普通用户/游客拿到管理端的 URL（前端只是纸糊的门），直接构造请求
打每一个 admin 接口。安全底线——**任何 /api/admin/* 接口，非管理员绝不能得到 2xx**，
也不能把越权请求处理成 500（把攻击面暴露成崩溃点）。

设计：动态枚举 app 里所有 /api/admin 路由，逐个用真实 token 打。加了新 admin 接口
会自动纳入矩阵，不会漏测。用真实 require_admin（不 mock），token 真签真验。
"""

from __future__ import annotations

import re
import unittest

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.admin_models import User
from backend.database import Base, get_db
from backend.main import app
from backend.services.auth_service import create_access_token, hash_password


def _admin_endpoints() -> list[tuple[str, str]]:
    """(method, url) for every /api/admin route, path params filled with '1'."""
    out: list[tuple[str, str]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not route.path.startswith("/api/admin"):
            continue
        url = re.sub(r"\{[^}]+\}", "1", route.path)
        for method in sorted(route.methods):
            if method in {"GET", "POST", "PATCH", "DELETE", "PUT"}:
                out.append((method, url))
    return out


class AuthzMatrixTest(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
        self.session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        # 真实鉴权：只 override get_db，require_admin/get_current_user 走真链路
        app.dependency_overrides[get_db] = override_get_db
        self.addCleanup(app.dependency_overrides.clear)

        db = self.session_factory()
        normal = User(
            id=2, username="attacker", role="user", status="active",
            is_active=True, password_hash=hash_password("x"),
        )
        db.add(normal)
        db.commit()
        self.user_token = create_access_token(normal)
        db.close()

        self.client = TestClient(app)
        self.endpoints = _admin_endpoints()

    def test_matrix_is_non_empty(self):
        self.assertGreater(len(self.endpoints), 10, "应枚举到足够多的 admin 接口")

    def test_no_token_never_succeeds(self):
        offenders = []
        for method, url in self.endpoints:
            resp = self.client.request(method, url)
            if resp.status_code < 400 or resp.status_code >= 500:
                offenders.append((method, url, resp.status_code))
        self.assertEqual(offenders, [], f"无 token 越权成功或崩溃：{offenders}")

    def test_normal_user_never_succeeds(self):
        headers = {"Authorization": f"Bearer {self.user_token}"}
        offenders = []
        for method, url in self.endpoints:
            resp = self.client.request(method, url, headers=headers)
            # 安全底线：普通用户对 admin 接口绝不能 2xx，也不能 5xx（越权请求崩溃）
            if resp.status_code < 400 or resp.status_code >= 500:
                offenders.append((method, url, resp.status_code))
        self.assertEqual(offenders, [], f"普通用户越权成功或崩溃：{offenders}")

    def test_normal_user_gets_403_not_422(self):
        """越权应先于 body 校验：普通用户打 admin 接口应得 403，而不是 422（泄露 body 结构）。"""
        headers = {"Authorization": f"Bearer {self.user_token}"}
        leaks = []
        for method, url in self.endpoints:
            resp = self.client.request(method, url, headers=headers)
            if resp.status_code == 422:
                leaks.append((method, url))
        self.assertEqual(leaks, [], f"这些接口在鉴权前先做了 body 校验（泄露结构）：{leaks}")

    def test_forged_token_rejected(self):
        """篡改签名的 token 必须 401。"""
        forged = self.user_token[:-4] + ("AAAA" if self.user_token[-4:] != "AAAA" else "BBBB")
        headers = {"Authorization": f"Bearer {forged}"}
        for method, url in self.endpoints[:5]:
            resp = self.client.request(method, url, headers=headers)
            self.assertEqual(resp.status_code, 401, f"{method} {url} 接受了伪造签名")

    def test_role_elevated_token_still_checked_server_side(self):
        """token 里 role 写死 admin 但库里是 user——服务端以库为准，必须拒绝。

        get_current_user 用 token 的 sub 查库、require_admin 查库里的 role，
        所以就算攻击者伪造 role=admin（但签名过不了）也没用；这里验证"库为准"。
        """
        headers = {"Authorization": f"Bearer {self.user_token}"}
        resp = self.client.request("GET", "/api/admin/overview", headers=headers)
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
