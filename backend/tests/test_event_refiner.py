"""事件精修的部署侧接线：把 ClusterRefiner 接到 call_llm（重试/缓存/用量计费白拿）。

核心包（llm_refine.py）只认识一个 Callable，不认识 HTTP、模型名和 API key——这里是把它
接上真实模型的那一层，也是唯一读 EVENT_LLM_* 配置的地方。

三件必须成立的事：
  1. **确定性**：temperature=0，且走 call_llm 的 JSON 缓存（同一批帖子第二次跑不再花钱）；
  2. **模型可单独指定**：EVENT_LLM_MODEL / _BASE_URL / _API_KEY，缺省回落到 OPENAI_*；
  3. **拿不到就返回 None**：未配 key、超时、返回垃圾——一律 None，核心退回 embedding 结果。

零网络：所有用例都把 call_llm / _send_chat_completion 换成假的。
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from backend.services import event_refiner, llm_client
from backend.services.llm_client import LlmCallResult


TEXTS = ["中山大学三大校区 哪个更好？", "中大作息调整引争议", "项飙讲座现场"]


def reply(payload: dict) -> LlmCallResult:
    return LlmCallResult(content=json.dumps(payload, ensure_ascii=False))


class RefinerAvailabilityTest(unittest.TestCase):
    def test_no_refiner_without_api_key(self) -> None:
        with mock.patch.object(event_refiner, "EVENT_LLM_API_KEY", ""):
            self.assertIsNone(event_refiner.get_cluster_refiner())

    def test_no_refiner_when_disabled(self) -> None:
        with (
            mock.patch.object(event_refiner, "EVENT_LLM_API_KEY", "sk-test"),
            mock.patch.object(event_refiner, "EVENT_REFINE_ENABLED", False),
        ):
            self.assertIsNone(event_refiner.get_cluster_refiner())

    def test_refiner_available_when_configured(self) -> None:
        with (
            mock.patch.object(event_refiner, "EVENT_LLM_API_KEY", "sk-test"),
            mock.patch.object(event_refiner, "EVENT_REFINE_ENABLED", True),
        ):
            self.assertIs(event_refiner.get_cluster_refiner(), event_refiner.refine_cluster_topics)


class RefinerCallTest(unittest.TestCase):
    def test_parses_topics_from_json_reply(self) -> None:
        payload = {
            "topics": [
                {"title": "校区与报考信息", "members": [1]},
                {"title": "作息调整争议", "members": [2]},
                {"title": "零散杂项帖", "members": [3], "miscellaneous": True},
            ]
        }
        with mock.patch.object(event_refiner, "call_llm", return_value=reply(payload)) as call:
            topics = event_refiner.refine_cluster_topics(TEXTS)

        self.assertEqual(topics, payload["topics"])
        kwargs = call.call_args.kwargs
        # 确定性：temperature=0，模型显式指定（不跟着 OPENAI_MODEL 漂）。
        self.assertEqual(kwargs["temperature"], 0)
        self.assertEqual(kwargs["model"], event_refiner.EVENT_LLM_MODEL)

    def test_prompt_numbers_the_posts_and_bans_boilerplate_titles(self) -> None:
        with mock.patch.object(event_refiner, "call_llm", return_value=reply({"topics": []})) as call:
            event_refiner.refine_cluster_topics(TEXTS)

        messages = call.call_args.args[0]
        prompt = "\n".join(message["content"] for message in messages)
        self.assertIn("相关讨论", prompt)  # 明令禁止的废话标题
        self.assertIn("1. 中山大学三大校区 哪个更好？", prompt)
        self.assertIn("3. 项飙讲座现场", prompt)
        self.assertIn("<data>", prompt)  # 采集内容当数据、不当指令

    def test_llm_error_returns_none(self) -> None:
        with mock.patch.object(event_refiner, "call_llm", return_value=LlmCallResult(error="Timeout")):
            self.assertIsNone(event_refiner.refine_cluster_topics(TEXTS))

    def test_unparseable_reply_returns_none(self) -> None:
        with mock.patch.object(event_refiner, "call_llm", return_value=LlmCallResult(content="话题一：食堂")):
            self.assertIsNone(event_refiner.refine_cluster_topics(TEXTS))

    def test_reply_without_topics_list_returns_none(self) -> None:
        with mock.patch.object(event_refiner, "call_llm", return_value=reply({"result": "ok"})):
            self.assertIsNone(event_refiner.refine_cluster_topics(TEXTS))


class RefinerEjectionTest(unittest.TestCase):
    """离群剔除的接线：模型的 unrelated 名单翻译成核心包认识的"剔除桶"。

    模型侧的 JSON 用一个顶层 `unrelated` 数组表达"这些帖子哪个话题都不属于"（比让它给一个
    假话题起名字更好答）；核心包的契约是一串话题项，因此在这里把它翻成
    {"members": [...], "unrelated": true} 追加进去。编号是否对得上真实帖子由核心包验。
    """

    def test_prompt_asks_the_model_to_name_posts_that_belong_to_no_topic(self) -> None:
        with mock.patch.object(event_refiner, "call_llm", return_value=reply({"topics": []})) as call:
            event_refiner.refine_cluster_topics(TEXTS)

        prompt = "\n".join(message["content"] for message in call.call_args.args[0])
        self.assertIn("unrelated", prompt)
        self.assertIn("不属于", prompt)
        # 保守：宁可留下一条边缘帖，也不要剔掉一条真实成员。
        self.assertIn("宁可", prompt)

    def test_unrelated_members_become_an_ejection_bucket(self) -> None:
        payload = {
            "topics": [
                {"title": "校区与报考信息", "members": [1]},
                {"title": "作息调整争议", "members": [2]},
            ],
            "unrelated": [3],
        }
        with mock.patch.object(event_refiner, "call_llm", return_value=reply(payload)):
            topics = event_refiner.refine_cluster_topics(TEXTS)

        self.assertEqual(topics[:2], payload["topics"])
        self.assertEqual(topics[-1], {"members": [3], "unrelated": True})

    def test_no_unrelated_key_keeps_the_old_shape(self) -> None:
        payload = {"topics": [{"title": "作息调整争议", "members": [1, 2, 3]}]}
        with mock.patch.object(event_refiner, "call_llm", return_value=reply(payload)):
            topics = event_refiner.refine_cluster_topics(TEXTS)

        self.assertEqual(topics, payload["topics"])

    def test_empty_or_malformed_unrelated_is_ignored(self) -> None:
        for unrelated in ([], "3", None):
            payload = {"topics": [{"title": "作息调整争议", "members": [1, 2, 3]}], "unrelated": unrelated}
            with mock.patch.object(event_refiner, "call_llm", return_value=reply(payload)):
                topics = event_refiner.refine_cluster_topics(TEXTS)
            self.assertEqual(topics, payload["topics"], f"unrelated={unrelated!r}")


class CallLlmModelOverrideTest(unittest.TestCase):
    """call_llm 要能按调用指定模型/端点，事件精修才能用 EVENT_LLM_MODEL 而不是全局 OPENAI_MODEL。"""

    def test_model_override_reaches_the_request_and_the_cache_key(self) -> None:
        seen: dict = {}

        def fake_send(messages, temperature, endpoint=None):
            seen["endpoint"] = endpoint
            return "{}", {}

        # 刻意用一个不等于 OPENAI_MODEL 的名字：.env 里两者当前相同，用真名断言等于没断言。
        other_model = f"not-{llm_client.OPENAI_MODEL}"
        with mock.patch.object(llm_client, "_send_chat_completion", fake_send):
            llm_client.call_llm(
                [{"role": "user", "content": "hi"}],
                temperature=0,
                cache=None,
                model=other_model,
                api_key="sk-event",
                base_url="https://events.example/v1",
            )

        self.assertEqual(seen["endpoint"].model, other_model)
        self.assertEqual(seen["endpoint"].api_key, "sk-event")
        self.assertEqual(seen["endpoint"].base_url, "https://events.example/v1")

        # 缓存键必须含模型：换模型还命中旧答案，等于拿另一个模型的结果冒充这次的。
        messages = [{"role": "user", "content": "hi"}]
        self.assertNotEqual(
            llm_client.build_cache_key(llm_client.OPENAI_MODEL, messages, 0),
            llm_client.build_cache_key(other_model, messages, 0),
        )

    def test_default_model_still_used_when_not_overridden(self) -> None:
        seen: dict = {}

        def fake_send(messages, temperature, endpoint=None):
            seen["endpoint"] = endpoint
            return "ok", {}

        with mock.patch.object(llm_client, "_send_chat_completion", fake_send):
            result = llm_client.call_llm([{"role": "user", "content": "hi"}], cache=None)

        self.assertEqual(result.content, "ok")
        self.assertEqual(seen["endpoint"].model, llm_client.OPENAI_MODEL)


if __name__ == "__main__":
    unittest.main()
