"""Configuration behavior tests."""

import unittest

from evidence_collector.config import SUPPORTED_PROVIDER_IDS, load_settings


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


if __name__ == "__main__":
    unittest.main()
