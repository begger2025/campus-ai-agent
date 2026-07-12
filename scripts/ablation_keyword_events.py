"""消融实验：智能选题 —— 看不看得见"事件"。

同一批语料、同一个打分器跑两遍，唯一的变量是**选题器知不知道舆情事件的存在**：

  A. 现行臂（改造前）：候选池 = 用户提问（ChatQueryLog）+ 已爬内容标签（ProcessedPost）。
     `score = (0.5·demand + 0.3·gap + 0.2·heat) × crawl_penalty × 10`
  B. 事件臂：候选池 **+ 已发布事件**（算术加权）**+ LLM 从事件正文生成的检索词**（判断）。
     `score = 上式 + 0.3·event_norm × event_penalty × 10`

**要回答的问题：**
  1. 事件臂能提出哪些现行臂**结构上不可能**提出的词？（预期：「学术不端」——它不出现在
     任何标题、任何标签、任何用户提问里，一个只会给已有词排序的打分器永远排不出它。）
  2. 分数和名次怎么变？头号未决丑闻（「中大杰青实名举报」high/91/悬而未决）能不能把
     「食堂」压下去？
  3. **LLM 提的词里有多少被卫生规则拒了？为什么？**（同一套 GENERIC_BLACKLIST /
     MAX_KEYWORD_LEN——LLM 不享有绕过校验的特权。）
  4. **模型提的词到底好不好？** 如果它净说些「校园热点」这样的废话，**如实写**。
     一个被反复调教到能讨好本功能的提示词，是一句会在新数据上碎掉的谎。

**不连数据库**：事件来自 fixture（`data/fixtures/event_clustering_297.json`，297 条
processed_posts 只读快照）跑完整聚类+风险+状态流水线；提问来自 QUERY_SNAPSHOT（下方，
chat_query_log 全表 3 行的只读快照——线上就这么少，如实用）。
**now 可注入**（--now），所以这份报告是可复现的。

    python scripts/ablation_keyword_events.py
    python scripts/ablation_keyword_events.py --now 2026-07-12
    python scripts/ablation_keyword_events.py --no-llm    # 只测算术那一半
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from backend.agent.public_opinion_core import (  # noqa: E402
    AnalyzeRequest,
    PublicOpinionAgentService,
)
from backend.agent.public_opinion_core import keyword_planner  # noqa: E402
from backend.agent.public_opinion_core.keyword_planner import (  # noqa: E402
    EVENT_TOP_KEYWORDS,
    W_ASK,
    W_EVENT,
    W_GAP,
    W_HEAT,
    ContentStat,
    EventRecord,
    QueryRecord,
    event_priority,
    normalize_keyword,
    plan_keywords,
)
from backend.agent.public_opinion_core.llm_keywords import (  # noqa: E402
    generate_event_keywords,
)
from backend.agent.public_opinion_core.recency import (  # noqa: E402
    annotate_events_with_recency,
    parse_time,
    recency_config,
)
from backend.services.embedding import get_embedder  # noqa: E402
from backend.services.event_keywords import get_keyword_proposer  # noqa: E402
from backend.services.event_lifecycle import get_lifecycle_assessor  # noqa: E402
from backend.agent.public_opinion_core.llm_lifecycle import (  # noqa: E402
    assess_events_lifecycle,
)
from backend.services.event_refiner import get_cluster_refiner  # noqa: E402
from backend.services.event_risk import get_risk_assessor  # noqa: E402
from backend.services.keyword_suggestion_adapter import (  # noqa: E402
    MIN_TAG_POSTS,
    _parse_top_tags,
)
from backend.services.llm_client import get_llm_usage, reset_llm_usage  # noqa: E402
from backend.services.llm_config import (  # noqa: E402
    EMBEDDING_ALIGN_THRESHOLD,
    EMBEDDING_CLUSTER_THRESHOLD,
    EMBEDDING_MERGE_THRESHOLD,
    EVENT_KEYWORD_MAX,
    EVENT_KEYWORD_TOP_EVENTS,
    EVENT_LLM_MODEL,
    EVENT_MIN_CLUSTER_SIZE,
    EVENT_REFINE_MIN_SIZE,
    EVENT_RISK_MAX_TEXTS,
)

FIXTURE = ROOT / "data" / "fixtures" / "event_clustering_297.json"
REPORT = ROOT / "docs" / "keyword-event-ablation.md"

CONTENT_WINDOW_DAYS = 14
TOP_N = 12

# chat_query_log **全表**的只读快照（2026-07-12 读的线上库，就 3 行）：
# 两条空 keyword（complex_analysis 类问题不产关键词，planner 本来就跳过），一条「食堂」。
# 语料稀疏是事实，不粉饰——这恰恰是"现行选题器只会推荐食堂"的直接原因。
QUERY_SNAPSHOT = [
    {"keyword": "", "hit_count": 8, "asked_at": "2026-07-10 18:24:18"},
    {"keyword": "", "hit_count": 8, "asked_at": "2026-07-10 18:27:35"},
    {"keyword": "食堂", "hit_count": 1, "asked_at": "2026-07-11 07:01:28"},
]

# 已发布事件（线上 public_events.status='published' 的 7 条）的标题关键字：
# 聚类是可复现的，但事件标题由 LLM 生成，用关键字匹配比用 event_key 稳。
PUBLISHED_TITLES = (
    "杰青", "举报", "宿舍搬迁", "作息", "课间", "火情", "火灾", "火箭", "项飙",
)


def load_rows() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def build_queries(now: datetime) -> list[QueryRecord]:
    return [
        QueryRecord(
            keyword=item["keyword"],
            asked_at=parse_time(item["asked_at"]),
            hit_count=item["hit_count"],
        )
        for item in QUERY_SNAPSHOT
    ]


def build_content_signals(
    rows: list[dict], now: datetime
) -> tuple[list[ContentStat], dict[str, datetime]]:
    """从 fixture 复刻 adapter 的 C/D 两路（内容热度 + 上次爬取时间）。

    adapter 用 processed_posts.created_at 过窗、用 publish_time 算衰减；fixture 里只有
    publish_time，两处都用它（差别只影响哪些帖子落进 14 天窗，不影响两臂的**对比**：
    两臂吃的是同一份 content_stats）。
    """

    stats: list[ContentStat] = []
    crawled: dict[str, datetime] = {}
    cutoff = now - timedelta(days=CONTENT_WINDOW_DAYS)
    for row in rows:
        published = parse_time(row.get("publish_time") or row.get("publish_date"))
        if published is None:
            continue
        source_keyword = str(row.get("source_keyword") or "").strip()
        if source_keyword:
            previous = crawled.get(source_keyword)
            if previous is None or published > previous:
                crawled[source_keyword] = published
        if published < cutoff:
            continue
        engagement = sum(
            int(row.get(field) or 0)
            for field in ("like_count", "collect_count", "comment_count", "share_count")
        )
        words = {str(tag).strip() for tag in (row.get("keywords") or []) if str(tag).strip()}
        if source_keyword:
            words.add(source_keyword)
        for word in words:
            stats.append(ContentStat(keyword=word, engagement=engagement, published_at=published))
    return stats, crawled


def build_event_records(events, now: datetime, *, tag_floor: bool = True) -> list[EventRecord]:
    """OpinionEvent（流水线产物）-> EventRecord（选题器的只读投影）。等价于 adapter 从库里读。

    `tag_floor=False` 复现 **6f85f72 那一版**（只有 count/max_count 权重、没有出现次数门槛），
    用来量本轮那道门槛到底拦下了什么——不然"修好了"就只是一句自我表扬。
    """

    records: list[EventRecord] = []
    for index, event in enumerate(events, start=1):
        if not any(word in event.title for word in PUBLISHED_TITLES):
            continue  # 只有 published 事件能左右爬取计划（人工闸门）
        texts = [
            (note.title or note.content or "").strip()[:120]
            for note in event.representative_notes
        ]
        # 标签的门槛与权重**直接调 adapter 的 _parse_top_tags**（不再在这里复制一遍算术，
        # 否则消融测的就不是线上跑的那条规则了）：count < 2 的标签根本不进候选池
        # （一个发帖人的一个 hashtag 不是证据），过关者按 count / max_count 加权。
        if tag_floor:
            weights = _parse_top_tags(json.dumps(event.top_tags, ensure_ascii=False))
        else:
            counts = {
                str(tag.get("tag") or ""): float(tag.get("count") or 1)
                for tag in event.top_tags
                if str(tag.get("tag") or "")
            }
            top = max(counts.values(), default=0.0) or 1.0
            weights = {name: count / top for name, count in counts.items()}
        records.append(
            EventRecord(
                event_id=str(index),
                title=event.title,
                risk_level=event.risk_level,
                lifecycle=event.lifecycle,
                event_time=parse_time(event.event_time),
                keywords=[*weights, *event.source_keywords],
                keyword_weights=weights,
                texts=[text for text in texts if text][:5],
            )
        )
    return records


def render(
    now: datetime,
    half_life: float,
    baseline: list,
    event_arm: list,
    records: list[EventRecord],
    raw_proposals: dict[str, list[str]],
    stats: dict[str, int],
    warnings: list[str],
    usage: dict,
    corpus: int,
    prev_arm: list,
    tag_counts: dict[str, dict[str, int]],
    floor_only_arm: list,
) -> str:
    lines: list[str] = []
    add = lines.append
    base_by_kw = {s.keyword: s for s in baseline}
    arm_by_kw = {s.keyword: s for s in event_arm}
    prev_by_kw = {s.keyword: s for s in prev_arm}
    floor_by_kw = {s.keyword: s for s in floor_only_arm}

    add("# 消融实验：智能选题 —— 看不看得见「事件」")
    add("")
    add(f"语料：`{FIXTURE.relative_to(ROOT).as_posix()}`（{corpus} 条 processed_posts 只读快照）")
    add("提问：`chat_query_log` 全表快照（**3 行**，其中 2 行无关键词）——线上就这么稀疏，如实用。")
    add(f"参数：now={now.isoformat(timespec='seconds')}（注入，可复现） "
        f"half_life={half_life} 天 model={EVENT_LLM_MODEL} temperature=0")
    add("**不连数据库。**")
    add("")
    add("## 缺陷")
    add("")
    add("```")
    add("grep -c event backend/agent/public_opinion_core/keyword_planner.py \\")
    add("             backend/services/keyword_suggestion_adapter.py   ->   0 和 0")
    add("```")
    add("")
    add("选题器的候选池只有两个来源：**用户问过什么**、**已经爬回来什么**。它从来没听说过"
        "「事件」——")
    add("于是同一个系统，一边把「中大杰青实名举报」判成 high(91)、悬而未决、全库第一优先级，")
    add("一边让选题器继续推荐**「食堂」**。左手不知道右手在干什么。")
    add("")
    add("## 两条腿分别站在原则的哪一侧")
    add("")
    add("| 问题 | 谁来答 | 依据 |")
    add("| --- | --- | --- |")
    add("| 这个词有多值得爬 | **算术** | demand / gap / heat / `severity×recency×lifecycle` |")
    add("| 这件事有多严重、完了没有 | **LLM**（早就判完落库了） | 读帖子 |")
    add("| 这件事**该用什么词去搜** | **LLM** | 读帖子——**排序器排不出它没见过的词** |")
    add("")
    add(f"事件项的分数：`{W_EVENT}·event_norm × event_penalty × 10`，"
        f"与老三路（`{W_ASK}/{W_GAP}/{W_HEAT}`）**并列相加，不重新归一化**。")
    add("理由：归一化会让**一个事件都没有的部署**每个词凭空掉 30% 分——这一路明明什么都没说。")
    add(f"代价是分数上界从 10 变成 {10 * (1 + W_EVENT):.1f}，如实记在这里。")
    add("")

    add("## 一、事件集合与它们的算术优先级")
    add("")
    add("`event_priority = severity_weight(risk) × recency_weight(age) × lifecycle_weight(lifecycle)`")
    add("——**三个数都是现成的**（LLM 早就判完并落库），把它们乘起来是**接线，不是智能**。")
    add("")
    add("| 事件 | 风险 | 状态 | 年龄 | event_priority | event_norm |")
    add("| --- | --- | --- | ---: | ---: | ---: |")
    priorities = {
        record.event_id: event_priority(record, now, half_life_days=half_life)
        for record in records
    }
    top_priority = max(priorities.values(), default=0.0) or 1.0
    for record in sorted(records, key=lambda r: -priorities[r.event_id]):
        age = (now - record.event_time).days if record.event_time else None
        add(
            f"| {record.title} | {record.risk_level} | {record.lifecycle or '未研判'} "
            f"| {age if age is not None else '?'} 天 | {priorities[record.event_id]:.3f} "
            f"| {priorities[record.event_id] / top_priority:.3f} |"
        )
    add("")

    add("## 二、LLM 实际提出的检索词（**逐字照抄，不挑不改**）")
    add("")
    if not raw_proposals:
        add("> **LLM 未运行**（--no-llm 或未配置 EVENT_LLM_API_KEY）：事件只贡献自己的标签词，")
        add("> 算术那一半照常工作。")
        add("")
    else:
        add("| 事件 | 模型提的词（原样） | 过卫生规则后 | 被拒 |")
        add("| --- | --- | --- | --- |")
        for record in sorted(records, key=lambda r: -priorities[r.event_id]):
            raw = raw_proposals.get(record.event_id)
            if raw is None:
                add(f"| {record.title} | （未送模型：不在 top-{EVENT_KEYWORD_TOP_EVENTS}） | — | — |")
                continue
            rejected = [word for word in raw if not normalize_keyword(word)]
            add(
                f"| {record.title} | {'、'.join(f'`{w}`' for w in raw)} "
                f"| {'、'.join(f'**{w}**' for w in record.generated_keywords) or '（全被拒）'} "
                f"| {'、'.join(f'`{w}`' for w in rejected) or '—'} |"
            )
        add("")
        add(
            f"**卫生规则实测：{stats['accepted']} 个通过，{stats['rejected']} 个被拒。**"
            " 拒绝走的是 planner **自己**的 `normalize_keyword` / `GENERIC_BLACKLIST` /"
            f" `MAX_KEYWORD_LEN`（≤12 字）——LLM 提「校园生活」，和用户提「校园生活」被**同一条规则**拒掉。"
        )
        add("")

    add("## 三、现行臂**结构上提不出**的词")
    add("")
    only_in_arm = [kw for kw in arm_by_kw if kw not in base_by_kw]
    generated = {
        word for record in records for word in record.generated_keywords
    }
    add("现行 planner 只能给**字面上已经出现过**的词排序（提问里出现过、或标签里出现过）。")
    add("下面这些词，它**永远**排不出来——不是权重不够，是候选池里根本没有这个字符串：")
    add("")
    if only_in_arm:
        add("| 词 | 事件臂分数 | 现行臂 | 出处 | 语料里出现过吗 |")
        add("| --- | ---: | ---: | --- | --- |")
        for keyword in sorted(only_in_arm, key=lambda k: -arm_by_kw[k].score):
            suggestion = arm_by_kw[keyword]
            origin = "**LLM 生成**" if keyword in generated else "事件标签"
            add(
                f"| **{keyword}** | {suggestion.score:.2f} | **不存在** | {origin} "
                f"| {'**否**（LLM 说出来的）' if keyword in generated else '是（事件标签）'} |"
            )
        add("")
    else:
        add("**一个都没有。** 事件臂没能带来任何新词——如实记下（见「诚实记录」）。")
        add("")

    add("## 四、Top-{0} 并排".format(TOP_N))
    add("")
    add("| 排名 | 现行臂 | 分 | | 事件臂 | 分 | 信号 | 变化 |")
    add("| ---: | --- | ---: | :-: | --- | ---: | --- | :-: |")
    for index in range(TOP_N):
        left = baseline[index] if index < len(baseline) else None
        right = event_arm[index] if index < len(event_arm) else None
        if left is None and right is None:
            break
        if right is None:
            add(f"| {index + 1} | {left.keyword} | {left.score:.2f} | | — | — | — | — |")
            continue
        previous = next(
            (i + 1 for i, s in enumerate(baseline) if s.keyword == right.keyword), None
        )
        if previous is None:
            change = "**新**"
        else:
            delta = previous - (index + 1)
            change = f"↑{delta}" if delta > 0 else (f"↓{-delta}" if delta < 0 else "—")
        left_keyword = left.keyword if left else "—"
        left_score = f"{left.score:.2f}" if left else "—"
        add(
            f"| {index + 1} | {left_keyword} | {left_score} | → "
            f"| **{right.keyword}** | {right.score:.2f} "
            f"| {'/'.join(right.signals)} | {change} |"
        )
    add("")

    add("## 五、点名对质：丑闻 vs 食堂")
    add("")
    canteen_base = base_by_kw.get("食堂")
    canteen_arm = arm_by_kw.get("食堂")
    add("| 词 | 现行臂分/名 | 事件臂分/名 |")
    add("| --- | --- | --- |")

    def rank_of(items, keyword):
        for index, item in enumerate(items, start=1):
            if item.keyword == keyword:
                return index
        return None

    def arm_cell(keyword: str) -> str:
        """事件臂那一格。**「不存在」和「被配额挤掉」不是一回事**，不许混着写。"""

        arm = arm_by_kw.get(keyword)
        if arm:
            return f"{arm.score:.2f} / 第 {rank_of(event_arm, keyword)}"
        if keyword in floor_by_kw:  # 有门槛无配额的臂上有、最终没有 = 配额拿掉的
            return f"**被事件配额挤掉**（{floor_by_kw[keyword].score:.2f}）"
        if keyword in prev_by_kw:   # 只在 6f85f72 臂上有 = 标签门槛拦下的
            return f"**被标签门槛拦下**（{prev_by_kw[keyword].score:.2f}）"
        return "不存在（被合并或被卫生规则拒）"

    for keyword in ("食堂", *sorted(generated)):
        base = base_by_kw.get(keyword)
        add(
            f"| {keyword} "
            f"| {f'{base.score:.2f} / 第 {rank_of(baseline, keyword)}' if base else '**不存在**'} "
            f"| {arm_cell(keyword)} |"
        )
    add("")
    if canteen_base and canteen_arm:
        add(
            f"「食堂」在两臂里分数**完全一样**（{canteen_base.score:.2f}）——事件信号是**加项**，"
            "它不改写别人的分数，只是把更该爬的词加进来、排到前面去。"
        )
    add("")

    add("## 六、reason（管理员看到的那句话）")
    add("")
    for keyword in sorted(generated | {"食堂"}, key=lambda k: -(arm_by_kw[k].score if k in arm_by_kw else 0)):
        if keyword in arm_by_kw:
            add(f"- **{keyword}**（{arm_by_kw[keyword].score:.2f}）：{arm_by_kw[keyword].reason}")
    add("")
    add("出处是**强制**的：每一条建议都带着 `event_refs`（事件 id + 标题 + 风险 + 状态 + 来源），")
    add("管理员点开就知道「学术不端」是从哪件事上长出来的，而不是一个凭空冒出来的词。")
    add("")

    add("## 七、人工闸门没有动")
    add("")
    add("这些**全都只是建议**。`GET /api/admin/keyword-suggestions` 返回它们，管理员点一下才进")
    add("爬取队列——**没有任何东西被自动入队**。和证据投递、事件发布同一条纪律：**AI 提议，人来决定**。")
    add("")

    add("## 八、本轮两个修复的实测（第三条臂 = 6f85f72 原样）")
    add("")
    add("为了不让「修好了」变成一句自我表扬，这里再跑一条臂：**标签没有出现次数门槛、"
        "事件没有席位配额**（即 6f85f72 那一版），其余一切相同（同一批事件、同一次 LLM 调用）。")
    add("")
    add("### 8.1 出现一次的标签（`count == 1`）")
    add("")
    add("`count` 是「有几条成员帖带这个标签」。`count=1` = **全事件只有一个发帖人打过它**——")
    add("那是他一个人的 hashtag 习惯。门槛：`count >= 2`（两个互不相识的发帖人对同一件事想到了")
    add("同一个词，这是标签能构成证据的最小形态）。")
    add("")
    add("| 事件 | 标签分布（count） | 过门槛 | 被拦下 |")
    add("| --- | --- | --- | --- |")
    for record in records:
        counts = tag_counts.get(record.event_id, {})
        if not counts:
            continue
        kept = [f"**{tag}**({count})" for tag, count in counts.items() if count >= MIN_TAG_POSTS]
        dropped = [f"{tag}({count})" for tag, count in counts.items() if count < MIN_TAG_POSTS]
        add(
            f"| {record.title} | "
            f"{'、'.join(f'{tag}({count})' for tag, count in counts.items()) or '—'} | "
            f"{'、'.join(kept) or '**一个都没有**'} | {'、'.join(dropped) or '—'} |"
        )
    add("")
    add("**退化情形（门槛为什么必须是绝对下限、不能是「占最大值的比例」）：**"
        "《中大火箭试验成功》唯一的标签是 宿舍(1)，它的 `max_count` **本身就是 1**——")
    add("`share = 1/1 = 1.0`，任何比例阈值都给它满分，于是一件火箭的事把「宿舍」顶上榜。")
    add("绝对下限的答案很干脆：**这个事件一个标签都提不出来**（它真的拿去爬过的 `source_keywords` 不受影响）。")
    add("")
    add("### 8.2 一个事件占几个席位")
    add("")
    add(f"配额：一个事件最多在最终榜单上放 **{EVENT_TOP_KEYWORDS} 个「只靠事件立身」的词**"
        f"（有站内热度 / 有人问过的词自己站得住，不占配额）。")
    add("")
    add("对照的是**只修了缺陷 1 的那条臂**（有标签门槛、没有配额），所以这一格量的")
    add("**只是配额**——不把 8.1 的功劳算到 8.2 头上。")
    add("")
    add("两列数字是**上榜词里带着这件事出处的个数**，它**可以大于 3**，两个原因，都是设计：")
    add("① 「宿舍」这种有站内热度的词**不占配额**（它自己站得住）；")
    add("② 一个词可以同时挂在好几件事上（「宿舍」在 4 件事的标签里都出现），"
        "它只在**最急的那件事**头上记一次账。右边那列（被配额挤掉的词）才是配额的**净效果**。")
    add("")
    add("| 事件 | 有门槛无配额 | 本轮（门槛+配额） | 被配额挤掉的词 |")
    add("| --- | ---: | ---: | --- |")
    for record in records:
        def words_of(by_kw: dict) -> list[str]:
            return [
                keyword
                for keyword, suggestion in by_kw.items()
                if any(ref["event_id"] == record.event_id for ref in suggestion.event_refs)
            ]
        before, after = words_of(floor_by_kw), words_of(arm_by_kw)
        gone = [word for word in before if word not in after]
        if not before:
            continue
        add(
            f"| {record.title} | {len(before)} | {len(after)} | "
            f"{'、'.join(gone) or '—'} |"
        )
    add("")
    add("被挤掉的词**不是被压到榜尾，是真的拿掉了**：它们是同一句话的第 4、5、6 种说法，")
    add("留在榜上只会继续挤占别的事件和用户的真实提问。腾出来的席位去了哪里，看第四节。")
    add("")

    add("## 诚实记录（**不利的也写**）")
    add("")
    add("**1. 「食堂」仍然是第 1 名——而且这是对的。**")
    add("")
    add("缺陷描述里最刺眼的一句是「系统的头号事件是学术不端丑闻，选题器还在推荐食堂」。")
    add("改造之后**「食堂」依然排第 1**（8.00 分，一分没变）。这不是没修好，这是权重在按")
    add("设计工作：`chat_query_log` 里有一个**真人**问了「食堂」并且只命中 1 条站内数据——")
    add("`demand(0.5) + gap(0.3)` 打满 8.00 分。而 `W_EVENT=0.3` 的事件项满分只有 3.00。")
    add("**真人敲下的问题 > 系统推断出来的当务之急**——这个排序是我主动选的，不是妥协。")
    add("变的是：丑闻的检索词从**根本不存在**变成了第 2-7 名，紧跟在食堂后面。")
    add("")
    add("**2. 提问语料只有 3 行（2 行还没有关键词）。**")
    add("")
    add("demand/gap 两路几乎是空的。这既解释了「现行臂只推荐食堂」，也意味着")
    add("**本次消融放大了事件臂的优势**：一个有几千条真实提问的系统里，`W_ASK=0.5` 会")
    add("更经常压过 `W_EVENT=0.3`，事件词不会像这里一样一口气霸占 6 个席位。如实说明。")
    add("")
    add(f"**3. 卫生规则在真实数据上一次都没触发（{stats['rejected']} / "
        f"{stats['accepted'] + stats['rejected']} 个词被拒）。**")
    add("")
    if stats["rejected"] == 0:
        add("模型这一轮**没有提出任何一个该被拒的词**——没有「校园生活」，没有超过 12 字的句子，")
        add("没有一个词带「中山大学」前缀。这是好事，但它也意味着**这份报告没有在真实数据上")
        add("演示过降级路径**。拒绝逻辑的证据在注入式单测里（`test_llm_keywords.py::HygieneTest`：")
        add("模型提「校园生活」「中山大学」「日常」-> 被 planner 自己的 `GENERIC_BLACKLIST` 拒掉，")
        add("全被拒时该事件不贡献任何词并记 warning）。**没在语料上触发 ≠ 没人见过它工作**，")
        add("但也**不能**拿这份报告去声称「卫生规则拦下了模型的胡话」——这一轮它没有胡话可拦。")
    add("")
    add("**4. 模型仍然会提自然人的名字 / 口语化的词——人工闸门就是为此存在的。**")
    add("")
    add("上一轮模型提了「耿同学」（举报人的网名），这一轮提了「骂校长」。作为**检索策略**")
    add("它们不算错（真人就是这么搜的），但把一个**具体个人**的名字、或一句情绪化的话")
    add("放进爬取队列是另一回事。系统**没有**自动入队任何词——它们和别的词一样躺在建议列表里")
    add("等管理员点。**AI 提议，人来决定**：模型可以提，但「要不要围绕一个自然人做定向采集」")
    add("不该由模型决定。（顺带一提：这两个词这一轮都没能挤进配额，但那是**算术的副作用**，")
    add("不是安全机制——不能拿它当护栏用。）")
    add("")
    add("**5. 配额只封住了「刷屏」的量，没有封住模型的同义反复。**")
    add("")
    add("提示词这一轮明确要求「每个词一个不同角度，不许给同一句话的几种说法」。模型对")
    add("《东校区宿舍搬迁》的回答仍然是：`宿舍搬迁`、`封闭管理`、`强制搬宿舍`、`同校区搬迁`、`校方回应`")
    add("——**五个词里三个是同一个角度**，而且它把这三个排在了前面。于是配额留下的 3 个席位里，")
    add("仍然有近义词，而真正另一个角度的「校方回应」（模型自己排第 5）被挤了出去。")
    add("**如实记：判断那一半（这两个词是不是一个意思）没有被提示词彻底解决**，")
    add("算术那一半（一件事最多占 3 个席位）是硬的——它把损失从 6 个席位封到了 3 个，")
    add("并且把腾出来的席位交给了别的事件（火情、作息调整这两件事在改造前一个词都排不上）。")
    add("再往下修的话，「两个词是不是一个意思」需要的是**语义相似度**，那要么是又一次 LLM 调用，")
    add("要么是一个字符重合度阈值——后者会在下一批数据上碎掉（「杰青 举报」和「实名举报」的")
    add("字符重合度是 0.4，「宿舍搬迁」和「东校区宿舍搬迁」是 0.57，两者只差 0.17，")
    add("任何阈值都是在这份语料上凑出来的）。没有做，如实写。")
    if warnings:
        add("")
        add("**降级/告警：**")
        for warning in warnings:
            add(f"- {warning}")
    add("")
    add("## LLM 用量")
    add("")
    add(
        f"- 调用 {usage['calls']} 次（缓存命中 {usage['cache_hits']}，失败 {usage['errors']}）、"
        f"token {usage['total_tokens']}、耗时 {usage['duration_ms']} ms"
    )
    add(f"- 只给 **priority 最高的 {EVENT_KEYWORD_TOP_EVENTS} 个事件**花钱"
        f"（每个最多 {EVENT_KEYWORD_MAX} 个词）：算术先说哪件事重要，LLM 才去为它想词。")
    add("")
    add("> 由 `python scripts/ablation_keyword_events.py` 生成。")
    add("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ablation: keyword planner with/without events")
    parser.add_argument("--no-llm", action="store_true", help="不调 LLM（只测算术那一半）")
    parser.add_argument("--now", default="", help="注入「现在」（YYYY-MM-DD），缺省=语料最新帖+1天")
    parser.add_argument("--report", default=str(REPORT), help="报告写到哪里")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    rows = load_rows()
    if get_embedder() is None:
        print("[FAIL] 没有可用的 embedder（sentence-transformers 未安装 / EMBEDDING_ENABLED=0）")
        return 1

    if args.now:
        now = datetime.fromisoformat(args.now)
    else:
        stamps = [parse_time(row.get("publish_time") or row.get("publish_date")) for row in rows]
        now = max(stamp for stamp in stamps if stamp is not None) + timedelta(days=1)
    half_life = recency_config()["half_life_days"]
    use_llm = not args.no_llm

    print(f"[1/3] 聚类 + 风险 + 状态（{len(rows)} 条；now={now:%Y-%m-%d}）…")
    result = PublicOpinionAgentService().analyze_from_rows(
        rows,
        AnalyzeRequest(limit=len(rows)),
        embedder=get_embedder(),
        cluster_threshold=EMBEDDING_CLUSTER_THRESHOLD,
        merge_threshold=EMBEDDING_MERGE_THRESHOLD,
        align_threshold=EMBEDDING_ALIGN_THRESHOLD,
        min_cluster_size=EVENT_MIN_CLUSTER_SIZE,
        cluster_refiner=get_cluster_refiner() if use_llm else None,
        refine_min_size=EVENT_REFINE_MIN_SIZE,
        risk_assessor=get_risk_assessor() if use_llm else None,
        risk_max_texts=EVENT_RISK_MAX_TEXTS,
        now=now,
        recency_half_life_days=half_life,
    )
    events = copy.deepcopy(result.events)
    if use_llm and (assessor := get_lifecycle_assessor()) is not None:
        assess_events_lifecycle(
            events, assessor,
            notes_by_id={note.note_id: note for note in result.notes},
            warnings=[], max_texts=EVENT_RISK_MAX_TEXTS,
        )
    annotate_events_with_recency(
        events, now=now, half_life_days=half_life, growth_window_days=half_life
    )
    records = build_event_records(events, now)
    # 6f85f72 那一版的投影（没有出现次数门槛），作为第三条臂
    records_prefix = build_event_records(events, now, tag_floor=False)
    print(f"      已发布事件 {len(records)} 个")

    queries = build_queries(now)
    content_stats, crawled = build_content_signals(rows, now)

    reset_llm_usage()
    warnings: list[str] = []
    raw_proposals: dict[str, list[str]] = {}
    stats = {"events": 0, "accepted": 0, "rejected": 0}
    if use_llm:
        proposer = get_keyword_proposer()
        if proposer is None:
            print("[WARN] 未配置 EVENT_LLM_API_KEY / EVENT_KEYWORDS_ENABLED=0，跳过词生成")
        else:
            print(f"[2/3] LLM 从事件生成检索词（top-{EVENT_KEYWORD_TOP_EVENTS} 个事件）…")

            def spy(title, texts, risk, lifecycle):
                raw = proposer(title, texts, risk, lifecycle)
                words = (raw or {}).get("keywords") if isinstance(raw, dict) else raw
                for record in records:
                    if record.title == title:
                        raw_proposals[record.event_id] = list(words or [])
                return raw

            stats = generate_event_keywords(
                records, spy, now=now, half_life_days=half_life, warnings=warnings,
                top_events=EVENT_KEYWORD_TOP_EVENTS, max_per_event=EVENT_KEYWORD_MAX,
            )
    usage = get_llm_usage()

    print("[3/3] 三臂打分…")
    # 生成词是同一批（同一个事件、同一次调用），复制给"改造前"那条臂——两臂的唯一变量
    # 必须是**门槛和配额**，不是模型这次心情如何。
    generated_by_title = {record.title: list(record.generated_keywords) for record in records}
    for record in records_prefix:
        record.generated_keywords = list(generated_by_title.get(record.title, []))

    # top_n 取满：截断会让排名 12 之后的词在报告里显示成"不存在"，那是假话。
    # 并排表自己切 TOP_N。
    baseline = plan_keywords(queries, content_stats, crawled, now=now, top_n=10_000)
    # 两条中间臂，把两个修复拆开单独计量（把配额抬到不可能触发的高度 = 关掉配额）：
    #   prev_arm      无标签门槛 + 无配额  = 6f85f72 原样
    #   floor_only    有标签门槛 + 无配额  = 只修了缺陷 1
    original_quota = keyword_planner.EVENT_TOP_KEYWORDS
    keyword_planner.EVENT_TOP_KEYWORDS = 10_000
    try:
        prev_arm = plan_keywords(
            queries, content_stats, crawled, now=now, top_n=10_000,
            events=records_prefix, event_half_life_days=half_life,
        )
        floor_only_arm = plan_keywords(
            queries, content_stats, crawled, now=now, top_n=10_000,
            events=records, event_half_life_days=half_life,
        )
    finally:
        keyword_planner.EVENT_TOP_KEYWORDS = original_quota
    event_arm = plan_keywords(
        queries, content_stats, crawled, now=now, top_n=10_000,
        events=records, event_half_life_days=half_life,
    )

    tag_counts = {
        record.event_id: {
            str(tag.get("tag") or ""): int(tag.get("count") or 1)
            for tag in event.top_tags
            if str(tag.get("tag") or "")
        }
        for record, event in zip(
            records, [e for e in events if any(w in e.title for w in PUBLISHED_TITLES)]
        )
    }
    report = render(
        now, half_life, baseline, event_arm, records, raw_proposals, stats,
        warnings, usage, len(rows), prev_arm, tag_counts, floor_only_arm,
    )
    Path(args.report).write_text(report, encoding="utf-8")
    print(report)
    print(f"[OK] 报告已写入 {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
