from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import json

from backend.admin_models import User
from backend.database import Base, get_db
from backend.main import app
from backend.models import ChatQueryLog, EventPostLink, ProcessedPost, PublicEvent
from backend.services.auth_service import get_current_user
from backend.services.keyword_suggestion_adapter import _parse_top_tags, get_keyword_suggestions

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


class TagCountFloorTest(unittest.TestCase):
    """**出现一次的标签是噪音，不是信号**（纯函数，零 DB、零网络）。

    线上实测的两份真实分布：

        《中大杰青实名举报》 学术(3) 热点(1) 新闻(1) 热点新闻事件(1) 社会新闻(1)
                            学术论文(1) 真实案件(1) 医学(1) 上海(1) 广州(1)
        《中大火箭试验成功》 宿舍(1)          ← 它**唯一**的标签

    count 就是"有几条成员帖带这个标签"。count=1 意味着**全事件只有一个发帖人**打过它——
    那是他一个人的 hashtag 习惯，不是"这件事值得拿这个词去搜"的证据。「学术」(3) 是信号，
    「上海」(1) 不是。

    **为什么不是"占最大值的比例"（share-of-max）而是绝对下限。** 火箭事件把这条路堵死了：
    它的 max_count 本身就是 1，宿舍(1)/1 = **1.0**，任何 share 阈值都给它满分。分母是 1 的
    比例说明不了任何事。所以门槛必须是绝对的：**至少 2 条成员帖带它**——两个互不相识的
    发帖人对同一件事都想到了同一个词，这是"标签能构成证据"的最小形态。
    （count/max_count 的**权重**照旧保留：它区分 学术(3) 和 大学宿舍(2)。门槛管"算不算证据"，
      权重管"有多像这件事"，两件事。）
    """

    def test_a_tag_only_one_poster_used_is_not_evidence(self) -> None:
        weights = _parse_top_tags(
            '[{"tag":"学术","count":3},{"tag":"医学","count":1},'
            '{"tag":"上海","count":1},{"tag":"广州","count":1}]'
        )
        self.assertEqual(weights, {"学术": 1.0})

    def test_an_event_whose_every_tag_appeared_once_offers_no_tag_at_all(self) -> None:
        """《中大火箭试验成功》的退化情形：唯一标签 宿舍(1)，max_count 也是 1。

        share-of-max 会给它 1.0（满分），把一个跟火箭毫无关系的「宿舍」挂到这件事上。
        绝对下限的答案是：**这个事件一个标签都提不出来**——一条帖子的一个 hashtag
        本来就不该左右爬取计划。（它的 source_keywords——真的拿去爬过的词——不受影响。）
        """

        self.assertEqual(_parse_top_tags('[{"tag":"宿舍","count":1}]'), {})

    def test_weight_is_still_counted_against_the_events_own_maximum(self) -> None:
        # 《东校区宿舍搬迁》：宿舍(5) 大学宿舍(2) 其余全是 1。分母仍是事件的 max=5，
        # 不是"过关者里的 max"——删掉噪音不该让剩下的词凭空涨分。
        weights = _parse_top_tags(
            '[{"tag":"宿舍","count":5},{"tag":"大学宿舍","count":2},{"tag":"高校","count":1}]'
        )
        self.assertEqual(weights, {"宿舍": 1.0, "大学宿舍": 0.4})

    def test_broken_or_empty_json_is_still_tolerated(self) -> None:
        self.assertEqual(_parse_top_tags("not-json"), {})
        self.assertEqual(_parse_top_tags(""), {})


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

    def test_tied_finished_at_prefers_run_with_output(self) -> None:
        """同毫秒完成的两次 run（零产出 + 有产出）→ 不判贫瘠，且与插入顺序无关。"""
        finished = _ms(NOW - timedelta(days=2))
        stored_by_platform = {"tieba": 0, "wb": 3}
        for order in (("tieba", "wb"), ("wb", "tieba")):
            with self.subTest(order=order):
                db = make_session_factory()()
                try:
                    db.execute(text(_HISTORY_DDL))
                    db.add(
                        ChatQueryLog(
                            user_id="7",
                            message="空调维修怎么样",
                            intent="opinion_answer",
                            keyword="空调维修",
                            hit_count=0,
                            created_at=NOW - timedelta(days=1),
                        )
                    )
                    for platform in order:
                        db.execute(
                            text(
                                "INSERT INTO crawler_run_history "
                                "(platform, source_keyword, started_at, finished_at, pages_fetched, items_seen, items_stored, stop_reason) "
                                "VALUES (:platform, :kw, :started, :finished, 1, 10, :stored, 'completed')"
                            ),
                            {
                                "platform": platform,
                                "kw": "空调维修",
                                "started": finished - 60_000,
                                "finished": finished,
                                "stored": stored_by_platform[platform],
                            },
                        )
                    db.commit()

                    data = get_keyword_suggestions(db, now=NOW)
                    suggestion = data["suggestions"][0]

                    # 有产出优先打破平局：不贫瘠，只按常规爬过降权（8.0×0.3=2.4）
                    self.assertEqual(data["meta"]["barren_count"], 0)
                    self.assertNotIn("无相关内容", suggestion["reason"])
                    self.assertAlmostEqual(suggestion["score"], 2.4, places=1)
                finally:
                    db.close()

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


