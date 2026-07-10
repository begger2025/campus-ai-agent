from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.admin_models import User
from backend.database import Base, get_db
from backend.main import app
from backend.models import ChatQueryLog, ProcessedPost
from backend.services.auth_service import get_current_user
from backend.services.keyword_suggestion_adapter import get_keyword_suggestions

NOW = datetime(2026, 7, 10, 12, 0, 0)


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _post(raw_post_id: int, source_keyword: str, days_ago: int, likes: int, tags_json: str = "") -> ProcessedPost:
    moment = NOW - timedelta(days=days_ago)
    return ProcessedPost(
        raw_post_id=raw_post_id,
        platform="xhs",
        title=f"{source_keyword}相关帖子{raw_post_id}",
        source_keyword=source_keyword,
        like_count=likes,
        tags_json=tags_json,
        publish_time=moment,
        created_at=moment,
    )


class KeywordSuggestionAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session_factory()()
        self.addCleanup(self.db.close)

    def test_empty_database_returns_empty_suggestions(self) -> None:
        data = get_keyword_suggestions(self.db, now=NOW)
        self.assertEqual(data["suggestions"], [])
        self.assertEqual(data["meta"]["query_count"], 0)
        self.assertEqual(data["meta"]["post_count"], 0)

    def test_end_to_end_four_signals(self) -> None:
        # A+B：宿舍空调被问 3 次、命中 0，从未爬过 → 应登顶
        for i in range(3):
            self.db.add(
                ChatQueryLog(
                    user_id="7",
                    message="宿舍空调怎么样",
                    intent="opinion_answer",
                    keyword="宿舍空调",
                    hit_count=0,
                    created_at=NOW - timedelta(days=1, hours=i),
                )
            )
        # C：食堂 3 天前爬过、内容热 → heat 信号且已降权
        # D：这些帖子带"期末周"标签，从未作为关键词爬过 → discovery
        self.db.add(_post(1, "食堂", 3, 500, tags_json='["期末周"]'))
        self.db.add(_post(2, "食堂", 3, 300, tags_json='["期末周"]'))
        self.db.commit()

        data = get_keyword_suggestions(self.db, now=NOW)
        by_kw = {s["keyword"]: s for s in data["suggestions"]}

        self.assertEqual(data["suggestions"][0]["keyword"], "宿舍空调")
        self.assertEqual(data["suggestions"][0]["signals"], ["demand", "gap"])
        self.assertIn("heat", by_kw["食堂"]["signals"])
        self.assertIn("已降权", by_kw["食堂"]["reason"])
        self.assertEqual(by_kw["期末周"]["signals"], ["discovery"])
        self.assertEqual(data["meta"]["query_count"], 3)
        self.assertEqual(data["meta"]["post_count"], 2)

    def test_broken_tags_json_is_tolerated(self) -> None:
        self.db.add(_post(1, "食堂", 3, 500, tags_json="not-json"))
        self.db.commit()
        data = get_keyword_suggestions(self.db, now=NOW)
        self.assertEqual([s["keyword"] for s in data["suggestions"]], ["食堂"])

    def test_queries_without_keyword_are_skipped(self) -> None:
        self.db.add(ChatQueryLog(user_id="7", message="综合分析一下", intent="complex_analysis", keyword="", hit_count=0, created_at=NOW))
        self.db.commit()
        data = get_keyword_suggestions(self.db, now=NOW)
        self.assertEqual(data["suggestions"], [])
        self.assertEqual(data["meta"]["query_count"], 0)


_EPOCH = datetime(1970, 1, 1)

# 与 MediaCrawler/database/models.py 的 CrawlerRunHistory 逐列一致（SQLite 方言）。
_HISTORY_DDL = """
CREATE TABLE crawler_run_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform VARCHAR(16),
    source_keyword VARCHAR(255),
    started_at BIGINT,
    finished_at BIGINT,
    pages_fetched INTEGER DEFAULT 0,
    items_seen INTEGER DEFAULT 0,
    items_stored INTEGER DEFAULT 0,
    stop_reason VARCHAR(64) DEFAULT ''
)
"""


