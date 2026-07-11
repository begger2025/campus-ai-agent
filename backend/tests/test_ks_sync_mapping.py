"""快手 sync 映射与注册面测试（不连库，纯映射逻辑）。"""

import unittest

from scripts.sync_media_to_raw_posts import (
    MAPPER_BY_PLATFORM,
    REFRESH_FIELDS_BY_PLATFORM,
    SUPPORTED_PLATFORMS,
    TABLE_BY_PLATFORM,
    _map_ks,
    _normalize_platforms,
)

MS_2026_06_12 = 1_781_193_600_000  # 毫秒 epoch


def make_row(**overrides):
    row = {
        "id": 7,
        "video_id": "3xabc",
        "source_keyword": "中山大学 宿舍",
        "title": "中山大学宿舍vlog",
        "desc": "中山大学宿舍vlog 完整文案",
        "nickname": "某同学",
        "create_time": MS_2026_06_12,
        "liked_count": "1234",
        "comment_count": "56",
        "viewd_count": "9999",
        "video_url": "https://www.kuaishou.com/short-video/3xabc",
        "add_ts": MS_2026_06_12 + 86_400_000,
        "last_modify_ts": MS_2026_06_12 + 86_400_000,
    }
    row.update(overrides)
    return row


class KsPlatformRegistrationTests(unittest.TestCase):
    def test_ks_registered_everywhere(self):
        self.assertIn("ks", SUPPORTED_PLATFORMS)
        self.assertEqual(TABLE_BY_PLATFORM["ks"], "kuaishou_video")
        self.assertIs(MAPPER_BY_PLATFORM["ks"], _map_ks)
        self.assertIn("ks", _normalize_platforms(None))
        self.assertIn("ks", _normalize_platforms(["all"]))

    def test_refresh_only_like_and_comment(self):
        # collect/share 恒 0，--refresh 只刷点赞与评论，避免 0 覆盖既有值
        self.assertEqual(REFRESH_FIELDS_BY_PLATFORM["ks"], ("like_count", "comment_count"))


class MapKsTests(unittest.TestCase):
    def test_basic_mapping(self):
        payload = _map_ks(make_row())
        self.assertEqual(payload["platform"], "ks")
        self.assertEqual(payload["source_table"], "kuaishou_video")
        self.assertEqual(payload["external_id"], "3xabc")
        self.assertEqual(payload["like_count"], 1234)
        self.assertEqual(payload["comment_count"], 56)
        self.assertEqual(payload["collect_count"], 0)
        self.assertEqual(payload["share_count"], 0)
        self.assertEqual(payload["tags_json"], "[]")
        self.assertEqual(payload["url"], "https://www.kuaishou.com/short-video/3xabc")
        # create_time 毫秒 epoch 正确换算（2026-06-12 前后）
        self.assertIsNotNone(payload["publish_time"])
        self.assertEqual(payload["publish_time"].year, 2026)

    def test_publish_time_falls_back_to_add_ts(self):
        for bad in (None, 0):
            payload = _map_ks(make_row(create_time=bad))
            self.assertIsNotNone(payload["publish_time"])  # 回退 add_ts
            self.assertEqual(payload["publish_time"].year, 2026)

    def test_text_count_tolerance(self):
        # store 写入 str(realLikeCount)，缺失时可能是 "None"；映射侧容错为 0
        payload = _map_ks(make_row(liked_count="None", comment_count=None))
        self.assertEqual(payload["like_count"], 0)
        self.assertEqual(payload["comment_count"], 0)


if __name__ == "__main__":
    unittest.main()
