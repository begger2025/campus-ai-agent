"""Offline tests for the optional citation-only HTTP transport."""

from __future__ import annotations

import unittest

from backend.services.evidence.collector import SYSU_QUERY_CONTEXT
from backend.services.evidence.http_transport import (
    HttpTransportUnavailableError,
    OpenAICompatibleTransport,
    build_http_transports,
    parse_citation_response,
)
from backend.services.evidence.provider_adapters import glm_search_query
from backend.services.evidence.providers import SearchRequest


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def post(self, url, *, headers, json):
        self.calls.append((url, headers, json))
        return FakeResponse(self.payload)


class HttpTransportTests(unittest.IsolatedAsyncioTestCase):
    def test_parser_accepts_structured_citations_only(self):
        hits = parse_citation_response(
            {
                "id": "req-1",
                "model": "test-model",
                "citations": [
                    {
                        "url": "https://www.sysu.edu.cn/notice/1",
                        "title": "SYSU notice",
                        "quote": "Sun Yat-sen University published a notice.",
                        "publisher": "SYSU",
                    }
                ],
            },
            provider_id="deepseek",
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].provider, "deepseek")
        self.assertEqual(hits[0].request_id, "req-1")
        self.assertEqual(hits[0].metadata["publisher"], "SYSU")

    def test_parser_accepts_json_in_message_and_rejects_no_citation(self):
        payload = {
            "choices": [
                {
                    "message": {
                        "content": '{"citations":[{"url":"https://news.example/a","quote":"Sun Yat-sen University was mentioned.","title":"News"}]}'
                    }
                }
            ]
        }
        self.assertEqual(len(parse_citation_response(payload, provider_id="qwen")), 1)
        self.assertEqual(
            parse_citation_response(
                {"choices": [{"message": {"content": "No sources were found."}}]},
                provider_id="qwen",
            ),
            [],
        )

    async def test_client_receives_bearer_and_sysu_search_body(self):
        client = FakeClient(
            {
                "id": "req-2",
                "choices": [
                    {
                        "message": {
                            "content": '[Notice](https://www.sysu.edu.cn/notice/2)'
                        }
                    }
                ],
            }
        )
        transport = OpenAICompatibleTransport(
            "deepseek", "https://api.example/v1/chat/completions", "model-a", "secret-key", client
        )
        request = SearchRequest(
            provider="deepseek", model="model-a", query="SYSU campus notice", max_results=2
        )
        payload = await transport(request)
        self.assertEqual(payload["id"], "req-2")
        self.assertEqual(client.calls[0][1]["Authorization"], "Bearer secret-key")
        self.assertEqual(client.calls[0][2]["model"], "model-a")
        self.assertIn("SYSU", client.calls[0][2]["messages"][1]["content"])
        self.assertNotIn("secret-key", repr(transport))

    async def test_missing_client_is_offline(self):
        transport = OpenAICompatibleTransport(
            "qwen", "https://api.example/v1", "model-a", "secret-key"
        )
        request = SearchRequest(provider="qwen", query="q")
        with self.assertRaises(HttpTransportUnavailableError):
            await transport(request)

    async def test_glm_posts_the_standalone_web_search_contract(self):
        client = FakeClient({"search_result": []})
        transport = OpenAICompatibleTransport(
            "glm",
            "https://open.bigmodel.cn/api/paas/v4/web_search",
            None,
            "secret-key",
            client,
        )
        request = SearchRequest(provider="glm", query="中山大学 校园通知", max_results=3)
        await transport(request)
        url, headers, body = client.calls[0]
        self.assertEqual(url, "https://open.bigmodel.cn/api/paas/v4/web_search")
        self.assertEqual(headers["Authorization"], "Bearer secret-key")
        self.assertEqual(
            body, {"search_engine": "search_pro_bing", "search_query": "中山大学 校园通知"}
        )

    def test_glm_search_query_reduces_the_collectors_prompt_to_a_search_string(self):
        # web_search 是**搜索引擎**接口：search_query 就是检索词本身，不是提示词。
        # 把采集器那句上下文（"……校园公共信息与舆情；仅返回……可引用公开信息。"）
        # 原样送进去，Bing 会去搜"信息公开"，于是每个关键词都返回同一批
        # "中山大学信息公开网"页面，真正的关键词一个字都没起作用（首次真实运行实测）。
        self.assertEqual(
            glm_search_query(f"{SYSU_QUERY_CONTEXT} 原始检索词：学术不端"),
            "中山大学 学术不端",
        )

    def test_glm_search_query_keeps_a_plain_search_string_and_scopes_it_to_sysu(self):
        self.assertEqual(glm_search_query("中山大学 校园通知"), "中山大学 校园通知")
        self.assertEqual(glm_search_query("食堂"), "中山大学 食堂")

    async def test_glm_posts_the_reduced_search_query(self):
        client = FakeClient({"search_result": []})
        transport = OpenAICompatibleTransport(
            "glm",
            "https://open.bigmodel.cn/api/paas/v4/web_search",
            None,
            "secret-key",
            client,
        )
        request = SearchRequest(
            provider="glm",
            query=f"{SYSU_QUERY_CONTEXT} 原始检索词：宿舍起火",
            max_results=3,
        )
        await transport(request)
        self.assertEqual(client.calls[0][2]["search_query"], "中山大学 宿舍起火")

    async def test_glm_search_engine_is_configurable(self):
        client = FakeClient({"search_result": []})
        transport = OpenAICompatibleTransport(
            "glm",
            "https://open.bigmodel.cn/api/paas/v4/web_search",
            None,
            "secret-key",
            client,
            search_engine="search_pro_jina",
        )
        await transport(SearchRequest(provider="glm", query="中山大学"))
        self.assertEqual(client.calls[0][2]["search_engine"], "search_pro_jina")

    async def test_glm_chat_completions_base_url_is_migrated_not_posted_to(self):
        client = FakeClient({"search_result": []})
        transport = OpenAICompatibleTransport(
            "glm",
            "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            "glm-4-plus",
            "secret-key",
            client,
        )
        await transport(SearchRequest(provider="glm", query="中山大学"))
        self.assertEqual(client.calls[0][0], "https://open.bigmodel.cn/api/paas/v4/web_search")
        self.assertNotIn("messages", client.calls[0][2])

    async def test_glm_unknown_base_url_fails_loudly(self):
        client = FakeClient({"search_result": []})
        transport = OpenAICompatibleTransport(
            "glm", "https://api.example/v1/responses", None, "secret-key", client
        )
        with self.assertRaises(ValueError) as caught:
            await transport(SearchRequest(provider="glm", query="中山大学"))
        self.assertIn("EVIDENCE_GLM_BASE_URL", str(caught.exception))
        self.assertIn("web_search", str(caught.exception))
        self.assertEqual(client.calls, [])

    async def test_generic_provider_keeps_the_plain_chat_body(self):
        client = FakeClient({"choices": []})
        transport = OpenAICompatibleTransport(
            "deepseek", "https://api.example/v1/chat/completions", "model-a", "secret-key", client
        )
        await transport(SearchRequest(provider="deepseek", model="model-a", query="SYSU"))
        self.assertNotIn("tools", client.calls[0][2])

    def test_glm_web_search_results_become_hits(self):
        payload = {
            "id": "req-9",
            "request_id": "rid-9",
            "search_intent": [{"query": "中山大学 通知"}],
            "search_result": [
                {
                    "media": "中山大学新闻网",
                    "title": "关于暑期安排的通知",
                    "link": "https://news.sysu.edu.cn/info/1",
                    "content": "中山大学发布暑期安排通知正文摘录。",
                    "refer": "ref_1",
                    "publish_date": "2026-07-08",
                }
            ],
        }
        hits = parse_citation_response(payload, provider_id="glm")
        self.assertEqual(len(hits), 1)
        self.assertEqual(str(hits[0].url), "https://news.sysu.edu.cn/info/1")
        self.assertEqual(hits[0].quote, "中山大学发布暑期安排通知正文摘录。")
        self.assertEqual(hits[0].title, "关于暑期安排的通知")
        self.assertEqual(hits[0].source_type, "official")
        self.assertEqual(hits[0].request_id, "req-9")
        self.assertEqual(hits[0].metadata["publisher"], "中山大学新闻网")
        self.assertEqual(hits[0].metadata["published_at"], "2026-07-08")

    def test_glm_results_without_a_usable_link_are_dropped(self):
        # search_std / search_pro return content with an empty ``link``; an
        # un-attributed result is not evidence and must never become a row.
        payload = {
            "id": "req-10",
            "search_result": [
                {"title": "无链接", "link": "", "content": "中山大学发布通知。"},
                {"title": "非 HTTP", "link": "ftp://x/y", "content": "中山大学发布通知。"},
                {
                    "title": "可用",
                    "link": "https://news.sysu.edu.cn/info/2",
                    "content": "中山大学发布通知正文。",
                },
            ],
        }
        hits = parse_citation_response(payload, provider_id="glm")
        self.assertEqual([str(hit.url) for hit in hits], ["https://news.sysu.edu.cn/info/2"])

    def test_source_type_is_derived_from_the_domain(self):
        official, news, unknown = (
            parse_citation_response(
                {
                    "citations": [
                        {
                            "link": url,
                            "title": "中山大学通知",
                            "content": "中山大学发布通知。",
                        }
                    ]
                },
                provider_id="glm",
            )[0]
            for url in (
                "https://news.sysu.edu.cn/info/1",
                "https://www.thepaper.cn/news/1",
                "https://blog.example.com/post/1",
            )
        )
        self.assertEqual(official.source_type, "official")
        self.assertEqual(news.source_type, "news")
        self.assertEqual(unknown.source_type, "web")

    def test_explicit_source_type_from_the_provider_is_preserved(self):
        hits = parse_citation_response(
            {
                "citations": [
                    {
                        "url": "https://news.sysu.edu.cn/info/1",
                        "quote": "中山大学发布通知。",
                        "source_type": "news",
                    }
                ]
            },
            provider_id="glm",
        )
        self.assertEqual(hits[0].source_type, "news")

    def test_environment_factory_requires_all_gates_and_injected_client(self):
        env = {
            "EVIDENCE_DEEPSEEK_API_KEY": "key",
            "EVIDENCE_DEEPSEEK_MODEL": "model",
            "EVIDENCE_DEEPSEEK_BASE_URL": "https://api.example/v1",
            "EVIDENCE_DEEPSEEK_WEB_SEARCH_ENABLED": "true",
            "EVIDENCE_GLM_API_KEY": "key",
            "EVIDENCE_GLM_MODEL": "model",
            "EVIDENCE_GLM_BASE_URL": "https://api.example/v1",
            "EVIDENCE_GLM_WEB_SEARCH_ENABLED": "false",
        }
        client = FakeClient({"citations": []})
        transports = build_http_transports(env, client=client)
        self.assertEqual(set(transports), {"deepseek"})
        self.assertNotIn("key", repr(transports["deepseek"]))
        self.assertEqual(build_http_transports(env), {})

    def test_glm_is_built_without_a_model_and_takes_its_engine_from_the_env(self):
        # 智谱的 web_search 接口不接受 model，缺少 EVIDENCE_GLM_MODEL 也不能让
        # GLM 悄悄消失；而 EVIDENCE_DEEPSEEK_* 仍然需要 model。
        env = {
            "EVIDENCE_GLM_API_KEY": "key",
            "EVIDENCE_GLM_BASE_URL": "https://open.bigmodel.cn/api/paas/v4/web_search",
            "EVIDENCE_GLM_WEB_SEARCH_ENABLED": "true",
            "EVIDENCE_GLM_SEARCH_ENGINE": "search_pro_sogou",
            "EVIDENCE_DEEPSEEK_API_KEY": "key",
            "EVIDENCE_DEEPSEEK_BASE_URL": "https://api.example/v1/chat/completions",
            "EVIDENCE_DEEPSEEK_WEB_SEARCH_ENABLED": "true",
        }
        transports = build_http_transports(env, client=FakeClient({"search_result": []}))
        self.assertEqual(set(transports), {"glm"})
        self.assertIsNone(transports["glm"].model)
        self.assertEqual(transports["glm"].search_engine, "search_pro_sogou")


if __name__ == "__main__":
    unittest.main()
