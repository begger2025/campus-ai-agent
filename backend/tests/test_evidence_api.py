"""管理端证据采集接口：鉴权、审核/验证、交付写入 raw_posts。

零网络：采集器用依赖覆盖注入假实现，不触碰任何 provider。
"""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.main import app
from backend.models import RawPost
from backend.models_evidence import EvidenceDocument, EvidenceItem, EvidenceQuery, EvidenceRun
from backend.routers.admin_evidence import get_evidence_collector, get_evidence_verifier
from backend.services.auth_service import create_access_token, ensure_user
from backend.services.evidence.canonicalize import canonical_url_hash, canonicalize_url
from backend.services.evidence.config import SUPPORTED_PROVIDER_IDS
from backend.services.evidence.verification import FETCH_VERIFICATION_METHOD, UrlFetchVerifier
from backend.tests.test_evidence_verification import FakeHttpClient, FakeResponse


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


class FakeCollector:
    """替身采集器：不发网络请求，直接落一个 completed run + 一条 in_scope 证据。"""

    def __init__(self, session_factory):
        self._session_factory = session_factory
        self.calls: list[dict] = []

    async def collect(self, topic, queries, *, provider_ids=None, creator=None, **kwargs):
        self.calls.append(
            {"topic": topic, "queries": queries, "provider_ids": provider_ids, "creator": creator}
        )
        db = self._session_factory()
        try:
            run = EvidenceRun(topic=topic, status="completed", creator=creator, duration_ms=12)
            db.add(run)
            db.flush()
            db.add(
                EvidenceQuery(
                    run_id=run.id,
                    provider="deepseek",
                    model="deepseek-test",
                    prompt_version="v1",
                    query_text=str(queries),
                    status="completed",
                )
            )
            db.commit()
            db.refresh(run)
            return run
        finally:
            db.close()


class EvidenceApiTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.session_factory = make_session_factory()
        db = self.session_factory()
        ensure_user(db, username="boss", password="admin-pass-8", role="admin")
        ensure_user(db, username="member", password="member-pass-8", role="user")
        db.commit()
        db.close()

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        self.collector = FakeCollector(self.session_factory)
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_evidence_collector] = lambda: self.collector
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def _headers(self, username: str, role: str) -> dict:
        db = self.session_factory()
        user = ensure_user(db, username=username, password="x" * 8, role=role)
        db.commit()
        token = create_access_token(user)
        db.close()
        return {"Authorization": f"Bearer {token}"}

    def admin_headers(self) -> dict:
        return self._headers("boss", "admin")

    def user_headers(self) -> dict:
        return self._headers("member", "user")

    def seed_item(self, url: str = "https://www.sysu.edu.cn/notice/1", scope: str = "in_scope") -> tuple[int, int]:
        """写入一个 run + 一条证据，返回 (run_id, item_id)。"""
        db = self.session_factory()
        try:
            run = db.query(EvidenceRun).first()
            if run is None:
                run = EvidenceRun(topic="中大校园通知", status="completed")
                db.add(run)
                db.flush()
            canonical = canonicalize_url(url)
            digest = canonical_url_hash(canonical)
            document = EvidenceDocument(
                source_type="official",
                source_url=url,
                canonical_url=canonical,
                canonical_url_hash=digest,
                domain="www.sysu.edu.cn",
                title="中大发布校园通知",
                publisher="中山大学",
                evidence_quote="中山大学发布了一则校园通知。",
            )
            db.add(document)
            db.flush()
            item = EvidenceItem(
                run_id=run.id,
                document_id=document.id,
                source_url=url,
                canonical_url=canonical,
                canonical_url_hash=digest,
                source_domain="www.sysu.edu.cn",
                source_type="official",
                evidence_quote=document.evidence_quote,
                retrieval_provider="deepseek",
                retrieval_model="deepseek-test",
                prompt_version="v1",
                scope_decision=scope,
            )
            db.add(item)
            db.commit()
            return run.id, item.id
        finally:
            db.close()

    def approve(self, item_id: int) -> None:
        headers = self.admin_headers()
        self.client.post(
            f"/api/admin/evidence/items/{item_id}/verify",
            json={"method": "manual", "status": "verified"},
            headers=headers,
        )
        self.client.patch(
            f"/api/admin/evidence/items/{item_id}/review",
            json={"status": "approved"},
            headers=headers,
        )


