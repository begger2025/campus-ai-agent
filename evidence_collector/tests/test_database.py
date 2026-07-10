"""Evidence database isolation and integrity tests."""

import unittest

from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError

from evidence_collector.database import create_session_factory, init_database
from evidence_collector.models import EvidenceDocument


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


if __name__ == "__main__":
    unittest.main()
