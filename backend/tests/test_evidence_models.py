"""Evidence model integrity tests (mapped on the backend's single Base)."""

import hashlib
import unittest

from sqlalchemy import String, UniqueConstraint, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models_evidence import (
    EvidenceDeliveryBatch,
    EvidenceDocument,
    EvidenceItem,
    EvidenceRun,
    EvidenceVerification,
)


class EvidenceModelsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_duplicate_canonical_url_hash_is_rejected_globally(self):
        canonical_url = "https://example.edu/article"
        values = {
            "source_type": "web",
            "source_url": "https://example.edu/article",
            "canonical_url": canonical_url,
            "canonical_url_hash": hashlib.sha256(canonical_url.encode()).hexdigest(),
            "evidence_quote": "A concrete supporting quote.",
        }
        self.session.add(EvidenceDocument(**values))
        self.session.commit()

        self.session.add(
            EvidenceDocument(
                **{
                    **values,
                    "source_type": "news",
                    "source_url": "https://mirror.example.edu/article",
                    "canonical_url": "https://mirror.example.edu/article",
                }
            )
        )
        with self.assertRaises(IntegrityError):
            self.session.commit()

    def test_evidence_tables_are_registered_on_the_backend_base(self):
        # The collector no longer owns a private Base/engine: init_db() must
        # provision every evidence_* table from backend.database.Base.
        from backend import database

        registered = set(Base.metadata.tables)
        self.assertTrue(
            {
                "evidence_runs",
                "evidence_queries",
                "evidence_documents",
                "evidence_items",
                "evidence_verifications",
                "evidence_delivery_batches",
            }.issubset(registered)
        )
        self.assertIn("raw_posts", registered)
        self.assertIs(EvidenceRun.metadata, database.Base.metadata)

    def test_delivery_batch_raw_post_id_is_a_nullable_foreign_key(self):
        column = EvidenceDeliveryBatch.__table__.c.raw_post_id
        self.assertTrue(column.nullable)
        self.assertEqual(
            [fk.target_fullname for fk in column.foreign_keys], ["raw_posts.id"]
        )

    def test_canonical_url_hash_is_mysql_safe_and_sole_unique_target(self):
        canonical_url_hash = EvidenceDocument.__table__.c.canonical_url_hash
        self.assertIsInstance(canonical_url_hash.type, String)
        self.assertEqual(canonical_url_hash.type.length, 64)
        self.assertFalse(canonical_url_hash.nullable)

        item_canonical_url_hash = EvidenceItem.__table__.c.canonical_url_hash
        self.assertFalse(item_canonical_url_hash.nullable)

        unique_constraints = [
            constraint
            for constraint in EvidenceDocument.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        ]
        self.assertEqual(len(unique_constraints), 1)
        self.assertEqual(
            [column.name for column in unique_constraints[0].columns],
            ["canonical_url_hash"],
        )

    def test_run_has_creator_usage_duration_and_sanitized_error_audit_fields(self):
        columns = set(EvidenceRun.__table__.c.keys())
        self.assertTrue(
            {"creator", "duration_ms", "usage_input_tokens", "usage_output_tokens",
             "usage_total_tokens", "sanitized_error_summary"}.issubset(columns)
        )

    def test_item_is_self_auditable_without_its_document_relationship(self):
        columns = set(EvidenceItem.__table__.c.keys())
        self.assertTrue(
            {
                "source_url", "canonical_url", "source_domain", "source_type",
                "canonical_url_hash",
                "published_at", "retrieved_at", "evidence_quote",
                "retrieval_provider", "retrieval_model", "prompt_version",
                "verification_status",
            }.issubset(columns)
        )

    def test_verification_has_conflict_and_version_audit_fields(self):
        columns = set(EvidenceVerification.__table__.c.keys())
        self.assertTrue(
            {"conflict_reason", "verification_version", "model_version"}.issubset(columns)
        )

    def test_delivery_batch_has_approver_audit_fields(self):
        columns = set(EvidenceDeliveryBatch.__table__.c.keys())
        self.assertTrue({"approver", "approved_at"}.issubset(columns))


if __name__ == "__main__":
    unittest.main()
