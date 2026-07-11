"""平台内归一化排序分 heat_rank + web 来源权威度热度。

背景（在共享库 331 行 processed_posts 上实测）：heat_score 是原始互动量加权和，
各平台互动量量级差 ~3 个数量级（xhs 中位数 3924 / ks 998 / weibo 3 / zhihu 5），
web 证据行没有互动量恒为 0。任何按 heat_score 排序的视图都会把 weibo/zhihu/web 埋掉。

不连真实数据库：sqlite 内存库 + Base.metadata.create_all，风格同 test_pipeline_refresh.py。
"""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import ProcessedPost, RawPost
from backend.services.heat_ranking import (
    WEB_PLATFORM,
    calculate_web_heat_score,
    percentile_ranks,
    recompute_heat_ranks,
    refresh_web_heat_scores,
)


def make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


class PercentileRanksTest(unittest.TestCase):
    """纯函数：一组分数 -> 0-100 的百分位。语料相对，不是逐行函数。"""

    def test_empty_list_returns_empty(self) -> None:
        self.assertEqual(percentile_ranks([]), [])

    def test_single_score_is_neutral_50_not_zero(self) -> None:
        # 只有一条的平台不能被判 0 分（那等于又把它埋了），也不该白拿 100。
        self.assertEqual(percentile_ranks([3.0]), [50.0])

    def test_all_equal_scores_share_one_neutral_percentile(self) -> None:
        self.assertEqual(percentile_ranks([7.0, 7.0, 7.0, 7.0]), [50.0, 50.0, 50.0, 50.0])

    def test_ties_get_identical_mid_rank_percentile(self) -> None:
        # 中位秩（mid-rank）：并列的分数取它们所占名次的平均，互相之间绝不分先后。
        # 100 * (比它小的个数 + 并列个数/2) / 总数：两个 20 都是 100*(1+1)/4 = 50.0
        ranks = percentile_ranks([10.0, 20.0, 20.0, 40.0])
        self.assertEqual(ranks[1], ranks[2])
        self.assertEqual(ranks, [12.5, 50.0, 50.0, 87.5])

    def test_order_is_monotonic_and_bounded(self) -> None:
        ranks = percentile_ranks([5.0, 1.0, 9.0])
        self.assertLess(ranks[1], ranks[0])
        self.assertLess(ranks[0], ranks[2])
        for value in ranks:
            self.assertGreater(value, 0.0)
            self.assertLess(value, 100.0)

    def test_percentile_is_comparable_across_platforms(self) -> None:
        # 这是整个任务的要点：weibo 的头部帖（原始热度 9）必须能和
        # xhs 的头部帖（原始热度 12000）在同一把尺子上竞争。
        weibo = percentile_ranks([1.0, 2.0, 3.0, 9.0])
        xhs = percentile_ranks([500.0, 3000.0, 8000.0, 12000.0])
        self.assertEqual(weibo[-1], xhs[-1])


class WebHeatScoreTest(unittest.TestCase):
    """web 页面没有互动量，热度只能来自来源权威度 + 核验强度。"""

    def test_official_verified_is_the_top_of_the_web_order(self) -> None:
        top = calculate_web_heat_score(url="https://news.sysu.edu.cn/a/1.html", verification_status="verified")
        others = [
            calculate_web_heat_score(url="https://news.sysu.edu.cn/a/1.html", verification_status="needs_review"),
            calculate_web_heat_score(url="https://www.thepaper.cn/x", verification_status="verified"),
            calculate_web_heat_score(url="https://random-blog.example.com/x", verification_status="verified"),
        ]
        for other in others:
            self.assertGreater(top, other)

    def test_unknown_domain_unverified_is_the_bottom(self) -> None:
        bottom = calculate_web_heat_score(url="https://random-blog.example.com/x", verification_status="pending")
        self.assertEqual(bottom, 0.0)
        self.assertGreater(
            calculate_web_heat_score(url="https://random-blog.example.com/x", verification_status="verified"),
            bottom,
        )

    def test_authority_order_official_gt_news_gt_other(self) -> None:
        official = calculate_web_heat_score(url="https://sysu.edu.cn/notice", verification_status="verified")
        news = calculate_web_heat_score(url="https://www.thepaper.cn/x", verification_status="verified")
        other = calculate_web_heat_score(url="https://blog.example.org/x", verification_status="verified")
        self.assertGreater(official, news)
        self.assertGreater(news, other)

    def test_verification_order_verified_gt_needs_review_gt_rest(self) -> None:
        def score(status: str) -> float:
            return calculate_web_heat_score(url="https://news.sysu.edu.cn/a", verification_status=status)

        self.assertGreater(score("verified"), score("needs_review"))
        self.assertGreater(score("needs_review"), score("pending"))
        self.assertEqual(score("rejected"), score("pending"))
        self.assertEqual(score("failed"), score(""))

    def test_subdomain_allowed_but_lookalike_domain_is_not(self) -> None:
        # 复用 scope_policy._domain_allowed 的点边界逻辑，不重写。
        allowed = calculate_web_heat_score(url="https://jwb.sysu.edu.cn/x", verification_status="verified")
        lookalike = calculate_web_heat_score(url="https://evil-sysu.edu.cn/x", verification_status="verified")
        self.assertGreater(allowed, lookalike)
        self.assertEqual(
            lookalike,
            calculate_web_heat_score(url="https://blog.example.org/x", verification_status="verified"),
        )

    def test_missing_or_malformed_url_falls_back_to_lowest_authority(self) -> None:
        for url in ["", None, "not a url", "file://sysu.edu.cn"]:
            self.assertEqual(
                calculate_web_heat_score(url=url, verification_status="pending"),
                0.0,
                msg=f"url={url!r}",
            )


