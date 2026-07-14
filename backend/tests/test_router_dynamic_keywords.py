"""路由话题词表的动态扩容：抢答覆盖率跟着语料走，不再靠手写。

## 为什么

规则抢答的第 4/5 关要求"话题词在表里 + 句子每个字都认得"，而 KNOWN_KEYWORDS
只有 9 个手写词——于是「宿舍搬迁有什么风险」这类**语料里明明有**的话题也要
白付一次 ~4 秒的分类 LLM。

播种关键词本身就是语料的话题词表：processed_posts.source_keyword 存的是
归一化后的话题词（「中山大学 宿舍搬迁」→「宿舍搬迁」），每爬一轮自动长出
新词。把它注入路由，抢答覆盖率就跟着语料走。

## 边界

- intent_router 在 sync 白名单里，必须保持可移植（不许 import 数据库）——
  词表通过 set_dynamic_keywords() **注入**，查库的活在部署侧
  backend/services/router_keywords.py。
- 含意图信号的词（如「风险监测」含「风险」）不进词表：话题词会先被消解，
  意图判定就少了一票，宁可漏收也不误判。
- 失败方向不变：词不在表里 → 交给 LLM（多付 4 秒），绝不会误答。
"""

from __future__ import annotations

import unittest
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import ProcessedPost
from backend.services import intent_router
from backend.services.intent_router import route_intent, set_dynamic_keywords
from backend.services.llm_client import LlmCallResult
from backend.services.router_keywords import refresh_router_keywords