def _ms(moment: datetime) -> int:
    """naive-UTC datetime -> 毫秒 epoch（与爬虫写入口径一致）。"""
    return int((moment - _EPOCH).total_seconds() * 1000)


class CrawlerRunHistoryBarrenTest(unittest.TestCase):
    """adapter 读 crawler_run_history：贫瘠词强降权 + finished_at 并入降权时间。"""

    def setUp(self) -> None:
        self.db = make_session_factory()()
        self.addCleanup(self.db.close)
        self.db.execute(text(_HISTORY_DDL))
        self.db.commit()

    def _ask(self, keyword: str, days_ago: float = 1) -> None:
        self.db.add(
            ChatQueryLog(
                user_id="7",
                message=f"{keyword}怎么样",
                intent="opinion_answer",
                keyword=keyword,
                hit_count=0,
                created_at=NOW - timedelta(days=days_ago),
            )
        )

    def _run(
        self,
        keyword: str,
        *,
        finished_days_ago: float | None,
        items_stored: int,
        started_days_ago: float | None = None,
        platform: str = "xhs",
    ) -> None:
        finished = 0 if finished_days_ago is None else _ms(NOW - timedelta(days=finished_days_ago))
        started = (
            _ms(NOW - timedelta(days=started_days_ago))
            if started_days_ago is not None
            else (finished - 60_000 if finished else 0)
        )
        self.db.execute(
            text(
                "INSERT INTO crawler_run_history "
                "(platform, source_keyword, started_at, finished_at, pages_fetched, items_seen, items_stored, stop_reason) "
                "VALUES (:platform, :kw, :started, :finished, 1, 10, :stored, 'completed')"
            ),
            {"platform": platform, "kw": keyword, "started": started, "finished": finished, "stored": items_stored},
        )

    def test_barren_keyword_is_strongly_penalized_with_reason(self) -> None:
        self._ask("空调维修")
        self._run("空调维修", finished_days_ago=2, items_stored=0)
        self.db.commit()

        data = get_keyword_suggestions(self.db, now=NOW)
        suggestion = data["suggestions"][0]

        self.assertEqual(suggestion["keyword"], "空调维修")
        # 唯一候选：demand_norm=1、gap 命中 → 基础分 8.0；贫瘠 ×0.1 → 0.8（常规降权是 2.4）
        self.assertAlmostEqual(suggestion["score"], 0.8, places=1)
        self.assertIn("爬过但无相关内容", suggestion["reason"])
        self.assertEqual(data["meta"]["barren_count"], 1)

    def test_latest_run_with_output_clears_barren_flag(self) -> None:
        self._ask("空调维修")
        self._run("空调维修", finished_days_ago=5, items_stored=0)
        self._run("空调维修", finished_days_ago=2, items_stored=3, platform="wb")
        self.db.commit()

        data = get_keyword_suggestions(self.db, now=NOW)
        suggestion = data["suggestions"][0]

        # 最新一次 run 有产出 → 不贫瘠，只按常规爬过降权（×0.3 → 2.4）
        self.assertAlmostEqual(suggestion["score"], 2.4, places=1)
        self.assertNotIn("无相关内容", suggestion["reason"])
        self.assertIn("已降权", suggestion["reason"])
        self.assertEqual(data["meta"]["barren_count"], 0)

    def test_history_finished_at_merged_into_crawled_at(self) -> None:
        # 内容表倒推的爬取时间是 10 天前；历史表 2 天前有一次有产出的 run → 取更新者
        self.db.add(_post(1, "食堂", 10, 500))
        self._run("食堂", finished_days_ago=2, items_stored=5)
        self.db.commit()

        data = get_keyword_suggestions(self.db, now=NOW)
        by_kw = {s["keyword"]: s for s in data["suggestions"]}

        self.assertEqual(
            by_kw["食堂"]["last_crawled_at"],
            (NOW - timedelta(days=2)).isoformat(),
        )
        self.assertIn("2天前爬过", by_kw["食堂"]["reason"])

    def test_out_of_window_history_is_ignored(self) -> None:
        self._ask("空调维修")
        self._run("空调维修", finished_days_ago=20, items_stored=0)
        self.db.commit()

        data = get_keyword_suggestions(self.db, now=NOW)
        suggestion = data["suggestions"][0]

        # 20 天前的零产出已过窗：不贫瘠、不降权、视作从未爬取
        self.assertAlmostEqual(suggestion["score"], 8.0, places=1)
        self.assertNotIn("无相关内容", suggestion["reason"])
        self.assertIsNone(suggestion["last_crawled_at"])
        self.assertEqual(data["meta"]["barren_count"], 0)

    def test_zero_finished_at_falls_back_to_started_at(self) -> None:
        self._ask("空调维修")
        self._run("空调维修", finished_days_ago=None, items_stored=0, started_days_ago=3)
        self.db.commit()

        data = get_keyword_suggestions(self.db, now=NOW)
        suggestion = data["suggestions"][0]

        self.assertAlmostEqual(suggestion["score"], 0.8, places=1)
        self.assertEqual(
            suggestion["last_crawled_at"],
            (NOW - timedelta(days=3)).isoformat(),
        )
        self.assertIn("3天前爬过但无相关内容", suggestion["reason"])


