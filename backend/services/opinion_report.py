"""Deterministic report builders for chat answers (core-schema edition).

子项目 report_builder 的核心 schema 适配版：字段名按
backend.agent.public_opinion_core.schemas 走（title/source_count/url 等）。
作为 LLM 不可用时的兜底文本，以及喂给 LLM 的压缩事件数据。
"""

from __future__ import annotations

from typing import Any

from backend.agent.public_opinion_core import OpinionEvent
from backend.services.event_read_model import MAX_REPRESENTATIVE_NOTES


# prompt 里每个事件带几条代表帖。**必须和存储上限对齐**：
#   event_post_links       每个事件存 5 条（role='representative'）
#   event_read_model       取回 5 条（MAX_REPRESENTATIVE_NOTES）
#   这里                   曾经写死 3 条  ← 静默丢掉 2 条
#
# 被丢掉的往往正是最切题的那条。EVT-49「东校区宿舍搬迁」的 5 条代表帖按热度排序，
# 第 4 条是知乎的「如何看待中山大学强制东校区万逾名学生在同校区内互相搬迁宿舍？」——
# 11 天前发的、讲的正是事件本身，但它 0 赞 0 评论、热度为 0，排在最后被砍掉；
# 而占着第 1 个坑的是一条 **2021 年**的「东校区封闭管理」（热度 9839）。
# 结果模型读到的是 5 年前的封闭管理，读不到 11 天前的强制搬迁。
PROMPT_MAX_REPRESENTATIVE_NOTES = MAX_REPRESENTATIVE_NOTES


def build_event_digest(events: list[OpinionEvent], *, title: str = "校园公共舆情简报") -> str:
    if not events:
        return "当前数据集中没有找到匹配的校园公共舆情内容。"

    lines = [title, ""]
    for index, event in enumerate(events[:5], start=1):
        concerns = "、".join(event.concerns[:4]) if event.concerns else "暂无明显集中诉求"
        reasons = "、".join(event.risk_reasons[:3]) if event.risk_reasons else "未发现明显风险信号"
        top_note = event.representative_notes[0] if event.representative_notes else None
        top_note_text = f"代表内容：{top_note.title}。" if top_note and top_note.title else ""
        lines.append(
            f"{index}. {event.title}：共 {event.source_count} 条内容，热度 {event.heat_score:.0f}，"
            f"情绪 {event.sentiment}，风险 {event.risk_level}。"
            f"关注点：{concerns}。风险依据：{reasons}。{top_note_text}"
        )
    return "\n".join(lines)


def compact_events_for_llm(events: list[OpinionEvent]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for event in events[:8]:
        compact.append(
            {
                "title": event.title,
                "source_count": event.source_count,
                "heat_score": event.heat_score,
                "sentiment": event.sentiment,
                "risk_level": event.risk_level,
                "risk_score": event.risk_score,
                "first_seen_at": event.first_seen_at,
                "last_seen_at": event.last_seen_at,
                "trend": event.trend,
                "concerns": event.concerns,
                "risk_reasons": event.risk_reasons,
                "representative_notes": [
                    {
                        "title": note.title,
                        "content": note.content[:300],
                        "publish_time": note.publish_time or note.publish_date,
                        "heat_score": note.heat_score,
                        "comment_count": note.comment_count,
                        "url": note.url,
                        # 评论区风向进简报语料（LLM 可引用"评论区反映…"）
                        **({"top_comments": [c[:100] for c in note.top_comments[:2]]}
                           if getattr(note, "top_comments", None) else {}),
                    }
                    for note in event.representative_notes[:PROMPT_MAX_REPRESENTATIVE_NOTES]
                ],
            }
        )
    return compact
