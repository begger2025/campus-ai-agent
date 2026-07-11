"""Offline tests for verification, review, and delivery boundaries."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
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
    mark_delivery,
    review_item,
    verify_item,
)


class ReviewDeliveryTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
