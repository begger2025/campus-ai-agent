"""证据引用真实性核验：真的去 GET 那个 URL，抓不到就不许过。

零网络：HTTP 客户端一律注入假实现；没有注入客户端时核验器必须"不可用"，
而不是静默通过。
"""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models_evidence import EvidenceDocument, EvidenceItem, EvidenceRun, EvidenceVerification
from backend.services.evidence.canonicalize import canonical_url_hash, canonicalize_url
from backend.services.evidence.schemas import VERIFICATION_STATUSES
from backend.services.evidence.verification import (
    FETCH_VERIFICATION_METHOD,
    UrlFetchVerifier,
    VerifierUnavailableError,
    verify_item_by_fetch,
)


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class FakeHttpClient:
    """只回放预置响应/异常，不做任何网络访问。"""

    def __init__(self, response: FakeResponse | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


QUOTE = "中山大学发布关于暑期作息安排的通知。"


class FetchVerifierTests(unittest.IsolatedAsyncioTestCase):
    async def test_without_client_the_verifier_is_unavailable(self) -> None:
        verifier = UrlFetchVerifier()
        self.assertFalse(verifier.available)
        with self.assertRaises(VerifierUnavailableError):
            await verifier.check("https://news.sysu.edu.cn/info/1", QUOTE)

    async def test_live_page_containing_the_quote_is_verified(self) -> None:
        client = FakeHttpClient(FakeResponse(200, f"<html><body><p>{QUOTE}</p></body></html>"))
        verifier = UrlFetchVerifier(client=client)
        result = await verifier.check("https://news.sysu.edu.cn/info/1", QUOTE)
        self.assertEqual(result.status, "verified")
        self.assertTrue(result.reasons)
        self.assertEqual(result.method, FETCH_VERIFICATION_METHOD)
        self.assertTrue(client.calls[0][1].get("follow_redirects"))
        self.assertIn("User-Agent", client.calls[0][1]["headers"])

    async def test_quote_split_by_tags_and_whitespace_still_matches(self) -> None:
        page = "<div>中山大学\n  发布<b>关于暑期作息安排</b>的通知。</div>"
        verifier = UrlFetchVerifier(client=FakeHttpClient(FakeResponse(200, page)))
        result = await verifier.check("https://news.sysu.edu.cn/info/1", QUOTE)
        self.assertEqual(result.status, "verified")

    async def test_truncated_provider_quote_matches_on_a_long_prefix(self) -> None:
        page = "<p>中山大学发布关于暑期作息安排的通知，具体安排如下……</p>"
        long_quote = QUOTE + "具体安排请见附件，本通知自发布之日起施行，请各单位遵照执行。"
        verifier = UrlFetchVerifier(client=FakeHttpClient(FakeResponse(200, page)))
        result = await verifier.check("https://news.sysu.edu.cn/info/1", long_quote)
        self.assertEqual(result.status, "verified")

    async def test_live_page_without_the_quote_needs_review(self) -> None:
        verifier = UrlFetchVerifier(
            client=FakeHttpClient(FakeResponse(200, "<p>本页与该引用无关。</p>"))
        )
        result = await verifier.check("https://news.sysu.edu.cn/info/1", QUOTE)
        self.assertEqual(result.status, "needs_review")
        self.assertIn(result.status, VERIFICATION_STATUSES)
        self.assertTrue(any("引用" in reason or "quote" in reason for reason in result.reasons))

    async def test_non_2xx_is_rejected(self) -> None:
        verifier = UrlFetchVerifier(client=FakeHttpClient(FakeResponse(404, "not found")))
        result = await verifier.check("https://news.sysu.edu.cn/fabricated", QUOTE)
        self.assertEqual(result.status, "rejected")
        self.assertTrue(any("404" in reason for reason in result.reasons))

    async def test_dns_failure_or_timeout_is_rejected(self) -> None:
        verifier = UrlFetchVerifier(client=FakeHttpClient(error=OSError("dns lookup failed")))
        result = await verifier.check("https://news.sysu.edu.cn/fabricated", QUOTE)
        self.assertEqual(result.status, "rejected")
        self.assertTrue(result.reasons)

    async def test_non_http_url_is_rejected_without_a_request(self) -> None:
        client = FakeHttpClient(FakeResponse(200, QUOTE))
        verifier = UrlFetchVerifier(client=client)
        result = await verifier.check("ftp://news.sysu.edu.cn/info/1", QUOTE)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(client.calls, [])


class VerifyItemByFetchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
        self.session = sessionmaker(bind=engine, autoflush=False)()
        self.addCleanup(self.session.close)

    def _item(self, url: str = "https://news.sysu.edu.cn/info/1") -> int:
        run = EvidenceRun(topic="中大校园通知", status="completed")
        self.session.add(run)
        self.session.flush()
        canonical = canonicalize_url(url)
        digest = canonical_url_hash(canonical)
        document = EvidenceDocument(
            source_type="official",
            source_url=url,
            canonical_url=canonical,
            canonical_url_hash=digest,
            domain="news.sysu.edu.cn",
            title="通知",
            evidence_quote=QUOTE,
        )
        self.session.add(document)
        self.session.flush()
        item = EvidenceItem(
            run_id=run.id,
            document_id=document.id,
            source_url=url,
            canonical_url=canonical,
            canonical_url_hash=digest,
            source_domain="news.sysu.edu.cn",
            source_type="official",
            evidence_quote=QUOTE,
            retrieval_provider="glm",
            retrieval_model="glm-4-plus",
            prompt_version="v1",
            scope_decision="in_scope",
        )
        self.session.add(item)
        self.session.commit()
        return item.id

    async def test_verified_item_records_an_auditable_row(self) -> None:
        item_id = self._item()
        verifier = UrlFetchVerifier(client=FakeHttpClient(FakeResponse(200, f"<p>{QUOTE}</p>")))
        verification = await verify_item_by_fetch(self.session, item_id, verifier)
        self.session.commit()
        self.assertEqual(verification.method, FETCH_VERIFICATION_METHOD)
        self.assertEqual(verification.status, "verified")
        self.assertIsNotNone(verification.verified_at)
        self.assertEqual(self.session.get(EvidenceItem, item_id).verification_status, "verified")
        self.assertEqual(self.session.query(EvidenceVerification).count(), 1)

    async def test_fabricated_url_is_rejected_before_a_human_trusts_it(self) -> None:
        item_id = self._item("https://news.sysu.edu.cn/info/fabricated")
        verifier = UrlFetchVerifier(client=FakeHttpClient(FakeResponse(404, "")))
        verification = await verify_item_by_fetch(self.session, item_id, verifier)
        self.session.commit()
        self.assertEqual(verification.status, "rejected")
        self.assertEqual(self.session.get(EvidenceItem, item_id).verification_status, "rejected")
        self.assertIn("404", verification.reasons or "")

    async def test_live_page_missing_the_quote_needs_review(self) -> None:
        item_id = self._item()
        verifier = UrlFetchVerifier(client=FakeHttpClient(FakeResponse(200, "<p>其他内容</p>")))
        verification = await verify_item_by_fetch(self.session, item_id, verifier)
        self.session.commit()
        self.assertEqual(verification.status, "needs_review")
        self.assertEqual(
            self.session.get(EvidenceItem, item_id).verification_status, "needs_review"
        )

    async def test_missing_client_never_marks_an_item_verified(self) -> None:
        item_id = self._item()
        with self.assertRaises(VerifierUnavailableError):
            await verify_item_by_fetch(self.session, item_id, UrlFetchVerifier())
        self.assertEqual(self.session.get(EvidenceItem, item_id).verification_status, "pending")
        self.assertEqual(self.session.query(EvidenceVerification).count(), 0)

    async def test_missing_item_raises_lookup_error(self) -> None:
        verifier = UrlFetchVerifier(client=FakeHttpClient(FakeResponse(200, QUOTE)))
        with self.assertRaises(LookupError):
            await verify_item_by_fetch(self.session, 4242, verifier)


if __name__ == "__main__":
    unittest.main()