class EventDrivenSuggestionsTest(unittest.TestCase):
    """adapter 把 public_events 接进选题器：算术那一半（事件加权）+ LLM 那一半（生成检索词）。

    零网络、零 MySQL：proposer 是注入的假货，事件躺在 SQLite 里，`now` 注入。
    """

    def setUp(self) -> None:
        self.db = make_session_factory()()
        self.addCleanup(self.db.close)

    def _publish_event(
        self,
        event_id: int,
        title: str,
        *,
        risk_level: str = "high",
        risk_score: float = 91.0,
        lifecycle: str = "ongoing",
        days_ago: float = 21.0,
        tags: dict[str, int] | None = None,
        status: str = "published",
        texts: list[str] | None = None,
    ) -> None:
        # tags 是 {标签: 有几条成员帖带它}——和 clustering._top_tags 落库的形状一致。
        # （原先的 fixture 把每个标签都写成 count=1，那正是本轮要修的噪音形态：
        #   一条帖子的一个 hashtag 冒充"这件事的特征"。）
        event_time = NOW - timedelta(days=days_ago)
        self.db.add(
            PublicEvent(
                id=event_id,
                event_key=f"evt_{event_id}",
                title=title,
                risk_level=risk_level,
                risk_score=risk_score,
                status=status,
                top_tags_json=json.dumps(
                    [{"tag": tag, "count": count} for tag, count in (tags or {}).items()],
                    ensure_ascii=False,
                ),
                source_keywords_json=json.dumps(["中山大学"], ensure_ascii=False),
                date_range_json=json.dumps(
                    {
                        "event_time": event_time.isoformat(),
                        "lifecycle": lifecycle,
                        "lifecycle_judgement": lifecycle,
                        "member_times": [event_time.isoformat()],
                    },
                    ensure_ascii=False,
                ),
                created_at=event_time,
            )
        )
        for index, text in enumerate(texts or [f"{title}的帖子正文"], start=1):
            post = ProcessedPost(
                raw_post_id=9000 + event_id * 10 + index,
                platform="xhs",
                title=text,
                source_keyword="中山大学",
                publish_time=event_time,
                created_at=event_time,
            )
            self.db.add(post)
            self.db.flush()
            self.db.add(
                EventPostLink(
                    event_id=event_id,
                    processed_post_id=post.id,
                    rank=index,
                    role="representative",
                )
            )

    def test_llm_proposes_a_keyword_that_exists_nowhere_in_the_corpus(self) -> None:
        """「学术不端」不在任何标题、标签、提问里——这正是现行 planner 结构上排不出的词。"""

        self._publish_event(
            20, "中大杰青实名举报", tags={"学术": 3, "热点": 1, "新闻": 1},
            texts=["耿同学杀疯了 继续举报中山大学另一位杰青"],
        )
        self.db.commit()

        seen: list[tuple] = []

        def proposer(title, texts, risk, lifecycle):
            seen.append((title, tuple(texts), risk, lifecycle))
            return {"keywords": ["学术不端", "论文造假", "校园生活"]}

        data = get_keyword_suggestions(self.db, now=NOW, keyword_proposer=proposer)
        by_kw = {s["keyword"]: s for s in data["suggestions"]}

        self.assertEqual(
            seen,
            [("中大杰青实名举报", ("耿同学杀疯了 继续举报中山大学另一位杰青",), "high", "ongoing")],
        )
        self.assertIn("学术不端", by_kw)
        self.assertIn("论文造假", by_kw)
        self.assertNotIn("校园生活", by_kw)  # 同一套黑名单拒掉它
        self.assertIn("event_llm", by_kw["学术不端"]["signals"])
        self.assertEqual(by_kw["学术不端"]["event_refs"][0]["title"], "中大杰青实名举报")
        self.assertEqual(by_kw["学术不端"]["event_refs"][0]["event_id"], "20")
        self.assertEqual(data["meta"]["event_count"], 1)
        self.assertEqual(data["meta"]["generated_keywords"], 2)
        self.assertEqual(data["meta"]["rejected_keywords"], 1)

    def test_the_scandal_outranks_the_canteen(self) -> None:
        """缺陷的原话：系统把学术不端丑闻定为头号事件，选题器还在推荐「食堂」。"""

        self.db.add(_post(1, "食堂", 3, 500))
        self.db.add(_post(2, "食堂", 3, 300))
        self._publish_event(20, "中大杰青实名举报", tags={"学术": 3})
        self.db.commit()

        data = get_keyword_suggestions(
            self.db, now=NOW, keyword_proposer=lambda *_: ["学术不端"]
        )
        keywords = [s["keyword"] for s in data["suggestions"]]

        self.assertEqual(keywords[0], "学术不端")
        self.assertIn("食堂", keywords)
        self.assertGreater(keywords.index("食堂"), keywords.index("学术不端"))

    def test_only_published_events_drive_the_planner(self) -> None:
        """人工闸门：草稿事件还没被管理员认可，不许它去左右爬取计划。"""

        self._publish_event(20, "中大杰青实名举报", tags={"学术": 3}, status="draft")
        self.db.commit()

        data = get_keyword_suggestions(
            self.db, now=NOW, keyword_proposer=lambda *_: ["学术不端"]
        )
        self.assertEqual(data["suggestions"], [])
        self.assertEqual(data["meta"]["event_count"], 0)

    def test_no_proposer_still_lets_the_arithmetic_half_work(self) -> None:
        self._publish_event(20, "中大杰青实名举报", tags={"学术": 3})
        self.db.commit()

        data = get_keyword_suggestions(self.db, now=NOW, keyword_proposer=None)
        by_kw = {s["keyword"]: s for s in data["suggestions"]}

        self.assertIn("学术", by_kw)                 # 事件标签照常进池
        self.assertNotIn("学术不端", by_kw)          # 但生不出新词
        self.assertEqual(by_kw["学术"]["signals"], ["event"])
        self.assertEqual(data["meta"]["generated_keywords"], 0)

    def test_proposer_blowing_up_degrades_to_a_warning(self) -> None:
        self._publish_event(20, "中大杰青实名举报", tags={"学术": 3})
        self.db.add(_post(1, "食堂", 3, 500))
        self.db.commit()

        def boom(*_):
            raise TimeoutError("api gateway timeout")

        data = get_keyword_suggestions(self.db, now=NOW, keyword_proposer=boom)
        keywords = [s["keyword"] for s in data["suggestions"]]

        self.assertIn("学术", keywords)   # 事件的算术那一路还在
        self.assertIn("食堂", keywords)   # 别的信号完全不受影响
        self.assertEqual(data["meta"]["generated_keywords"], 0)
        self.assertTrue(any("TimeoutError" in w for w in data["meta"]["warnings"]))

    def test_a_live_event_survives_a_fresh_crawl_but_a_resolved_one_does_not(self) -> None:
        self._publish_event(20, "中大杰青实名举报", lifecycle="ongoing", tags={"学术": 3})
        self._publish_event(
            77, "东校区宿舍火情", risk_level="high", risk_score=95.0,
            lifecycle="resolved", tags={"火情": 4},
        )
        # 两个词昨天都刚爬过
        for keyword in ("学术不端", "宿舍火情"):
            self.db.add(_post(hash(keyword) % 1000, keyword, 1, 10))
        self.db.commit()

        proposals = {"中大杰青实名举报": ["学术不端"], "东校区宿舍火情": ["宿舍火情"]}
        data = get_keyword_suggestions(
            self.db, now=NOW, keyword_proposer=lambda title, *_: proposals[title]
        )
        by_kw = {s["keyword"]: s for s in data["suggestions"]}

        # 悬而未决：新证据还在来，"昨天爬过"不构成理由 -> 事件项不降权
        self.assertIn("仍在发酵", by_kw["学术不端"]["reason"])
        # 已了结：不会再有新帖，"昨天爬过"是真的 -> 照常 ×0.3
        self.assertNotIn("仍在发酵", by_kw["宿舍火情"]["reason"])
        self.assertGreater(by_kw["学术不端"]["score"], by_kw["宿舍火情"]["score"])


    def test_single_use_hashtags_never_reach_the_board(self) -> None:
        """线上真实分布：学术(3) 才是这件事，上海(1)/广州(1)/医学(1) 是一个人的 hashtag 习惯。"""

        self._publish_event(
            20, "中大杰青实名举报",
            tags={"学术": 3, "热点": 1, "新闻": 1, "医学": 1, "上海": 1, "广州": 1},
        )
        self.db.commit()

        data = get_keyword_suggestions(
            self.db, now=NOW, keyword_proposer=lambda *_: ["学术不端", "实名举报"]
        )
        keywords = [s["keyword"] for s in data["suggestions"]]

        for noise in ("上海", "广州", "医学", "新闻", "热点"):
            self.assertNotIn(noise, keywords)
        # 学术(3) 照常进池（这里它被并入唯一包含它的「学术不端」）
        self.assertIn("学术不端", keywords)
        self.assertIn("实名举报", keywords)

    def test_an_events_only_tag_appearing_once_contributes_nothing(self) -> None:
        """《中大火箭试验成功》：唯一标签 宿舍(1)。它不该把「宿舍」挂到一件火箭的事上。"""

        self._publish_event(
            25, "中大火箭试验成功", risk_level="low", risk_score=10.0,
            lifecycle="not_applicable", tags={"宿舍": 1},
        )
        self.db.commit()

        data = get_keyword_suggestions(self.db, now=NOW, keyword_proposer=None)
        self.assertEqual([s["keyword"] for s in data["suggestions"]], [])

    def test_one_event_cannot_flood_the_board_with_paraphrases(self) -> None:
        """线上实测：《东校区宿舍搬迁》一件事占了 6 个席位（全是同一句话的不同说法）。"""

        self._publish_event(
            49, "东校区宿舍搬迁", risk_level="medium", risk_score=60.0, tags={"宿舍": 5},
        )
        self._publish_event(20, "中大杰青实名举报", tags={"学术": 3})
        self.db.commit()

        proposals = {
            "东校区宿舍搬迁": ["东校区宿舍搬迁", "强制搬宿舍", "同校区搬迁", "封闭管理", "搬宿舍 原因"],
            "中大杰青实名举报": ["杰青 举报", "实名举报", "副院长 质疑", "学术不端", "耿同学"],
        }
        data = get_keyword_suggestions(
            self.db, now=NOW, top=16, keyword_proposer=lambda title, *_: proposals[title]
        )
        by_event: dict[str, list[str]] = {}
        for suggestion in data["suggestions"]:
            for ref in suggestion["event_refs"]:
                by_event.setdefault(ref["title"], []).append(suggestion["keyword"])

        self.assertLessEqual(len(by_event["东校区宿舍搬迁"]), 3)
        # 而丑闻那件事的三个非要不可的词一个都不许少
        for must in ("学术不端", "实名举报", "杰青 举报"):
            self.assertIn(must, [s["keyword"] for s in data["suggestions"]])


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
