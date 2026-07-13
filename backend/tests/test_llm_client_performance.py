"""LLM 客户端的两个性能/安全前提：连接复用 与 缓存的线程安全。

这两件事本来只是"慢一点"，但**事件流水线并行化之后它们会变成正确性问题**，
所以先在这里钉死：

1. **连接池**。原实现在 ``_send_chat_completion`` 里 ``with httpx.Client(...)``，
   每次调用新建 + 关闭一个客户端，于是每次调用都要重做一遍 TCP + TLS 握手。
   一次复杂提问会打 7~12 次 LLM，握手开销乘以 12。

2. **缓存写入的线程安全**。原实现的 ``JsonLlmCache.set`` 会把**整个** entries
   字典重新序列化、覆写整个文件（当前 data/llm_cache.json 已 138KB）。
   单线程时只是慢；一旦 8 个线程并发研判事件，两个 ``set`` 交错就会写出
   **半个 JSON**——下次启动 ``_load`` 解析失败，静默返回 {}，**整个缓存丢光**。
   ``temperature=0 + 缓存`` 是消融实验可复现的前提，缓存丢了实验就没法复现。

3. **计数器的线程安全**。``_usage["calls"] += 1`` 不是原子操作（读-改-写三步），
   并发下会丢计数。token 计费数字是答辩材料的一部分，不能是错的。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from backend.services import llm_client
from backend.services.llm_client import JsonLlmCache, LlmEndpoint, call_llm, reset_llm_usage


class _FakeCompletions:
    def create(self, **_kwargs):
        message = mock.Mock(content="ok")
        return mock.Mock(choices=[mock.Mock(message=message)], usage=None)


class _FakeOpenAI:
    last_kwargs: dict = {}

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs
        self.chat = mock.Mock(completions=_FakeCompletions())


class HttpConnectionPoolTests(unittest.TestCase):
    """同一个 httpx 客户端必须跨调用复用，否则每次调用都重做 TLS 握手。"""

    def setUp(self) -> None:
        llm_client.reset_http_clients()
        self.endpoint = LlmEndpoint(api_key="k", base_url="https://example.test/v1", model="m")

    def tearDown(self) -> None:
        llm_client.reset_http_clients()

    def _send_once(self):
        with mock.patch.dict("sys.modules", {"openai": mock.Mock(OpenAI=_FakeOpenAI)}):
            llm_client._send_chat_completion([{"role": "user", "content": "hi"}], None, self.endpoint)
        return _FakeOpenAI.last_kwargs["http_client"]

    def test_the_same_http_client_is_reused_across_calls(self):
        first = self._send_once()
        second = self._send_once()
        self.assertIs(
            first,
            second,
            "两次调用必须复用同一个 httpx 客户端；每次新建就是每次重做 TCP+TLS 握手",
        )

    def test_the_pooled_client_is_left_open_for_the_next_call(self):
        client = self._send_once()
        self.assertFalse(
            client.is_closed,
            "池化的客户端不能在调用结束时被关掉，否则连接池等于没有",
        )

    def test_switching_trust_env_still_yields_a_correctly_configured_client(self):
        """池化不能把 LLM_HTTP_TRUST_ENV 冻住——改了配置必须拿到新语义的客户端。"""

        with mock.patch.object(llm_client, "LLM_HTTP_TRUST_ENV", False):
            direct = self._send_once()
        with mock.patch.object(llm_client, "LLM_HTTP_TRUST_ENV", True):
            proxied = self._send_once()

        self.assertFalse(direct.trust_env, "默认必须直连")
        self.assertTrue(proxied.trust_env, "显式开启后必须走代理")
        self.assertIsNot(direct, proxied, "两种语义不能共用同一个客户端")


class CacheSingletonTests(unittest.TestCase):
    """缓存必须只从磁盘加载一次，而不是每次 call_llm 都把 138KB 重读一遍。"""

    def tearDown(self) -> None:
        llm_client.reset_cache()

    def test_the_cache_is_loaded_once_not_rebuilt_on_every_call(self):
        llm_client.reset_cache()
        with mock.patch.object(llm_client, "LLM_CACHE_ENABLED", True):
            first = llm_client._default_cache()
            second = llm_client._default_cache()
        self.assertIs(
            first,
            second,
            "每次 call_llm 都新建 JsonLlmCache，等于每次调用都重读+重解析整个缓存文件",
        )

    def test_a_disabled_cache_still_returns_none(self):
        llm_client.reset_cache()
        with mock.patch.object(llm_client, "LLM_CACHE_ENABLED", False):
            self.assertIsNone(llm_client._default_cache())


class CacheThreadSafetyTests(unittest.TestCase):
    """并发写入不能写坏文件——事件流水线并行化之后这是硬要求。"""

    def test_concurrent_writes_leave_the_file_parseable_and_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            cache = JsonLlmCache(path)
            writes = 32

            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda i: cache.set(f"key-{i}", {"content": f"value-{i}"}), range(writes)))

            # 文件必须仍是合法 JSON——交错覆写会留下半个文件
            raw = path.read_text(encoding="utf-8")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                self.fail(f"并发写入把缓存文件写坏了（下次启动会静默丢光整个缓存）：{exc}")

            self.assertEqual(
                len(data),
                writes,
                "并发写入丢了条目：后写的整字典覆写盖掉了先写的",
            )
            for i in range(writes):
                self.assertEqual(data[f"key-{i}"]["content"], f"value-{i}")

    def test_a_reader_never_sees_a_half_written_file(self):
        """读者与写者并发时的三条硬要求。

        场景是真实的：``routers/agent_public.py`` 的状态接口会 read_text() 这个缓存
        文件，而事件流水线正用线程池并发写它。这里刻意把读压力调到最狠（两个线程紧
        循环读 60 次），比现实更极端。

        1. 读者永远读不到半个 JSON（原子替换的意义）；
        2. 写者永远不抛异常——缓存是优化，抢不到文件锁不该炸掉调用方；
        3. 争抢结束后，被放弃的那几轮**不会永久丢失**——因为每次写的都是整个字典，
           下一次成功的 set() 会把它们一并刷出去（自愈）。
        """

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            cache = JsonLlmCache(path)
            cache.set("seed", {"content": "x"})

            corrupt_reads: list[str] = []
            write_errors: list[str] = []
            writes = 40

            def write_many() -> None:
                for i in range(writes):
                    try:
                        cache.set(f"w-{i}", {"content": "y" * 500})
                    except Exception as exc:  # 契约：set 不该抛
                        write_errors.append(f"{type(exc).__name__}: {exc}")

            def read_many() -> None:
                for _ in range(60):
                    if not path.exists():
                        continue
                    try:
                        json.loads(path.read_text(encoding="utf-8"))
                    except json.JSONDecodeError as exc:
                        corrupt_reads.append(str(exc))
                    except OSError:
                        pass  # 读者自己撞上替换窗口是允许的，它可以重读

            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(write_many), pool.submit(read_many), pool.submit(read_many)]
                for future in futures:
                    future.result()

            self.assertEqual(corrupt_reads, [], f"读到了写了一半的缓存文件：{corrupt_reads[:2]}")
            self.assertEqual(write_errors, [], f"缓存写入把异常甩给了调用方：{write_errors[:2]}")

            # 自愈：争抢结束后再写一条，之前被放弃的那几轮必须一起落盘。
            self.assertTrue(cache.set("final", {"content": "z"}), "无争抢时写盘必须成功")
            data = json.loads(path.read_text(encoding="utf-8"))
            missing = [f"w-{i}" for i in range(writes) if f"w-{i}" not in data]
            self.assertEqual(missing, [], f"这些条目永久丢失了，自愈没生效：{missing[:5]}")


class CacheWriteFailureTests(unittest.TestCase):
    """缓存是优化，不是事实来源——写盘失败绝不能把已经付过钱的回答丢掉。"""

    def test_a_failing_cache_write_does_not_lose_the_answer(self):
        class ExplodingCache(JsonLlmCache):
            def get(self, key):  # 永远未命中，强制走真实调用
                return None

            def set(self, key, value):
                raise PermissionError("[WinError 5] 拒绝访问")

        with tempfile.TemporaryDirectory() as tmp:
            cache = ExplodingCache(Path(tmp) / "cache.json")

            def fake_send(_messages, _temperature, _endpoint=None):
                return "模型的回答", {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}

            with mock.patch.object(llm_client, "_send_chat_completion", side_effect=fake_send):
                result = call_llm([{"role": "user", "content": "x"}], cache=cache)

        self.assertEqual(
            result.content,
            "模型的回答",
            "缓存写盘失败把 LLM 的回答一起丢了——token 已经花了，答案却没送到用户手上",
        )
        self.assertEqual(result.error, "", "缓存写盘失败不该被当成 LLM 调用失败")


class UsageCounterThreadSafetyTests(unittest.TestCase):
    """token / 调用次数是答辩材料的一部分，并发下不能丢计数。"""

    def test_call_counts_are_exact_under_concurrency(self):
        reset_llm_usage()
        calls = 64

        def fake_send(_messages, _temperature, _endpoint=None):
            return "ok", {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

        with mock.patch.object(llm_client, "_send_chat_completion", side_effect=fake_send):
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda _: call_llm([{"role": "user", "content": "x"}], cache=None), range(calls)))

        usage = llm_client.get_llm_usage()
        self.assertEqual(usage["calls"], calls, "`_usage['calls'] += 1` 不是原子操作，并发下会丢计数")
        self.assertEqual(usage["total_tokens"], calls * 15, "token 累加同样会丢")
        reset_llm_usage()


if __name__ == "__main__":
    unittest.main()