class CrawlerRunHistoryMissingTableTest(unittest.TestCase):
    """表不存在（默认建表元数据里没有 crawler_run_history）→ 行为与现状完全一致。"""

    def setUp(self) -> None:
        self.db = make_session_factory()()
        self.addCleanup(self.db.close)

    def test_missing_table_degrades_gracefully(self) -> None:
        self.db.add(
            ChatQueryLog(
                user_id="7",
                message="宿舍空调怎么样",
                intent="opinion_answer",
                keyword="宿舍空调",
                hit_count=0,
                created_at=NOW - timedelta(days=1),
            )
        )
        self.db.add(_post(1, "食堂", 3, 500))
        self.db.commit()

        data = get_keyword_suggestions(self.db, now=NOW)
        by_kw = {s["keyword"]: s for s in data["suggestions"]}

        self.assertIn("宿舍空调", by_kw)
        self.assertIn("食堂", by_kw)
        self.assertEqual(data["meta"]["barren_count"], 0)


class KeywordSuggestionsApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session_factory = make_session_factory()

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def login_as(self, role: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: User(id=1, username=f"test_{role}", role=role)

    def test_requires_token(self) -> None:
        self.assertEqual(self.client.get("/api/admin/keyword-suggestions").status_code, 401)

    def test_normal_user_is_forbidden(self) -> None:
        self.login_as("user")
        self.assertEqual(self.client.get("/api/admin/keyword-suggestions").status_code, 403)

    def test_admin_gets_suggestions_payload(self) -> None:
        self.login_as("admin")
        db = self.session_factory()
        db.add(ChatQueryLog(user_id="1", message="宿舍空调怎么样", intent="search", keyword="宿舍空调", hit_count=0, created_at=datetime.utcnow()))
        db.commit()
        db.close()

        response = self.client.get("/api/admin/keyword-suggestions?days=30&top=5")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["code"], 0)
        data = body["data"]
        self.assertEqual(data["suggestions"][0]["keyword"], "宿舍空调")
        self.assertIn("meta", data)

    def test_empty_data_returns_empty_list(self) -> None:
        self.login_as("admin")
        response = self.client.get("/api/admin/keyword-suggestions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["suggestions"], [])


if __name__ == "__main__":
    unittest.main()
