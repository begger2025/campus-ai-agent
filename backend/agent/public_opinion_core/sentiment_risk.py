"""Rule-based sentiment and public-risk analysis for OpinionNote records."""

from __future__ import annotations

from collections import Counter

from .normalizer import normalize_note_fields, normalize_risk_level, normalize_sentiment_label, note_text
from .schemas import OpinionNote


NEGATIVE_WORDS = {
    "不稳定",
    "断供",
    "断",
    "太久",
    "排队",
    "涨价",
    "误会",
    "投诉",
    "诈骗",
    "别点",
    "冲突",
    "压力",
    "暗",
    "不太安心",
    "陌生人",
    "尾随",
    "担心",
    "影响",
    "问题",
    "意见",
    "故障",
    "风险",
    "焦虑",
}

POSITIVE_WORDS = {
    "不错",
    "恢复",
    "改善",
    "接受",
    "好",
    "提醒",
    "明确",
    "清楚",
    "安全感",
    "官方",
    "参加",
    "开放",
    "统一处理",
    "快",
}

HIGH_RISK_WORDS = {
    "诈骗",
    "银行卡",
    "验证码",
    "陌生人",
    "尾随",
    "缴费链接",
}

RISK_TOPIC_WORDS = {
    "校园安全",
    "防诈骗",
    "短信",
    "缴费",
    "路灯",
    "夜间",
    "巡逻",
    "门禁",
    "宿舍",
    "热水",
    "食堂",
    "卫生",
    "课程安排",
    "课表",
    "考试",
    "选课",
    "教务",
    "作业",
}

CONCERN_RULES = {
    "宿舍后勤服务": {"宿舍", "热水", "维修", "洗衣房", "后勤"},
    "食堂服务体验": {"食堂", "饭堂", "排队", "价格", "卫生", "错峰"},
    "课程与教务安排": {"课程安排", "课表", "考试", "选课", "补退选", "教务", "作业"},
    "校园安全风险": {"校园安全", "诈骗", "防诈骗", "短信", "缴费", "路灯", "夜间", "巡逻", "门禁", "陌生人"},
}

RISK_HINT_SCORE = {
    "low": 0,
    "medium": 32,
    "high": 60,
}

SENTIMENT_HINT_SCORE = {
    "positive": 2,
    "neutral": 0,
    "negative": -2,
    "controversial": -1,
}


def _hits(text: str, words: set[str]) -> list[str]:
    return [word for word in words if word in text]


def detect_concerns(text: str) -> list[str]:
    concerns: list[str] = []
    for concern, words in CONCERN_RULES.items():
        if any(word in text for word in words):
            concerns.append(concern)
    return concerns


def analyze_note_sentiment_and_risk(note: OpinionNote) -> OpinionNote:
    note = normalize_note_fields(note)
    text = note_text(note)

    negative_hits = _hits(text, NEGATIVE_WORDS)
    positive_hits = _hits(text, POSITIVE_WORDS)
    high_risk_hits = _hits(text, HIGH_RISK_WORDS)
    risk_topic_hits = _hits(text, RISK_TOPIC_WORDS)

    sentiment_hint = normalize_sentiment_label(note.sentiment)
    sentiment_score = SENTIMENT_HINT_SCORE.get(sentiment_hint, 0)
    sentiment_score += len(positive_hits) - len(negative_hits)

    if negative_hits and positive_hits and abs(sentiment_score) <= 1:
        sentiment = "controversial"
    elif sentiment_score <= -2:
        sentiment = "negative"
    elif sentiment_score >= 2:
        sentiment = "positive"
    elif negative_hits:
        sentiment = "negative"
    elif positive_hits:
        sentiment = "positive"
    else:
        sentiment = "neutral"

    risk_level_hint = normalize_risk_level(note.risk_level)
    risk_score = RISK_HINT_SCORE.get(risk_level_hint, 0)
    reasons: list[str] = []

    if high_risk_hits:
        risk_score += min(len(high_risk_hits) * 18, 45)
        reasons.append("出现安全或诈骗高风险词")
    if negative_hits:
        risk_score += min(len(negative_hits) * 6, 24)
        reasons.append("负面反馈词集中")
    if risk_topic_hits:
        risk_score += min(len(risk_topic_hits) * 4, 24)
        reasons.append("涉及校园公共事务")
    if note.comment_count >= 25:
        risk_score += 8
        reasons.append("评论讨论量较高")
    if note.share_count >= 10:
        risk_score += 10
        reasons.append("分享传播量较高")
    if note.heat_score >= 150:
        risk_score += 8
        reasons.append("综合热度较高")

    if not high_risk_hits and sentiment == "positive":
        risk_score = min(risk_score, 55)

    if risk_score >= 85:
        risk_level = "high"
    elif risk_score >= 35:
        risk_level = "medium"
    else:
        risk_level = "low"

    note.sentiment = sentiment
    note.sentiment_score = float(sentiment_score)
    note.risk_level = risk_level
    note.risk_score = float(min(risk_score, 100))
    note.risk_reasons = list(dict.fromkeys(reasons))
    note.concerns = detect_concerns(text)
    return note


def analyze_notes_sentiment_and_risk(notes: list[OpinionNote]) -> list[OpinionNote]:
    return [analyze_note_sentiment_and_risk(note) for note in notes]


def aggregate_sentiment(notes: list[OpinionNote]) -> str:
    if not notes:
        return "neutral"

    counts = Counter(note.sentiment for note in notes)
    negative_total = counts["negative"] + counts["controversial"]
    if negative_total >= max(2, len(notes) // 3):
        return "negative"
    if counts["positive"] > negative_total:
        return "positive"
    if counts["controversial"] >= 2:
        return "controversial"
    return counts.most_common(1)[0][0]


def aggregate_risk_level(notes: list[OpinionNote]) -> tuple[str, float, list[str], list[str]]:
    if not notes:
        return "low", 0.0, [], []

    risk_score = max(note.risk_score for note in notes)
    if sum(1 for note in notes if note.risk_level == "high") >= 2:
        risk_score += 10
    if sum(1 for note in notes if note.risk_level in {"medium", "high"}) >= 3:
        risk_score += 8

    if risk_score >= 85:
        level = "high"
    elif risk_score >= 35:
        level = "medium"
    else:
        level = "low"

    reasons: list[str] = []
    concerns: list[str] = []
    for note in notes:
        reasons.extend(note.risk_reasons)
        concerns.extend(note.concerns)

    return level, float(min(risk_score, 100)), list(dict.fromkeys(reasons)), list(dict.fromkeys(concerns))
