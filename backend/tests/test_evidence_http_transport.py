"""Offline tests for the optional citation-only HTTP transport."""

from __future__ import annotations

import unittest

from backend.services.evidence.http_transport import (
    HttpTransportUnavailableError,
    OpenAICompatibleTransport,
    build_http_transports,
    parse_citation_response,
)
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

    async def test_glm_request_enables_the_web_search_tool(self):
        client = FakeClient({"choices": []})
        transport = OpenAICompatibleTransport(
            "glm",
            "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            "glm-4-plus",
            "secret-key",
            client,
        )
        request = SearchRequest(
            provider="glm", model="glm-4-plus", query="中山大学 校园通知", max_results=3
        )
        await transport(request)
        body = client.calls[0][2]
        self.assertEqual(
            body["tools"],
            [{"type": "web_search", "web_search": {"enable": True, "search_result": True}}],
        )

    async def test_generic_provider_keeps_the_plain_chat_body(self):
        client = FakeClient({"choices": []})
        transport = OpenAICompatibleTransport(
            "deepseek", "https://api.example/v1/chat/completions", "model-a", "secret-key", client
        )
        await transport(SearchRequest(provider="deepseek", model="model-a", query="SYSU"))
        self.assertNotIn("tools", client.calls[0][2])

    def test_glm_tool_call_search_results_become_hits(self):
        payload = {
            "id": "req-9",
            "model": "glm-4-plus",
            "choices": [
                {
                    "message": {
                        "content": "中山大学发布了通知[1]",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "web_search",
                                "search_result": [
                                    {
                                        "media": "中山大学新闻网",
                                        "title": "关于暑期安排的通知",
                                        "link": "https://news.sysu.edu.cn/info/1",
                                        "content": "中山大学发布暑期安排通知正文摘录。",
                                    }
                                ],
                            }
                        ],
                    }
                }
            ],
        }
        hits = parse_citation_response(payload, provider_id="glm")
        self.assertEqual(len(hits), 1)
        self.assertEqual(str(hits[0].url), "https://news.sysu.edu.cn/info/1")
        self.assertEqual(hits[0].quote, "中山大学发布暑期安排通知正文摘录。")
        self.assertEqual(hits[0].request_id, "req-9")

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


if __name__ == "__main__":
    unittest.main()
