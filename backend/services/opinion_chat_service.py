"""DB-backed conversational public opinion agent.

子项目 OpinionAgent.chat() 的数据库版：数据源从本地文件换成 processed_posts，
schema 换成可移植核心。分发逻辑保持一致——LLM 意图路由（规则兜底）、
5 个单步意图、complex_analysis 进 ReAct 多步工具循环、report 意图带 Critic 审校。
只读，不写任何表。
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from typing import Any

from sqlalchemy.orm import Session

from backend.agent.public_opinion_core.clustering import cluster_notes, note_rank_key
from backend.agent.public_opinion_core.schemas import OpinionEvent, OpinionNote
from backend.agent.public_opinion_core.scoring import score_notes
from backend.agent.public_opinion_core.sentiment_risk import analyze_notes_sentiment_and_risk
from backend.services.citations import CITATION_HINT, attach_citation_ids, validate_citations
from backend.services.critic import ReviewResult, review_report
from backend.services.event_read_model import query_published_events
from backend.services.intent_router import is_follow_up, route_intent
from backend.services.llm_client import LlmCallResult, generate_llm_report, stream_llm_report
from backend.services.opinion_report import build_event_digest, compact_events_for_llm
from backend.services.public_opinion_adapter import processed_posts_to_notes, query_agent_rows
from backend.services.react_loop import ReactResult, ReactStep, ReactTool, iter_react, run_react


CHAT_NOTE_LIMIT = 200

# 事件层一次最多带回几个事件。和 compact_events_for_llm 的 events[:8] 对齐——
# 再多也进不了 prompt，白查。
EVENT_TIER_LIMIT = 8

# 三个"取一批事件、让模型直接作答"的意图，只在 (取哪些事件 / 标题 / 指令) 上不同。
# 抽成一张表，让阻塞版 chat() 和流式版 chat_stream() 共用——两套实现各写一遍，
# 迟早会漂移成"同一个问题走聊天和走流式得到不同答案"。
_ANSWER_INTENTS: dict[str, dict[str, str]] = {
    "risk_analysis": {
        "title": "校园风险预警",
        "instruction": (
            "围绕用户实际问的那个问题直接回答，把风险结论自然融进去：是否有风险、什么等级、"
            "最主要的依据、可以怎么应对。不要采用 Q:/A: 式的自问自答，不要替用户编造他没问的问题，"
            "不要写成完整简报。涉及多个风险事件时，先用一张 Markdown 表格汇总"
            "（事件、风险等级、热度、主要依据）再展开。标题最多使用三级标题。"
        ),
    },
    "opinion_answer": {
        "title": "校园观点问答",
        "instruction": (
            "用自然的对话口吻直接回答，答其所问——先用两三句话正面回应用户问的那个问题，"
            "再补充必要的依据（大家怎么看、情绪、值得注意的点，只挑与问题相关的说）。"
            "用户陈述自身处境、表达感受或征求建议时，先回应他的处境本身，"
            "再基于数据给出背景和可行的建议，不要反过来先做风险评估。"
            "像一位手里有数据的同事在聊天：可以用少量要点，但不要套热点/风险/建议的固定栏目，"
            "不要写成简报或工作汇报。标题最多使用三级标题，简短问题直接用段落回答即可。"
        ),
    },
    "hotspots": {
        "title": "校园热点分析",
        "instruction": (
            "请直接回答用户的热点问题，列出最重要的热点事件、热度和原因。"
            "涉及多个事件时，先用一张 Markdown 表格汇总（事件、热度、风险、情绪），"
            "再分点说明最重要的两三个事件为什么值得关注。"
            "不要写成完整简报，标题最多使用三级标题。"
        ),
    },
}

REPORT_INSTRUCTION = (
    "请生成正式的中文舆情简报，结构包含：热点概括、主要观点、情绪倾向、风险等级、"
    "风险依据、建议关注点。热点概括涉及多个事件时，可用一张 Markdown 表格汇总对比。"
    "语言偏报告体，标题最多使用三级标题。"
)

_RISK_RANK = {"high": 3, "medium": 2, "low": 1}


def _link_event_citations(cite_map: dict[str, dict[str, Any]], events: list[OpinionEvent]) -> None:
    """给 eN 引用补上可跳转的事件 id（工作台 ?event_id=）。

    citations.attach_citation_ids 吃的是喂给 LLM 的压缩 payload，里面刻意不放
    数据库 id（对模型是噪声）；跳转信息在这里、也只在这里回填。编号顺序与
    compact_events_for_llm 一致（events[:8] 原序），所以 zip 对得上。
    规则聚类的兜底事件没有落库 id —— 不回填，前端保持不可点：宁可不可点，不可点错。
    """

    for index, event in enumerate(events[:8], start=1):
        entry = cite_map.get(f"e{index}")
        event_id = (event.extra or {}).get("event_id")
        if entry is not None and event_id is not None:
            entry["event_id"] = event_id


def _prepare_citations(events: list[OpinionEvent]) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    """事件集 → (编号后的 LLM payload, 带跳转信息的引用映射)。

    简报和问答意图共用：两处各写一遍迟早漂移成"简报的角标能点、问答的不能"。
    """

    tagged_events, cite_map = attach_citation_ids(compact_events_for_llm(events))
    _link_event_citations(cite_map, events)
    return tagged_events, cite_map


def _cited_event_subset(
    answer: str, tagged_events: list[dict[str, Any]], events: list[OpinionEvent]
) -> list[OpinionEvent]:
    """回答实际引用到的事件——「关联事件」弹哪些由它决定。

    实测截图（2026-07-15）：问「宿舍搬迁简报」弹出康某论文调查、耿同学举报副院长——
    此前 payload 里有什么卡片就弹什么，与回答讲了什么无关。

    「这个回答用了哪些事件」是模型的判断，它已经通过引用标注表达出来了；这里只做
    算术提取：[来源:eN] 直接命中该事件，[来源:pN] 命中该代表帖所属的事件。
    回答一个引用都没标（降级摘要、闲聊式回答）→ 无从判断，维持话题过滤后的原样，
    绝不瞎猜着清空。
    """

    cited = set(validate_citations(answer, {})["cited"])
    if not cited:
        return list(events[: len(tagged_events)])
    subset = [
        event
        for tagged, event in zip(tagged_events, events)
        if not cited.isdisjoint(
            {tagged.get("cite_id")}
            | {note.get("cite_id") for note in tagged.get("representative_notes", [])}
        )
    ]
    return subset or list(events[: len(tagged_events)])

# 审校结论只随响应的 review 字段返回，**不追加进正文**。曾经两头都写：后端把提示
# 拼在正文末尾（流式还作为 delta 推送），前端又用 review 字段画警告卡——同一份审校
# 在气泡里出现两遍（实测截图）。正文是简报本身，审校是关于简报的元数据，
# 展示位只能有一个：前端的警告卡。

# 进程内会话记忆：user_id -> 上一轮话题关键词 / 最近对话历史。单进程限制：
# 多 worker 部署或重启后丢失，丢失的后果只是追问需要重新带上话题词，可接受。
_last_keyword_by_user: dict[str, str] = {}
_last_intent_by_user: dict[str, str] = {}
_history_by_user: dict[str, deque] = {}

# 最近 5 轮对话（10 条记录）进 prompt；助手回答截断存储，控 token。
# 曾经是 3 轮——用户的真实对话七八轮起步，聊到后半段，开头交代的话题背景已经
# 滑出窗口，"混乱感"的来源之一。5 轮的代价是每次多几百 token，值。
HISTORY_MAX_ENTRIES = 10
HISTORY_ANSWER_MAX_CHARS = 200


def reset_chat_memory() -> None:
    _last_keyword_by_user.clear()
    _last_intent_by_user.clear()
    _history_by_user.clear()


def _clear_user_memory(user_id: str) -> None:
    _last_keyword_by_user.pop(user_id, None)
    _last_intent_by_user.pop(user_id, None)
    _history_by_user.pop(user_id, None)


def _history_block(user_id: str) -> str:
    entries = _history_by_user.get(user_id)
    if not entries:
        return ""
    lines = [("用户" if role == "user" else "助手") + "：" + text for role, text in entries]
    return "（最近对话回顾，仅用于理解本轮问题中的指代：\n" + "\n".join(lines) + "）\n"


def _last_user_question(user_id: str) -> str:
    """上一轮用户问了什么——路由判断 continue/switch 需要它（光有话题词不够：
    「新宿舍条件更差」延续的是「搬迁」这件事，词面上毫无交集）。"""

    entries = _history_by_user.get(user_id)
    if not entries:
        return ""
    for role, text in reversed(entries):
        if role == "user":
            return text
    return ""


def _resolve_topic_keyword(routed: Any, message: str, last_keyword: str) -> tuple[str, str]:
    """话题状态机：返回（本轮检索话题词, 归一化后的 topic）。

    「这句话还在不在聊刚才那件事」是判断题——路由 LLM 给出 topic 判断就服从它：

        continue → 沿用上一轮话题（即使句子里没有指代词、即使冒出了新名词）
        switch   → 用路由提取的新话题词
        global   → 空话题词，检索全部

    路由没给 topic（老缓存 / LLM 降级 / 测试桩）时按 is_follow_up 规则近似——
    这是判断能力缺席时的算术兜底，不是首选路径。
    """

    topic = routed.topic or (
        "switch" if routed.keyword else ("continue" if is_follow_up(message) else "global")
    )
    if topic == "continue":
        return (last_keyword or routed.keyword, topic)
    if topic == "switch":
        return (routed.keyword, topic)
    return ("", topic)


def _record_turn(user_id: str, message: str, answer: str, intent: str = "") -> None:
    if not user_id:
        return
    if intent:
        _last_intent_by_user[user_id] = intent
    history = _history_by_user.setdefault(user_id, deque(maxlen=HISTORY_MAX_ENTRIES))
    history.append(("user", message))
    if len(answer) > HISTORY_ANSWER_MAX_CHARS:
        answer = answer[:HISTORY_ANSWER_MAX_CHARS] + "…"
    history.append(("assistant", answer))


class OpinionChatService:
    """One instance per request; notes are cached per keyword within the request."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._notes_cache: dict[str, list[OpinionNote]] = {}

    # ------------------------------------------------------------------ data

    def _notes(self, keyword: str = "") -> list[OpinionNote]:
        if keyword not in self._notes_cache:
            rows = query_agent_rows(self.db, keyword=keyword, platforms=None, limit=CHAT_NOTE_LIMIT)
            notes = processed_posts_to_notes(rows, warnings=[])
            # 对话工具用规则情绪（快）；LLM 级情绪在分析端点里做。
            self._notes_cache[keyword] = analyze_notes_sentiment_and_risk(score_notes(notes))
        return self._notes_cache[keyword]

    def _published_events(self, keyword: str = "", limit: int = EVENT_TIER_LIMIT) -> list[OpinionEvent]:
        """事件层（已发布的 LLM 研判事件），查库故障时返回空。

        单独抽出来是因为它有两个消费方，且降级语义必须一致：
          - ``_events``：事件层空了回落帖子层；
          - search 兜底：事件层命中就升级为真正的回答，空了才退回帖子清单。
        """

        try:
            return query_published_events(self.db, keyword=keyword, limit=limit)
        except Exception:
            return []  # 事件层故障 -> 降级，别让整个对话跟着挂

    def _events(self, keyword: str = "", limit: int = EVENT_TIER_LIMIT) -> list[OpinionEvent]:
        """两层检索：已发布的 LLM 事件优先，命中不了才回落到帖子层。

        ## 层① 事件层

        `public_events` 里放的是走完整条 AI 链路的产物：embedding 语义聚类 → LLM 簇精修
        → LLM 风险研判 → LLM 生命周期研判。改造前聊天**从来不读这张表**，每次提问都从
        `processed_posts` 现场用规则重新聚一遍（4 个写死的桶），于是所有 AI 研判在聊天
        窗口里一样都看不见——事件页说「东校区宿舍搬迁 medium 风险」，聊天却说"没检索到"。

        事件层还顺手解决了字面检索的死穴：同一件事有「宿舍搬迁」「搬宿舍」「封闭管理」
        三种说法，`LIKE '%宿舍搬迁%'` 只认第一种；而 embedding 离线时已经把它们聚成一个
        事件，命中任意一条代表帖就能**上浮**到整簇（见 query_published_events）。

        ## 层② 帖子层（兜底，绝不能少）

        published 事件只有 7 个、只覆盖 26/397 条帖子。问「食堂」时没有对应的已发布事件，
        若只读事件层就会直接查无此事——而改造前它能查到 32 条真实食堂帖。**那不是改进，
        是退化。** 所以一个事件都不命中时，照旧走 `processed_posts` + 规则聚类。

        事件层查库出任何问题也走兜底：聊天可用性优先于 AI 深度。
        """

        events = self._published_events(keyword, limit=limit)
        if events:
            return events
        return cluster_notes(self._notes(keyword))

    def _risk_sorted_events(self, keyword: str = "") -> list[OpinionEvent]:
        # 截断必须发生在**风险排序之后**。_events 默认按展示优先级截 8——一个年头久
        # 但 high 的事件（时效权重 0.5^(age/21) 趋零）会先被截掉，low 的新事件反而在列
        # （实测：「最近有什么风险」的名单里有火箭试验成功，没有刘一阳去世）。
        # published 事件量级很小（几十个），全量取回再让调用方按风险截断，代价可忽略。
        events = self._events(keyword, limit=0)
        return sorted(
            events,
            # 同风险时按 ranking_score（平台先验权重 × 平台内百分位）排；
            # 未归一化的老数据 ranking_score 为 0，依次回退 heat_rank -> heat_score。
            key=lambda event: (
                _RISK_RANK.get(event.risk_level, 0),
                event.risk_score,
                event.ranking_score,
                event.heat_rank,
                event.heat_score,
            ),
            reverse=True,
        )

    def _search_ranked_notes(self, keyword: str = "", limit: int = 10) -> list[OpinionNote]:
        """检索场景挑 top-N（chat 用 10 条、ReAct 的 search_notes 用 5 条）。

        排序（选择）用 `note_rank_key` = ranking_score -> heat_rank -> heat_score；返回的帖子
        本身仍带真实 heat_score（展示）。按 heat_score 排会把 weibo/zhihu/web 整体排到
        xhs/ks 后面；按裸 heat_rank 排又会让一条 3 赞的微博帖和一条 10 万赞的小红书帖平起
        平坐。ranking_score 两头都占。
        """

        return sorted(self._notes(keyword), key=note_rank_key, reverse=True)[: max(limit, 0)]

    # ------------------------------------------------------------------ chat

    def chat(self, message: str, user_id: str = "", reset: bool = False) -> dict[str, Any]:
        if reset and user_id:
            _clear_user_memory(user_id)
        last_keyword = _last_keyword_by_user.get(user_id, "")
        # 路由用原句（历史会干扰关键词提取）；答案生成用带历史的版本。
        # last_intent/last_question 供路由判断"这轮是不是还在聊同一件事"。
        routed = route_intent(
            message,
            last_keyword=last_keyword,
            last_intent=_last_intent_by_user.get(user_id, ""),
            last_question=_last_user_question(user_id),
        )
        history = _history_block(user_id)
        contextual = f"{history}本轮问题：{message}" if history else message

        if routed.intent == "complex_analysis":
            # 多话题问题没有单一话题可继承，不更新话题词记忆。
            response = self._chat_complex(contextual, routed)
            _record_turn(user_id, message, response["answer"], "complex_analysis")
            return response

        keyword, topic = _resolve_topic_keyword(routed, message, last_keyword)
        # 只有 switch 才改写话题记忆：continue 时句子里冒出的新名词（"新宿舍"）
        # 不是换话题，不许顺手把记忆改了——下一轮的 continue 还要靠它。
        if topic == "switch" and routed.keyword and user_id:
            _last_keyword_by_user[user_id] = routed.keyword
        if keyword:
            # 话题锚：生成也要围绕当前话题组织，别被泛化数据带跑。
            contextual = f"（当前对话话题：{keyword}）\n{contextual}"

        if routed.intent == "report":
            response = self._chat_report(contextual, keyword, routed)
            _record_turn(user_id, message, response["answer"], "report")
            return response

        # 三个单步问答意图共用 _ANSWER_INTENTS（唯一事实来源）。曾经这里各自内联一份
        # 一模一样的指令文案——和流式版迟早漂移成"同一个问题两种答案"，且缓存键分裂。
        # 问答也挂引用编号（软要求，不逐句强制、不跑审校）：用户可点角标溯源，
        # 弹出的关联事件跟着回答实际引用到的走。
        if routed.intent in _ANSWER_INTENTS:
            spec = _ANSWER_INTENTS[routed.intent]
            events = (
                self._risk_sorted_events(keyword)
                if routed.intent == "risk_analysis"
                else self._events(keyword)
            )[:8]
            tagged_events, cite_map = _prepare_citations(events)
            answer = generate_llm_report(
                user_task=contextual,
                analysis_payload={"events": tagged_events},
                fallback_text=build_event_digest(events, title=spec["title"]),
                output_instruction=spec["instruction"] + CITATION_HINT,
            )
            _record_turn(user_id, message, answer, routed.intent)
            response = self._response(
                routed.intent, keyword, answer, routed, _cited_event_subset(answer, tagged_events, events)
            )
            response["citations"] = cite_map
            return response

        # search 兜底。路由没认出意图 ≠ 库里没有这件事：「刘一阳的事怎么样了」这类
        # 问法（X怎么样了/X的事）不落在任何单步意图里，曾在这里只得到一句
        # 「已找到 5 条相关校园公开内容」——而「刘一阳去世」是 published 的 high 风险
        # 事件。事件层（字面→语义→裁决的完整三层）命中时升级为观点问答；
        # 只有事件层也一无所获，才退回帖子清单（那条路保持零 LLM 调用）。
        events = self._published_events(keyword)[:8] if keyword else []
        if events:
            spec = _ANSWER_INTENTS["opinion_answer"]
            tagged_events, cite_map = _prepare_citations(events)
            answer = generate_llm_report(
                user_task=contextual,
                analysis_payload={"events": tagged_events},
                fallback_text=build_event_digest(events, title=spec["title"]),
                output_instruction=spec["instruction"] + CITATION_HINT,
            )
            _record_turn(user_id, message, answer, "search")
            response = self._response(
                "search", keyword, answer, routed, _cited_event_subset(answer, tagged_events, events)
            )
            response["citations"] = cite_map
            return response
        notes = self._search_ranked_notes(keyword or message, limit=10)
        answer = f"已找到 {len(notes)} 条相关校园公开内容。你可以进一步询问热点、风险或生成简报。"
        _record_turn(user_id, message, answer, "search")
        response = self._response("search", keyword or message, answer, routed, [])
        response["notes"] = [
            {"title": note.title, "sentiment": note.sentiment, "heat_score": note.heat_score, "url": note.url}
            for note in notes
        ]
        return response

    # ------------------------------------------------------------ chat_stream

    def chat_stream(
        self, message: str, user_id: str = "", reset: bool = False
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        """与 chat() 同样的分发逻辑，但把过程实时吐出来。

        产出 (事件名, 载荷)：
            meta  路由结果——一出来就发，用户立刻知道"这是一份简报"而不是干等
            step  ReAct 每走完一步（"正在检索宿舍…"）
            delta 正文增量
            done  事件列表 / 引用 / 审校结论 / 是否降级

        实测：简报意图原本要 43 秒才出现第一个字（路由 4.2s + 生成 19.4s + 审校 19.4s），
        流式后 2.7 秒开始出字，且审校挪到正文之后——用户读简报的时间就把它跑完了。
        """

        if reset and user_id:
            _clear_user_memory(user_id)
        last_keyword = _last_keyword_by_user.get(user_id, "")
        routed = route_intent(
            message,
            last_keyword=last_keyword,
            last_intent=_last_intent_by_user.get(user_id, ""),
            last_question=_last_user_question(user_id),
        )
        history = _history_block(user_id)
        contextual = f"{history}本轮问题：{message}" if history else message

        if routed.intent == "complex_analysis":
            yield ("meta", {"intent": "complex_analysis", "keyword": "", "route_source": routed.source})
            yield from self._stream_complex(message, contextual, routed, user_id)
            return

        # 话题状态机与阻塞版 chat() 同一语义（见 _resolve_topic_keyword）。
        keyword, topic = _resolve_topic_keyword(routed, message, last_keyword)
        if topic == "switch" and routed.keyword and user_id:
            _last_keyword_by_user[user_id] = routed.keyword
        if keyword:
            contextual = f"（当前对话话题：{keyword}）\n{contextual}"
        yield ("meta", {"intent": routed.intent, "keyword": keyword, "route_source": routed.source})

        if routed.intent == "report":
            yield from self._stream_report(message, contextual, keyword, routed, user_id)
            return

        if routed.intent in _ANSWER_INTENTS:
            yield from self._stream_answer(message, contextual, keyword, routed, user_id)
            return

        # search 兜底：事件层命中时升级为观点问答——与阻塞版 chat() 同一语义，
        # 两套实现漂移 = 同一个问题走聊天和走流式得到不同答案。
        # 事件层一无所获才退回帖子清单，那条路保持零 LLM 调用。
        events = self._published_events(keyword)[:8] if keyword else []
        if events:
            spec = _ANSWER_INTENTS["opinion_answer"]
            tagged_events, cite_map = _prepare_citations(events)
            outcome = LlmCallResult()
            for delta in stream_llm_report(
                user_task=contextual,
                analysis_payload={"events": tagged_events},
                fallback_text=build_event_digest(events, title=spec["title"]),
                output_instruction=spec["instruction"] + CITATION_HINT,
                outcome=outcome,
            ):
                yield ("delta", {"text": delta})
            answer = outcome.content or ""
            _record_turn(user_id, message, answer, "search")
            done = self._response(
                "search", keyword, answer, routed, _cited_event_subset(answer, tagged_events, events)
            )
            done["citations"] = cite_map
            yield ("done", done)
            return
        notes = self._search_ranked_notes(keyword or message, limit=10)
        answer = f"已找到 {len(notes)} 条相关校园公开内容。你可以进一步询问热点、风险或生成简报。"
        yield ("delta", {"text": answer})
        _record_turn(user_id, message, answer, "search")
        done = self._response("search", keyword or message, answer, routed, [])
        done["notes"] = [
            {"title": note.title, "sentiment": note.sentiment, "heat_score": note.heat_score, "url": note.url}
            for note in notes
        ]
        yield ("done", done)

    def _stream_answer(
        self, message: str, contextual: str, keyword: str, routed: Any, user_id: str
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        spec = _ANSWER_INTENTS[routed.intent]
        events = (
            self._risk_sorted_events(keyword) if routed.intent == "risk_analysis" else self._events(keyword)
        )[:8]
        tagged_events, cite_map = _prepare_citations(events)

        outcome = LlmCallResult()
        for delta in stream_llm_report(
            user_task=contextual,
            analysis_payload={"events": tagged_events},
            fallback_text=build_event_digest(events, title=spec["title"]),
            output_instruction=spec["instruction"] + CITATION_HINT,
            outcome=outcome,
        ):
            yield ("delta", {"text": delta})

        answer = outcome.content or ""
        _record_turn(user_id, message, answer, routed.intent)
        done = self._response(
            routed.intent, keyword, answer, routed, _cited_event_subset(answer, tagged_events, events)
        )
        done["citations"] = cite_map
        yield ("done", done)

    def _stream_report(
        self, message: str, contextual: str, keyword: str, routed: Any, user_id: str
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        events = self._events(keyword)
        tagged_events, cite_map = _prepare_citations(events)
        payload = {"keyword": keyword, "events": tagged_events}
        fallback = build_event_digest(events, title=f"校园舆情简报：{keyword or '全部数据'}")

        outcome = LlmCallResult()
        for delta in stream_llm_report(
            user_task=f"{contextual}\n任务：生成校园公共舆情简报，关键词：{keyword or '全部'}",
            analysis_payload=payload,
            fallback_text=fallback,
            output_instruction=REPORT_INSTRUCTION,
            require_citations=bool(cite_map),
            outcome=outcome,
        ):
            yield ("delta", {"text": delta})

        report_text = outcome.content or ""

        # —— 正文已经全部送达用户，现在才跑 critic ——
        # 它是第二次完整 LLM 调用（实测 19.4 秒）。堵在正文前面 = 用户白等 19 秒；
        # 放在这里 = 用户读简报的功夫它就跑完了，感知成本约等于零。
        # 降级时（report_text 是规则版摘要）跳过审校：天然无引用，且审校 LLM 大概率同样不可用。
        verdict = ReviewResult()
        if not report_text.startswith(fallback):
            verdict = review_report(report_text, payload, citations=cite_map or None)

        _record_turn(user_id, message, report_text, "report")
        done = self._response(
            "report", keyword, report_text, routed, _cited_event_subset(report_text, tagged_events, events)
        )
        done["review"] = {"verdict": verdict.verdict, "issues": verdict.issues}
        done["citations"] = cite_map
        yield ("done", done)

    def _stream_complex(
        self, message: str, contextual: str, routed: Any, user_id: str
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        """ReAct 的中间步骤实时推给前端。

        最终答案是从一个 JSON 对象里取 final_answer 字段的，逐字流出来会是原始 JSON 字符——
        所以正文仍然一次性给。但**每一步工具调用一完成就推**：一次复杂分析约 40 秒，
        用户看见的是"正在检索宿舍 → 正在对比食堂 → 正在综合研判"，而不是一个假进度条。

        用 iter_react（生成器）而不是 run_react + 回调：回调里没法 yield，硬要实时就得把
        工具执行挪到另一个线程——而工具要查库，SQLAlchemy 的 Session 不是线程安全的。
        """

        result = ReactResult(answer="", steps=[], stop_reason="llm_error")
        for item in iter_react(contextual, tools=self._react_tools()):
            if isinstance(item, ReactStep):
                yield ("step", item.to_dict())  # 这一步刚跑完，立刻推
            else:
                result = item

        answer = result.answer.strip()
        degraded = not answer
        if degraded:
            answer = build_event_digest(self._events(), title="校园舆情综合分析（已降级为规则摘要）")
        yield ("delta", {"text": answer})

        _record_turn(user_id, message, answer, "complex_analysis")
        done = self._response("complex_analysis", "", answer, routed, [])
        done["steps"] = [step.to_dict() for step in result.steps]
        done["stop_reason"] = result.stop_reason
        done["degraded"] = degraded
        yield ("done", done)

    # ---------------------------------------------------------------- intents

    def _chat_report(self, message: str, keyword: str, routed: Any) -> dict[str, Any]:
        events = self._events(keyword)
        # 引用强制：代表帖编号 p1..pN，简报论断必须标注 [来源:pN]，映射随响应返回供前端溯源。
        tagged_events, cite_map = _prepare_citations(events)
        payload = {"keyword": keyword, "events": tagged_events}
        fallback = build_event_digest(events, title=f"校园舆情简报：{keyword or '全部数据'}")
        report_text = generate_llm_report(
            user_task=f"{message}\n任务：生成校园公共舆情简报，关键词：{keyword or '全部'}",
            analysis_payload=payload,
            fallback_text=fallback,
            output_instruction=REPORT_INSTRUCTION,  # 与流式版共用，别再内联一份等它漂移
            # 数据集为空时没有可引编号，不强制 LLM 标注引用。
            require_citations=bool(cite_map),
        )
        # LLM 降级时 report_text 是规则版摘要（fallback 前缀），天然无引用且审校 LLM
        # 大概率同样不可用——跳过 critic，避免误报"无引用"和对故障服务的二次重试。
        verdict = ReviewResult()
        if not report_text.startswith(fallback):
            verdict = review_report(report_text, payload, citations=cite_map or None)
        response = self._response(
            "report", keyword, report_text, routed, _cited_event_subset(report_text, tagged_events, events)
        )
        response["review"] = {"verdict": verdict.verdict, "issues": verdict.issues}
        response["citations"] = cite_map
        return response

    def _chat_complex(self, message: str, routed: Any) -> dict[str, Any]:
        result = run_react(message, tools=self._react_tools())
        answer = result.answer.strip()
        degraded = not answer
        if degraded:
            answer = build_event_digest(self._events(), title="校园舆情综合分析（已降级为规则摘要）")
        response = self._response("complex_analysis", "", answer, routed, [])
        response["steps"] = [step.to_dict() for step in result.steps]
        response["stop_reason"] = result.stop_reason
        response["degraded"] = degraded
        return response

    # ----------------------------------------------------------------- tools

    def _react_tools(self) -> dict[str, ReactTool]:
        def run_search(action_input: dict[str, Any]) -> dict[str, Any]:
            keyword = str(action_input.get("keyword") or "")
            notes = self._search_ranked_notes(keyword, limit=5)
            return {
                "keyword": keyword,
                "count": len(notes),
                "notes": [
                    {"title": note.title, "sentiment": note.sentiment, "heat_score": note.heat_score}
                    for note in notes
                ],
            }

        def run_hotspots(action_input: dict[str, Any]) -> dict[str, Any]:
            keyword = str(action_input.get("keyword") or "")
            events = self._events(keyword)[:5]
            return {"keyword": keyword, "count": len(events), "events": compact_events_for_llm(events)}

        def run_risks(action_input: dict[str, Any]) -> dict[str, Any]:
            keyword = str(action_input.get("keyword") or "")
            events = self._risk_sorted_events(keyword)[:5]
            return {"keyword": keyword, "count": len(events), "events": compact_events_for_llm(events)}

        def run_overview(action_input: dict[str, Any]) -> dict[str, Any]:
            notes = self._notes()
            events = self._events()
            sentiments: dict[str, int] = {}
            risks: dict[str, int] = {}
            for note in notes:
                sentiments[note.sentiment] = sentiments.get(note.sentiment, 0) + 1
            for event in events:
                risks[event.risk_level] = risks.get(event.risk_level, 0) + 1
            return {
                "total_notes": len(notes),
                "total_events": len(events),
                "sentiment_distribution": sentiments,
                "risk_distribution": risks,
            }

        return {
            "search_notes": ReactTool(
                name="search_notes",
                description="按关键词检索原始帖子，返回标题、情绪和热度（keyword 为空时返回全部热门帖）",
                run=run_search,
            ),
            "hotspots": ReactTool(
                name="hotspots",
                description="按关键词聚合热点事件，返回事件标题、热度、情绪、风险等级",
                run=run_hotspots,
            ),
            "risks": ReactTool(
                name="risks",
                description="按关键词查询风险事件，按风险等级从高到低排序，含风险依据",
                run=run_risks,
            ),
            "overview": ReactTool(
                name="overview",
                description="全局概览：帖子总数、事件总数、情绪分布、风险分布（不需要 keyword）",
                run=run_overview,
            ),
        }

    # --------------------------------------------------------------- helpers

    def _response(
        self,
        intent: str,
        keyword: str,
        answer: str,
        routed: Any,
        events: list[OpinionEvent],
    ) -> dict[str, Any]:
        return {
            "intent": intent,
            "keyword": keyword,
            "answer": answer,
            "route_source": routed.source,
            "events": [
                {
                    # 落库 id：前端「关联事件」卡片跳工作台（?event_id=）用。
                    # 规则聚类的兜底事件没有 —— None，卡片保持不可点。
                    "id": (event.extra or {}).get("event_id"),
                    "title": event.title,
                    "sentiment": event.sentiment,
                    "risk_level": event.risk_level,
                    "heat_score": event.heat_score,
                    "source_count": event.source_count,
                    "trend": event.trend,
                }
                for event in events
            ],
        }
