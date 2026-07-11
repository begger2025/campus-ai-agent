"""平台先验权重：ranking_score = platform_weight[platform] × heat_rank。

heat_rank（平台内百分位）修好了"跨平台不可比"，但矫枉过正：它把**量级**整个丢了。
一条 3 个赞、排在 weibo 95% 的帖子，和一条 10 万赞、排在 xhs 95% 的帖子拿到同一个分——
可它们的真实触达差了三个数量级。项目负责人人工过了一遍抓到的帖子：xhs/ks 的触达和数据
质量都高于 weibo/zhihu。

所以在百分位之上再乘一个**平台先验权重**：
  - 平台内百分位保住平台内公平（weibo 的头部帖依然赢过 weibo 的长尾帖）；
  - 平台权重把跨平台的触达/质量差异还回来（zhihu 99 分位 ≈ xhs 中位数，能冒头，但压不住 xhs 头部）。

权重必须**不改数据库就能调**：ranking_score 不是新列，是 (platform, heat_rank) 的纯函数。
"""

from __future__ import annotations

import unittest
from unittest import mock

from backend.agent.public_opinion_core.platform_weights import (
    DEFAULT_PLATFORM_WEIGHTS,
    PLATFORM_WEIGHTS_ENV,
    UNKNOWN_PLATFORM_WEIGHT,
    note_ranking_score,
    platform_weight,
    platform_weights,
    ranking_score,
)
from backend.agent.public_opinion_core.schemas import OpinionNote


def _note(platform: str, heat_rank: float, heat_score: float = 0.0) -> OpinionNote:
    return OpinionNote(
        note_id=f"{platform}:{heat_rank}",
        title="标题",
        content="正文",
        platform=platform,
        heat_rank=heat_rank,
        heat_score=heat_score,
    )


class DefaultWeightTableTest(unittest.TestCase):
    """负责人钦定的默认权重表：xhs 1.0 / ks 0.9 / web 0.8 / zhihu 0.5 / weibo 0.4。"""

    def test_owner_chosen_defaults(self) -> None:
        self.assertEqual(DEFAULT_PLATFORM_WEIGHTS["xhs"], 1.0)
        self.assertEqual(DEFAULT_PLATFORM_WEIGHTS["ks"], 0.9)
        self.assertEqual(DEFAULT_PLATFORM_WEIGHTS["web"], 0.8)
        self.assertEqual(DEFAULT_PLATFORM_WEIGHTS["zhihu"], 0.5)
        self.assertEqual(DEFAULT_PLATFORM_WEIGHTS["weibo"], 0.4)

    def test_tieba_has_a_default_even_though_it_has_no_rows_yet(self) -> None:
        # tieba 是受支持的爬虫平台，但库里一行都还没有：给个中游默认值，不留 KeyError。
        self.assertEqual(DEFAULT_PLATFORM_WEIGHTS["tieba"], 0.6)

    def test_unknown_platform_never_silently_drops_a_post_to_zero(self) -> None:
        self.assertEqual(UNKNOWN_PLATFORM_WEIGHT, 1.0)
        self.assertEqual(platform_weight("douyin"), 1.0)
        self.assertEqual(platform_weight(""), 1.0)
        self.assertEqual(platform_weight(None), 1.0)

    def test_platform_lookup_is_case_and_space_insensitive(self) -> None:
        self.assertEqual(platform_weight(" WeiBo "), 0.4)


class RankingScoreTest(unittest.TestCase):
    def test_ranking_score_is_weight_times_heat_rank(self) -> None:
        self.assertEqual(ranking_score("zhihu", 99.0), 49.5)
        self.assertEqual(ranking_score("xhs", 50.0), 50.0)

    def test_ranking_score_of_an_unnormalized_legacy_row_is_zero(self) -> None:
        # heat_rank 未归一化（0）时 ranking_score 也是 0，排序键会退回 heat_rank/heat_score。
        self.assertEqual(ranking_score("xhs", 0.0), 0.0)

    def test_note_ranking_score_reads_the_note_platform(self) -> None:
        self.assertEqual(note_ranking_score(_note("weibo", 95.0)), 38.0)


