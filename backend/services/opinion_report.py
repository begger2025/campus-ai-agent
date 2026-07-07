"""Deterministic report builders for chat answers (core-schema edition).

子项目 report_builder 的核心 schema 适配版：字段名按
backend.agent.public_opinion_core.schemas 走（title/source_count/url 等）。
作为 LLM 不可用时的兜底文本，以及喂给 LLM 的压缩事件数据。
"""

from __future__ import annotations

from typing import Any

from backend.agent.public_opinion_core import OpinionEvent


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
                    }
                    for note in event.representative_notes[:3]
                ],
            }
        )
    return compact
