"""注意点 3：--refresh 刷新互动量与热度（sync/process 两条流水线）。

设计见 docs/superpowers/specs/2026-07-10-dedup-hardening-design.md 注意点 3。
不连接真实数据库：sqlite 内存库 + Base.metadata.create_all，风格同 test_platform_tags.py。
"""

from __future__ import annotations

import sys
import unittest
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import ProcessedPost, RawPost
from scripts.process_raw_posts import _process_raw_posts, calculate_heat_score
from scripts.sync_media_to_raw_posts import _base_payload, _insert_payloads


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _payload(external_id: str = "note-1", **overrides):
    payload = _base_payload(
        platform="xhs",
        source_table="xhs_note",
        source_raw_id="1",
        external_id=external_id,
        source_keyword="宿舍",
        title="新标题（爬取最新值）",
        content="新正文（爬取最新值）",
        author="作者",
        publish_time=None,
        url="https://example.com/note-1",
        like_count=99,
        collect_count=9,
        comment_count=8,
        share_count=7,
    )
    payload.update(overrides)
    return payload


class SyncRefreshTest(unittest.TestCase):
    """`_insert_payloads` 的 refresh 分支：命中已存在行时是否刷新互动量。"""

    def setUp(self) -> None:
        self.db = make_session_factory()()
        self.addCleanup(self.db.close)

    def _seed_raw_post(self, **overrides) -> RawPost:
        row = RawPost(
            platform="xhs",
            external_id="note-1",
            title="旧标题",
            content="旧正文",
            like_count=1,
            collect_count=1,
            comment_count=1,
            share_count=1,
        )
        for key, value in overrides.items():
            setattr(row, key, value)
        self.db.add(row)
        self.db.commit()
        return row

    def test_refresh_off_leaves_existing_row_untouched_and_counts_skipped(self) -> None:
        self._seed_raw_post()

        stats = _insert_payloads(self.db, "xhs", [_payload()], dry_run=False, refresh=False)

        self.assertEqual(stats.skipped_duplicate, 1)
        self.assertEqual(stats.updated, 0)
        row = self.db.query(RawPost).filter_by(external_id="note-1").one()
        self.assertEqual(row.like_count, 1)
        self.assertEqual(row.title, "旧标题")

    def test_refresh_on_with_changed_engagement_updates_four_fields_only(self) -> None:
        self._seed_raw_post()

        stats = _insert_payloads(self.db, "xhs", [_payload()], dry_run=False, refresh=True)
        self.db.commit()

        self.assertEqual(stats.updated, 1)
        self.assertEqual(stats.skipped_duplicate, 0)
        row = self.db.query(RawPost).filter_by(external_id="note-1").one()
        self.assertEqual(row.like_count, 99)
        self.assertEqual(row.collect_count, 9)
        self.assertEqual(row.comment_count, 8)
        self.assertEqual(row.share_count, 7)
        # 非互动量字段（标题/正文）必须保持原样
        self.assertEqual(row.title, "旧标题")
        self.assertEqual(row.content, "旧正文")

    def test_refresh_on_with_identical_engagement_counts_as_skipped(self) -> None:
        self._seed_raw_post(like_count=99, collect_count=9, comment_count=8, share_count=7)

        stats = _insert_payloads(self.db, "xhs", [_payload()], dry_run=False, refresh=True)

        self.assertEqual(stats.updated, 0)
        self.assertEqual(stats.skipped_duplicate, 1)