class DynamicKeywordFastPathTests(unittest.TestCase):
    def setUp(self) -> None:
        set_dynamic_keywords([])
        self.addCleanup(set_dynamic_keywords, [])
        self.call_llm = mock.Mock(return_value=LlmCallResult(content='{"intent": "search", "keyword": ""}'))
        for patcher in (
            mock.patch.object(intent_router, "call_llm", self.call_llm),
            mock.patch.object(intent_router, "llm_available", return_value=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_dynamic_keyword_enables_the_fast_path(self) -> None:
        set_dynamic_keywords(["宿舍搬迁"])

        route = route_intent("宿舍搬迁有什么风险")

        self.assertEqual(route.source, "rules", "语料里的话题词应该让规则抢答，不再白付分类 LLM")
        self.assertEqual(route.intent, "risk_analysis")
        self.assertEqual(route.keyword, "宿舍搬迁")
        self.assertEqual(self.call_llm.call_count, 0)

    def test_without_the_dynamic_keyword_the_llm_still_pays(self) -> None:
        # 对照组：词不在表里 → 残余「搬迁」拦住抢答 → LLM 路由（既有失败方向不变）
        route_intent("宿舍搬迁有什么风险")

        self.assertEqual(self.call_llm.call_count, 1)

    def test_longest_match_wins_across_static_and_dynamic(self) -> None:
        # 静态表有「宿舍」，动态表有更长的「宿舍搬迁」——必须取长的，
        # 否则 keyword 被截成头词，检索 LIKE '%宿舍%' 会把搬迁淹掉。
        set_dynamic_keywords(["宿舍搬迁"])

        route = route_intent("宿舍搬迁有什么风险")

        self.assertEqual(route.keyword, "宿舍搬迁")

    def test_rule_fallback_also_sees_dynamic_keywords(self) -> None:
        # LLM 挂掉时的兜底路由同样受益——两条规则路径必须同词表。
        set_dynamic_keywords(["宿舍搬迁"])
        with mock.patch.object(intent_router, "llm_available", return_value=False):
            route = route_intent("宿舍搬迁有什么风险")

        self.assertEqual(route.keyword, "宿舍搬迁")
        self.assertEqual(self.call_llm.call_count, 0)


class RefreshFromCorpusTests(unittest.TestCase):
    """部署侧：从 processed_posts.source_keyword 刷出词表并注入。"""

    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[ProcessedPost.__table__])
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        set_dynamic_keywords([])
        self.addCleanup(set_dynamic_keywords, [])

    def _post(self, note_id: str, source_keyword: str, excluded: bool = False) -> None:
        self.db.add(
            ProcessedPost(
                note_id=note_id,
                raw_post_id=hash(note_id) % 100000,
                platform="xhs",
                title="t",
                content="c",
                source_keyword=source_keyword,
                excluded=excluded,
            )
        )

    def test_distinct_keywords_are_loaded_and_injected(self) -> None:
        self._post("a1", "宿舍搬迁")
        self._post("a2", "宿舍搬迁")  # 重复只算一次
        self._post("a3", "食堂涨价")
        self.db.commit()

        loaded = refresh_router_keywords(self.db)

        self.assertIn("宿舍搬迁", loaded)
        self.assertIn("食堂涨价", loaded)
        self.assertEqual(loaded.count("宿舍搬迁"), 1)

    def test_excluded_posts_do_not_contribute_keywords(self) -> None:
        # 被剔除的帖子不是语料——它的搜索词也不该扩进路由词表（剔除要切断所有下游）。
        self._post("b1", "床垫集采", excluded=True)
        self.db.commit()

        loaded = refresh_router_keywords(self.db)

        self.assertNotIn("床垫集采", loaded)

    def test_keywords_containing_intent_signals_are_skipped(self) -> None:
        # 「风险监测」含意图信号「风险」：进了词表会把意图词消解掉，宁可漏收。
        self._post("c1", "风险监测")
        self._post("c2", "校园热点")
        self._post("c3", "宿舍搬迁")
        self.db.commit()

        loaded = refresh_router_keywords(self.db)

        self.assertNotIn("风险监测", loaded)
        self.assertNotIn("校园热点", loaded)
        self.assertIn("宿舍搬迁", loaded)

    def test_qualifier_prefix_is_stripped_from_composite_keywords(self) -> None:
        # 老数据存的是组合形「中山大学 X」——话题是 X，不是整串。
        self._post("q1", "中山大学 东校宿舍搬迁")
        self.db.commit()

        loaded = refresh_router_keywords(self.db)

        self.assertIn("东校宿舍搬迁", loaded)
        self.assertNotIn("中山大学 东校宿舍搬迁", loaded)

    def test_degenerate_keywords_are_skipped(self) -> None:
        self._post("d1", "")  # 空
        self._post("d2", "水")  # 单字：太泛，误命中率高
        self._post("d3", "这是一个长得完全不像话题词的搜索串超过十二个字")  # 超长
        self._post("d4", "中山大学")  # 主题限定词本身，不是话题
        self.db.commit()

        loaded = refresh_router_keywords(self.db)

        self.assertEqual(loaded, [])

    def test_refresh_wires_the_fast_path_end_to_end(self) -> None:
        self._post("e1", "宿舍搬迁")
        self.db.commit()
        refresh_router_keywords(self.db)

        with mock.patch.object(intent_router, "llm_available", return_value=False):
            route = route_intent("宿舍搬迁有什么风险")

        self.assertEqual(route.keyword, "宿舍搬迁")

    def test_a_broken_query_leaves_the_static_table_intact(self) -> None:
        # 刷新失败（库抖动）→ 返回空列表且不清掉已注入的词——降级不降配。
        set_dynamic_keywords(["宿舍搬迁"])
        broken = mock.Mock()
        broken.query.side_effect = RuntimeError("db down")

        loaded = refresh_router_keywords(broken)

        self.assertEqual(loaded, [])
        with mock.patch.object(intent_router, "llm_available", return_value=False):
            route = route_intent("宿舍搬迁有什么风险")
        self.assertEqual(route.keyword, "宿舍搬迁", "刷新失败不该把上一次的词表清掉")


class RouterEndpointOverrideTests(unittest.TestCase):
    """路由分类可以指到更快的模型（ROUTER_LLM_* 环境变量），默认不设 = 行为不变。

    路由是 15 个 token 的分类活，却在为大模型付 ~4 秒——分类质量小模型足够。
    覆写只作用于路由调用，生成/审校仍走主端点。
    """

    def setUp(self) -> None:
        self.call_llm = mock.Mock(return_value=LlmCallResult(content='{"intent": "search", "keyword": ""}'))
        for patcher in (
            mock.patch.object(intent_router, "call_llm", self.call_llm),
            mock.patch.object(intent_router, "llm_available", return_value=True),
            mock.patch.object(intent_router, "RULE_FAST_PATH_ENABLED", False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_unset_env_keeps_the_default_endpoint(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=False):
            for name in ("ROUTER_LLM_MODEL", "ROUTER_LLM_API_KEY", "ROUTER_LLM_BASE_URL"):
                mock.patch.dict("os.environ", {name: ""}).start()
            route_intent("随便什么问题需要走LLM路由的那种")

        kwargs = self.call_llm.call_args.kwargs
        self.assertIsNone(kwargs.get("model"), "不设 ROUTER_LLM_MODEL 时必须走主端点（老行为）")
        self.assertIsNone(kwargs.get("api_key"))
        self.assertIsNone(kwargs.get("base_url"))

    def test_router_env_redirects_only_the_routing_call(self) -> None:
        env = {
            "ROUTER_LLM_MODEL": "glm-4-flash",
            "ROUTER_LLM_API_KEY": "test-key",
            "ROUTER_LLM_BASE_URL": "https://example.com/v4",
        }
        with mock.patch.dict("os.environ", env):
            route_intent("随便什么问题需要走LLM路由的那种")

        kwargs = self.call_llm.call_args.kwargs
        self.assertEqual(kwargs.get("model"), "glm-4-flash")
        self.assertEqual(kwargs.get("api_key"), "test-key")
        self.assertEqual(kwargs.get("base_url"), "https://example.com/v4")


if __name__ == "__main__":
    unittest.main()
