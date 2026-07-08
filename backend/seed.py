from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from backend.models import ProcessedPost, PublicEvent, RawPost

SAMPLE_POSTS = [
    {
        "platform": "weibo",
        "title": "学校调整课间休息时间引发讨论",
        "content": "有同学反映课间从10分钟缩短到5分钟，跨教学楼上课更紧张了。",
        "author": "校园观察",
        "url": "https://example.com/post/1",
    },
    {
        "platform": "xiaohongshu",
        "title": "食堂新窗口排队情况",
        "content": "二楼新开的轻食窗口中午排队约20分钟，价格偏贵但评价不错。",
        "author": "吃货同学",
        "url": "https://example.com/post/2",
    },
    {
        "platform": "weibo",
        "title": "警惕兼职刷单诈骗",
        "content": "近期有同学收到刷单兼职私信，已有被骗案例，请勿轻信。",
        "author": "安全提醒",
        "url": "https://example.com/post/3",
    },
]


def seed_if_empty(db: Session) -> None:
    if db.query(RawPost).count() > 0:
        return

    now = datetime.utcnow()
    for i, item in enumerate(SAMPLE_POSTS):
        publish_time = now - timedelta(hours=6 - i)
        raw = RawPost(
            **item,
            publish_time=publish_time,
            crawl_time=now,
        )
        db.add(raw)
        db.flush()

        processed = ProcessedPost(
            raw_post_id=raw.id,
            platform=raw.platform,
            title=raw.title,
            content=raw.content,
            author=raw.author,
            publish_time=raw.publish_time,
        )
        db.add(processed)

    db.add(
        PublicEvent(
            title="课间时间调整",
            summary="课间缩短引发跨楼上课赶时间讨论",
            sentiment="negative",
            topic="作息调整",
            heat_score=0.82,
            source_post_id=1,
        )
    )
    db.commit()
