"""backend/routers/api.py `_normalize_platform` 的平台别名收敛。

零网络、零数据库：纯函数单测。
"""

from __future__ import annotations

import unittest

from backend.routers.api import _normalize_platform


class NormalizePlatformTest(unittest.TestCase):
    def test_zhihu_english_code(self) -> None:
        self.assertEqual(_normalize_platform("zhihu"), "zhihu")

    def test_zhihu_chinese_alias(self) -> None:
        self.assertEqual(_normalize_platform("知乎"), "zhihu")

    def test_zhihu_mixed_text_contains_alias(self) -> None:
        self.assertEqual(_normalize_platform("来源：知乎"), "zhihu")

    def test_existing_platforms_unaffected(self) -> None:
        self.assertEqual(_normalize_platform("微博"), "weibo")
        self.assertEqual(_normalize_platform("xhs"), "xhs")
        self.assertEqual(_normalize_platform("贴吧"), "tieba")

    def test_ks_variants(self):
        self.assertEqual(_normalize_platform("ks"), "ks")
        self.assertEqual(_normalize_platform("KS"), "ks")
        self.assertEqual(_normalize_platform("kuaishou"), "ks")
        self.assertEqual(_normalize_platform("快手"), "ks")

    def test_web_variants(self):
        # 证据交付写入 raw_posts 时用的平台码
        self.assertEqual(_normalize_platform("web"), "web")
        self.assertEqual(_normalize_platform("WEB"), "web")
        self.assertEqual(_normalize_platform("网页"), "web")

    def test_web_alias_does_not_shadow_weibo(self):
        # "web" 是 "weibo" 的前缀：子串匹配写反了会把微博误判成 web
        self.assertEqual(_normalize_platform("weibo"), "weibo")
        self.assertEqual(_normalize_platform("微博"), "weibo")


class ProcessRawPostsPlatformChoicesTest(unittest.TestCase):
    """raw_posts -> processed_posts 必须能按 web 平台定向处理证据交付的行。"""

    def test_web_is_selectable(self) -> None:
        from scripts.process_raw_posts import PLATFORM_CHOICES

        self.assertIn("web", PLATFORM_CHOICES)
        for platform in ("xhs", "weibo", "tieba", "zhihu", "ks"):
            self.assertIn(platform, PLATFORM_CHOICES)


if __name__ == "__main__":
    unittest.main()
