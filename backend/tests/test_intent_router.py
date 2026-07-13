"""意图路由的规则快路径：省掉一次 4.2 秒的分类 LLM，但**不能**把复杂问题降级成检索。

原实现每一个用户提问都先打一次 LLM 做意图分类：实测 4.2 秒、只产出 15 个 token。
"最近宿舍有什么风险吗"这种信号词明摆着的问题也要交这笔过路费。

现在规则**在高置信时**直接抢答。高置信的定义是四条同时成立（见 intent_router）：
短句 + 恰好 1 个意图信号 + 恰好 1 个已知话题词 + 没有对比/综合/追问信号。

这个文件真正要钉死的是**反向**的那一半——规则绝不能抢答下面三类问题：

1. **复杂/对比问题**（"对比食堂和宿舍哪个风险更高"）。``_route_by_rules`` 里根本没有
   complex_analysis 分支，规则如果无脑抢答，这类问题会掉进 search 兜底，
   ReAct 多步推理就等于被悄悄关掉了。
2. **指代式追问**（"再展开讲讲""刚才那个"）。规则读不懂指代，只有 LLM 能沿用 last_intent。
3. **话题词不在 KNOWN_KEYWORDS 里的问题**（"热水最近有什么风险吗"）。规则提不出 keyword
   就会返回空串，而 chat 层的 `routed.keyword or last_keyword` 会把它悄悄替换成**上一轮的
   旧话题**——用户问热水，答的是食堂。这比慢 4.2 秒糟糕得多。

所以下面的 LLM 断言全部是 call_count==1（必须付这笔钱），rules 断言全部是 call_count==0。
"""

from __future__ import annotations

import unittest
from unittest import mock

from backend.services import intent_router
from backend.services.intent_router import IntentRoute, route_intent
from backend.services.llm_client import LlmCallResult


# 规则能抢答的：短、单一话题、单一意图、无对比/追问信号，且**句子里没有规则读不懂的字**。
SIMPLE_QUESTIONS = {
    "最近宿舍有什么风险吗": ("risk_analysis", "宿舍"),
    "食堂有什么风险": ("risk_analysis", "食堂"),
    "中山大学最近有什么负面舆情": ("risk_analysis", "中山大学"),
    "作息调整有什么风险": ("risk_analysis", "作息调整"),
    "帮我生成一份食堂的舆情简报": ("report", "食堂"),
    "给宿舍出个总结报告": ("report", "宿舍"),
    "大家对食堂怎么看": ("opinion_answer", "食堂"),
    "同学们对课表有什么看法": ("opinion_answer", "课表"),
    "最近校庆的热点是什么": ("hotspots", "校庆"),
    "食堂现在讨论热度高吗": ("hotspots", "食堂"),
    "计算机学院最近有什么热门话题": ("hotspots", "计算机"),
}

# 复合话题：句子里的话题是"通用头词 + 具体事件"（宿舍**搬迁**、课表**调整**），而规则的
# 关键词表只有那个通用头词。抢答会把 keyword 截断成头词，检索 LIKE '%宿舍%' 把真正的
# 搬迁内容淹掉——比慢 4.2 秒糟糕得多。这类必须交给 LLM 去提取完整话题词。
COMPOUND_TOPIC_QUESTIONS = [
    "请给我一份宿舍搬迁舆情简报",  # 线上真实提问：LLM 提取的是"宿舍搬迁"，不是"宿舍"
    "宿舍热水有什么风险",
    "同学们对课表调整有什么看法",
    "大家对新生军训怎么看",
    "食堂涨价有什么负面评价",
    "珠海校区食堂有什么风险",
]

# 规则绝不能抢答的：对比多个话题 / 综合多类信息 / 需要分多步检索。
COMPLEX_QUESTIONS = [
    "对比食堂和宿舍哪个风险更高",
    "比较一下食堂和宿舍的舆情",
    "宿舍和食堂相比哪个负面舆情更多",
    "食堂和宿舍哪个更值得关注",
    "结合热点和风险给个整体判断",
    "综合分析一下食堂的热点和风险",
    "从热度和风险两个维度评估一下校庆",
    "先看看宿舍的风险，再看看食堂的热点",
    "食堂、宿舍、课表这几个话题的舆情如何",
    "把宿舍的风险和食堂的热点放在一起分析",
    "分别说说食堂和宿舍的风险",
    "食堂的热点和风险分别是什么",
]

