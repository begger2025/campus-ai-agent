from __future__ import annotations

import json
import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import ProcessedPost, RawPost
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


NOW = datetime(2026, 7, 10, 12, 0, 0)


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


class ParseTagsDictToleranceTest(unittest.TestCase):
    def test_dict_shaped_legacy_tags_yield_names_not_reprs(self) -> None:
        # 回归：真实 xhs 旧数据是字典数组，str(dict) 会产出乱码关键词
        from backend.services.keyword_suggestion_adapter import _parse_tags

        raw = json.dumps([{"name": "宿舍", "type": "topic"}], ensure_ascii=False)
        self.assertEqual(_parse_tags(raw), ["宿舍"])

    def test_string_tags_still_work(self) -> None:
        from backend.services.keyword_suggestion_adapter import _parse_tags

        self.assertEqual(_parse_tags('["期末周"]'), ["期末周"])


class BackfillTagsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session_factory()()
        self.addCleanup(self.db.close)

    def _add_pair(self, rid: int, platform: str, *, content: str = "", tags_json: str = "", raw_json: str = "") -> None:
        self.db.add(
            RawPost(
                id=rid, platform=platform, external_id=f"e{rid}", title=f"标题{rid}",
                content=content, tags_json=tags_json, raw_json=raw_json,
            )
        )
        self.db.add(
            ProcessedPost(
                raw_post_id=rid, platform=platform, title=f"标题{rid}",
                tags_json=tags_json, created_at=NOW, publish_time=NOW,
            )
        )

    def test_backfill_updates_all_three_platforms(self) -> None:
        from scripts.backfill_tags import backfill_tags

        legacy_xhs = json.dumps([{"name": "宿舍", "type": "topic"}], ensure_ascii=False)
        self._add_pair(1, "xhs", tags_json=legacy_xhs)
        self._add_pair(2, "weibo", content="#食堂涨价#热议中")
        self._add_pair(3, "tieba", raw_json=json.dumps({"tieba_name": "中大宿舍"}, ensure_ascii=False))
        self.db.commit()

        result = backfill_tags(self.db)
        self.db.commit()

        self.assertEqual(result.updated, 3)
        raws = {r.id: r for r in self.db.query(RawPost).all()}
        procs = {p.raw_post_id: p for p in self.db.query(ProcessedPost).all()}
        self.assertEqual(json.loads(raws[1].tags_json), ["宿舍"])
        self.assertEqual(json.loads(procs[1].tags_json), ["宿舍"])
        self.assertEqual(json.loads(raws[2].tags_json), ["食堂涨价"])
        self.assertEqual(json.loads(procs[2].tags_json), ["食堂涨价"])
        self.assertEqual(json.loads(raws[3].tags_json), ["中大宿舍"])
        self.assertEqual(json.loads(procs[3].tags_json), ["中大宿舍"])

    def test_backfill_is_idempotent(self) -> None:
        from scripts.backfill_tags import backfill_tags

        self._add_pair(1, "weibo", content="#食堂涨价#")
        self.db.commit()
        backfill_tags(self.db)
        self.db.commit()
        result = backfill_tags(self.db)
        self.assertEqual(result.updated, 0)  # 第二遍无变化

    def test_backfill_skips_rows_without_extractable_tags(self) -> None:
        from scripts.backfill_tags import backfill_tags

        self._add_pair(1, "weibo", content="没有话题的微博")
        self.db.commit()
        result = backfill_tags(self.db)
        self.assertEqual(result.updated, 0)
        self.assertEqual(result.scanned, 1)


if __name__ == "__main__":
    unittest.main()
