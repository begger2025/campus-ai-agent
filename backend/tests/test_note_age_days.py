"""聊天工具里的帖龄计算：必须用 UTC 基准，与库里 publish_time 的口径一致。

审计发现（2026-07-17）：原实现是嵌在 ReAct 工具闭包里的
`datetime.now() - published`——now() 是本地时区（UTC+8），而 publish_time
落库时是 naive UTC，两者相减让每条帖子的年龄系统性多算 8 小时，
run_trend 的窗口分半统计随之偏移。修法：提为模块级函数 + UTC 基准 +
now 参数可注入（可测试）。
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from backend.services.opinion_chat_service import note_age_days


def _note(publish_time: str = "", publish_date: str = "") -> SimpleNamespace:
    return SimpleNamespace(publish_time=publish_time, publish_date=publish_date)


class NoteAgeDaysTests(unittest.TestCase):
    def test_age_is_measured_against_injected_now(self) -> None:
        age = note_age_days(
            _note("2026-07-16 00:00:00"),
            now=datetime(2026, 7, 17, 0, 0, 0),
        )

        self.assertAlmostEqual(age, 1.0)

    def test_default_now_is_utc_not_local(self) -> None:
        # 刚刚（UTC）发布的帖子年龄应约等于 0。
        # 旧实现用 datetime.now()（本地 UTC+8）会算出 ~0.33 天。
        just_now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        age = note_age_days(_note(just_now))

        self.assertIsNotNone(age)
        self.assertLess(age, 0.05, "UTC 基准下刚发布的帖子年龄必须≈0（本地时区基准会差 8 小时）")

    def test_future_timestamp_clamps_to_zero(self) -> None:
        future = (datetime.utcnow() + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")

        self.assertEqual(note_age_days(_note(future)), 0.0)

    def test_missing_or_bad_time_returns_none(self) -> None:
        self.assertIsNone(note_age_days(_note("")))
        self.assertIsNone(note_age_days(_note("不是时间")))

    def test_falls_back_to_publish_date(self) -> None:
        age = note_age_days(
            _note("", "2026-07-15"),
            now=datetime(2026, 7, 16, 0, 0, 0),
        )

        self.assertAlmostEqual(age, 1.0)


if __name__ == "__main__":
    unittest.main()
