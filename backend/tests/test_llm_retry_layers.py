"""重试只能有一层：call_llm 自己管重试，SDK 的内层重试必须关掉。

## 为什么（实测事故，2026-07-13 审核）

openai SDK（2.41.1）构造客户端时**默认 max_retries=2**。而 call_llm 外层已经有
LLM_MAX_RETRIES=2（共 3 次尝试），两层叠乘后一次逻辑调用最坏要打 3×3=9 次真实请求：

    9 × 45 秒超时 ≈ 405 秒

实测（中转站拥堵当天）：「生成一份校园舆情简报」等了 **373.4 秒**才降级
（APITimeoutError）；一个 11 字符回复的探针调用花了 **192 秒**（外层 attempts=2，
说明 SDK 在每次外层尝试里又各自重试了）。用户以为系统挂了——其实是两层重试在
背着调用方翻倍烧时间。

重试策略必须收敛在 call_llm 一处（它有指数退避、有 NON_RETRYABLE_ERRORS 白名单、
有用量计费）；SDK 层一律 max_retries=0。
"""

from __future__ import annotations

import unittest
from unittest import mock

from backend.services.llm_client import _send_chat_completion, _send_chat_completion_stream


def _fake_response():
    message = mock.Mock()
    message.content = "ok"
    choice = mock.Mock()
    choice.message = message
    response = mock.Mock()
    response.choices = [choice]
    response.usage = None
    return response


class SdkRetryDisabledTests(unittest.TestCase):
    def test_the_blocking_client_does_not_retry_on_its_own(self):
        with mock.patch("openai.OpenAI") as openai_cls:
            openai_cls.return_value.chat.completions.create.return_value = _fake_response()
            _send_chat_completion([{"role": "user", "content": "hi"}], 0)

        self.assertEqual(
            openai_cls.call_args.kwargs.get("max_retries"),
            0,
            "SDK 默认 max_retries=2，会和 call_llm 的外层重试叠成 9 次真实请求"
            "（实测 373 秒才降级）——重试必须只由 call_llm 一层管",
        )

    def test_the_streaming_client_does_not_retry_on_its_own(self):
        with mock.patch("openai.OpenAI") as openai_cls:
            openai_cls.return_value.chat.completions.create.return_value = iter([])
            # 生成器要真的跑起来才会构造客户端
            list(_send_chat_completion_stream([{"role": "user", "content": "hi"}], 0))

        self.assertEqual(
            openai_cls.call_args.kwargs.get("max_retries"),
            0,
            "流式路径的重试窗口只在第一个字之前（call_llm_stream 管）——"
            "SDK 再叠一层重试会让用户在空屏前多等好几个 45 秒",
        )


if __name__ == "__main__":
    unittest.main()
