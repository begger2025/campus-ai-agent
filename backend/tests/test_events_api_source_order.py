"""事件的来源平台：**顺序是稳定的**。

## 缺陷（2026-07-14 用户反馈，截图实证）

事件列表的「来源」列里，有的事件小红书排在快手前面，有的快手排在小红书前面——
同一组平台，两个事件给出两种顺序，看板看起来是乱的。

根因：`source_platforms` 是**按代表帖的热度排名首次出现**的顺序拼出来的——

    for link in sorted(links, key=lambda item: item.rank):   # rank = 代表帖热度序
        if normalized not in source_platforms:
            source_platforms.append(normalized)

于是"哪个平台排前面"取决于"哪个平台的帖子更火"。那是一个**关于热度的事实**，
但它被摆在了一个**关于来源构成的**位置上——读者会以为顺序有含义，其实没有。

修法：按一个**固定的展示顺序**排。顺序在后端定（`PLATFORM_DISPLAY_ORDER`），
所有页面共用一份——前端各自排一遍，迟早排出两个世界。
"""

from __future__ import annotations

import unittest

from backend.routers.api import PLATFORM_DISPLAY_ORDER, _sort_platforms


class PlatformOrderTest(unittest.TestCase):
    def test_the_same_platforms_always_come_back_in_the_same_order(self):
        """输入顺序不同，输出顺序必须相同——这就是「稳定」的全部含义。"""

        self.assertEqual(_sort_platforms(["ks", "xhs"]), _sort_platforms(["xhs", "ks"]))

    def test_the_order_follows_the_declared_display_order(self):
        shuffled = ["web", "tieba", "weibo", "zhihu", "ks", "xhs"]

        self.assertEqual(_sort_platforms(shuffled), list(PLATFORM_DISPLAY_ORDER))

    def test_an_unknown_platform_goes_last_but_is_never_dropped(self):
        """没见过的平台码排到最后，但**绝不丢弃**——宁可多冒头，不可凭空消失。"""

        ordered = _sort_platforms(["mystery", "xhs"])

        self.assertEqual(ordered, ["xhs", "mystery"])

    def test_duplicates_collapse(self):
        self.assertEqual(_sort_platforms(["xhs", "xhs", "ks"]), ["xhs", "ks"])


class EventItemUsesTheStableOrderTest(unittest.TestCase):
    """接口返回的 source_platforms 必须已经排好序——前端拿到就能直接渲染。"""

    def test_the_api_returns_platforms_in_display_order(self):
        from datetime import UTC, datetime

        from backend.models import EventPostLink, ProcessedPost, PublicEvent
        from backend.routers.api import _event_item

        event = PublicEvent(
            id=1, event_key="k", title="t", summary="s", status="published",
            risk_level="high", risk_score=1.0, heat_score=1.0, source_count=2,
        )
        # 代表帖按 rank：快手的帖子更火（rank=1），小红书的次之（rank=2）。
        # 老实现会因此把 ks 排在 xhs 前面——而另一个事件正好相反，看板就乱了。
        links = []
        for rank, platform in [(1, "ks"), (2, "xhs")]:
            link = EventPostLink(event_id=1, rank=rank, role="representative", raw_post_id=rank)
            link.processed_post = ProcessedPost(
                id=rank, raw_post_id=rank, platform=platform, title="x", content="",
            )
            link.raw_post = None
            links.append(link)

        item = _event_item(event, links, None, now=datetime.now(UTC))

        self.assertEqual(
            item["source_platforms"],
            ["xhs", "ks"],
            "来源顺序跟着代表帖的热度走了——同一组平台在不同事件里会排出不同顺序",
        )
        self.assertEqual(item["sourcePlatforms"], ["xhs", "ks"], "驼峰别名也要是排好序的那份")


if __name__ == "__main__":
    unittest.main()
