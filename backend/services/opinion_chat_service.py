"""DB-backed conversational public opinion agent.

子项目 OpinionAgent.chat() 的数据库版：数据源从本地文件换成 processed_posts，
schema 换成可移植核心。分发逻辑保持一致——LLM 意图路由（规则兜底）、
5 个单步意图、complex_analysis 进 ReAct 多步工具循环、report 意图带 Critic 审校。
只读，不写任何表。
"""

from __future__ import annotations

from collections import deque
from typing import Any

from sqlalchemy.orm import Session

from backend.agent.public_opinion_core.clustering import cluster_notes, note_rank_key
from backend.agent.public_opinion_core.schemas import OpinionEvent, OpinionNote
from backend.agent.public_opinion_core.scoring import score_notes
from backend.agent.public_opinion_core.sentiment_risk import analyze_notes_sentiment_and_risk
from backend.services.citations import attach_citation_ids
from backend.services.critic import ReviewResult, review_report
from backend.services.intent_router import route_intent
from backend.services.llm_client import generate_llm_report
from backend.services.opinion_report import build_event_digest, compact_events_for_llm
from backend.services.public_opinion_adapter import processed_posts_to_notes, query_agent_rows
from backend.services.react_loop import ReactTool, run_react


CHAT_NOTE_LIMIT = 200

_RISK_RANK = {"high": 3, "medium": 2, "low": 1}

# 进程内会话记忆：user_id -> 上一轮话题关键词 / 最近对话历史。单进程限制：
# 多 worker 部署或重启后丢失，丢失的后果只是追问需要重新带上话题词，可接受。
_last_keyword_by_user: dict[str, str] = {}
_last_intent_by_user: dict[str, str] = {}
_history_by_user: dict[str, deque] = {}

# 最近 3 轮对话（6 条记录）进 prompt；助手回答截断存储，控 token。
HISTORY_MAX_ENTRIES = 6
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

    def _events(self, keyword: str = "") -> list[OpinionEvent]:
        return cluster_notes(self._notes(keyword))

    def _risk_sorted_events(self, keyword: str = "") -> list[OpinionEvent]:
        events = self._events(keyword)
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
        # last_intent 让"再展开讲讲"式追问沿用上一轮意图，而不是落进 search 兜底。
        routed = route_intent(
            message,
            last_keyword=last_keyword,
            last_intent=_last_intent_by_user.get(user_id, ""),
        )
        history = _history_block(user_id)
        contextual = f"{history}本轮问题：{message}" if history else message

        if routed.intent == "complex_analysis":
            # 多话题问题没有单一话题可继承，不更新话题词记忆。
            response = self._chat_complex(contextual, routed)
            _record_turn(user_id, message, response["answer"], "complex_analysis")
            return response

        keyword = routed.keyword or last_keyword
        if routed.keyword and user_id:
            _last_keyword_by_user[user_id] = routed.keyword

        if routed.intent == "risk_analysis":
            events = self._risk_sorted_events(keyword)[:8]
            answer = self._llm_answer(
                contextual,
                events,
                fallback_title="校园风险预警",
                instruction=(
                    "请直接回答用户的风险问题，用较短的问答口吻输出。"
                    "重点说明是否有风险、风险等级、最主要的 3 条依据和处理建议。"
                    "不要写成完整简报，标题最多使用三级标题。"
                ),
            )
            _record_turn(user_id, message, answer, "risk_analysis")
            return self._response("risk_analysis", keyword, answer, routed, events)

        if routed.intent == "report":
            response = self._chat_report(contextual, keyword, routed)
            _record_turn(user_id, message, response["answer"], "report")
            return response

        if routed.intent == "opinion_answer":
            events = self._events(keyword)[:8]
            answer = self._llm_answer(
                contextual,
                events,
                fallback_title="校园观点问答",
                instruction=(
                    "请用 Agent 问答口吻回答用户，不要写成舆情简报。"
                    "用 1 段结论加 3 到 5 个要点说明大家主要怎么看、情绪倾向和应关注的问题。"
                    "语气自然、简洁，标题最多使用三级标题。"
                ),
            )
            _record_turn(user_id, message, answer, "opinion_answer")
            return self._response("opinion_answer", keyword, answer, routed, events)

        if routed.intent == "hotspots":
            events = self._events(keyword)[:8]
            answer = self._llm_answer(
                contextual,
                events,
                fallback_title="校园热点分析",
                instruction=(
                    "请直接回答用户的热点问题，列出最重要的热点事件、热度和原因。"
                    "不要写成完整简报，标题最多使用三级标题。"
                ),
            )
            _record_turn(user_id, message, answer, "hotspots")
            return self._response("hotspots", keyword, answer, routed, events)

        # search 兜底
        notes = self._search_ranked_notes(keyword or message, limit=10)
        answer = f"已找到 {len(notes)} 条相关校园公开内容。你可以进一步询问热点、风险或生成简报。"
        _record_turn(user_id, message, answer, "search")
        response = self._response("search", keyword or message, answer, routed, [])
        response["notes"] = [
            {"title": note.title, "sentiment": note.sentiment, "heat_score": note.heat_score, "url": note.url}
            for note in notes
        ]
        return response

    # ---------------------------------------------------------------- intents

    def _chat_report(self, message: str, keyword: str, routed: Any) -> dict[str, Any]:
        events = self._events(keyword)
        # 引用强制：代表帖编号 p1..pN，简报论断必须标注 [来源:pN]，映射随响应返回供前端溯源。
        tagged_events, cite_map = attach_citation_ids(compact_events_for_llm(events))
        payload = {"keyword": keyword, "events": tagged_events}
        fallback = build_event_digest(events, title=f"校园舆情简报：{keyword or '全部数据'}")
        report_text = generate_llm_report(
            user_task=f"{message}\n任务：生成校园公共舆情简报，关键词：{keyword or '全部'}",
            analysis_payload=payload,
            fallback_text=fallback,
            output_instruction=(
                "请生成正式的中文舆情简报，结构包含：热点概括、主要观点、情绪倾向、风险等级、"
                "风险依据、建议关注点。语言偏报告体，标题最多使用三级标题。"
            ),
            # 数据集为空时没有可引编号，不强制 LLM 标注引用。
            require_citations=bool(cite_map),
        )
        # LLM 降级时 report_text 是规则版摘要（fallback 前缀），天然无引用且审校 LLM
        # 大概率同样不可用——跳过 critic，避免误报"无引用"和对故障服务的二次重试。
        verdict = ReviewResult()
        if not report_text.startswith(fallback):
            verdict = review_report(report_text, payload, citations=cite_map or None)
        if verdict.verdict == "warn" and verdict.issues:
            report_text += "\n\n> ⚠️ 审校提示：" + "；".join(verdict.issues)
        response = self._response("report", keyword, report_text, routed, events[:8])
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

    def _llm_answer(
        self,
        message: str,
        events: list[OpinionEvent],
        *,
        fallback_title: str,
        instruction: str,
    ) -> str:
        return generate_llm_report(
            user_task=message,
            analysis_payload={"events": compact_events_for_llm(events)},
            fallback_text=build_event_digest(events, title=fallback_title),
            output_instruction=instruction,
        )

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
