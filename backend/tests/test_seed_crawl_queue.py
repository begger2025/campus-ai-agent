"""播种纯逻辑测试：笛卡尔积、去重（当前 pending/claimed）、行构造。"""

import unittest

from scripts.seed_crawl_queue import build_seed_rows, filter_new_rows, parse_platforms


class ParsePlatformsTests(unittest.TestCase):
    def test_splits_and_trims(self):
        self.assertEqual(parse_platforms("ks, zhihu ,wb"), ["ks", "zhihu", "wb"])

    def test_rejects_unknown(self):
        with self.assertRaises(ValueError):
            parse_platforms("ks,douyin")


class BuildSeedRowsTests(unittest.TestCase):
    def test_cartesian_product(self):
        rows = build_seed_rows(["ks", "zhihu"], ["宿舍", "食堂"], priority=3, now_ms=1000)
        keys = {(r["platform"], r["keyword"]) for r in rows}
        self.assertEqual(
            keys, {("ks", "宿舍"), ("ks", "食堂"), ("zhihu", "宿舍"), ("zhihu", "食堂")}
        )
        for r in rows:
            self.assertEqual(r["status"], "pending")
            self.assertEqual(r["priority"], 3)
            self.assertEqual(r["created_at"], 1000)

    def test_dedup_keywords_within_input(self):
        rows = build_seed_rows(["ks"], ["宿舍", "宿舍", " 宿舍 "], priority=0, now_ms=1)
        self.assertEqual(len(rows), 1)


class FilterNewRowsTests(unittest.TestCase):
    def test_skips_active_pairs(self):
        candidate = build_seed_rows(["ks", "zhihu"], ["宿舍"], priority=0, now_ms=1)
        # ks/宿舍 已在队列且 pending → 跳过；zhihu/宿舍 是新的 → 保留
        active = {("ks", "宿舍")}
        new_rows = filter_new_rows(candidate, active)
        self.assertEqual([(r["platform"], r["keyword"]) for r in new_rows], [("zhihu", "宿舍")])

    def test_done_pairs_not_active_so_requeued(self):
        candidate = build_seed_rows(["ks"], ["宿舍"], priority=0, now_ms=1)
        active = set()  # done/failed 不在 active 集 → 允许重新入队
        self.assertEqual(len(filter_new_rows(candidate, active)), 1)


if __name__ == "__main__":
    unittest.main()
