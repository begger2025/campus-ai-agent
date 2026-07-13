"""路由的第三个判断：topic——本轮和上一轮话题是什么关系。

## 为什么把话题连续性交给路由 LLM（2026-07-13 用户七轮实测）

「这句话还在不在聊刚才那件事」是**判断**，不是测量。规则闸门（指代词表）修好了
"泛问被旧话题绑架"，却在反方向留了洞——两句只差一个背景词的提问，答案天差地别：

    「你觉得搬迁宿舍为什么学生会产生负面的情绪」 → 聚焦搬迁，1 个事件 ✓
    「你觉得为什么学生会产生负面的情绪」         → 检索全部，8 个事件 ✗
      （用户刚聊完搬迁——人类都知道这是同一个问题，指代词表不知道）

还有"提取即跳台"：「关键是我搬到的**新宿舍**条件更差」——句子里出现新名词就
覆盖话题记忆，但用户根本没换话题。

于是路由的输出从 {intent, keyword} 扩成 {intent, keyword, topic}：

    continue：延续上一轮话题（即使没有指代词、即使句中出现新名词）
    switch  ：明确转向新话题（此时 keyword 给新词）
    global  ：与单一话题无关的全局提问（最近有什么热点）

规则层的角色不变：抢答路径只处理它全懂的自足短句（keyword 有则 switch、无则
global）；LLM 挂掉时的兜底路由退回指代词表近似（is_follow_up）。
"""

from __future__ import annotations

import unittest

from backend.services import intent_router
from backend.services.intent_router import (
    IntentRoute,
    ROUTER_SYSTEM_PROMPT,
    _confident_rule_route,
    _parse_llm_route,
    _route_by_rules,
)


class ParseTopicTests(unittest.TestCase):
    def test_a_valid_topic_is_read_from_the_llm_reply(self):
        route = _parse_llm_route('{"intent": "opinion_answer", "keyword": "", "topic": "continue"}')

        self.assertEqual(route.topic, "continue")

    def test_an_invalid_topic_degrades_to_unspecified(self):
        """模型编了个不存在的值 -> 置空，由调用方按规则近似（不硬信模型）。"""

        route = _parse_llm_route('{"intent": "search", "keyword": "食堂", "topic": "banana"}')

        self.assertEqual(route.topic, "")

    def test_a_missing_topic_degrades_to_unspecified(self):
        route = _parse_llm_route('{"intent": "search", "keyword": ""}')

        self.assertEqual(route.topic, "")


class RuleRouteTopicTests(unittest.TestCase):
    def test_a_zero_keyword_fast_path_is_global(self):
        """「最近有什么热点？」——规则抢答的泛问，topic 必须是 global。"""

        route = _confident_rule_route("最近有什么热点？")

        self.assertIsNotNone(route)
        self.assertEqual(route.topic, "global")

    def test_a_keyword_fast_path_is_a_switch(self):
        route = _confident_rule_route("食堂有什么风险")

        self.assertIsNotNone(route)
        self.assertEqual(route.keyword, "食堂")
        self.assertEqual(route.topic, "switch")

    def test_the_degraded_fallback_approximates_with_follow_up_signals(self):
        """LLM 挂掉时的兜底路由：有指代词 -> continue，否则 global（老行为的近似）。"""

        self.assertEqual(_route_by_rules("再展开讲讲").topic, "continue")
        self.assertEqual(_route_by_rules("有什么新动态").topic, "global")
        self.assertEqual(_route_by_rules("食堂怎么样").topic, "switch")


class RouterPromptContractTests(unittest.TestCase):
    def test_the_prompt_asks_for_the_topic_field(self):
        self.assertIn('"topic"', ROUTER_SYSTEM_PROMPT, "路由提示词必须要求输出 topic 字段")
        for value in ("continue", "switch", "global"):
            self.assertIn(value, ROUTER_SYSTEM_PROMPT)

    def test_the_prompt_teaches_continue_without_pronouns(self):
        """continue 的定义必须覆盖"没有指代词/出现新名词"的情况——那正是规则学不会的。"""

        self.assertIn("即使", ROUTER_SYSTEM_PROMPT)

    def test_statements_and_advice_seeking_are_not_risk_analysis(self):
        """「新宿舍条件更差」「我能和辅导员反馈吗」是陈述/求助——不许被归进风险预警。"""

        self.assertIn("陈述", ROUTER_SYSTEM_PROMPT, "路由提示词要教模型识别陈述/求助类话语")


if __name__ == "__main__":
    unittest.main()
