"""Service entrypoint for the portable public opinion Agent core."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
import time
from typing import Any

from .adapter import processed_posts_to_notes
from .clustering import classify_event, cluster_notes, sort_events
from .concurrency import DEFAULT_LLM_CONCURRENCY
from .llm_lifecycle import LifecycleAssessor, assess_events_lifecycle
from .llm_refine import DEFAULT_REFINE_MIN_SIZE, ClusterRefiner
from .llm_risk import DEFAULT_MAX_TEXTS, RiskAssessor, assess_events_risk
from .memory import annotate_events_with_memory, build_snapshot
from .normalizer import analysis_text, clean_text, note_text
from .recency import annotate_events_with_recency, growth_config, recency_config
from .schemas import AgentRunLogPayload, AnalyzeRequest, AnalyzeResult, MemorySnapshot, OpinionNote
from .scoring import score_notes
from .semantic_clustering import cluster_notes_semantic, strip_social_noise
from .sentiment_risk import analyze_notes_sentiment_and_risk
from .visualization import build_visualization_payload


# (list[str]) -> list[list[float]]，由运行环境注入（如 app.services.embedding），核心不依赖模型库。
Embedder = Callable[[list[str]], list[list[float]]]

# (list[str]) -> list[str | None]，None 表示该条保留规则结果（如 app.services.sentiment_llm）。
SentimentClassifier = Callable[[list[str]], list[str | None]]

# ClusterRefiner：(一个簇的帖子文本) -> 话题列表，同样由运行环境注入
# （如 app.services.event_refiner）。None = 跳过精修、保留 embedding 的簇。
# 协议、验证口径和失败降级见 llm_refine.py。

# RiskAssessor：(事件标题, 成员帖文本) -> 风险研判，由运行环境注入（如 app.services.event_risk）。
# None = 跳过研判、保留规则风险（六个电诈词 + 互动量加分）。见 llm_risk.py 的缺陷说明。

VALID_SENTIMENT_LABELS = {"positive", "negative", "neutral", "controversial"}


class PublicOpinionAgentService:
    """Analyze processed_posts-like rows without knowing their data source."""

    def analyze_from_rows(
        self,
        rows: Iterable[Mapping[str, Any] | Any],
        request: AnalyzeRequest | None = None,
        previous_snapshot: MemorySnapshot | None = None,
        embedder: Embedder | None = None,
        cluster_threshold: float | None = None,
        merge_threshold: float | None = None,
        align_threshold: float | None = None,
        # 一个事件的成员时间跨度上限（天）。embedding 只问"像不像"，不问"是不是同一时候
        # 发生的"——一条 2021 年的疫情封校帖曾被聚进 2026 年的宿舍搬迁事件（跨度 1782 天），
        # 一条就贡献了该事件 90% 的热度。None = 用核心默认值。
        max_span_days: float | None = None,
        sentiment_classifier: SentimentClassifier | None = None,
        min_cluster_size: int | None = None,
        cluster_refiner: ClusterRefiner | None = None,
        refine_min_size: int | None = None,
        # 近重簇合并裁决（llm_merge）：None = 只拆不合的老行为。
        merge_judge: Any | None = None,
        risk_assessor: RiskAssessor | None = None,
        risk_max_texts: int | None = None,
        lifecycle_assessor: LifecycleAssessor | None = None,
        # 事件级 LLM 调用（精修 / 风险 / 状态）的并发度。这三处都是 per-event / per-cluster
        # 的独立调用，串行跑就是 90+ 次 × 5s ≈ 7~8 分钟。并发只改**跑得多快**，不改**跑出什么**
        # （结果按输入顺序回填，逐位一致 —— 见 concurrency.py）。None = 默认 8，1 = 退回串行。
        llm_concurrency: int | None = None,
        now: datetime | None = None,
        recency_half_life_days: float | None = None,
        growth_window_days: float | None = None,
    ) -> AnalyzeResult:
        request = request or AnalyzeRequest()
        started_perf = time.perf_counter()
        started_at = _utc_now_text()
        # 时效性的"现在"：**在流水线入口取一次**，往下一路传参。纯函数里绝不允许出现
        # datetime.now()——否则同一批输入在不同时刻跑出不同事件顺序，单测不可重复、
        # 消融不可复现。调用方（API / 脚本 / 消融）可以显式注入任意 now。
        now = now or datetime.now(UTC)

        warnings: list[str] = []
        row_list = list(rows or [])
        notes = processed_posts_to_notes(row_list, warnings=warnings)
        adapted_count = len(notes)

        notes = self._filter_notes(notes, request)
        if request.limit:
            notes = notes[: request.limit]
        matched_count = len(notes)

        if not row_list:
            warnings.append("no input rows")
        elif matched_count == 0:
            warnings.append("no notes matched request filters")

        # 单帖不成事件：min_cluster_size 以下的簇直接不产出事件（见 clustering/semantic_clustering）。
        minimum = max(int(min_cluster_size), 1) if min_cluster_size is not None else 1

        events = []
        centroids: dict[str, list[float]] = {}
        clustering_mode = "rules"
        sentiment_mode = "rules"
        sentiment_overridden = 0
        suppressed_clusters = 0
        refined_clusters = 0
        ejected_notes = 0
        if notes:
            notes = score_notes(notes)
            notes = analyze_notes_sentiment_and_risk(notes)
            llm_sentiment = self._try_llm_sentiment(notes, sentiment_classifier, warnings)
            if llm_sentiment is not None:
                sentiment_mode, sentiment_overridden = "llm", llm_sentiment
            semantic = self._try_semantic_clustering(
                notes,
                embedder,
                previous_snapshot,
                cluster_threshold,
                merge_threshold,
                align_threshold,
                max_span_days,
                minimum,
                warnings,
                cluster_refiner,
                refine_min_size,
                llm_concurrency,
                merge_judge,
            )
            if semantic is not None:
                events, centroids, suppressed_clusters, refined_clusters, ejected_notes = semantic
                # LLM 一个簇都没精修成（超时/幻觉/全部作废）时，产出的就是纯 embedding 结果，
                # 模式如实记成 "semantic"——降级必须在日志里看得见，不能假装 AI 上过。
                clustering_mode = "semantic+llm" if refined_clusters else "semantic"
            else:
                events = cluster_notes(notes, min_cluster_size=minimum)
                suppressed_clusters = sum(
                    1
                    for _key, size in Counter(classify_event(note) for note in notes).items()
                    if size < minimum
                )
        if suppressed_clusters:
            suppressed_notes = len(notes) - sum(event.source_count for event in events)
            # 离群剔除出来的单帖簇正是从这条通道被压制掉的：把它的份额挑明，
            # 否则读日志的人只看到"少了几条帖子"，看不出其中几条是被 LLM 判定为不属于事件的。
            ejected_note = (
                f"（其中 {ejected_notes} 条是 LLM 判为「不属于任何事件」而剔除的离群帖："
                f"帖子仍在语料中，只是不再充当事件证据）"
                if ejected_notes
                else ""
            )
            warnings.append(
                f"suppressed {suppressed_clusters} clusters ({suppressed_notes} notes) "
                f"smaller than min_cluster_size={minimum}: they are not public events"
                f"{ejected_note}"
            )

        # 事件级 LLM 风险研判：把"这件事有多严重"从六个电诈词 + 互动量加分里解放出来。
        # 它**只**改写 risk_*（严重性），热度字段（heat_score/heat_rank/ranking_score）是算术，
        # 不许 LLM 碰。assessor 为 None 或逐事件失败时，该事件保留 build_event_from_group
        # 算好的规则风险——事件照出，只是风险回到旧口径（降级记进 warnings）。
        risk_mode = "rules"
        risk_assessed = 0
        if events and risk_assessor is not None:
            risk_assessed = assess_events_risk(
                events,
                risk_assessor,
                notes_by_id={note.note_id: note for note in notes},
                warnings=warnings,
                max_texts=risk_max_texts if risk_max_texts is not None else DEFAULT_MAX_TEXTS,
                concurrency=llm_concurrency,
            )
            if risk_assessed:
                # 一个事件都没判成（全部超时/幻觉）时模式如实记成 rules：降级必须看得见。
                risk_mode = "llm"

        # 事件状态研判（第四根轴）：这件事**完了没有**。时效衰减只看年龄，分不出「3.5 个月前
        # 已经了结的火情」和「2 个月前仍无结论的实名举报」——而这个区别恰恰决定了看板要不要
        # 继续把它顶在上面。它**只**写 lifecycle / lifecycle_reason，随后经 lifecycle_weight
        # 进入 priority_score（严重性、热度、时效算术一个字节都不碰）。
        # assessor 为 None 或逐事件失败时，该事件保持"未研判"（因子 1.0 = 改造前的行为）。
        lifecycle_mode = "none"
        lifecycle_assessed = 0
        if events and lifecycle_assessor is not None:
            lifecycle_assessed = assess_events_lifecycle(
                events,
                lifecycle_assessor,
                notes_by_id={note.note_id: note for note in notes},
                warnings=warnings,
                max_texts=risk_max_texts if risk_max_texts is not None else DEFAULT_MAX_TEXTS,
                concurrency=llm_concurrency,
            )
            if lifecycle_assessed:
                # 一个都没判成（全部超时/幻觉）时如实记成 none：降级必须看得见，不许假装 AI 上过。
                lifecycle_mode = "llm"

        # 事件时效性：给每个事件盖上 age_days / recency_weight / priority_score，然后**重排**。
        # 必须排在风险研判和状态研判**之后**：
        #   priority = severity_weight(risk_level) × recency_weight × lifecycle_weight(lifecycle)
        # 风险和状态都被 LLM 判过，优先级得用新的严重性和新的状态算。
        # 只写这三个新字段：risk_*（严重性不因时间打折）和 heat_*（实测量）一个字节都不碰。
        half_life = (
            recency_config()["half_life_days"]
            if recency_half_life_days is None
            else float(recency_half_life_days)
        )
        # 增长窗口缺省 = 半衰期本身（**不是一个新常数**：半衰期的定义就是"一个校园议题的典型
        # 活跃长度"，一个事件若在一个半衰期内还在追加证据，它就还赶得上衰减打折它的速度）。
        growth_window = (
            growth_window_days
            if growth_window_days is not None
            else (half_life if half_life > 0 else growth_config()["window_days"])
        )
        if events:
            # 这一步同时做三件事，顺序是刻意的：
            #   1. 时效算术（年龄 -> recency_weight）；
            #   2. **增长算术**（成员帖时间分布 -> growing）；
            #   3. **合成**：escalating = ongoing（LLM 的判断） ∧ growing（算术的测量）。
            # 必须排在状态研判之后：合成要用模型刚判出来的那一半。
            events = annotate_events_with_recency(
                events, now=now, half_life_days=half_life, growth_window_days=growth_window
            )
            events = sort_events(events)
        events = annotate_events_with_memory(events, previous_snapshot)

        finished_at = _utc_now_text()
        duration_ms = max(int((time.perf_counter() - started_perf) * 1000), 0)
        snapshot = build_snapshot(events, captured_at=finished_at, centroids=centroids)
        visualization = build_visualization_payload(notes, events)
        run_log = AgentRunLogPayload(
            agent_type="public_opinion",
            status="success",
            input_count=len(row_list),
            event_count=len(events),
            keyword=clean_text(request.keyword),
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            warnings=list(warnings),
            extra={
                "adapted_count": adapted_count,
                "matched_count": matched_count,
                "platforms": list(request.platforms),
                "limit": request.limit,
                "trend_counts": dict(Counter(event.trend for event in events)),
                "risk_escalated_count": sum(1 for event in events if event.risk_escalated),
                "clustering_mode": clustering_mode,
                "sentiment_mode": sentiment_mode,
                "sentiment_overridden": sentiment_overridden,
                # 风险来源：llm = 事件风险由大模型研判；rules = 关键词表 + 互动量加分（旧口径）。
                "risk_mode": risk_mode,
                "risk_assessed": risk_assessed,
                # 状态研判：llm = 事件状态由大模型判过；none = 没判成（未配置/全部失败），
                # 此时生命周期因子恒为 1.0，排序退化回改造前。lifecycle_counts 是各状态的事件数。
                "lifecycle_mode": lifecycle_mode,
                "lifecycle_assessed": lifecycle_assessed,
                "lifecycle_counts": dict(
                    Counter(event.lifecycle for event in events if event.lifecycle)
                ),
                # 增长（「持续发酵」的**算术**判据）：窗口是多少天、有几个事件被测出仍在增长。
                # escalating = ongoing ∧ growing，所以 escalating 的个数永远 <= growing_events
                # （已了结 / 非事件 即使还在来新帖也不会被提升）。两个数一起记，差值本身就是证据。
                "growth_window_days": growth_window,
                "growing_events": sum(
                    1 for event in events if event.growth.get("growing")
                ),
                # 时效性：本次排序用的半衰期与"现在"。0 = 关掉衰减（消融对照臂）。
                # 记进 agent_run_logs 才能事后复现"这一版看板为什么是这个顺序"。
                "recency_half_life_days": half_life,
                "recency_now": now.isoformat(timespec="seconds"),
                "recency_dated_events": sum(1 for event in events if event.event_time),
                "min_cluster_size": minimum,
                "suppressed_clusters": suppressed_clusters,
                "refined_clusters": refined_clusters,
                # 被 LLM 剔出事件的离群帖数（剔除 ≠ 删除：帖子仍在 processed_posts 里）。
                "ejected_notes": ejected_notes,
            },
        )

        return AnalyzeResult(
            request=request,
            events=events,
            run_log=run_log,
            warnings=list(warnings),
            snapshot=snapshot,
            visualization=visualization,
            notes=notes,
        )

    def _try_llm_sentiment(
        self,
        notes: list[OpinionNote],
        classifier: SentimentClassifier | None,
        warnings: list[str],
    ) -> int | None:
        """Override note sentiments with LLM labels; None means rules-only.

        Returns the number of overridden notes. Per-item None labels keep the
        rules result for those notes; any structural failure keeps everything.
        """

        if classifier is None:
            return None
        try:
            labels = classifier([analysis_text(note) for note in notes])
            if labels is None or len(labels) != len(notes):
                raise ValueError("classifier returned wrong label count")
        except Exception as exc:
            warnings.append(f"llm sentiment unavailable, kept rules result: {type(exc).__name__}: {exc}")
            return None

        overridden = 0
        for note, label in zip(notes, labels):
            if isinstance(label, str) and label in VALID_SENTIMENT_LABELS:
                note.sentiment = label
                overridden += 1
        return overridden

    def _try_semantic_clustering(
        self,
        notes: list[OpinionNote],
        embedder: Embedder | None,
        previous_snapshot: MemorySnapshot | None,
        cluster_threshold: float | None,
        merge_threshold: float | None,
        align_threshold: float | None,
        max_span_days: float | None,
        min_cluster_size: int,
        warnings: list[str],
        cluster_refiner: ClusterRefiner | None = None,
        refine_min_size: int | None = None,
        llm_concurrency: int | None = None,
        merge_judge: Any | None = None,
    ) -> tuple[list, dict[str, list[float]], int, int, int] | None:
        """Run semantic clustering if an embedder is supplied; None means fall back to rules."""

        if embedder is None:
            return None
        try:
            vectors = embedder([strip_social_noise(note_text(note)) for note in notes])
            if vectors is None or len(vectors) != len(notes):
                raise ValueError("embedder returned wrong vector count")
            kwargs: dict[str, Any] = {
                "previous": previous_snapshot,
                "min_cluster_size": min_cluster_size,
                # None = 不精修：LLM 未配置时这一层是恒等变换（同 embedder/sentiment 的注入口径）。
                "refiner": cluster_refiner,
                # None = 不做近重合并裁决（只拆不合的老行为，见 llm_merge）。
                "merge_judge": merge_judge,
                # 每个够大的簇一次 LLM 调用，簇之间互不依赖 -> 并发跑（结果按簇序回填）。
                "refine_concurrency": (
                    DEFAULT_LLM_CONCURRENCY if llm_concurrency is None else llm_concurrency
                ),
            }
            if cluster_threshold is not None:
                kwargs["cluster_threshold"] = cluster_threshold
            if merge_threshold is not None:
                kwargs["merge_threshold"] = merge_threshold
            if align_threshold is not None:
                kwargs["align_threshold"] = align_threshold
            if max_span_days is not None:
                kwargs["max_span_days"] = max_span_days
            if refine_min_size is not None:
                kwargs["refine_min_size"] = refine_min_size
            result = cluster_notes_semantic(notes, [list(vector) for vector in vectors], **kwargs)
        except Exception as exc:
            warnings.append(f"semantic clustering unavailable, fell back to rules: {type(exc).__name__}: {exc}")
            return None
        # 精修的降级记录进 warnings（-> agent_run_logs）：LLM 挂了不影响事件产出，但必须留痕。
        # 离群剔除也在这里留痕（剔了哪几条、剔了几条）：被移出事件的帖子绝不允许无声消失。
        warnings.extend(result.refine_warnings)
        if result.merged_clusters:
            # 合并改变事件版图（两个事件变一个），运行日志必须能看出这轮合并了几对。
            warnings.append(f"near-duplicate merge: {result.merged_clusters} 对近重簇经 LLM 裁决合并")
        return (
            result.events,
            result.centroids,
            result.suppressed_clusters,
            result.refined_clusters,
            result.ejected_notes,
        )

    def _filter_notes(self, notes: list[OpinionNote], request: AnalyzeRequest) -> list[OpinionNote]:
        keyword = clean_text(request.keyword)
        platforms = {clean_text(platform).lower() for platform in request.platforms if clean_text(platform)}

        result: list[OpinionNote] = []
        for note in notes:
            if platforms and note.platform.lower() not in platforms:
                continue
            if keyword and keyword not in _search_text(note):
                continue
            result.append(note)
        return result


def _search_text(note: OpinionNote) -> str:
    return " ".join([note_text(note), note.platform, note.author_name])


def _utc_now_text() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
