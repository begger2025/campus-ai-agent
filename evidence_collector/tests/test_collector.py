"""Deterministic retrieval-pipeline tests; no provider makes a network call."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine

from evidence_collector.database import create_session_factory, init_database
from evidence_collector.models import EvidenceDocument, EvidenceItem, EvidenceQuery
from evidence_collector.services.collector import EvidenceCollector
from evidence_collector.services.providers import SearchHit


class FakeProvider:
    def __init__(self, provider_id: str, hits: list[SearchHit] | None = None, error: Exception | None = None):
        self.provider_id = provider_id
        self.hits = hits or []
        self.error = error
        self.requests = []

    async def search(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return list(self.hits)


class FakeRegistry:
    def __init__(self, providers):
        self.providers = providers

    @property
    def enabled_provider_ids(self):
        return tuple(self.providers)

    def get(self, provider_id):
        return self.providers[provider_id]


class CollectorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}
        )
        init_database(self.engine)
        self.session = create_session_factory(self.engine)()

        self.official = SearchHit(
            url="https://www.sysu.edu.cn/notice?id=7&utm_source=feed",
            title="中山大学关于校园服务的通知",
            quote="中山大学发布校园公共服务安排。",
            source_type="official",
        )
        self.duplicate = SearchHit(
            url="https://www.sysu.edu.cn/notice?id=7#fragment",
            title="中山大学关于校园服务的通知（转载）",
            quote="中山大学发布校园公共服务安排。",
            source_type="official",
        )
        self.out_scope = SearchHit(
            url="https://example.invalid/post",
            title="其他高校通知",
            quote="这条信息没有明确的中山大学实体。",
            source_type="web",
        )
        self.review = SearchHit(
            url="https://untrusted.example/news",
            title="校园新闻",
            quote="Sun Yat-sen University announced a campus update.",
            source_type="news",
        )

    async def asyncTearDown(self):
        self.session.close()
        self.engine.dispose()

    async def test_multi_provider_scope_and_run_completion(self):
        first = FakeProvider("deepseek", [self.official, self.out_scope, self.review])
        second = FakeProvider("qwen", [self.duplicate])
        registry = FakeRegistry({"deepseek": first, "qwen": second})
        collector = EvidenceCollector(self.session, registry)

        run = await collector.collect(
            "校园公共信息",
            ["宿舍通知"],
            provider_ids=["deepseek", "qwen"],
        )

        self.assertEqual(run.status, "completed")
        self.assertEqual(len(self.session.query(EvidenceQuery).all()), 2)
        self.assertEqual(self.session.query(EvidenceDocument).count(), 3)
        self.assertEqual(self.session.query(EvidenceItem).count(), 3)
        decisions = {
            item.scope_decision
            for item in self.session.query(EvidenceItem).all()
        }
        self.assertEqual(decisions, {"in_scope", "out_of_scope", "needs_review"})
        self.assertIn("中山大学", first.requests[0].query)
        self.assertIn("SYSU", first.requests[0].query)

    async def test_duplicate_url_is_deduplicated_across_providers(self):
        first = FakeProvider("deepseek", [self.official])
        second = FakeProvider("qwen", [self.duplicate])
        collector = EvidenceCollector(
            self.session,
            FakeRegistry({"deepseek": first, "qwen": second}),
        )

        await collector.collect("topic", ["q"], provider_ids=["deepseek", "qwen"])
        self.assertEqual(self.session.query(EvidenceDocument).count(), 1)
        self.assertEqual(self.session.query(EvidenceItem).count(), 1)

    async def test_provider_failure_marks_query_and_run_and_redacts_error(self):
        failing = FakeProvider(
            "deepseek", error=RuntimeError("api_key=supersecret token=secret-token")
        )
        collector = EvidenceCollector(self.session, FakeRegistry({"deepseek": failing}))

        run = await collector.collect("topic", ["q"], provider_ids=["deepseek"])

        query = self.session.query(EvidenceQuery).one()
        self.assertEqual(run.status, "failed")
        self.assertEqual(query.status, "failed")
        self.assertNotIn("supersecret", query.error or "")
        self.assertNotIn("secret-token", query.error or "")
        self.assertIn("redacted", query.error or "")

    async def test_existing_global_document_can_be_reused_by_a_later_run(self):
        provider = FakeProvider("deepseek", [self.official])
        collector = EvidenceCollector(self.session, FakeRegistry({"deepseek": provider}))
        await collector.collect("first", ["q"], provider_ids=["deepseek"])
        await collector.collect("second", ["q"], provider_ids=["deepseek"])

        self.assertEqual(self.session.query(EvidenceDocument).count(), 1)
        self.assertEqual(self.session.query(EvidenceItem).count(), 2)


if __name__ == "__main__":
    unittest.main()
