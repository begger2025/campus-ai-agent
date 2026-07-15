"""提示词的结构契约：报告体保留栏目，聊天口吻不许被共享提示词绑架。

## 为什么（2026-07-13 用户反馈，截图实证）

用户问「你觉得学生产生这些负面情绪，谁应该背锅」——一个彻头彻尾的聊天式问题，
得到的回答却带着 热点概括/情绪倾向/风险等级/建议关注点 的完整栏目骨架。

根因是一个提示词矛盾：共享的 SYSTEM_PROMPT 写死了

    「输出要包含：热点概括、主要观点、情绪倾向、风险等级、风险依据、建议关注点」

它对**每一个**走 build_report_messages 的回答生效——哪怕观点问答的意图指令
明说了"不要写成舆情简报"。模型夹在两条矛盾指令中间，折中成"聊天的开头 +
汇报的骨架"，就是用户看到的那股生硬劲。

## 契约

- **结构要求属于意图指令，不属于共享系统提示词。** SYSTEM_PROMPT 只管地基：
  只基于数据、不编造、不画像、数据不足要明说、Markdown 层级、注入围栏。
- **简报（report）保留完整栏目**——报告体本来就该有固定结构，它在
  REPORT_INSTRUCTION 里。
- **观点问答（opinion_answer）答其所问**——问什么答什么，不套栏目。
"""

from __future__ import annotations

import unittest

from backend.services.intent_router import ROUTER_SYSTEM_PROMPT
from backend.services.llm_client import SYSTEM_PROMPT
from backend.services.opinion_chat_service import _ANSWER_INTENTS, REPORT_INSTRUCTION


REPORT_SECTIONS = ("热点概括", "主要观点", "情绪倾向", "风险等级", "风险依据", "建议关注点")


class SystemPromptStaysStructureFreeTests(unittest.TestCase):
    def test_the_shared_system_prompt_does_not_force_report_sections(self):
        """六段式栏目是简报的结构，不是每个回答的结构——不许写进共享系统提示词。"""

        self.assertNotIn(
            "输出要包含",
            SYSTEM_PROMPT,
            "共享系统提示词又开始给所有回答套栏目了——"
            "「谁该背锅」这种聊天式提问会重新变回工作汇报",
        )
        for section in ("风险依据", "建议关注点"):
            self.assertNotIn(section, SYSTEM_PROMPT, f"栏目「{section}」应该只出现在简报指令里")

    def test_the_grounding_rules_survive(self):
        """减负只减结构，地基一条不许丢。"""

        for rule in ("不要编造", "不做个人画像", "数据不足", "<data>", "三级标题"):
            self.assertIn(rule, SYSTEM_PROMPT, f"系统提示词的地基规则「{rule}」被误删了")

    def test_the_agent_stays_on_the_campus_opinion_theme(self):
        """通用性提升的是对话形态，不是话题范围——域外请求要礼貌拒答并引导回舆情。"""

        self.assertIn("无关", SYSTEM_PROMPT, "系统提示词需要一条域内守则：无关请求怎么处置")
        self.assertIn("引导回", SYSTEM_PROMPT, "处置方式（礼貌说明并引导回舆情话题）必须写明")


class ReportKeepsItsSectionsTests(unittest.TestCase):
    def test_the_formal_report_still_has_all_sections(self):
        """报告体的完整栏目转移到 REPORT_INSTRUCTION，一个都不能少。"""

        for section in REPORT_SECTIONS:
            self.assertIn(section, REPORT_INSTRUCTION, f"简报栏目「{section}」丢了")


class OpinionAnswerIsConversationalTests(unittest.TestCase):
    def test_opinion_answers_are_told_to_answer_the_question_asked(self):
        instruction = _ANSWER_INTENTS["opinion_answer"]["instruction"]

        self.assertIn("答其所问", instruction, "观点问答的指令必须要求围绕用户的问题组织回答")
        self.assertNotIn("热点概括", instruction, "观点问答不许被套简报栏目")


class RouterTopicExtractionTests(unittest.TestCase):
    """路由提示词的话题契约（2026-07-15 真库实测）。

    「请给我一份宿舍搬迁舆情简报」被 LLM 路由判成 topic=global、keyword 空——
    因为 global 的定义里写着「或没有上一轮话题」，而新对话第一句必然没有上一轮，
    模型就把点名了话题的句子也判成了 global。空 keyword 一路传下去：
    payload 塞进全量 8 个事件，关联事件卡弹出一堆与提问毫无关系的内容。
    """

    def test_naming_a_topic_is_switch_even_on_the_first_turn(self):
        self.assertIn(
            "点名",
            ROUTER_SYSTEM_PROMPT,
            "提示词必须教会模型：本句点名了具体话题就是 switch，与有没有上一轮无关",
        )
        self.assertIn(
            "宿舍搬迁舆情简报",
            ROUTER_SYSTEM_PROMPT,
            "要带上实测踩过坑的那个例句——「请给我一份宿舍搬迁舆情简报」→ switch + 宿舍搬迁",
        )

    def test_explicit_web_requests_are_taught_to_route_to_complex(self):
        """「联网查X」必须进 complex_analysis——web_search 工具只在 ReAct 循环里，
        路由错了用户的显式联网请求就石沉大海。"""

        self.assertIn("联网", ROUTER_SYSTEM_PROMPT)

    def test_global_no_longer_hinges_on_missing_history_alone(self):
        self.assertNotIn(
            "或没有上一轮话题",
            ROUTER_SYSTEM_PROMPT,
            "「没有上一轮话题 → global」把对话第一句全部推成了 global——"
            "点名话题的第一句也会被判 global、keyword 置空（实测）",
        )


if __name__ == "__main__":
    unittest.main()
