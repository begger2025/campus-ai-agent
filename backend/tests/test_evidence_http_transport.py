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
