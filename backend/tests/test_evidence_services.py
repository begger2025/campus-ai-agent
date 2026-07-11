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

    def test_meaningful_query_parameters_are_sorted(self) -> None:
        # Providers return the same article with different parameter order; a
        # canonical form must sort them so the two collapse to one document.
        value = canonicalize_url("https://example.com/?z=1&utm_medium=x&a=2&z=3")
        self.assertEqual(value, "https://example.com/?a=2&z=1&z=3")

    def test_query_parameter_order_does_not_change_the_hash(self) -> None:
        first = canonical_url_hash("https://news.sysu.edu.cn/a?b=1&c=2")
        second = canonical_url_hash("https://news.sysu.edu.cn/a?c=2&b=1")
        self.assertEqual(first, second)

    def test_empty_path_is_normalized_to_root(self) -> None:
        self.assertEqual(
            canonicalize_url("https://news.sysu.edu.cn"),
            canonicalize_url("https://news.sysu.edu.cn/"),
        )
        self.assertEqual(
            canonical_url_hash("https://news.sysu.edu.cn"),
            canonical_url_hash("https://news.sysu.edu.cn/"),
        )

    def test_trailing_slash_on_a_non_empty_path_is_stripped(self) -> None:
        # Providers return the same article with and without the trailing slash;
        # without this the article lands in evidence_documents twice and is
        # double-counted in sentiment statistics and event clustering.
        self.assertEqual(
            canonicalize_url("https://news.sysu.edu.cn/notice/1/"),
            "https://news.sysu.edu.cn/notice/1",
        )
        self.assertEqual(
            canonical_url_hash("https://news.sysu.edu.cn/notice/1"),
            canonical_url_hash("https://news.sysu.edu.cn/notice/1/"),
        )

    def test_root_path_keeps_its_slash(self) -> None:
        # ``https://host`` must stay ``https://host/`` — stripping the root
        # slash would produce a hostname-only URL that is not a valid page.
        self.assertEqual(canonicalize_url("https://news.sysu.edu.cn/"), "https://news.sysu.edu.cn/")
        self.assertEqual(canonicalize_url("https://news.sysu.edu.cn"), "https://news.sysu.edu.cn/")
        self.assertEqual(
            canonicalize_url("https://news.sysu.edu.cn/?a=1"),
            "https://news.sysu.edu.cn/?a=1",
        )

    def test_trailing_slash_is_stripped_before_the_query(self) -> None:
        self.assertEqual(
            canonical_url_hash("https://news.sysu.edu.cn/notice/?id=1"),
            canonical_url_hash("https://news.sysu.edu.cn/notice?id=1"),
        )

    def test_default_port_is_stripped(self) -> None:
        self.assertEqual(
            canonical_url_hash("https://news.sysu.edu.cn/a"),
            canonical_url_hash("https://news.sysu.edu.cn:443/a"),
        )
        self.assertEqual(
            canonical_url_hash("http://news.sysu.edu.cn/a"),
            canonical_url_hash("http://news.sysu.edu.cn:80/a"),
        )

    def test_non_default_port_is_retained(self) -> None:
        self.assertEqual(
            canonicalize_url("https://news.sysu.edu.cn:8443/a"),
            "https://news.sysu.edu.cn:8443/a",
        )
        self.assertNotEqual(
            canonical_url_hash("https://news.sysu.edu.cn/a"),
            canonical_url_hash("https://news.sysu.edu.cn:8443/a"),
        )

    def test_ipv6_host_is_bracketed_and_normalized(self) -> None:
        self.assertEqual(
            canonicalize_url("https://[2001:DB8::1]:443"),
            "https://[2001:db8::1]/",
        )

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

    def test_unrecognized_source_type_needs_review(self) -> None:
        # A real web-search hit on an unknown domain keeps the default "web"
        # type.  Dropping it silently hid genuine evidence from reviewers, so it
        # goes to the human queue instead.
        result = assess_scope("web", "blog.example.com", "中山大学通知", "中山大学发布通知")
        self.assertEqual(result.decision, "needs_review")
        self.assertTrue(result.reasons)

    def test_missing_source_type_is_out_of_scope(self) -> None:
        for missing in (None, "", "   "):
            result = assess_scope(missing, "www.sysu.edu.cn", "中山大学通知", "中山大学发布通知")
            self.assertEqual(result.decision, "out_of_scope", missing)

    def test_unrecognized_source_type_without_quote_is_out_of_scope(self) -> None:
        result = assess_scope("web", "blog.example.com", "中山大学通知", "   ")
        self.assertEqual(result.decision, "out_of_scope")

    def test_unrecognized_source_type_with_malformed_domain_is_out_of_scope(self) -> None:
        result = assess_scope("web", "evil..sysu.edu.cn", "中山大学通知", "中山大学发布通知")
        self.assertEqual(result.decision, "out_of_scope")

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

    def test_allowlisted_official_domain_establishes_the_entity(self) -> None:
        # Real SYSU notices on the university's own site say 我校/学校 rather
        # than spelling out 中山大学; the domain itself proves the entity.
        result = assess_scope(
            "official",
            "news.sysu.edu.cn",
            "关于东校区宿舍搬迁的通知",
            "学校决定于本月启动搬迁工作，请同学配合。",
        )
        self.assertEqual(result.decision, "in_scope")
        self.assertIn(
            "allowlisted official domain establishes the SYSU entity",
            result.reasons,
        )

    def test_official_domain_entity_reason_is_distinct_from_text_entity(self) -> None:
        by_domain = assess_scope(
            "official", "news.sysu.edu.cn", "通知", "我校将于下周启动搬迁。"
        )
        by_text = assess_scope(
            "official", "news.sysu.edu.cn", "中山大学通知", "中山大学发布通知。"
        )
        self.assertEqual(by_domain.decision, "in_scope")
        self.assertEqual(by_text.decision, "in_scope")
        self.assertNotEqual(by_domain.reason, by_text.reason)

    def test_news_domain_still_requires_an_explicit_entity(self) -> None:
        # A passing mention on an allowlisted news domain must not be hoovered
        # up: the news site has to actually name the university.
        result = assess_scope(
            "news",
            "people.com.cn",
            "关于东校区宿舍搬迁的通知",
            "学校决定于本月启动搬迁工作。",
        )
        self.assertEqual(result.decision, "out_of_scope")

    def test_non_allowlisted_official_domain_without_entity_is_out_of_scope(self) -> None:
        result = assess_scope(
            "official",
            "notice.example.com",
            "关于宿舍搬迁的通知",
            "学校决定于本月启动搬迁工作。",
        )
        self.assertEqual(result.decision, "out_of_scope")

    def test_official_domain_shortcut_still_requires_a_quote(self) -> None:
        result = assess_scope("official", "news.sysu.edu.cn", "通知", "   ")
        self.assertEqual(result.decision, "out_of_scope")


if __name__ == "__main__":
    unittest.main()
