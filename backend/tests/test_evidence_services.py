"""Focused tests for deterministic URL and source-scope policy helpers."""

from __future__ import annotations

import unittest

from backend.services.evidence.canonicalize import (
    canonical_url_hash,
    canonicalize_url,
    stable_external_id,
)
from backend.services.evidence.scope_policy import assess_scope


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
    def test_official_is_in_scope(self) -> None:
        result = assess_scope(
            "official",
            "www.sysu.edu.cn",
            "中山大学关于暑期安排的通知",
            "中山大学发布暑期安排通知。",
        )
        self.assertEqual(result.decision, "in_scope")
        self.assertTrue(result.reasons)

    def test_official_notice_alias_is_normalized(self) -> None:
        result = assess_scope(
            "official_notice",
            "www.sysu.edu.cn",
            "中山大学关于暑期安排的通知",
            "中山大学发布暑期安排通知。",
        )
        self.assertEqual(result.decision, "in_scope")

    def test_allowlisted_news_is_in_scope(self) -> None:
        result = assess_scope(
            "news",
            "people.com.cn",
            "高校新闻",
            "Sun Yat-sen University announced the new program.",
        )
        self.assertEqual(result.decision, "in_scope")
        self.assertTrue(result.reasons)

    def test_ambiguous_zhongda_needs_review(self) -> None:
        result = assess_scope("official_notice", "www.sysu.edu.cn", "中大通知", "中大公布安排")
        self.assertEqual(result.decision, "needs_review")
        self.assertTrue(result.reasons)

    def test_missing_quote_is_out_of_scope(self) -> None:
        result = assess_scope("official_notice", "www.sysu.edu.cn", "中山大学通知", "  ")
        self.assertEqual(result.decision, "out_of_scope")
        self.assertTrue(result.reasons)

    def test_unsupported_source_is_out_of_scope(self) -> None:
        result = assess_scope("web", "www.sysu.edu.cn", "中山大学通知", "中山大学发布通知")
        self.assertEqual(result.decision, "out_of_scope")
        self.assertTrue(result.reasons)

    def test_scope_decision_rejects_invalid_state(self) -> None:
        from backend.services.evidence.scope_policy import ScopeDecision

        with self.assertRaises(ValueError):
            ScopeDecision("accepted", ["invalid state"])  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            ScopeDecision("in_scope", ["  "])

    def test_malformed_domain_url_is_rejected(self) -> None:
        for malformed in ("file://sysu.edu.cn", "http://sysu.edu.cn:bad", "ftp://sysu.edu.cn"):
            result = assess_scope(
                "official",
                malformed,
                "中山大学通知",
                "中山大学发布通知",
            )
            self.assertEqual(result.decision, "out_of_scope")

    def test_lookalike_domain_is_not_allowlisted(self) -> None:
        result = assess_scope(
            "official",
            "evil-sysu.edu.cn",
            "中山大学通知",
            "中山大学发布通知",
        )
        self.assertEqual(result.decision, "needs_review")

    def test_empty_hostname_label_is_out_of_scope(self) -> None:
        result = assess_scope(
            "official",
            "evil..sysu.edu.cn",
            "中山大学通知",
            "中山大学发布通知",
        )
        self.assertEqual(result.decision, "out_of_scope")

    def test_official_subdomain_uses_dot_boundary(self) -> None:
        result = assess_scope(
            "official",
            "notice.sysu.edu.cn",
            "中山大学通知",
            "中山大学发布通知",
        )
        self.assertEqual(result.decision, "in_scope")

    def test_unknown_news_domain_needs_review(self) -> None:
        result = assess_scope(
            "news",
            "untrusted.example",
            "高校新闻",
            "Sun Yat-sen University announced the new program.",
        )
        self.assertEqual(result.decision, "needs_review")


if __name__ == "__main__":
    unittest.main()