class EvidenceApiAuthTest(EvidenceApiTestBase):
    ENDPOINTS = (
        ("get", "/api/admin/evidence/runs"),
        ("get", "/api/admin/evidence/runs/1"),
        ("get", "/api/admin/evidence/items"),
        ("get", "/api/admin/evidence/providers"),
        ("post", "/api/admin/evidence/runs"),
        ("post", "/api/admin/evidence/runs/1/deliver"),
        ("post", "/api/admin/evidence/items/1/verify"),
        ("patch", "/api/admin/evidence/items/1/review"),
    )

    def _call(self, method: str, path: str, headers: dict | None = None):
        kwargs: dict = {"headers": headers} if headers else {}
        if method != "get":
            kwargs["json"] = {}
        return getattr(self.client, method)(path, **kwargs)

    def test_endpoints_reject_anonymous(self) -> None:
        for method, path in self.ENDPOINTS:
            response = self._call(method, path)
            self.assertEqual(response.status_code, 401, f"{method} {path}")

    def test_endpoints_reject_non_admin(self) -> None:
        headers = self.user_headers()
        for method, path in self.ENDPOINTS:
            response = self._call(method, path, headers)
            self.assertEqual(response.status_code, 403, f"{method} {path}")


class EvidenceRunApiTest(EvidenceApiTestBase):
    def test_start_run_awaits_async_collect(self) -> None:
        response = self.client.post(
            "/api/admin/evidence/runs",
            json={"topic": "中大食堂", "queries": ["中山大学 食堂"], "provider_ids": ["deepseek"]},
            headers=self.admin_headers(),
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["topic"], "中大食堂")
        self.assertEqual(data["status"], "completed")
        self.assertEqual(self.collector.calls[0]["topic"], "中大食堂")
        self.assertEqual(self.collector.calls[0]["provider_ids"], ["deepseek"])
        # 采集人取当前管理员，不由请求体伪造
        self.assertEqual(self.collector.calls[0]["creator"], "boss")

    def test_blank_topic_is_rejected(self) -> None:
        response = self.client.post(
            "/api/admin/evidence/runs",
            json={"topic": "   ", "queries": ["x"]},
            headers=self.admin_headers(),
        )
        self.assertEqual(response.status_code, 422)

    def test_list_runs_is_newest_first_and_paginated(self) -> None:
        self.seed_item()

        response = self.client.get("/api/admin/evidence/runs", headers=self.admin_headers())

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["page"], 1)
        row = data["items"][0]
        self.assertEqual(row["topic"], "中大校园通知")
        self.assertEqual(row["item_count"], 1)
        self.assertIn("created_at", row)

    def test_run_detail_includes_queries(self) -> None:
        run_id, _ = self.seed_item()
        db = self.session_factory()
        db.add(
            EvidenceQuery(
                run_id=run_id,
                provider="glm",
                model="glm-test",
                prompt_version="v1",
                query_text="中山大学 通知",
                status="failed",
                error="provider down",
            )
        )
        db.commit()
        db.close()

        response = self.client.get(
            f"/api/admin/evidence/runs/{run_id}", headers=self.admin_headers()
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["id"], run_id)
        query = data["queries"][0]
        self.assertEqual(query["provider"], "glm")
        self.assertEqual(query["model"], "glm-test")
        self.assertEqual(query["status"], "failed")
        self.assertEqual(query["error"], "provider down")

    def test_unknown_run_is_404(self) -> None:
        response = self.client.get("/api/admin/evidence/runs/9999", headers=self.admin_headers())
        self.assertEqual(response.status_code, 404)


