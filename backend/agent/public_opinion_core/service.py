"""Service entrypoint for the portable public opinion Agent core."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
import time
from typing import Any

from .adapter import processed_posts_to_notes
from .clustering import classify_event, cluster_notes, sort_events
from .llm_refine import DEFAULT_REFINE_MIN_SIZE, ClusterRefiner
from .llm_risk import DEFAULT_MAX_TEXTS, RiskAssessor, assess_events_risk
from .memory import annotate_events_with_memory, build_snapshot
from .normalizer import analysis_text, clean_text, note_text
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
        sentiment_classifier: SentimentClassifier | None = None,
        min_cluster_size: int | None = None,
        cluster_refiner: ClusterRefiner | None = None,
        refine_min_size: int | None = None,
        risk_assessor: RiskAssessor | None = None,
        risk_max_texts: int | None = None,
    ) -> AnalyzeResult:
        request = request or AnalyzeRequest()
        started_perf = time.perf_counter()
        started_at = _utc_now_text()

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
                minimum,
                warnings,
                cluster_refiner,
                refine_min_size,
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
            )
            if risk_assessed:
                # 一个事件都没判成（全部超时/幻觉）时模式如实记成 rules：降级必须看得见。
                risk_mode = "llm"
                # 事件排序的第一排序键就是风险等级（sort_events）。风险被重判之后必须重排，
                # 否则列表还是按旧风险排的——火灾判成 high 了却还躺在最底下。
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
        min_cluster_size: int,
        warnings: list[str],
        cluster_refiner: ClusterRefiner | None = None,
        refine_min_size: int | None = None,
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
            }
            if cluster_threshold is not None:
                kwargs["cluster_threshold"] = cluster_threshold
            if merge_threshold is not None:
                kwargs["merge_threshold"] = merge_threshold
            if align_threshold is not None:
                kwargs["align_threshold"] = align_threshold
            if refine_min_size is not None:
                kwargs["refine_min_size"] = refine_min_size
            result = cluster_notes_semantic(notes, [list(vector) for vector in vectors], **kwargs)
        except Exception as exc:
            warnings.append(f"semantic clustering unavailable, fell back to rules: {type(exc).__name__}: {exc}")
            return None
        # 精修的降级记录进 warnings（-> agent_run_logs）：LLM 挂了不影响事件产出，但必须留痕。
        # 离群剔除也在这里留痕（剔了哪几条、剔了几条）：被移出事件的帖子绝不允许无声消失。
        warnings.extend(result.refine_warnings)
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
