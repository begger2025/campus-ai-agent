"""监控汇总 + 重置目标选择纯逻辑测试。"""

import unittest

from scripts.crawl_queue_status import summarize
from scripts.reset_crawl_queue import select_target_ids


def _row(id, platform, status, keyword="kw", claimed_by=None, lease_expires_at=0):
    return {
        "id": id, "platform": platform, "status": status, "keyword": keyword,
        "claimed_by": claimed_by, "lease_expires_at": lease_expires_at,
    }


class SummarizeTests(unittest.TestCase):
    def test_counts_by_platform_and_status(self):
        rows = [
            _row(1, "ks", "pending"), _row(2, "ks", "done"), _row(3, "ks", "done"),
            _row(4, "zhihu", "claimed"), _row(5, "zhihu", "failed"),
        ]
        summary = summarize(rows)
        self.assertEqual(summary["ks"], {"pending": 1, "claimed": 0, "done": 2, "failed": 0})
        self.assertEqual(summary["zhihu"], {"pending": 0, "claimed": 1, "done": 0, "failed": 1})


class SelectTargetIdsTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            _row(1, "ks", "claimed"), _row(2, "ks", "failed"),
            _row(3, "ks", "done"), _row(4, "zhihu", "claimed"),
        ]

    def test_requeue_claimed(self):
        ids = select_target_ids(self.rows, requeue_claimed=True, requeue_failed=False,
                                clear_done=False, platform=None)
        self.assertEqual(sorted(ids), [1, 4])

    def test_requeue_failed(self):
        ids = select_target_ids(self.rows, requeue_claimed=False, requeue_failed=True,
                                clear_done=False, platform=None)
        self.assertEqual(sorted(ids), [2])

    def test_clear_done(self):
        ids = select_target_ids(self.rows, requeue_claimed=False, requeue_failed=False,
                                clear_done=True, platform=None)
        self.assertEqual(sorted(ids), [3])

    def test_platform_filter(self):
        ids = select_target_ids(self.rows, requeue_claimed=True, requeue_failed=False,
                                clear_done=False, platform="ks")
        self.assertEqual(sorted(ids), [1])


if __name__ == "__main__":
    unittest.main()
