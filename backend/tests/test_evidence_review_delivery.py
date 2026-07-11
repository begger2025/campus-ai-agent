"""Offline tests for verification, review, and delivery boundaries."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import RawPost
from backend.models_evidence import (
    EvidenceDeliveryBatch,
    EvidenceDocument,
    EvidenceItem,
    EvidenceRun,
    EvidenceVerification,
)
from backend.services.evidence.canonicalize import canonical_url_hash, canonicalize_url
from backend.services.evidence.review_delivery import (
    build_delivery_payload,
    create_delivery_batch,
    deliver_batch,
    mark_delivery,
    review_item,
    verify_item,
)


class EvidenceFixture(unittest.TestCase):
    """共享夹具：一条 in_scope 证据 + 一条 needs_review 证据，同属一个 run。"""

    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )()
        self.run = EvidenceRun(topic="SYSU campus notice", status="completed")
        self.session.add(self.run)
        self.session.flush()
        self.item = self._item("https://www.sysu.edu.cn/notice/1", "in_scope")
        self.pending = self._item("https://www.sysu.edu.cn/notice/2", "needs_review")
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def _item(self, url: str, scope: str) -> EvidenceItem:
        canonical = canonicalize_url(url)
        digest = canonical_url_hash(canonical)
        document = EvidenceDocument(
            source_type="official",
            source_url=url,
            canonical_url=canonical,
            canonical_url_hash=digest,
            domain="www.sysu.edu.cn",
            title="SYSU campus notice",
            publisher="Sun Yat-sen University",
            evidence_quote="Sun Yat-sen University issued a campus notice.",
        )
        self.session.add(document)
        self.session.flush()
        item = EvidenceItem(
            run_id=self.run.id,
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
        self.session.add(item)
        self.session.flush()
        return item


class ReviewDeliveryTests(EvidenceFixture):
    def test_verify_appends_audit_record_and_syncs_item(self):
        record = verify_item(
            self.session,
            self.item.id,
            method="cross_source",
            status="verified",
            reasons=["official source", "quote is attributable"],
            verification_version="verify-v1",
            model_version="judge-1",
        )
        self.assertEqual(record.status, "verified")
        self.assertEqual(self.item.verification_status, "verified")
        self.assertIsNotNone(record.verified_at)
        self.assertEqual(self.session.query(EvidenceVerification).count(), 1)

    def test_invalid_verification_status_does_not_write(self):
        with self.assertRaises(ValueError):
            verify_item(self.session, self.item.id, "manual", "unknown")
        self.session.rollback()
        self.assertEqual(self.session.query(EvidenceVerification).count(), 0)
        self.assertEqual(self.session.get(EvidenceItem, self.item.id).verification_status, "pending")

    def test_approval_requires_scope_and_verified_status(self):
        with self.assertRaises(ValueError):
            review_item(self.session, self.item.id, "reviewer", "approved")
        self.assertEqual(self.item.review_status, "pending")
        verify_item(self.session, self.item.id, "manual", "verified", "checked")
        review_item(self.session, self.item.id, "reviewer", "approved", "approved for delivery")
        self.assertEqual(self.item.review_status, "approved")
        self.assertEqual(self.item.reviewed_by, "reviewer")

    def test_delivery_payload_filters_unreviewed_items_and_omits_internal_fields(self):
        verify_item(self.session, self.item.id, "manual", "verified")
        review_item(self.session, self.item.id, "reviewer", "approved")
        payload = build_delivery_payload(self.session, self.run.id)
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["url"], self.item.canonical_url)
        self.assertNotIn("reviewed_by", payload["items"][0])
        self.assertNotIn("prompt_version", payload["items"][0])
        self.assertNotIn("source_url", payload["items"][0])

    def test_batch_requires_eligible_evidence_and_tracks_audit_times(self):
        with self.assertRaises(ValueError):
            create_delivery_batch(self.session, self.run.id, "approver")
        verify_item(self.session, self.item.id, "manual", "verified")
        review_item(self.session, self.item.id, "reviewer", "approved")
        batch = create_delivery_batch(self.session, self.run.id, "approver")
        self.assertEqual(batch.status, "pending")
        self.assertIsNotNone(batch.approved_at)
        delivered = mark_delivery(self.session, batch.id, "delivered")
        self.assertEqual(delivered.status, "delivered")
        self.assertIsNotNone(delivered.delivered_at)
        with self.assertRaises(ValueError):
            mark_delivery(self.session, batch.id, "failed", error="second attempt")

    def test_failed_delivery_error_is_bounded_and_redacted(self):
        verify_item(self.session, self.item.id, "manual", "verified")
        review_item(self.session, self.item.id, "reviewer", "approved")
        batch = create_delivery_batch(self.session, self.run.id, "approver")
        failed = mark_delivery(
            self.session,
            batch.id,
            "failed",
            error="api_key=super-secret token=hidden",
        )
        self.assertEqual(failed.status, "failed")
        self.assertNotIn("super-secret", failed.error or "")
        self.assertNotIn("hidden", failed.error or "")
        self.assertIn("redacted", failed.error or "")


class DeliverBatchTests(EvidenceFixture):
    """交付最后一公里：合格证据必须真正写入 raw_posts（舆情管线的入口表）。"""

    def _approve(self, item: EvidenceItem) -> None:
        verify_item(self.session, item.id, "manual", "verified")
        review_item(self.session, item.id, "reviewer", "approved")

    def test_delivery_inserts_eligible_evidence_into_raw_posts(self):
        self._approve(self.item)

        result = deliver_batch(self.session, self.run.id, "approver")

        self.assertEqual(result["created"], 1)
        self.assertEqual(result["existing"], 0)
        post = self.session.query(RawPost).one()
        self.assertEqual(post.platform, "web")
        self.assertEqual(post.external_id, self.item.canonical_url_hash)
        self.assertEqual(post.content, self.item.evidence_quote)
        self.assertEqual(post.url, self.item.canonical_url)
        self.assertEqual(post.raw_url, self.item.canonical_url)
        self.assertEqual(post.title, "SYSU campus notice")
        self.assertEqual(post.author, "Sun Yat-sen University")
        self.assertEqual(post.source_table, "evidence_items")
        self.assertEqual(post.source_raw_id, str(self.item.id))
        self.assertEqual(post.source_keyword, self.run.topic)
        self.assertIsNotNone(post.crawl_time)

    def test_delivery_only_moves_eligible_items(self):
        # self.pending 是 needs_review + 未验证 + 未审核：一条都不许进 raw_posts
        self._approve(self.item)

        deliver_batch(self.session, self.run.id, "approver")

        posts = self.session.query(RawPost).all()
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].external_id, self.item.canonical_url_hash)

    def test_redelivery_is_idempotent_and_creates_no_duplicate_raw_posts(self):
        self._approve(self.item)
        first = deliver_batch(self.session, self.run.id, "approver")

        second = deliver_batch(self.session, self.run.id, "approver")

        self.assertEqual(first["created"], 1)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["existing"], 1)
        self.assertEqual(self.session.query(RawPost).count(), 1)

    def test_delivery_links_raw_post_id_and_marks_batch_delivered(self):
        self._approve(self.item)

        result = deliver_batch(self.session, self.run.id, "approver")

        post = self.session.query(RawPost).one()
        batch = self.session.query(EvidenceDeliveryBatch).one()
        self.assertEqual(batch.raw_post_id, post.id)
        self.assertEqual(batch.status, "delivered")
        self.assertIsNotNone(batch.delivered_at)
        self.assertIsNone(batch.error)
        self.assertEqual(result["batch_ids"], [batch.id])

    def test_delivery_without_eligible_evidence_raises(self):
        with self.assertRaises(ValueError):
            deliver_batch(self.session, self.run.id, "approver")
        self.assertEqual(self.session.query(RawPost).count(), 0)

    def test_delivery_reuses_raw_post_inserted_by_a_concurrent_writer(self):
        # 并发写入者已抢先插入同一 (platform, external_id)：必须自愈复用，不得抛 IntegrityError
        self._approve(self.item)
        self.session.add(
            RawPost(
                platform="web",
                external_id=self.item.canonical_url_hash,
                title="already there",
            )
        )
        self.session.commit()

        result = deliver_batch(self.session, self.run.id, "approver")

        self.assertEqual(result["created"], 0)
        self.assertEqual(result["existing"], 1)
        self.assertEqual(self.session.query(RawPost).count(), 1)


if __name__ == "__main__":
    unittest.main()
