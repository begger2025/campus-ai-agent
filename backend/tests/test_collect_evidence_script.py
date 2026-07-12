"""证据采集 CLI（scripts/collect_evidence.py）纯逻辑测试。

零网络、零共享库写入：队列关键词用内存 SQLite，采集器用注入的假 runner。
"""

import io
import unittest
from contextlib import redirect_stdout

from sqlalchemy import create_engine, text

from scripts.collect_evidence import (
    KeywordSummary,
    format_report,
    load_pending_keywords,
    main,
    resolve_keywords,
    summarize,
)


def _queue_engine(rows):
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE crawl_task_queue ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " platform TEXT, keyword TEXT, status TEXT,"
            " priority INTEGER DEFAULT 0, created_at INTEGER DEFAULT 0)"
        ))
        for platform, keyword, status in rows:
            conn.execute(
                text(
                    "INSERT INTO crawl_task_queue (platform, keyword, status)"
                    " VALUES (:p, :k, :s)"
                ),
                {"p": platform, "k": keyword, "s": status},
            )
    return engine


def _item(keyword, scope="in_scope", verification="verified", reasons=(), url="https://x.sysu.edu.cn/a"):
    return {
        "keyword": keyword,
        "url": url,
        "domain": "x.sysu.edu.cn",
        "title": "t",
        "scope_decision": scope,
        "verification_status": verification,
        "verification_reasons": list(reasons),
    }


class LoadPendingKeywordsTests(unittest.TestCase):
    def test_only_pending_and_distinct(self):
        engine = _queue_engine([
            ("xhs", "食堂", "pending"),
            ("ks", "食堂", "pending"),          # 同一关键词两个平台 → 只取一次
            ("xhs", "学术不端", "pending"),
            ("ks", "已完成的词", "done"),        # done 不算
            ("xhs", "认领中的词", "claimed"),    # claimed 不算（已经在爬了，不重复检索）
        ])
        with engine.connect() as conn:
            self.assertEqual(load_pending_keywords(conn), ["食堂", "学术不端"])

    def test_platform_filter(self):
        engine = _queue_engine([("xhs", "食堂", "pending"), ("ks", "宿舍", "pending")])
        with engine.connect() as conn:
            self.assertEqual(load_pending_keywords(conn, platform="ks"), ["宿舍"])


class ResolveKeywordsTests(unittest.TestCase):
    def test_merges_explicit_and_queue_preserving_order_without_duplicates(self):
        self.assertEqual(
            resolve_keywords("宿舍, 食堂 ,宿舍", ["食堂", "学术不端"]),
            ["宿舍", "食堂", "学术不端"],
        )

    def test_empty_is_an_error(self):
        with self.assertRaises(ValueError):
            resolve_keywords("", [])


class SummarizeTests(unittest.TestCase):
    def test_keyword_with_zero_citations_is_reported_not_hidden(self):
        summaries = summarize(["学术不端", "食堂"], [_item("食堂")])
        by_kw = {s.keyword: s for s in summaries}
        self.assertEqual(sorted(by_kw), ["学术不端", "食堂"])
        self.assertEqual(by_kw["学术不端"].citations, 0)
        self.assertEqual(by_kw["食堂"].citations, 1)

    def test_counts_scope_and_verification_and_keeps_rejection_reasons(self):
        items = [
            _item("食堂", scope="in_scope", verification="verified"),
            _item("食堂", scope="needs_review", verification="needs_review",
                  reasons=["页面可访问，但正文中未能定位到该证据引用"], url="https://a.com/1"),
            _item("食堂", scope="out_of_scope", verification="rejected",
                  reasons=["证据链接返回 HTTP 404"], url="https://b.com/2"),
        ]
        summary = summarize(["食堂"], items)[0]
        self.assertEqual(summary.citations, 3)
        self.assertEqual(summary.scope, {"in_scope": 1, "needs_review": 1, "out_of_scope": 1})
        self.assertEqual(
            summary.verification,
            {"pending": 0, "verified": 1, "rejected": 1, "needs_review": 1, "failed": 0},
        )
        self.assertEqual(summary.rejection_reasons, ["证据链接返回 HTTP 404"])


class FormatReportTests(unittest.TestCase):
    def test_states_plainly_when_a_keyword_returned_nothing(self):
        lines = format_report(summarize(["学术不端"], []), run_id=7, run_status="completed")
        text_out = "\n".join(lines)
        self.assertIn("学术不端", text_out)
        self.assertIn("0 条引用", text_out)
        self.assertIn("官方网络上没有检索到", text_out)

    def test_points_at_the_admin_page_and_never_claims_delivery(self):
        summaries = [
            KeywordSummary(
                keyword="食堂",
                citations=1,
                scope={"in_scope": 1, "out_of_scope": 0, "needs_review": 0},
                verification={"pending": 0, "verified": 1, "rejected": 0,
                              "needs_review": 0, "failed": 0},
                rejection_reasons=[],
            )
        ]
        text_out = "\n".join(format_report(summaries, run_id=7, run_status="completed"))
        self.assertIn("证据采集", text_out)          # 指向后台管理页
        self.assertNotIn("raw_posts", text_out.replace("未写入 raw_posts", ""))


class MainDryRunTests(unittest.TestCase):
    def setUp(self):
        self.engine = _queue_engine([
            ("xhs", "学术不端", "pending"),
            ("ks", "学术不端", "pending"),
            ("xhs", "食堂", "pending"),
        ])
        self.calls = []

    def _runner(self, **kwargs):
        self.calls.append(kwargs)
        return {"run_id": 1, "run_status": "completed", "items": [], "query_failures": []}

    def test_dry_run_prints_the_plan_and_calls_nothing(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = main(["--from-queue", "--dry-run"], engine=self.engine, runner=self._runner)
        out = buffer.getvalue()
        self.assertEqual(rc, 0)
        self.assertEqual(self.calls, [])            # 零 LLM 调用
        self.assertIn("dry-run", out)
        self.assertIn("学术不端", out)
        self.assertIn("食堂", out)
        with self.engine.connect() as conn:         # 零 DB 写入
            self.assertEqual(
                conn.execute(text("SELECT COUNT(*) FROM crawl_task_queue")).scalar(), 3
            )

    def test_from_queue_passes_distinct_pending_keywords_to_the_runner(self):
        with redirect_stdout(io.StringIO()):
            rc = main(
                ["--from-queue", "--topic", "校园舆情"],
                engine=self.engine,
                runner=self._runner,
            )
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]["keywords"], ["学术不端", "食堂"])
        self.assertEqual(self.calls[0]["topic"], "校园舆情")

    def test_requires_keywords(self):
        empty = _queue_engine([])
        with self.assertRaises(SystemExit):
            with redirect_stdout(io.StringIO()):
                main(["--from-queue"], engine=empty, runner=self._runner)


if __name__ == "__main__":
    unittest.main()