class EvidenceProviderApiTest(EvidenceApiTestBase):
    """provider 可用性接口：只暴露 id + enabled，绝不外泄任何凭据。"""

    SECRETS = {
        "EVIDENCE_DEEPSEEK_API_KEY": "sk-deepseek-super-secret",
        "EVIDENCE_DEEPSEEK_WEB_SEARCH_ENABLED": "true",
        "EVIDENCE_DEEPSEEK_MODEL": "deepseek-chat",
        "EVIDENCE_DEEPSEEK_BASE_URL": "https://api.deepseek.internal/v1",
        "EVIDENCE_GLM_API_KEY": "sk-glm-super-secret",
        "EVIDENCE_GLM_WEB_SEARCH_ENABLED": "false",
    }

    def _get(self, environ: dict) -> dict:
        cleared = {
            key: "" for key in os.environ if key.startswith("EVIDENCE_")
        }
        with mock.patch.dict(os.environ, {**cleared, **environ}, clear=False):
            response = self.client.get(
                "/api/admin/evidence/providers", headers=self.admin_headers()
            )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_lists_every_supported_provider_with_its_enabled_flag(self) -> None:
        data = self._get(self.SECRETS)["data"]

        listed = {row["provider_id"]: row["enabled"] for row in data["providers"]}
        self.assertEqual(sorted(listed), sorted(SUPPORTED_PROVIDER_IDS))
        # 有 key 且 WEB_SEARCH_ENABLED=true 才算可用
        self.assertTrue(listed["deepseek"])
        # 有 key 但未开联网检索 → 不可用
        self.assertFalse(listed["glm"])
        self.assertFalse(listed["kimi"])
        self.assertEqual(data["enabled_provider_ids"], ["deepseek"])
        # 每行只有 id 与 enabled 两个字段，不给凭据留位置
        for row in data["providers"]:
            self.assertEqual(set(row), {"provider_id", "enabled"})

    def test_no_credential_material_leaks_into_the_response(self) -> None:
        body = json.dumps(self._get(self.SECRETS), ensure_ascii=False)

        for secret in self.SECRETS.values():
            if secret in ("true", "false"):
                continue
            self.assertNotIn(secret, body)
        for fragment in ("api_key", "apiKey", "base_url", "sk-", "deepseek.internal"):
            self.assertNotIn(fragment, body)

    def test_no_configured_provider_yields_an_empty_enabled_list(self) -> None:
        data = self._get({})["data"]

        self.assertEqual(data["enabled_provider_ids"], [])
        self.assertEqual(len(data["providers"]), len(SUPPORTED_PROVIDER_IDS))
        self.assertTrue(all(row["enabled"] is False for row in data["providers"]))