class RecomputeHeatRanksTest(unittest.TestCase):
    """DB 归一化 pass：每个平台在自己的语料内算百分位。"""

    def setUp(self) -> None:
        self.db = make_session()
        self.addCleanup(self.db.close)

    def _add(self, platform: str, heat: float) -> ProcessedPost:
        raw = RawPost(platform=platform, title="t", external_id=f"{platform}-{heat}")
        self.db.add(raw)
        self.db.flush()
        post = ProcessedPost(
            raw_post_id=raw.id,
            platform=platform,
            note_id=f"{platform}:{raw.id}",
            title="t",
            heat_score=heat,
        )
        self.db.add(post)
        self.db.flush()
        return post

    def test_rank_is_computed_within_platform_not_globally(self) -> None:
        weibo_low = self._add("weibo", 1.0)
        weibo_top = self._add("weibo", 9.0)
        xhs_low = self._add("xhs", 500.0)
        xhs_top = self._add("xhs", 12000.0)

        updated = recompute_heat_ranks(self.db)
        self.db.flush()

        self.assertEqual(updated, 4)
        # 微博头部帖和小红书头部帖在同一把尺子上并列，尽管原始热度差 3 个数量级。
        self.assertEqual(weibo_top.heat_rank, xhs_top.heat_rank)
        self.assertEqual(weibo_low.heat_rank, xhs_low.heat_rank)
        self.assertGreater(weibo_top.heat_rank, xhs_low.heat_rank)

    def test_rerun_is_idempotent_and_reports_no_change(self) -> None:
        self._add("xhs", 1.0)
        self._add("xhs", 2.0)
        self.assertEqual(recompute_heat_ranks(self.db), 2)
        self.db.flush()
        self.assertEqual(recompute_heat_ranks(self.db), 0)

    def test_platform_filter_only_touches_that_platform(self) -> None:
        xhs = self._add("xhs", 10.0)
        weibo = self._add("weibo", 10.0)
        updated = recompute_heat_ranks(self.db, platforms=["weibo"])
        self.db.flush()
        self.assertEqual(updated, 1)
        self.assertEqual(weibo.heat_rank, 50.0)
        self.assertEqual(xhs.heat_rank, 0.0)


class RefreshWebHeatScoresTest(unittest.TestCase):
    """web 行的 heat_score 从 raw_posts.url（域名）+ evidence_items.verification_status 推。"""

    def setUp(self) -> None:
        self.db = make_session()
        self.addCleanup(self.db.close)

    def _add_web(self, url: str, post_id: int | None = None) -> ProcessedPost:
        raw = RawPost(
            platform=WEB_PLATFORM,
            external_id=f"hash-{url}",
            source_table="evidence_items",
            source_raw_id=str(post_id or ""),
            title="通知",
            url=url,
        )
        self.db.add(raw)
        self.db.flush()
        post = ProcessedPost(
            raw_post_id=raw.id,
            platform=WEB_PLATFORM,
            note_id=f"web:{raw.id}",
            title="通知",
            heat_score=0.0,
        )
        self.db.add(post)
        self.db.flush()
        return post

    def test_official_web_row_outranks_unknown_domain_web_row(self) -> None:
        official = self._add_web("https://news.sysu.edu.cn/notice/1")
        unknown = self._add_web("https://random.example.com/x")

        updated = refresh_web_heat_scores(self.db)
        self.db.flush()

        self.assertEqual(updated, 1)  # unknown 本来就是 0.0，没变化
        self.assertGreater(official.heat_score, unknown.heat_score)
        self.assertEqual(unknown.heat_score, 0.0)

    def test_web_rows_get_a_nonzero_rank_after_refresh(self) -> None:
        official = self._add_web("https://news.sysu.edu.cn/notice/1")
        unknown = self._add_web("https://random.example.com/x")

        refresh_web_heat_scores(self.db)
        recompute_heat_ranks(self.db)
        self.db.flush()

        self.assertGreater(official.heat_rank, unknown.heat_rank)

    def test_non_web_platforms_are_never_touched(self) -> None:
        raw = RawPost(platform="xhs", title="t", external_id="x-1", url="https://sysu.edu.cn/x")
        self.db.add(raw)
        self.db.flush()
        post = ProcessedPost(
            raw_post_id=raw.id, platform="xhs", note_id="xhs:1", title="t", heat_score=42.0
        )
        self.db.add(post)
        self.db.flush()

        self.assertEqual(refresh_web_heat_scores(self.db), 0)
        self.assertEqual(post.heat_score, 42.0)