# 指代式追问：规则读不懂"那个""再"指的是什么，必须让 LLM 沿用 last_intent。
FOLLOW_UP_QUESTIONS = [
    "再展开讲讲",
    "刚才那个再详细说说",
    "继续说",
    "上面提到的风险再展开一下",
    "那个话题的热点呢",
    "这个再具体点",
]

# 话题词不在 KNOWN_KEYWORDS 里：规则提不出 keyword，抢答会串台到上一轮的旧话题。
UNKNOWN_TOPIC_QUESTIONS = [
    "热水最近有什么风险吗",
    "军训的热点有哪些",
    "图书馆有什么负面评价",
    "快递站大家怎么看",
]


def _llm_reply(intent: str = "complex_analysis", keyword: str = "") -> LlmCallResult:
    return LlmCallResult(content=f'{{"intent": "{intent}", "keyword": "{keyword}"}}')


class IntentRouterTestBase(unittest.TestCase):
    """默认：LLM 可用 + call_llm 被打桩。于是 call_count 就是"这次提问花没花那 4.2 秒"。"""

    def setUp(self) -> None:
        self.call_llm = mock.Mock(return_value=_llm_reply())
        for patcher in (
            mock.patch.object(intent_router, "call_llm", self.call_llm),
            mock.patch.object(intent_router, "llm_available", return_value=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)


class RuleFastPathTest(IntentRouterTestBase):
    def test_simple_question_is_answered_by_rules_without_calling_llm(self) -> None:
        route = route_intent("最近宿舍有什么风险吗")

        self.assertEqual(route.intent, "risk_analysis")
        self.assertEqual(route.keyword, "宿舍")
        self.assertEqual(route.source, "rules")
        self.assertEqual(self.call_llm.call_count, 0)

    def test_all_simple_questions_skip_the_llm_with_right_intent_and_keyword(self) -> None:
        for message, (intent, keyword) in SIMPLE_QUESTIONS.items():
            with self.subTest(message=message):
                self.call_llm.reset_mock()
                route = route_intent(message)

                self.assertEqual(route.source, "rules")
                self.assertEqual(route.intent, intent)
                self.assertEqual(route.keyword, keyword)
                self.assertEqual(self.call_llm.call_count, 0)

    def test_overlapping_keyword_picks_the_longest_match(self) -> None:
        # KNOWN_KEYWORDS 同时有 "作息调整" 和 "作息"：两个都命中不等于两个话题，
        # 否则 "作息调整" 会被误判成多话题、白白丢掉一次抢答。
        route = route_intent("作息调整有什么风险")

        self.assertEqual(route.keyword, "作息调整")
        self.assertEqual(self.call_llm.call_count, 0)

    def test_fast_path_agrees_with_the_rule_fallback(self) -> None:
        # 抢答走的是和兜底同一张信号表，所以两条路径必须给出同一个答案——
        # 这是"LLM 不可用时行为不变"的前提。
        for message in SIMPLE_QUESTIONS:
            with self.subTest(message=message):
                fast = route_intent(message)
                fallback = intent_router._route_by_rules(message)

                self.assertEqual((fast.intent, fast.keyword), (fallback.intent, fallback.keyword))


class ComplexQuestionsStillGoToLlmTest(IntentRouterTestBase):
    def test_complex_questions_are_never_hijacked_by_rules(self) -> None:
        # 这是本次改造的核心风险：规则里没有 complex_analysis 分支，抢答=把 ReAct 关掉。
        self.call_llm.return_value = _llm_reply("complex_analysis", "")
        for message in COMPLEX_QUESTIONS:
            with self.subTest(message=message):
                self.call_llm.reset_mock()
                route = route_intent(message)

                self.assertEqual(self.call_llm.call_count, 1, "复杂问题必须进 LLM 路由")
                self.assertEqual(route.source, "llm")
                self.assertEqual(route.intent, "complex_analysis")

    def test_two_topics_defer_to_llm_even_without_comparison_words(self) -> None:
        # 没有"对比/比较"这类词，但并列了两个话题——仍然算复杂。
        route_intent("食堂宿舍的风险")

        self.assertEqual(self.call_llm.call_count, 1)

    def test_two_intent_signals_defer_to_llm(self) -> None:
        # 同时问热点和风险 = 综合多类信息，规则不许抢。
        route_intent("食堂的热点风险")

        self.assertEqual(self.call_llm.call_count, 1)

    def test_long_question_defers_to_llm(self) -> None:
        # 长度是兜底防线：信号词黑名单天然列不全，而复杂问题几乎总是更长。
        long_question = "宿舍" + "这件事情最近到底发展成什么样了我想知道具体情况" * 2 + "有风险吗"
        self.assertGreater(len(long_question), intent_router.RULE_FAST_PATH_MAX_CHARS)

        route_intent(long_question)

        self.assertEqual(self.call_llm.call_count, 1)


class FollowUpQuestionsStillGoToLlmTest(IntentRouterTestBase):
    def test_follow_up_questions_defer_to_llm(self) -> None:
        self.call_llm.return_value = _llm_reply("risk_analysis", "")
        for message in FOLLOW_UP_QUESTIONS:
            with self.subTest(message=message):
                self.call_llm.reset_mock()
                route = route_intent(message, last_keyword="宿舍", last_intent="risk_analysis")

                self.assertEqual(self.call_llm.call_count, 1, "追问要靠 LLM 沿用 last_intent")
                self.assertEqual(route.source, "llm")

    def test_follow_up_context_is_still_passed_to_llm(self) -> None:
        route_intent("再展开讲讲", last_keyword="宿舍", last_intent="risk_analysis")

        prompt = self.call_llm.call_args[0][0][-1]["content"]
        self.assertIn("宿舍", prompt)
        self.assertIn("risk_analysis", prompt)


class UnknownTopicGoesToLlmTest(IntentRouterTestBase):
    def test_question_without_known_keyword_defers_to_llm(self) -> None:
        # 规则的关键词表只有 9 个词。提不出 keyword 就抢答，chat 层会拿上一轮的旧话题
        # 顶上（`routed.keyword or last_keyword`）——用户问热水，答的是食堂。
        self.call_llm.return_value = _llm_reply("risk_analysis", "热水")
        for message in UNKNOWN_TOPIC_QUESTIONS:
            with self.subTest(message=message):
                self.call_llm.reset_mock()
                route = route_intent(message, last_keyword="食堂")

                self.assertEqual(self.call_llm.call_count, 1)
                self.assertEqual(route.source, "llm")

    def test_compound_topic_defers_to_llm(self) -> None:
        # 话题是"宿舍搬迁"而规则只认得"宿舍"：抢答会把话题截断成头词。
        self.call_llm.return_value = _llm_reply("report", "宿舍搬迁")
        for message in COMPOUND_TOPIC_QUESTIONS:
            with self.subTest(message=message):
                self.call_llm.reset_mock()
                route = route_intent(message)

                self.assertEqual(self.call_llm.call_count, 1, "复合话题必须让 LLM 提关键词")
                self.assertEqual(route.source, "llm")

    def test_real_logged_question_is_not_truncated_to_head_noun(self) -> None:
        # chat_query_log 里的真实提问。LLM 当时提取的 keyword 是 "宿舍搬迁"；
        # 规则若抢答只会给出 "宿舍"，检索 LIKE '%宿舍%' 会把搬迁内容淹没在宿舍日常里。
        # 这条是本次改造真正的护栏——前几道关（长度/对比/追问/计数）全都放行了它。
        message = "请给我一份宿舍搬迁舆情简报"

        self.assertIsNone(intent_router._confident_rule_route(message))
        self.assertEqual(intent_router._rule_residual(message, ["宿舍"]), "搬迁")

    def test_residual_content_word_blocks_the_fast_path(self) -> None:
        # "剩余量为空"这条关的直接单测：能消解干净的才抢答。
        self.assertEqual(intent_router._rule_residual("最近宿舍有什么风险吗", ["宿舍"]), "")
        self.assertEqual(intent_router._rule_residual("宿舍热水有什么风险", ["宿舍"]), "热水")


class LlmPathUnchangedTest(IntentRouterTestBase):
    def test_llm_route_keeps_source_llm(self) -> None:
        self.call_llm.return_value = _llm_reply("hotspots", "食堂")

        route = route_intent("最近学校里大家都在聊些什么呀")

        self.assertEqual(route, IntentRoute(intent="hotspots", keyword="食堂", source="llm"))

    def test_unparseable_llm_reply_falls_back_to_rules(self) -> None:
        self.call_llm.return_value = LlmCallResult(content="我觉得是热点")

        route = route_intent("最近学校里大家都在聊些什么呀")

        self.assertEqual(route.source, "rules")
        self.assertEqual(route.intent, "search")

    def test_unknown_intent_from_llm_falls_back_to_rules(self) -> None:
        self.call_llm.return_value = _llm_reply("chit_chat", "食堂")

        route = route_intent("这个学校怎么样呀")

        self.assertEqual(route.source, "rules")


class LlmUnavailableTest(unittest.TestCase):
    """没有 API key 时行为必须和改造前一致：全部回落规则，一次 LLM 都不打。"""

    def setUp(self) -> None:
        self.call_llm = mock.Mock(return_value=_llm_reply())
        for patcher in (
            mock.patch.object(intent_router, "call_llm", self.call_llm),
            mock.patch.object(intent_router, "llm_available", return_value=False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_simple_question_still_routed_by_rules(self) -> None:
        route = route_intent("最近宿舍有什么风险吗")

        self.assertEqual(
            route,
            # 规则抢答提取到话题词 = 用户在点名一个话题 -> topic="switch"
            IntentRoute(intent="risk_analysis", keyword="宿舍", source="rules", topic="switch"),
        )
        self.assertEqual(self.call_llm.call_count, 0)

    def test_complex_question_falls_back_to_rules_without_llm(self) -> None:
        # 没有 LLM 就没有 complex_analysis——这是改造前就有的降级，不是本次引入的。
        route = route_intent("对比食堂和宿舍哪个风险更高")

        self.assertEqual(route.source, "rules")
        self.assertEqual(route.intent, "risk_analysis")
        self.assertEqual(self.call_llm.call_count, 0)

    def test_follow_up_falls_back_to_rules_without_llm(self) -> None:
        route = route_intent("再展开讲讲")

        self.assertEqual(route.source, "rules")
        self.assertEqual(route.intent, "search")
        self.assertEqual(self.call_llm.call_count, 0)


class KillSwitchTest(IntentRouterTestBase):
    def test_disabling_fast_path_restores_llm_first_routing(self) -> None:
        with mock.patch.object(intent_router, "RULE_FAST_PATH_ENABLED", False):
            self.call_llm.return_value = _llm_reply("risk_analysis", "宿舍")
            route = route_intent("最近宿舍有什么风险吗")

        self.assertEqual(route.source, "llm")
        self.assertEqual(self.call_llm.call_count, 1)


class ReactStillReachableEndToEndTest(IntentRouterTestBase):
    """端到端护栏：复杂问题必须真的走到 ReAct，而不只是路由器嘴上说 complex_analysis。

    上面的路由单测证明 route_intent 会返回 complex_analysis；这里**不打桩 route_intent**，
    让 OpinionChatService 走真实路由，确认 run_react 真的被调用了——"ReAct 被悄悄关掉"
    是这次改造唯一不可接受的后果，值得用一条集成测试钉死。
    """

    def test_complex_question_reaches_react_through_the_real_router(self) -> None:
        from backend.services.opinion_chat_service import OpinionChatService, reset_chat_memory
        from backend.services.react_loop import ReactResult

        reset_chat_memory()
        self.addCleanup(reset_chat_memory)
        self.call_llm.return_value = _llm_reply("complex_analysis", "")
        react = mock.Mock(return_value=ReactResult(answer="对比结论", steps=[], stop_reason="answered"))

        service = OpinionChatService(db=None)
        with mock.patch.object(OpinionChatService, "_notes", return_value=[]), mock.patch(
            "backend.services.opinion_chat_service.run_react", react
        ):
            response = service.chat("对比食堂和宿舍哪个风险更高", user_id="u1")

        self.assertEqual(react.call_count, 1, "复杂问题必须进 ReAct 多步推理")
        self.assertEqual(response["intent"], "complex_analysis")
        self.assertEqual(response["route_source"], "llm")

    def test_simple_question_skips_react_and_skips_the_llm_router(self) -> None:
        from backend.services.opinion_chat_service import OpinionChatService, reset_chat_memory
        from backend.services.react_loop import ReactResult

        reset_chat_memory()
        self.addCleanup(reset_chat_memory)
        react = mock.Mock(return_value=ReactResult(answer="", steps=[], stop_reason="answered"))

        service = OpinionChatService(db=None)
        with mock.patch.object(OpinionChatService, "_notes", return_value=[]), mock.patch(
            "backend.services.opinion_chat_service.generate_llm_report", return_value="答案"
        ), mock.patch("backend.services.opinion_chat_service.run_react", react):
            response = service.chat("最近宿舍有什么风险吗", user_id="u1")

        self.assertEqual(response["intent"], "risk_analysis")
        self.assertEqual(response["route_source"], "rules")
        self.assertEqual(react.call_count, 0)
        self.assertEqual(self.call_llm.call_count, 0, "简单问题不该再为意图分类付 4.2 秒")


if __name__ == "__main__":
    unittest.main()


class GeneralQuestionFastPathTests(unittest.TestCase):
    """没有话题词的**泛问**同样可以规则抢答——"剩余量为空"这一关足以兜底。

    背景：原来第 4 关要求"恰好命中 1 个已知话题词"，于是"最近有什么热点？"（0 个话题词）
    被挡在快速路径外——而它正是 UI 上的头号示例问句，也是最常见的开场白。

    但这一关是多余的：真正扛事的是第 5 关（剩余量为空）。
        "最近有什么热点？"     → 消解完 最近/有/什么/热点/？ 后一个字不剩 → 规则真的看懂了
        "学术不端有什么风险吗"  → 消解完之后「学术不端」还杵着     → 规则不认识，交给 LLM
    泛问的正确 keyword 本来就是空串（LLM 路由给的也是空串），所以抢答与 LLM 的结论一致。
    """

    def _route(self, message: str):
        with mock.patch.object(intent_router, "call_llm") as fake_llm:
            fake_llm.return_value = mock.Mock(content='{"intent": "search", "keyword": "x"}')
            with mock.patch.object(intent_router, "llm_available", return_value=True):
                route = intent_router.route_intent(message)
        return route, fake_llm.call_count

    def test_a_general_hotspot_question_is_answered_by_rules(self):
        route, calls = self._route("最近有什么热点？")
        self.assertEqual(route.source, "rules", "UI 的头号示例问句还在白付 4.2 秒")
        self.assertEqual(route.intent, "hotspots")
        self.assertEqual(route.keyword, "", "泛问的话题词就该是空串——和 LLM 路由的结论一致")
        self.assertEqual(calls, 0)

    def test_a_general_report_request_is_answered_by_rules(self):
        route, calls = self._route("给我一份校园舆情简报")
        self.assertEqual(route.source, "rules")
        self.assertEqual(route.intent, "report")
        self.assertEqual(route.keyword, "")
        self.assertEqual(calls, 0)

    def test_an_unknown_topic_is_still_handed_to_the_llm(self):
        """这是放宽话题词数量之后**唯一**的新风险，必须由剩余量那一关拦住。

        「学术不端」不在 KNOWN_KEYWORDS 里。若规则拿 keyword="" 抢答，就会去检索**全部**
        事件而不是学术不端的事件——答非所问。而它恰恰是 LLM 选题生成出来的招牌词。
        """

        for message in ("学术不端有什么风险吗", "期末周大家怎么看", "实名举报的热点"):
            with self.subTest(message=message):
                route, calls = self._route(message)
                self.assertEqual(
                    route.source,
                    "llm",
                    f"「{message}」含规则不认识的话题词，抢答会检索全部事件、答非所问",
                )
                self.assertEqual(calls, 1)