class WeightsAreTunableWithoutAMigrationTest(unittest.TestCase):
    """权重会被调。调它不能改代码、更不能改数据库——只能改配置。"""

    def test_env_var_overrides_a_single_platform_and_keeps_the_rest(self) -> None:
        with mock.patch.dict("os.environ", {PLATFORM_WEIGHTS_ENV: '{"weibo": 0.9}'}):
            weights = platform_weights()
            self.assertEqual(weights["weibo"], 0.9)
            self.assertEqual(weights["xhs"], 1.0)  # 未覆盖的平台保持默认
            self.assertEqual(ranking_score("weibo", 100.0), 90.0)

    def test_env_var_accepts_key_value_pairs_too(self) -> None:
        with mock.patch.dict("os.environ", {PLATFORM_WEIGHTS_ENV: "zhihu=0.7, weibo=0.6"}):
            weights = platform_weights()
            self.assertEqual(weights["zhihu"], 0.7)
            self.assertEqual(weights["weibo"], 0.6)

    def test_env_var_can_introduce_a_platform_that_is_not_in_the_default_table(self) -> None:
        with mock.patch.dict("os.environ", {PLATFORM_WEIGHTS_ENV: '{"douyin": 0.3}'}):
            self.assertEqual(platform_weight("douyin"), 0.3)

    def test_garbage_config_falls_back_to_defaults_instead_of_crashing_the_pipeline(self) -> None:
        for garbage in ["", "{not json", '{"weibo": "high"}', '{"weibo": -1}', "[1, 2, 3]"]:
            with self.subTest(garbage=garbage):
                with mock.patch.dict("os.environ", {PLATFORM_WEIGHTS_ENV: garbage}):
                    self.assertEqual(platform_weight("weibo"), 0.4)


class CrossPlatformEffectTest(unittest.TestCase):
    """这才是这次改动要的效果，用实测中位数（xhs 3924 / ks 998 / weibo 3 / zhihu 5）说话。"""

    def test_a_99th_percentile_zhihu_post_lands_near_a_median_xhs_post(self) -> None:
        zhihu_top = note_ranking_score(_note("zhihu", 99.0))     # 0.5 × 99 = 49.5
        xhs_median = note_ranking_score(_note("xhs", 50.0))      # 1.0 × 50 = 50.0

        self.assertAlmostEqual(zhihu_top, 49.5)
        self.assertAlmostEqual(xhs_median, 50.0)
        # "能冒头"：和 xhs 中位数在同一档（差距 < 5 分），不再被埋。
        self.assertLess(abs(zhihu_top - xhs_median), 5.0)

    def test_a_99th_percentile_zhihu_post_cannot_outrank_a_high_percentile_xhs_post(self) -> None:
        zhihu_top = note_ranking_score(_note("zhihu", 99.0))     # 49.5
        xhs_high = note_ranking_score(_note("xhs", 90.0))        # 90.0
        self.assertLess(zhihu_top, xhs_high)

    def test_but_it_still_beats_an_xhs_long_tail_post(self) -> None:
        # 纯 heat_score 排序时代，zhihu 头部帖（heat_score 个位数）永远输给 xhs 长尾帖（几千）。
        self.assertGreater(
            note_ranking_score(_note("zhihu", 99.0, heat_score=8.0)),
            note_ranking_score(_note("xhs", 20.0, heat_score=3000.0)),
        )

    def test_intra_platform_fairness_survives(self) -> None:
        # 平台权重是常数倍，平台内的相对顺序一点都不动。
        self.assertGreater(
            note_ranking_score(_note("weibo", 95.0)),
            note_ranking_score(_note("weibo", 10.0)),
        )


if __name__ == "__main__":
    unittest.main()
