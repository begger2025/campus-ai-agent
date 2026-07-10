"""Evidence database isolation and integrity tests."""

import unittest

from sqlalchemy import String, create_engine, inspect
from sqlalchemy.exc import IntegrityError

from evidence_collector.database import create_session_factory, init_database
from evidence_collector.models import (
    EvidenceDeliveryBatch,
    EvidenceDocument,
    EvidenceItem,
    EvidenceRun,
    EvidenceVerification,
)


class EvidenceDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}
        )
        init_database(self.engine)
        self.session = create_session_factory(self.engine)()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_duplicate_source_type_and_canonical_url_is_rejected(self):
        values = {
            "source_type": "web",
            "source_url": "https://example.edu/article",
            "canonical_url": "https://example.edu/article",
            "evidence_quote": "A concrete supporting quote.",
        }
        self.session.add(EvidenceDocument(**values))
        self.session.commit()

        self.session.add(EvidenceDocument(**values))
        with self.assertRaises(IntegrityError):
            self.session.commit()

    def test_init_creates_only_evidence_tables(self):
        table_names = set(inspect(self.engine).get_table_names())
        self.assertTrue(table_names)
        self.assertTrue(all(name.startswith("evidence_") for name in table_names))
        self.assertNotIn("raw_posts", table_names)

    def test_unique_canonical_url_column_is_bounded_for_mysql_indexes(self):
        canonical_url = EvidenceDocument.__table__.c.canonical_url
        self.assertIsInstance(canonical_url.type, String)
        self.assertEqual(canonical_url.type.length, 2048)

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