class ZhihuSyncRefreshTest(unittest.TestCase):
    """Z5：zhihu 的 --refresh 只刷 like_count（voteup）与 comment_count，collect/share 不动。"""

    def setUp(self) -> None:
        self.db = make_session_factory()()
        self.addCleanup(self.db.close)

    @staticmethod
    def _zhihu_payload(voteup: int = 99, comment: int = 8):
        from scripts.sync_media_to_raw_posts import _map_zhihu

        return _map_zhihu(
            {
                "id": 7,
                "content_id": "answer-1",
                "content_text": "新正文",
                "content_url": "https://www.zhihu.com/question/1/answer/1",
                "title": "新标题",
                "created_time": "1750000000",
                "voteup_count": voteup,
                "comment_count": comment,
                "source_keyword": "宿舍",
                "add_ts": 1750000000000,
            }
        )

    def _seed_zhihu_row(self, **overrides) -> RawPost:
        row = RawPost(
            platform="zhihu",
            external_id="answer-1",
            title="旧标题",
            content="旧正文",
            like_count=1,
            collect_count=5,
            comment_count=1,
            share_count=3,
        )
        for key, value in overrides.items():
            setattr(row, key, value)
        self.db.add(row)
        self.db.commit()
        return row

    def test_zhihu_refresh_updates_like_and_comment_only(self) -> None:
        self._seed_zhihu_row()

        stats = _insert_payloads(self.db, "zhihu", [self._zhihu_payload()], dry_run=False, refresh=True)
        self.db.commit()

        self.assertEqual(stats.updated, 1)
        row = self.db.query(RawPost).filter_by(platform="zhihu", external_id="answer-1").one()
        self.assertEqual(row.like_count, 99)
        self.assertEqual(row.comment_count, 8)
        # 知乎映射的 collect/share 恒 0，refresh 不得用 0 覆盖已有值
        self.assertEqual(row.collect_count, 5)
        self.assertEqual(row.share_count, 3)
        self.assertEqual(row.title, "旧标题")

    def test_zhihu_refresh_identical_two_fields_counts_as_skipped(self) -> None:
        # collect/share 与 payload（恒 0）不同，但不在 zhihu 的刷新字段内 -> 视为无变化
        self._seed_zhihu_row(like_count=99, comment_count=8)

        stats = _insert_payloads(self.db, "zhihu", [self._zhihu_payload()], dry_run=False, refresh=True)

        self.assertEqual(stats.updated, 0)
        self.assertEqual(stats.skipped_duplicate, 1)


class ProcessRefreshTest(unittest.TestCase):
    """`_process_raw_posts` 的 refresh 分支：已存在的 processed_posts 行是否重算互动量 + 热度。"""

    def setUp(self) -> None:
        self.db = make_session_factory()()
        self.addCleanup(self.db.close)

    def _seed_pair(self) -> tuple[RawPost, ProcessedPost]:
        raw = RawPost(
            platform="xhs",
            external_id="note-1",
            title="标题",
            content="正文",
            like_count=50,
            collect_count=5,
            comment_count=10,
            share_count=2,
        )
        self.db.add(raw)
        self.db.commit()

        processed = ProcessedPost(
            raw_post_id=raw.id,
            platform="xhs",
            note_id=f"xhs:{raw.external_id}",
            title="标题",
            content="正文",
            like_count=1,
            collect_count=1,
            comment_count=1,
            share_count=1,
            heat_score=1.0,
            sentiment="negative",
            sentiment_score=-0.8,
        )
        self.db.add(processed)
        self.db.commit()
        return raw, processed

    def test_refresh_on_recomputes_engagement_and_heat_but_not_sentiment(self) -> None:
        raw, processed = self._seed_pair()

        result = _process_raw_posts(self.db, limit=100, platforms=None, dry_run=False, refresh=True)
        self.db.commit()

        self.assertEqual(result.refreshed, 1)
        row = self.db.query(ProcessedPost).filter_by(raw_post_id=raw.id).one()
        self.assertEqual(row.like_count, 50)
        self.assertEqual(row.collect_count, 5)
        self.assertEqual(row.comment_count, 10)
        self.assertEqual(row.share_count, 2)
        self.assertEqual(
            row.heat_score,
            calculate_heat_score(like_count=50, collect_count=5, comment_count=10, share_count=2),
        )
        # 情绪等分析字段绝不能被 refresh 碰
        self.assertEqual(row.sentiment, "negative")
        self.assertEqual(row.sentiment_score, -0.8)

    def test_refresh_off_leaves_processed_post_untouched(self) -> None:
        raw, processed = self._seed_pair()

        result = _process_raw_posts(self.db, limit=100, platforms=None, dry_run=False, refresh=False)
        self.db.commit()

        self.assertEqual(result.refreshed, 0)
        row = self.db.query(ProcessedPost).filter_by(raw_post_id=raw.id).one()
        self.assertEqual(row.like_count, 1)
        self.assertEqual(row.heat_score, 1.0)


class ProcessRawPostsCliTest(unittest.TestCase):
    """`main()` 的 argparse：`--platform zhihu` 必须被接受（不报 SystemExit）。"""

    def test_platform_zhihu_is_accepted_by_argparse(self) -> None:
        import scripts.process_raw_posts as prp

        captured: dict = {}

        def fake_process(**kwargs):
            captured.update(kwargs)
            return prp.ProcessResult()

        with mock.patch.object(prp, "process_raw_posts", side_effect=fake_process), mock.patch.object(
            sys, "argv", ["process_raw_posts.py", "--platform", "zhihu"]
        ):
            rc = prp.main()

        self.assertEqual(rc, 0)
        self.assertEqual(captured.get("platforms"), ["zhihu"])


if __name__ == "__main__":
    unittest.main()