class ProcessRawPostsHeatRankTest(unittest.TestCase):
    """process_raw_posts 处理完之后跑一次归一化 pass。"""

    def setUp(self) -> None:
        self.db = make_session()
        self.addCleanup(self.db.close)

    def _add_raw(self, platform: str, **counts) -> RawPost:
        raw = RawPost(
            platform=platform,
            external_id=f"{platform}-{counts.get('external', '1')}",
            title=f"{platform} 标题",
            content="正文",
            status="normal",
            url=counts.pop("url", ""),
            source_table=counts.pop("source_table", ""),
            source_raw_id=counts.pop("source_raw_id", ""),
            like_count=counts.pop("like_count", 0),
            comment_count=counts.pop("comment_count", 0),
        )
        counts.pop("external", None)
        self.db.add(raw)
        self.db.flush()
        return raw

    def test_processing_assigns_heat_rank_within_platform(self) -> None:
        from scripts.process_raw_posts import _process_raw_posts

        self._add_raw("xhs", external="a", like_count=12000)
        self._add_raw("xhs", external="b", like_count=10)
        self._add_raw("weibo", external="c", like_count=9)
        self._add_raw("weibo", external="d", like_count=1)

        result = _process_raw_posts(self.db, limit=100, platforms=None, dry_run=False)
        self.db.commit()

        self.assertEqual(result.inserted, 4)
        self.assertEqual(result.ranked, 4)
        posts = {p.note_id: p for p in self.db.query(ProcessedPost).all()}
        xhs_top = posts["xhs:xhs-a"]
        weibo_top = posts["weibo:weibo-c"]
        weibo_low = posts["weibo:weibo-d"]
        # 微博头部帖（原始热度 9）与小红书头部帖（原始热度 12000）拿到相同的排序分。
        self.assertEqual(weibo_top.heat_rank, xhs_top.heat_rank)
        self.assertGreater(weibo_top.heat_rank, weibo_low.heat_rank)
        # heat_score 原样保留（展示用），公式一个字没改。
        self.assertEqual(xhs_top.heat_score, 12000.0)
        self.assertEqual(weibo_top.heat_score, 9.0)

    def test_web_row_gets_authority_heat_and_beats_a_trivial_post(self) -> None:
        from scripts.process_raw_posts import _process_raw_posts

        self._add_raw(
            WEB_PLATFORM,
            external="w1",
            url="https://news.sysu.edu.cn/notice/1",
            source_table="evidence_items",
            source_raw_id="",
        )
        self._add_raw(WEB_PLATFORM, external="w2", url="https://random.example.com/x")

        _process_raw_posts(self.db, limit=100, platforms=None, dry_run=False)
        self.db.commit()

        posts = {p.note_id: p for p in self.db.query(ProcessedPost).all()}
        official = posts["web:web-w1"]
        unknown = posts["web:web-w2"]
        # 官方通知不再是 0.0 热度（否则它排在任何一条无聊帖子后面）。
        self.assertGreater(official.heat_score, 0.0)
        self.assertGreater(official.heat_rank, unknown.heat_rank)

    def test_refresh_does_not_zero_out_a_web_rows_authority_heat(self) -> None:
        # --refresh 从互动量重算 heat_score；web 行四个互动量都是 0，天真地重算会把
        # 来源权威度分抹成 0。
        from scripts.process_raw_posts import _process_raw_posts

        self._add_raw(
            WEB_PLATFORM,
            external="w1",
            url="https://news.sysu.edu.cn/notice/1",
            source_table="evidence_items",
        )
        _process_raw_posts(self.db, limit=100, platforms=None, dry_run=False)
        self.db.commit()
        post = self.db.query(ProcessedPost).filter_by(platform=WEB_PLATFORM).one()
        authority_heat = post.heat_score
        self.assertGreater(authority_heat, 0.0)

        _process_raw_posts(self.db, limit=100, platforms=None, dry_run=False, refresh=True)
        self.db.commit()

        self.assertEqual(post.heat_score, authority_heat)

    def test_dry_run_writes_no_heat_rank(self) -> None:
        from scripts.process_raw_posts import _process_raw_posts

        raw = self._add_raw("xhs", external="a", like_count=100)
        self.db.commit()

        result = _process_raw_posts(self.db, limit=100, platforms=None, dry_run=True)

        self.assertEqual(result.inserted, 1)
        self.assertEqual(self.db.query(ProcessedPost).count(), 0)
        self.assertIsNotNone(raw.id)


if __name__ == "__main__":
    unittest.main()
