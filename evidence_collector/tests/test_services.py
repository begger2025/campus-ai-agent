"""Focused tests for deterministic URL and source-scope policy helpers."""

from __future__ import annotations

import re
import unittest

from evidence_collector.services.canonicalize import (
    canonical_url_hash,
    canonicalize_url,
    stable_external_id,
)
from evidence_collector.services.scope_policy import assess_scope


class CanonicalizeTests(unittest.TestCase):
    def test_tracking_parameters_and_fragment_are_removed(self) -> None:
        value = canonicalize_url(
            "HTTPS://Example.COM/notice?utm_source=x&id=42&spm=abc&from=search&tag=one#section"
        )
        self.assertEqual(value, "https://example.com/notice?id=42&tag=one")

    def test_meaningful_query_order_is_preserved(self) -> None:
        value = canonicalize_url("https://example.com/?z=1&utm_medium=x&a=2&z=3")
        self.assertEqual(value, "https://example.com/?z=1&a=2&z=3")

    def test_malformed_url_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            canonicalize_url("not a URL")
        with self.assertRaises(ValueError):
            canonicalize_url("ftp://example.com/file")

    def test_hash_is_deterministic_lowercase_sha256(self) -> None:
        first = stable_external_id("https://Example.com/a?utm_source=one&id=7#fragment")
        second = canonical_url_hash("https://example.com/a?id=7")
        self.assertEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{64}$")


class ScopePolicyTests(unittest.TestCase):
    def test_official_notice_is_accepted(self) -> None:
        result = assess_scope(
            "official_notice",
            "www.sysu.edu.cn",
            "中山大学关于暑期安排的通知",
            "中山大学发布暑期安排通知。",
        )
        self.assertEqual(result.decision, "accepted")
        self.assertTrue(result.reasons)

    def test_allowlisted_news_is_accepted(self) -> None:
        result = assess_scope(
            "news",
            "people.com.cn",
            "高校新闻",
            "Sun Yat-sen University announced the new program.",
        )
        self.assertEqual(result.decision, "accepted")
        self.assertTrue(result.reasons)

    def test_ambiguous_zhongda_is_uncertain(self) -> None:
        result = assess_scope("official_notice", "www.sysu.edu.cn", "中大通知", "中大公布安排")
        self.assertEqual(result.decision, "uncertain")
        self.assertTrue(result.reasons)

    def test_missing_quote_is_rejected(self) -> None:
        result = assess_scope("official_notice", "www.sysu.edu.cn", "中山大学通知", "  ")
        self.assertEqual(result.decision, "rejected")
        self.assertTrue(result.reasons)

    def test_unsupported_source_is_rejected(self) -> None:
        result = assess_scope("web", "www.sysu.edu.cn", "中山大学通知", "中山大学发布通知")
        self.assertEqual(result.decision, "rejected")
        self.assertTrue(result.reasons)


if __name__ == "__main__":
    unittest.main()
