"""Schema validation tests."""

import unittest

from pydantic import ValidationError

from evidence_collector.schemas import SearchHit


class SearchHitTests(unittest.TestCase):
    def test_file_url_is_rejected(self):
        with self.assertRaises(ValidationError):
            SearchHit(url="file:///private/source.txt", quote="Supporting evidence.")

    def test_blank_quote_is_rejected(self):
        with self.assertRaises(ValidationError):
            SearchHit(url="https://example.edu/source", quote="   ")


if __name__ == "__main__":
    unittest.main()
