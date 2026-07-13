"""ReAct 循环的调用预算必须是**有界的**。

原实现的漏洞（backend/services/react_loop.py）：

    while actions_used < budget:
        result = call_llm(messages, ...)          # 每轮一次 LLM
        data = extract_json_object(result.content)
        if not isinstance(data, dict):
            consecutive_bad += 1
            if consecutive_bad >= 2:
                return ...                        # 只挡"连续"两次坏 JSON
            ...
            continue                              # ← 没有 actions_used += 1
        consecutive_bad = 0                       # ← 一次好 JSON 就清零

坏 JSON 那条路 `continue` 了但**不消耗预算**，而 `consecutive_bad` 又被下一轮的好 JSON
清零。于是"坏-好-坏-好-坏-好…"这个模式**永远触发不了 `>= 2` 的熔断**，也永远不推进
`actions_used`——LLM 调用次数可以远超 budget。

按实测单次 6.7 秒算，budget=5 本该封顶 6 次调用（约 45s），坏 JSON 交替时能翻到 12 次
（约 78s）。用户等的就是这个。

修法：**按 LLM 调用次数封顶**，而不是只按成功的工具动作数封顶。
"""

from __future__ import annotations

import unittest
from unittest import mock

from backend.services import react_loop
from backend.services.llm_client import LlmCallResult
from backend.services.react_loop import ReactTool, run_react


def _tools() -> dict[str, ReactTool]:
    return {
        "hotspots": ReactTool(
            name="hotspots",
            description="按关键词聚合热点事件",
            run=lambda action_input: {"keyword": action_input.get("keyword", ""), "events": []},
        ),
    }


class _ScriptedLlm:
    """按脚本依次返回内容；记录被调用了多少次。"""

    def __init__(self, *replies: str, tail: str = "") -> None:
        self.replies = list(replies)
        self.tail = tail
        self.calls = 0

    def __call__(self, _messages, **_kwargs) -> LlmCallResult:
        self.calls += 1
        content = self.replies.pop(0) if self.replies else self.tail
        return LlmCallResult(content=content, attempts=1)


_GOOD_ACTION = '{"thought": "查一下", "action": "hotspots", "action_input": {"keyword": "宿舍"}}'
_BAD = "这不是 JSON，我先说点别的想法……"
_FINAL = '{"thought": "够了", "final_answer": "结论"}'


class ReactBudgetTests(unittest.TestCase):
    def test_alternating_bad_and_good_json_cannot_exceed_the_call_budget(self):
        """坏-好-坏-好…必须撞到硬上限，不能无限绕过预算。"""

        # 每个"好"动作的 keyword 都不同，避免撞上 repeated_action 提前熔断——
        # 这样才能真正压测预算本身。
        script: list[str] = []
        for i in range(40):
            script.append(_BAD)
            script.append(
                '{"thought": "查", "action": "hotspots", "action_input": {"keyword": "话题%d"}}' % i
            )
        llm = _ScriptedLlm(*script, tail=_FINAL)

        with mock.patch.object(react_loop, "call_llm", side_effect=llm):
            run_react("对比很多话题", tools=_tools(), max_steps=5)

        # budget=5 个成功动作 + 有界的坏 JSON 重试 + 1 次收尾。
        # 原实现这里会打到 40+ 次；任何 <= 10 的硬上限都算修好了。
        self.assertLessEqual(
            llm.calls,
            10,
            f"坏 JSON 绕过了步数预算：打了 {llm.calls} 次 LLM。"
            f"按实测 6.7s/次，这就是用户多等的一分钟",
        )

    def test_a_well_behaved_run_still_gets_its_full_step_budget(self):
        """修预算不能误伤正常路径：5 步预算就该允许 5 次工具调用。"""

        script = [
            '{"thought": "查", "action": "hotspots", "action_input": {"keyword": "话题%d"}}' % i
            for i in range(5)
        ]
        llm = _ScriptedLlm(*script, tail=_FINAL)

        with mock.patch.object(react_loop, "call_llm", side_effect=llm):
            result = run_react("复杂问题", tools=_tools(), max_steps=5)

        actions = [step for step in result.steps if step.action]
        self.assertEqual(len(actions), 5, "正常路径必须能用满 5 步预算")

    def test_an_early_final_answer_still_short_circuits(self):
        """模型想清楚了就直接作答——这是 ReAct 省时间的正常方式，不能被改坏。"""

        llm = _ScriptedLlm(_FINAL)
        with mock.patch.object(react_loop, "call_llm", side_effect=llm):
            result = run_react("简单问题", tools=_tools(), max_steps=5)

        self.assertEqual(result.answer, "结论")
        self.assertEqual(result.stop_reason, "answered")
        self.assertEqual(llm.calls, 1, "一次就答出来了，不该多打 LLM")

    def test_two_consecutive_bad_json_still_bails_out(self):
        """模型彻底卡住（连着吐坏 JSON）时的熔断不能丢。"""

        llm = _ScriptedLlm(_BAD, _BAD, tail=_BAD)
        with mock.patch.object(react_loop, "call_llm", side_effect=llm):
            result = run_react("问题", tools=_tools(), max_steps=5)

        self.assertEqual(result.stop_reason, "llm_error")
        self.assertLessEqual(llm.calls, 3, "连续坏 JSON 应该很快熔断，不该一直重试")


if __name__ == "__main__":
    unittest.main()
