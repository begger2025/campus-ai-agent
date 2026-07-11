"""Deterministic retrieval-pipeline tests; no provider makes a network call."""

from __future__ import annotations

import asyncio
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models_evidence import EvidenceDocument, EvidenceItem, EvidenceQuery
from backend.services.evidence.canonicalize import canonical_url_hash, canonicalize_url
from backend.services.evidence.collector import EvidenceCollector, sanitize_error
from backend.services.evidence.providers import SearchHit
from backend.services.evidence.scope_policy import assess_scope


def make_evidence_session(engine):
    """Create the backend schema and return a session over the given engine."""

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


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


class QualityScope:
    decision = "in_scope"
    reasons = ["test scope"]
    quality_score = 0.87


class Gate:
    """Release only once ``expected`` providers are inside ``search`` at once.

    A sequential fan-out never reaches the second arrival, so the first waiter
    times out and the query is recorded as failed; a concurrent fan-out passes.
    """

    def __init__(self, expected: int) -> None:
        self.expected = expected
        self.arrived = 0
        self.opened = asyncio.Event()
        self.max_concurrent = 0

    async def pass_through(self) -> None:
        self.arrived += 1
        self.max_concurrent = max(self.max_concurrent, self.arrived)
        if self.arrived >= self.expected:
            self.opened.set()
        await asyncio.wait_for(self.opened.wait(), timeout=2)


class GatedProvider:
    def __init__(self, provider_id: str, gate: Gate, hits: list[SearchHit] | None = None):
        self.provider_id = provider_id
        self.gate = gate
        self.hits = hits or []

    async def search(self, request):
        await self.gate.pass_through()
        return list(self.hits)


class CollectorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}
        )
        self.session = make_evidence_session(self.engine)

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

    def test_sanitize_error_redacts_bearer_and_query_credentials(self):
        rendered = sanitize_error(
            "Authorization Bearer top-secret; https://api.invalid/search?api_key=url-secret"
        )
        self.assertNotIn("top-secret", rendered)
        self.assertNotIn("url-secret", rendered)
        self.assertIn("redacted", rendered)

    async def test_factory_with_default_expiration_returns_readable_run(self):
        provider = FakeProvider("deepseek", [self.official])
        collector = EvidenceCollector(
            sessionmaker(bind=self.engine),
            FakeRegistry({"deepseek": provider}),
        )

        run = await collector.collect("topic", ["q"], provider_ids=["deepseek"])

        self.assertEqual(run.status, "completed")
        self.assertIsNotNone(run.completed_at)

    async def test_bad_provider_and_request_are_audited_per_query(self):
        provider = FakeProvider("deepseek", [self.official])
        collector = EvidenceCollector(
            self.session,
            FakeRegistry({"deepseek": provider}),
        )

        run = await collector.collect(
            "topic",
            [
                {"provider": "not-a-provider", "query": "q"},
                {"provider": "deepseek", "query": "q", "max_results": 0},
            ],
            provider_ids=["deepseek"],
        )

        self.assertEqual(run.status, "failed")
        queries = self.session.query(EvidenceQuery).order_by(EvidenceQuery.id).all()
        self.assertEqual(len(queries), 2)
        self.assertTrue(all(query.status == "failed" for query in queries))
        self.assertTrue(all(query.error for query in queries))

    async def test_scope_quality_score_is_persisted(self):
        provider = FakeProvider("deepseek", [self.official])
        collector = EvidenceCollector(
            self.session,
            FakeRegistry({"deepseek": provider}),
            scope_assessor=lambda *_args: QualityScope(),
        )

        await collector.collect("topic", ["q"], provider_ids=["deepseek"])

        item = self.session.query(EvidenceItem).one()
        self.assertEqual(item.quality_score, 0.87)

    async def test_existing_global_document_can_be_reused_by_a_later_run(self):
        provider = FakeProvider("deepseek", [self.official])
        collector = EvidenceCollector(self.session, FakeRegistry({"deepseek": provider}))
        await collector.collect("first", ["q"], provider_ids=["deepseek"])
        await collector.collect("second", ["q"], provider_ids=["deepseek"])

        self.assertEqual(self.session.query(EvidenceDocument).count(), 1)
        self.assertEqual(self.session.query(EvidenceItem).count(), 2)

    async def test_concurrent_document_insert_is_recovered_not_fatal(self):
        """A racing worker committing the same canonical URL must not kill the run.

        ``collect`` does SELECT-then-INSERT on ``evidence_documents``.  The
        injected ``scope_assessor`` is invoked inside exactly that window, so it
        is used here to make the conflicting row genuinely exist in the database
        before the collector's own INSERT reaches the UNIQUE constraint.  The
        resulting ``IntegrityError`` is real, raised by the real constraint.
        """

        canonical = canonicalize_url(str(self.official.url))
        digest = canonical_url_hash(canonical)
        raced: list[EvidenceDocument] = []

        def racing_assessor(source_type, domain, title, quote):
            if not raced:
                winner = EvidenceDocument(
                    source_type="official",
                    source_url=str(self.official.url),
                    canonical_url=canonical,
                    canonical_url_hash=digest,
                    domain=domain,
                    title="raced in by a concurrent worker",
                    evidence_quote="另一台机器先写入了同一条文档。",
                )
                self.session.add(winner)
                self.session.flush()
                raced.append(winner)
            return assess_scope(source_type, domain, title, quote)

        provider = FakeProvider("deepseek", [self.official])
        collector = EvidenceCollector(
            self.session,
            FakeRegistry({"deepseek": provider}),
            scope_assessor=racing_assessor,
        )

        run = await collector.collect("topic", ["q"], provider_ids=["deepseek"])

        self.assertEqual(run.status, "completed")
        query = self.session.query(EvidenceQuery).one()
        self.assertEqual(query.status, "completed")
        self.assertIsNone(query.error)
        # The row the other worker wrote is reused; no duplicate is created and
        # the hit is still attributed to this run.
        self.assertEqual(self.session.query(EvidenceDocument).count(), 1)
        item = self.session.query(EvidenceItem).one()
        self.assertEqual(item.document_id, raced[0].id)
        self.assertEqual(item.canonical_url_hash, digest)

    async def test_provider_queries_run_concurrently(self):
        gate = Gate(expected=3)
        providers = {
            "deepseek": GatedProvider("deepseek", gate, [self.official]),
            "qwen": GatedProvider("qwen", gate, [self.review]),
            "glm": GatedProvider("glm", gate, [self.out_scope]),
        }
        collector = EvidenceCollector(self.session, FakeRegistry(providers))

        run = await collector.collect(
            "topic", ["q"], provider_ids=["deepseek", "qwen", "glm"]
        )

        self.assertEqual(gate.max_concurrent, 3)
        self.assertEqual(run.status, "completed")
        queries = self.session.query(EvidenceQuery).all()
        self.assertEqual(len(queries), 3)
        self.assertTrue(all(query.status == "completed" for query in queries))
        self.assertEqual(self.session.query(EvidenceItem).count(), 3)

    async def test_partial_run_status_when_only_some_providers_fail(self):
        working = FakeProvider("deepseek", [self.official])
        failing = FakeProvider("qwen", error=RuntimeError("api_key=supersecret"))
        collector = EvidenceCollector(
            self.session, FakeRegistry({"deepseek": working, "qwen": failing})
        )

        run = await collector.collect("topic", ["q"], provider_ids=["deepseek", "qwen"])

        self.assertEqual(run.status, "partial")
        self.assertIn("1 of 2", run.sanitized_error_summary or "")
        statuses = {
            query.provider: query.status
            for query in self.session.query(EvidenceQuery).all()
        }
        self.assertEqual(statuses, {"deepseek": "completed", "qwen": "failed"})
        failed = (
            self.session.query(EvidenceQuery)
            .filter(EvidenceQuery.provider == "qwen")
            .one()
        )
        self.assertNotIn("supersecret", failed.error or "")
        self.assertIn("redacted", failed.error or "")
        # The surviving provider's evidence is still persisted.
        self.assertEqual(self.session.query(EvidenceItem).count(), 1)

    async def test_concurrent_fanout_keeps_dedup_deterministic(self):
        # Both providers return the same page; the slower one must not win the
        # dedup race.  Persistence order follows the query spec order.
        slow = FakeProvider("deepseek", [self.official])
        fast = FakeProvider("qwen", [self.duplicate])

        original_search = slow.search

        async def delayed_search(request):
            await asyncio.sleep(0.05)
            return await original_search(request)

        slow.search = delayed_search
        collector = EvidenceCollector(
            self.session, FakeRegistry({"deepseek": slow, "qwen": fast})
        )

        run = await collector.collect("topic", ["q"], provider_ids=["deepseek", "qwen"])

        self.assertEqual(run.status, "completed")
        self.assertEqual(self.session.query(EvidenceDocument).count(), 1)
        item = self.session.query(EvidenceItem).one()
        self.assertEqual(item.retrieval_provider, "deepseek")


if __name__ == "__main__":
    unittest.main()
