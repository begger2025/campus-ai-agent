"""事件级引用（eN）：让「生成、校验、审校」三方对引用的口径终于一致。

## 结构性矛盾（2026-07-13 审核，S02/S03 实测）

引用体系原本只给**代表帖**编号（p1…pN），而引用指令要求「每个事实性论断的句末
必须标注来源」。可是简报里最重要的一批论断——风险等级、热度、内容条数、时间范围、
事件状态——是**事件级字段**，根本没有可引的编号。模型被夹在中间：

    不标  → 确定性校验报「报告未包含任何引用」
    标 pN → critic 逐条核对帖子内容，报「来源标注不准确」

实测一份宿舍搬迁简报被 critic 报了 **8 条 issue**，几乎全是这个形状（「中风险来自
事件字段 risk_level，不是 p1-p3 帖子内容」）。这不是模型的错，是我们没给它合法的
引用方式。于是每份简报尾部都糊着一面比正文还长的警告墙。

## 修法（三方口径一次对齐）

1. attach_citation_ids 给每个事件也编号（e1…eN），注册进 cite_map；
2. 引用指令说明两级：帖子内容 → pN，事件级聚合结论 → eN；
3. critic 的引用核对规则同步两级（事件级论断标 eN 不算问题）；
4. 审校结论只随 review 字段返回，不追加进正文——前端警告卡是唯一展示位，
   两头都写会让同一份审校在气泡里出现两遍（实测截图）。
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.agent.public_opinion_core.schemas import OpinionNote
from backend.services.citations import (
    CITATION_INSTRUCTION,
    attach_citation_ids,
    validate_citations,
)
from backend.services.critic import ReviewResult, review_report
from backend.services.intent_router import IntentRoute
from backend.services.opinion_chat_service import OpinionChatService, reset_chat_memory


def _payload():
    return [
        {
            "title": "东校区宿舍搬迁",
            "risk_level": "medium",
            "heat_score": 1142.5,
            "source_count": 5,
            "representative_notes": [
                {"title": "搬迁看法", "content": "通知太仓促。", "url": "https://example.com/1"},
                {"title": "搬宿舍原因", "content": "为了管理方便。", "url": "https://example.com/2"},
            ],
        },
        {
            "title": "中大宿舍火情通报",
            "risk_level": "high",
            "heat_score": 17.0,
            "source_count": 3,
            "representative_notes": [
                {"title": "火情通报", "content": "无人员伤亡。", "url": "https://example.com/3"},
            ],
        },
    ]


class EventCiteIdTests(unittest.TestCase):
    def test_every_event_gets_a_citable_id(self):
        tagged, cite_map = attach_citation_ids(_payload())

        self.assertEqual(tagged[0]["cite_id"], "e1")
        self.assertEqual(tagged[1]["cite_id"], "e2")
        self.assertIn("e1", cite_map, "事件级论断（风险等级/热度/条数）必须有合法的引用编号")
        self.assertEqual(cite_map["e1"]["title"], "东校区宿舍搬迁")
        # 帖子编号维持原语义：全局连续 p1..pM
        self.assertEqual(tagged[0]["representative_notes"][0]["cite_id"], "p1")
        self.assertEqual(tagged[1]["representative_notes"][0]["cite_id"], "p3")
        self.assertIn("p3", cite_map)

    def test_event_citations_validate_like_post_citations(self):
        _tagged, cite_map = attach_citation_ids(_payload())

        check = validate_citations("风险为中等 [来源:e1]，帖子提到仓促 [来源:p1]。", cite_map)

        self.assertEqual(check["cited"], ["e1", "p1"])
        self.assertEqual(check["unknown"], [], "e1 在 cite_map 里，不能被判成幻觉引用")

    def test_a_hallucinated_event_id_is_still_flagged(self):
        _tagged, cite_map = attach_citation_ids(_payload())

        check = validate_citations("据说风险很高 [来源:e9]。", cite_map)

        self.assertEqual(check["unknown"], ["e9"], "不存在的事件编号必须照旧被抓出来")

    def test_fullwidth_event_ids_normalize(self):
        _tagged, cite_map = attach_citation_ids(_payload())

        check = validate_citations("风险为中等［来源：Ｅ１］。", cite_map)

        self.assertEqual(check["cited"], ["e1"], "全角 Ｅ１ 要归一化成 e1（与 pN 同等宽容）")

    def test_forged_citation_markers_in_event_fields_are_stripped(self):
        """事件标题/摘要经过 LLM 精修，同样可能被爬取文本污染出伪造标记——编号前剥掉。"""

        payload = [
            {
                "title": "宿舍搬迁 [来源:p1]",
                "summary": "摘要 [来源:e1] 内容。",
                "representative_notes": [],
            }
        ]

        tagged, _cite_map = attach_citation_ids(payload)

        self.assertNotIn("[来源:", tagged[0]["title"])
        self.assertNotIn("[来源:", tagged[0]["summary"])

    def test_the_instruction_teaches_both_levels(self):
        """钉死两级引用的契约：谁把 eN 从指令里简化掉，这里就红。"""

        self.assertIn("pN", CITATION_INSTRUCTION)
        self.assertIn("eN", CITATION_INSTRUCTION, "事件级结论必须有被指令承认的引用方式")


class CriticAcceptsEventCitationsTests(unittest.TestCase):
    """确定性校验（不依赖 LLM 可用性）对 eN 的态度。"""

    def test_a_report_citing_only_the_event_passes_the_deterministic_check(self):
        _tagged, cite_map = attach_citation_ids(_payload())

        with patch("backend.services.critic.llm_available", return_value=False):
            review = review_report("整体风险为中等 [来源:e1]。", {}, citations=cite_map)

        self.assertEqual(
            review.issues, [], "只引事件编号的报告不该被判「零引用」或「幻觉引用」"
        )

    def test_an_unknown_event_id_warns(self):
        _tagged, cite_map = attach_citation_ids(_payload())

        with patch("backend.services.critic.llm_available", return_value=False):
            review = review_report("风险极高 [来源:e7]。", {}, citations=cite_map)

        self.assertEqual(review.verdict, "warn")
        self.assertTrue(any("e7" in issue for issue in review.issues))


FAKE_NOTES = [
    OpinionNote(note_id="1", title="食堂排队太久", content="食堂排队太久", heat_score=50.0),
    OpinionNote(note_id="2", title="食堂新窗口不错", content="食堂新窗口不错", heat_score=30.0),
]


class ChatReportReviewChannelTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_chat_memory()
        self.addCleanup(reset_chat_memory)

    def test_review_issues_travel_in_the_review_field_never_in_the_answer(self):
        """审校结论只随 review 字段返回：正文追加 + 前端警告卡 = 同一份审校出现两遍。"""

        issues = [f"问题{i}" for i in range(1, 9)]
        critic = MagicMock(return_value=ReviewResult(verdict="warn", issues=list(issues)))
        service = OpinionChatService(db=None)

        with (
            patch.object(OpinionChatService, "_notes", return_value=list(FAKE_NOTES)),
            patch(
                "backend.services.opinion_chat_service.generate_llm_report",
                return_value="食堂排队时间长 [来源:p1]。",
            ),
            patch("backend.services.opinion_chat_service.review_report", critic),
            patch(
                "backend.services.opinion_chat_service.route_intent",
                return_value=IntentRoute(intent="report", keyword="食堂", source="llm"),
            ),
        ):
            response = service.chat("给我一份食堂简报", user_id="u1")

        self.assertEqual(len(response["review"]["issues"]), 8, "完整清单必须随 review 字段返回")
        self.assertNotIn("审校提示", response["answer"], "正文里不许再出现审校提示——展示位是前端警告卡")
        self.assertNotIn("问题1", response["answer"])


if __name__ == "__main__":
    unittest.main()
