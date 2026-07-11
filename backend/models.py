from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class RawPost(Base):
    """Unified raw posts synced from MediaCrawler native tables."""

    __tablename__ = "raw_posts"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="ux_raw_posts_platform_external_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # platform/publish_time 有索引：管理端按平台筛选、按发布时间排序/日期过滤
    platform: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_table: Mapped[str] = mapped_column(String(64), default="")
    source_raw_id: Mapped[str] = mapped_column(String(255), default="")
    source_keyword: Mapped[str] = mapped_column(String(255), default="")
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(100), default="")
    publish_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    url: Mapped[str] = mapped_column(String(500), default="")
    raw_url: Mapped[str] = mapped_column(String(500), default="")
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    collect_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    share_count: Mapped[int] = mapped_column(Integer, default=0)
    tags_json: Mapped[str] = mapped_column(Text, default="")
    images_json: Mapped[str] = mapped_column(Text, default="")
    raw_json: Mapped[str] = mapped_column(Text, default="")
    crawl_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    processed: Mapped["ProcessedPost | None"] = relationship(back_populates="raw_post")
    event_links: Mapped[list["EventPostLink"]] = relationship(back_populates="raw_post")


class ProcessedPost(Base):
    """Cleaned post record used by the public opinion agent."""

    __tablename__ = "processed_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    raw_post_id: Mapped[int] = mapped_column(ForeignKey("raw_posts.id"), unique=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    note_id: Mapped[str] = mapped_column(String(255), default="")
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    source_keyword: Mapped[str] = mapped_column(String(255), default="")
    publish_date: Mapped[str] = mapped_column(String(20), default="")
    publish_time_raw: Mapped[str] = mapped_column(Text, default="")
    author_name: Mapped[str] = mapped_column(String(128), default="")
    tags_json: Mapped[str] = mapped_column(Text, default="")
    note_url: Mapped[str] = mapped_column(String(500), default="")
    raw_note_url: Mapped[str] = mapped_column(String(500), default="")
    images_json: Mapped[str] = mapped_column(Text, default="")
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    collect_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    share_count: Mapped[int] = mapped_column(Integer, default=0)
    heat_score: Mapped[float] = mapped_column(Float, default=0.0)
    # 平台内归一化排序分（0-100）：该帖 heat_score 在**它自己平台内**的百分位。
    # heat_score 是原始互动量加权和，跨平台量级差 ~3 个数量级（xhs 中位 3924 / weibo 3），
    # 直接排序会把 weibo/zhihu/web 全埋掉；排序/选 top-N/加权一律改用 heat_rank，
    # heat_score 只留给展示。由 backend/services/heat_ranking.py 的归一化 pass 全量重算。
    heat_rank: Mapped[float] = mapped_column(Float, default=0.0)
    sentiment: Mapped[str] = mapped_column(String(20), default="neutral")
    sentiment_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_level: Mapped[str] = mapped_column(String(20), default="low")
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_reasons_json: Mapped[str] = mapped_column(Text, default="")
    concerns_json: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Week-1 compatibility fields kept because they already exist in the shared DB.
    author: Mapped[str] = mapped_column(String(100), default="")
    publish_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    raw_post: Mapped["RawPost"] = relationship(back_populates="processed")
    event_links: Mapped[list["EventPostLink"]] = relationship(back_populates="processed_post")


class ChatQueryLog(Base):
    """用户对舆情助手的一次提问（智能选题的需求/缺口信号源）。"""

    __tablename__ = "chat_query_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), default="")
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    intent: Mapped[str] = mapped_column(String(32), default="")
    # keyword 是意图路由提取的话题词；hit_count 是该轮回答检索命中的事件数。
    keyword: Mapped[str] = mapped_column(String(64), default="", index=True)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class PublicEvent(Base):
    """Public opinion event generated by the opinion agent."""

    __tablename__ = "public_events"
    __table_args__ = (
        UniqueConstraint("event_key", name="ux_public_events_event_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="")
    topic: Mapped[str] = mapped_column(String(100), default="")
    event_type: Mapped[str] = mapped_column(String(64), default="")
    sentiment: Mapped[str] = mapped_column(String(20), default="neutral")
    risk_level: Mapped[str] = mapped_column(String(20), default="low")
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    heat_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    date_range_json: Mapped[str] = mapped_column(Text, default="")
    source_keywords_json: Mapped[str] = mapped_column(Text, default="")
    top_tags_json: Mapped[str] = mapped_column(Text, default="")
    concerns_json: Mapped[str] = mapped_column(Text, default="")
    risk_reasons_json: Mapped[str] = mapped_column(Text, default="")
    # status/created_at 有索引：公开接口按 status 过滤 + created_at 排序是最高频查询
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    reviewed_by: Mapped[str] = mapped_column(String(64), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Week-1 single-source field kept for compatibility; new code should prefer EventPostLink.
    source_post_id: Mapped[int | None] = mapped_column(
        ForeignKey("processed_posts.id"), nullable=True
    )

    post_links: Mapped[list["EventPostLink"]] = relationship(back_populates="event")


class EventPostLink(Base):
    """Many-to-many support relation between an event and its source posts."""

    __tablename__ = "event_post_links"
    __table_args__ = (
        Index("idx_event_post_links_event_id", "event_id"),
        Index("idx_event_post_links_processed_post_id", "processed_post_id"),
        Index("idx_event_post_links_raw_post_id", "raw_post_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("public_events.id"), nullable=False)
    processed_post_id: Mapped[int | None] = mapped_column(
        ForeignKey("processed_posts.id"), nullable=True
    )
    raw_post_id: Mapped[int | None] = mapped_column(ForeignKey("raw_posts.id"), nullable=True)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    role: Mapped[str] = mapped_column(String(32), default="source")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    event: Mapped["PublicEvent"] = relationship(back_populates="post_links")
    processed_post: Mapped["ProcessedPost | None"] = relationship(back_populates="event_links")
    raw_post: Mapped["RawPost | None"] = relationship(back_populates="event_links")


# 已废弃：week-1 的 user_tasks / user_schedules 表（个人事项现走前端本地存储）。
# 模型已移除，共享库中的空表保留不 drop（团队库谨慎），见 docs/database.md。