class EvidenceItemApiTest(EvidenceApiTestBase):
    def test_list_items_exposes_reviewer_fields(self) -> None:
        run_id, item_id = self.seed_item()

        response = self.client.get(
            "/api/admin/evidence/items", params={"run_id": run_id}, headers=self.admin_headers()
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["total"], 1)
        row = data["items"][0]
        for field in (
            "source_url",
            "canonical_url",
            "source_domain",
            "title",
            "evidence_quote",
            "retrieval_provider",
            "retrieval_model",
            "scope_decision",
            "scope_reasons",
        ):
            self.assertIn(field, row)
        self.assertEqual(row["id"], item_id)
        self.assertEqual(row["title"], "中大发布校园通知")
        self.assertEqual(row["scope_decision"], "in_scope")

    def test_items_filterable_by_status(self) -> None:
        self.seed_item()
        self.seed_item("https://weibo.com/x/2", scope="out_of_scope")

        response = self.client.get(
            "/api/admin/evidence/items",
            params={"scope_decision": "out_of_scope"},
            headers=self.admin_headers(),
        )

        data = response.json()["data"]
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["scope_decision"], "out_of_scope")

    def test_verify_endpoint_mutates_state(self) -> None:
        _, item_id = self.seed_item()

        response = self.client.post(
            f"/api/admin/evidence/items/{item_id}/verify",
            json={"method": "cross_source", "status": "verified", "reasons": ["官方来源"]},
            headers=self.admin_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["verification_status"], "verified")
        db = self.session_factory()
        self.assertEqual(db.get(EvidenceItem, item_id).verification_status, "verified")
        db.close()

    def test_verify_without_status_fetches_the_url_and_rejects_a_dead_link(self) -> None:
        _, item_id = self.seed_item()
        app.dependency_overrides[get_evidence_verifier] = lambda: UrlFetchVerifier(
            client=FakeHttpClient(FakeResponse(404, ""))
        )

        response = self.client.post(
            f"/api/admin/evidence/items/{item_id}/verify",
            json={},
            headers=self.admin_headers(),
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["verification_status"], "rejected")
        self.assertEqual(data["verification"]["method"], FETCH_VERIFICATION_METHOD)
        self.assertTrue(any("404" in reason for reason in data["verification"]["reasons"]))
        db = self.session_factory()
        self.assertEqual(db.get(EvidenceItem, item_id).verification_status, "rejected")
        db.close()

    def test_verify_by_fetch_verifies_a_live_page_and_exposes_the_reason(self) -> None:
        run_id, item_id = self.seed_item()
        app.dependency_overrides[get_evidence_verifier] = lambda: UrlFetchVerifier(
            client=FakeHttpClient(FakeResponse(200, "<p>中山大学发布了一则校园通知。</p>"))
        )

        response = self.client.post(
            f"/api/admin/evidence/items/{item_id}/verify",
            json={"method": FETCH_VERIFICATION_METHOD},
            headers=self.admin_headers(),
        )

        data = response.json()["data"]
        self.assertEqual(data["verification_status"], "verified")
        self.assertTrue(data["verification_reasons"])

        listed = self.client.get(
            "/api/admin/evidence/items", params={"run_id": run_id}, headers=self.admin_headers()
        ).json()["data"]["items"][0]
        self.assertEqual(listed["verification_status"], "verified")
        self.assertEqual(listed["verification_method"], FETCH_VERIFICATION_METHOD)
        self.assertTrue(listed["verification_reasons"])

    def test_verify_without_an_http_client_is_unavailable_not_a_silent_pass(self) -> None:
        _, item_id = self.seed_item()
        app.dependency_overrides[get_evidence_verifier] = lambda: UrlFetchVerifier()

        response = self.client.post(
            f"/api/admin/evidence/items/{item_id}/verify",
            json={},
            headers=self.admin_headers(),
        )

        self.assertEqual(response.status_code, 503)
        db = self.session_factory()
        self.assertEqual(db.get(EvidenceItem, item_id).verification_status, "pending")
        db.close()

    def test_review_endpoint_records_current_admin_as_reviewer(self) -> None:
        _, item_id = self.seed_item()
        self.client.post(
            f"/api/admin/evidence/items/{item_id}/verify",
            json={"method": "manual", "status": "verified"},
            headers=self.admin_headers(),
        )

        response = self.client.patch(
            f"/api/admin/evidence/items/{item_id}/review",
            json={"status": "approved", "note": "可用于交付"},
            headers=self.admin_headers(),
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["review_status"], "approved")
        self.assertEqual(data["reviewed_by"], "boss")

    def test_approving_unverified_item_is_rejected(self) -> None:
        _, item_id = self.seed_item()

        response = self.client.patch(
            f"/api/admin/evidence/items/{item_id}/review",
            json={"status": "approved"},
            headers=self.admin_headers(),
        )

        self.assertEqual(response.status_code, 400)
        db = self.session_factory()
        self.assertEqual(db.get(EvidenceItem, item_id).review_status, "pending")
        db.close()


