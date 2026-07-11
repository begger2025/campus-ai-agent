"""Configuration behavior tests."""

import unittest

from backend.services.evidence.config import (
    SUPPORTED_PROVIDER_IDS,
    http_trust_env,
    load_settings,
)


class CollectorSettingsTests(unittest.TestCase):
    def test_provider_requires_both_api_key_and_enabled_flag(self):
        for provider_id in SUPPORTED_PROVIDER_IDS:
            key_name = f"EVIDENCE_{provider_id.upper()}_API_KEY"
            flag_name = f"EVIDENCE_{provider_id.upper()}_WEB_SEARCH_ENABLED"

            with self.subTest(provider=provider_id, case="neither"):
                settings = load_settings({})
                self.assertFalse(settings.providers[provider_id].enabled)

            with self.subTest(provider=provider_id, case="key_only"):
                settings = load_settings({key_name: "not-a-real-key"})
                self.assertFalse(settings.providers[provider_id].enabled)

            with self.subTest(provider=provider_id, case="flag_only"):
                settings = load_settings({flag_name: "true"})
                self.assertFalse(settings.providers[provider_id].enabled)

            with self.subTest(provider=provider_id, case="both"):
                settings = load_settings({key_name: "not-a-real-key", flag_name: "true"})
                self.assertTrue(settings.providers[provider_id].enabled)
                self.assertNotIn("not-a-real-key", repr(settings))


class HttpTrustEnvTests(unittest.TestCase):
    """httpx 默认 trust_env=True，在 Windows 上会读注册表里的系统代理（Clash 等），
    真实可达的中大官网因此连接超时、被误判成编造链接。默认必须直连。"""

    def test_default_is_direct_connection(self):
        self.assertFalse(http_trust_env({}))
        self.assertFalse(http_trust_env({"HTTPS_PROXY": "http://127.0.0.1:7890"}))

    def test_can_be_opted_into_explicitly(self):
        self.assertTrue(http_trust_env({"EVIDENCE_HTTP_TRUST_ENV": "true"}))
        self.assertTrue(http_trust_env({"EVIDENCE_HTTP_TRUST_ENV": "TRUE"}))

    def test_any_other_value_stays_direct(self):
        for value in ("false", "0", "", "yes"):
            with self.subTest(value=value):
                self.assertFalse(http_trust_env({"EVIDENCE_HTTP_TRUST_ENV": value}))


if __name__ == "__main__":
    unittest.main()
