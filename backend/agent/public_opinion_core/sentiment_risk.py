"""Rule-based sentiment and public-risk analysis for OpinionNote records."""

from __future__ import annotations

from collections import Counter

from .normalizer import analysis_text, normalize_note_fields, normalize_risk_level, normalize_sentiment_label, note_text
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
    # 不收单字"快"：它在"快四十分钟/快迟到"里是时间副词，会被误判为正面（评测集 s01 发现）。
    "很快",
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


# "综合热度较高"的判定：原来用绝对阈值 heat_score >= 150。它跨平台不可比——weibo 的
# heat_score 中位数只有 3，头部帖也就个位数，这条风险加权对 weibo/zhihu/web 永远不可能
# 触发，只有 xhs/ks 吃得到。改成看平台内百分位：热度进本平台前 20% 才算"热度较高"。
#
# 【为什么这条门槛**故意不**乘平台先验权重（不用 ranking_score）】
# 平台权重是给"**选择/排序**"用的——在跨平台的候选池里比大小、挑 top-N，那时才需要把
# 真实触达差异还回来。而这条规则问的是另一个问题：这条帖子**在它自己的社区里**是不是烧起来
# 了？那是一个纯粹的**平台内属性**，也正是风险信号本身的含义（一条在微博里排进前 5% 的
# 投诉帖，就是在微博里烧起来了，跟小红书的量级无关）。
# 而且如果这里改用 ranking_score >= 80，weibo（权重 0.4）的 ranking_score 上限只有 40、
# zhihu（0.5）只有 50，**永远**够不到 80——这条规则对它们会像绝对阈值 150 时代一样彻底
# 失效，恰恰是上一版要修的那个 bug 原样复发。所以门槛留在裸 heat_rank 上。
HIGH_HEAT_RANK = 80.0
# 归一化之前的老数据 heat_rank 为 0，退回原来的绝对阈值，不让这条规则凭空失效。
LEGACY_HIGH_HEAT_SCORE = 150.0


def _is_high_heat(note: OpinionNote) -> bool:
    if note.heat_rank:
        return note.heat_rank >= HIGH_HEAT_RANK
    return note.heat_score >= LEGACY_HIGH_HEAT_SCORE


def detect_concerns(text: str) -> list[str]:
    concerns: list[str] = []
    for concern, words in CONCERN_RULES.items():
        if any(word in text for word in words):
            concerns.append(concern)
    return concerns


def analyze_note_sentiment_and_risk(note: OpinionNote) -> OpinionNote:
    note = normalize_note_fields(note)
    # 情绪/风险看"帖子+评论区"，聚类嵌入仍只看帖子本体（note_text）。
    text = analysis_text(note)

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
    if _is_high_heat(note):
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


# 平票时的取值顺序（越靠前越优先）。事件情感是要落库、要在事件列表里展示的值，
# 不能由 Counter.most_common 的插入顺序（= 帖子进簇的先后）决定：同一批帖子换个
# 取数顺序就换一个标签，既不可复现也不可辩护。票数相同时取**更保守**的一侧——
# 舆情平台把两半对半的事件说成"正面"，代价远大于说成"中性"。
SENTIMENT_PRECEDENCE = ("negative", "controversial", "neutral", "positive")


def aggregate_sentiment(notes: list[OpinionNote]) -> str:
    """事件级情感 = 负面放大 + 真实多数派（不是"正面只要压过负面就算正面"）。

    历史 bug：`if counts["positive"] > negative_total: return "positive"` 只把 positive
    和 negative 比大小，**neutral 完全不参与**。于是「东校区宿舍火灾」（3 条中性事实
    播报 + 1 条被误聚进来的正面帖）被标成 positive；极端情况 1 正 + 99 中 也是 positive。

    现在的规则，从强到弱：

    1. **负面放大**（保留，故意为之）：负面 + 争议达到 `max(2, len(notes)//3)` 就判 negative。
       舆情场景里少数负面确实比多数中性更值得报出来，这条是设计不是 bug。
    2. **争议放大**（保留）：≥2 条争议帖 ⇒ controversial。
    3. 否则取**真实多数派**（四种标签一起数，neutral 不再被无视），平票按
       `SENTIMENT_PRECEDENCE` 取更保守的一侧，结果与帖子顺序无关。
    """

    if not notes:
        return "neutral"

    counts = Counter(note.sentiment for note in notes)
    negative_total = counts["negative"] + counts["controversial"]
    if negative_total >= max(2, len(notes) // 3):
        return "negative"
    if counts["controversial"] >= 2:
        return "controversial"

    # 未登记的标签（理论上 normalize 之后不会出现）也参与计数，但排在已知标签之后，
    # 并按字母序固定位置——任何情况下都不允许出现"顺序敏感"的结果。
    labels = list(SENTIMENT_PRECEDENCE) + sorted(set(counts) - set(SENTIMENT_PRECEDENCE))

    def rank(label: str) -> tuple[int, int]:
        return counts[label], -labels.index(label)

    return max(labels, key=rank)


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