class EvidenceDeliveryApiTest(EvidenceApiTestBase):
    def test_delivery_writes_eligible_evidence_into_raw_posts(self) -> None:
        run_id, item_id = self.seed_item()
        self.approve(item_id)

        response = self.client.post(
            f"/api/admin/evidence/runs/{run_id}/deliver", headers=self.admin_headers()
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["created"], 1)
        self.assertEqual(data["existing"], 0)
        db = self.session_factory()
        post = db.query(RawPost).one()
        db.close()
        self.assertEqual(post.platform, "web")
        self.assertEqual(post.source_table, "evidence_items")
        self.assertEqual(post.content, "中山大学发布了一则校园通知。")

    def test_delivery_skips_ineligible_items(self) -> None:
        run_id, item_id = self.seed_item()
        self.approve(item_id)
        # 第二条只验证不审核：不得进入 raw_posts
        _, pending_id = self.seed_item("https://www.sysu.edu.cn/notice/2")
        self.client.post(
            f"/api/admin/evidence/items/{pending_id}/verify",
            json={"method": "manual", "status": "verified"},
            headers=self.admin_headers(),
        )

        response = self.client.post(
            f"/api/admin/evidence/runs/{run_id}/deliver", headers=self.admin_headers()
        )

        self.assertEqual(response.json()["data"]["created"], 1)
        db = self.session_factory()
        posts = db.query(RawPost).all()
        db.close()
        self.assertEqual(len(posts), 1)

    def test_redelivery_creates_no_duplicate_raw_posts(self) -> None:
        run_id, item_id = self.seed_item()
        self.approve(item_id)
        headers = self.admin_headers()

        first = self.client.post(f"/api/admin/evidence/runs/{run_id}/deliver", headers=headers)
        second = self.client.post(f"/api/admin/evidence/runs/{run_id}/deliver", headers=headers)

        self.assertEqual(first.json()["data"]["created"], 1)
        self.assertEqual(second.json()["data"]["created"], 0)
        self.assertEqual(second.json()["data"]["existing"], 1)
        db = self.session_factory()
        self.assertEqual(db.query(RawPost).count(), 1)
        db.close()

    def test_delivery_without_eligible_evidence_is_400(self) -> None:
        run_id, _ = self.seed_item()

        response = self.client.post(
            f"/api/admin/evidence/runs/{run_id}/deliver", headers=self.admin_headers()
        )

        self.assertEqual(response.status_code, 400)
        db = self.session_factory()
        self.assertEqual(db.query(RawPost).count(), 0)
        db.close()


class RecordingAsyncClient:
    """替身 httpx.AsyncClient：只记录构造参数，绝不联网。"""

    instances: list[dict] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.trust_env = kwargs.get("trust_env")
        RecordingAsyncClient.instances.append(kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


class EvidenceHttpClientWiringTests(unittest.IsolatedAsyncioTestCase):
    """httpx 默认 trust_env=True，会读 Windows 注册表里的系统代理（Clash），
    让真实可达的中大官网连接超时。证据侧的两个客户端默认必须直连。"""

    def setUp(self) -> None:
        RecordingAsyncClient.instances = []
        self.session_factory = make_session_factory()

    async def _build_clients(self) -> list[dict]:
        from backend.routers import admin_evidence

        with mock.patch.object(admin_evidence.httpx, "AsyncClient", RecordingAsyncClient):
            db = self.session_factory()
            try:
                async for _collector in admin_evidence.get_evidence_collector(db):
                    break
            finally:
                db.close()
            async for _verifier in admin_evidence.get_evidence_verifier():
                break
        return RecordingAsyncClient.instances

    async def test_evidence_clients_ignore_the_system_proxy_by_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EVIDENCE_HTTP_TRUST_ENV", None)
            instances = await self._build_clients()
        self.assertEqual(len(instances), 2)
        for kwargs in instances:
            self.assertIs(kwargs.get("trust_env"), False)

    async def test_trust_env_can_be_switched_on_by_configuration(self) -> None:
        with mock.patch.dict(os.environ, {"EVIDENCE_HTTP_TRUST_ENV": "true"}):
            instances = await self._build_clients()
        self.assertEqual(len(instances), 2)
        for kwargs in instances:
            self.assertIs(kwargs.get("trust_env"), True)


if __name__ == "__main__":
    unittest.main()
