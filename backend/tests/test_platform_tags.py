from __future__ import annotations

import json
import unittest

from scripts.sync_media_to_raw_posts import (
    _map_tieba,
    _map_weibo,
    _map_xhs,
    extract_weibo_topics,
    normalize_xhs_tag_list,
)


class ExtractWeiboTopicsTest(unittest.TestCase):
    def test_extracts_multiple_topics(self) -> None:
        content = "今天去了#中山大学食堂#，还聊到#宿舍空调#的问题"
        self.assertEqual(extract_weibo_topics(content), ["中山大学食堂", "宿舍空调"])

    def test_strips_supertopic_suffix(self) -> None:
        self.assertEqual(extract_weibo_topics("#中山大学[超话]#今日打卡"), ["中山大学"])

    def test_deduplicates_preserving_order(self) -> None:
        self.assertEqual(extract_weibo_topics("#食堂#好吃 #食堂#真好吃 #涨价#"), ["食堂", "涨价"])

    def test_no_topics_returns_empty(self) -> None:
        self.assertEqual(extract_weibo_topics("普通微博没有话题"), [])
        self.assertEqual(extract_weibo_topics(""), [])
        self.assertEqual(extract_weibo_topics(None), [])

    def test_length_bounds(self) -> None:
        # 单字话题与超长话题（>20 字）不提取
        long_topic = "很" * 21
        self.assertEqual(extract_weibo_topics(f"#水# #{long_topic}#"), [])


class NormalizeXhsTagListTest(unittest.TestCase):
    def test_dict_shaped_tags_become_names(self) -> None:
        raw = json.dumps([{"name": "宿舍", "type": "topic"}, {"name": "空调", "type": "topic"}], ensure_ascii=False)
        self.assertEqual(normalize_xhs_tag_list(raw), ["宿舍", "空调"])

    def test_string_array_passes_through(self) -> None:
        self.assertEqual(normalize_xhs_tag_list('["期末周", "食堂"]'), ["期末周", "食堂"])

    def test_broken_or_empty_input_tolerated(self) -> None:
        self.assertEqual(normalize_xhs_tag_list("not-json"), [])
        self.assertEqual(normalize_xhs_tag_list(""), [])
        self.assertEqual(normalize_xhs_tag_list(None), [])
        self.assertEqual(normalize_xhs_tag_list("null"), [])


class MapperTagsTest(unittest.TestCase):
    def test_map_xhs_normalizes_dict_tags(self) -> None:
        row = {
            "id": 1,
            "note_id": "abc",
            "title": "宿舍空调",
            "desc": "热死了",
            "tag_list": json.dumps([{"name": "宿舍", "type": "topic"}], ensure_ascii=False),
            "source_keyword": "宿舍",
        }
        payload = _map_xhs(row)
        self.assertEqual(json.loads(payload["tags_json"]), ["宿舍"])

    def test_map_weibo_extracts_topics_from_content(self) -> None:
        row = {"id": 1, "note_id": 2, "content": "#食堂涨价#大家怎么看", "source_keyword": "食堂"}
        payload = _map_weibo(row)
        self.assertEqual(json.loads(payload["tags_json"]), ["食堂涨价"])

    def test_map_weibo_without_topics_has_empty_tags(self) -> None:
        row = {"id": 1, "note_id": 2, "content": "无话题内容", "source_keyword": "食堂"}
        payload = _map_weibo(row)
        self.assertEqual(payload["tags_json"], "")

    def test_map_tieba_uses_tieba_name_as_tag(self) -> None:
        row = {"id": 1, "note_id": "t1", "title": "空调什么时候修", "desc": "", "tieba_name": "中大宿舍", "source_keyword": "宿舍"}
        payload = _map_tieba(row)
        self.assertEqual(json.loads(payload["tags_json"]), ["中大宿舍"])

    def test_map_tieba_without_name_has_empty_tags(self) -> None:
        row = {"id": 1, "note_id": "t1", "title": "标题", "desc": "", "source_keyword": "宿舍"}
        payload = _map_tieba(row)
        self.assertEqual(payload["tags_json"], "")


if __name__ == "__main__":
    unittest.main()
