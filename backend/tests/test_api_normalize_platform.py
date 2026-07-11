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


if __name__ == "__main__":
    unittest.main()
