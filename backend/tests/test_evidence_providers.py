"""Provider abstraction tests (offline and deterministic)."""

from __future__ import annotations

import asyncio
import unittest

from pydantic import ValidationError

from backend.services.evidence.providers import (
    DisabledProviderError,
    GenericProviderAdapter,
    InvalidSearchHitError,
    ProbeResult,
    ProviderRegistry,
    ProviderSettings,
    ProviderTransportUnavailableError,
    SearchHit,
    SearchRequest,
    SearchProvider,
    StaticSearchProvider,
    normalize_hit,
)


IDS = ("deepseek", "glm", "kimi", "doubao", "qwen")


def enabled_settings(provider_id: str) -> ProviderSettings:
    return ProviderSettings(
        provider_id,
        api_key="test-secret",
        model=f"{provider_id}-model",
        base_url="https://api.invalid",
        web_search_enabled=True,
    )


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    def test_all_supported_ids_are_gated_on_all_fields(self) -> None:
        for provider_id in IDS:
            enabled = enabled_settings(provider_id)
            self.assertTrue(enabled.enabled)
            for field in ("api_key", "model", "base_url"):
                kwargs = {
                    "api_key": "test-secret",
                    "model": f"{provider_id}-model",
                    "base_url": "https://api.invalid",
                    "web_search_enabled": True,
                }
                kwargs[field] = ""  # type: ignore[index]
                self.assertFalse(
                    ProviderSettings(provider_id, **kwargs).enabled,
                    (provider_id, field),
                )
            self.assertFalse(
                ProviderSettings(
                    provider_id,
                    api_key="test-secret",
                    model="model",
                    base_url="https://api.invalid",
                    web_search_enabled=False,
                ).enabled
            )

    async def test_disabled_adapter_never_calls_transport(self) -> None:
        calls: list[object] = []

        async def transport(*args: object) -> list[object]:
            calls.append(args)
            return []

        adapter = GenericProviderAdapter(
            ProviderSettings("deepseek", model="model", base_url="https://api.invalid"),
            transport=transport,
        )
        with self.assertRaises(DisabledProviderError):
            await adapter.search(SearchRequest(provider="deepseek", query="test"))
        self.assertEqual(calls, [])

    async def test_enabled_without_transport_is_offline(self) -> None:
        adapter = GenericProviderAdapter(enabled_settings("glm"))
        with self.assertRaises(ProviderTransportUnavailableError):
            await adapter.search(SearchRequest(provider="glm", query="test"))

    async def test_static_provider_and_protocol(self) -> None:
        hit = SearchHit(url="https://example.invalid/a", quote="Evidence quote")
        provider = StaticSearchProvider("kimi", [hit], model="kimi-test", request_id="r-1")
        self.assertIsInstance(provider, SearchProvider)
        results = await provider.search(SearchRequest(provider="kimi", query="q"))
        self.assertEqual(results[0].url, hit.url)
        probe = await provider.probe()
        self.assertTrue(probe.eligible)
        self.assertEqual(probe.request_id, "r-1")

    def test_invalid_hits_are_rejected(self) -> None:
        with self.assertRaises(InvalidSearchHitError):
            normalize_hit({"url": "ftp://example.invalid/a", "quote": "evidence"})
        with self.assertRaises(InvalidSearchHitError):
            normalize_hit({"url": "https://example.invalid/a", "quote": "  "})

    async def test_registry_probe_requires_citation_and_caches(self) -> None:
        state: dict[str, object] = {"hits": []}

        async def transport(_request: SearchRequest) -> object:
            return {"hits": state["hits"]}

        registry = ProviderRegistry(
            {"qwen": enabled_settings("qwen")},
            transports={"qwen": transport},
        )
        first = await registry.probe("qwen")
        second = await registry.probe("qwen")
        self.assertIs(first, second)
        self.assertFalse(registry.is_eligible("qwen"))
        state["hits"] = [{"url": "https://example.invalid/a", "quote": "quoted evidence"}]
        # Cached negative result remains until explicitly forced.
        self.assertFalse((await registry.probe("qwen")).eligible)
        self.assertTrue((await registry.probe("qwen", force=True)).eligible)

    def test_immutable_request_and_metadata_are_preserved(self) -> None:
        request = SearchRequest(provider="deepseek", query="q")
        with self.assertRaises(ValidationError):  # type: ignore[name-defined]
            request.query = "changed"  # type: ignore[misc]
        hit = normalize_hit(
            {
                "url": "https://example.invalid/a",
                "quote": "quoted",
                "provider": "deepseek",
                "model": "deepseek-r1",
                "request_id": "req-7",
            }
        )
        self.assertEqual((hit.provider, hit.model, hit.request_id), ("deepseek", "deepseek-r1", "req-7"))

    def test_registry_repr_and_safe_settings_do_not_expose_keys(self) -> None:
        registry = ProviderRegistry({"deepseek": enabled_settings("deepseek")})
        rendered = repr(registry) + repr(registry.settings["deepseek"])
        self.assertNotIn("test-secret", rendered)
        self.assertNotIn("test-secret", repr(registry.settings["deepseek"].safe_dict))

    def test_registry_converts_legacy_settings_objects_and_enabled_alias(self) -> None:
        class LegacySettings:
            def __init__(self, provider_id: str) -> None:
                self.provider_id = provider_id
                self.api_key = "legacy-secret"
                self.model = f"{provider_id}-model"
                self.base_url = "https://api.invalid"
                # Legacy config exposed ``enabled`` instead of the explicit
                # web_search_enabled flag.
                self.enabled = True

        class LegacyCollector:
            providers = {provider_id: LegacySettings(provider_id) for provider_id in IDS}

        registry = ProviderRegistry.from_config(LegacyCollector())
        self.assertEqual(registry.enabled_provider_ids, IDS)

    def test_mapping_settings_accept_enabled_alias_for_all_providers(self) -> None:
        config = {
            provider_id: {
                "api_key": "mapping-secret",
                "model": f"{provider_id}-model",
                "base_url": "https://api.invalid",
                "enabled": True,
            }
            for provider_id in IDS
        }
        registry = ProviderRegistry.from_config(config)
        self.assertEqual(registry.enabled_provider_ids, IDS)

    def test_normalization_rejects_forged_provider_provenance(self) -> None:
        with self.assertRaises(InvalidSearchHitError):
            normalize_hit(
                {
                    "url": "https://example.invalid/a",
                    "quote": "quoted evidence",
                    "provider": "glm",
                },
                provider_id="deepseek",
            )


if __name__ == "__main__":
    unittest.main()
