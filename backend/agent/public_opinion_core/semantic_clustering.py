"""Semantic event clustering on injected embedding vectors.

Single-pass greedy clustering: notes are processed in descending heat order;
each note joins the cluster whose centroid is most similar (cosine, vectors
normalized so cosine == dot product) above ``cluster_threshold``, otherwise
it opens a new cluster. Cross-run event alignment matches new centroids
against the previous MemorySnapshot's stored centroids so a recurring event
keeps its event_key and the memory module's trend annotations stay connected.

This module stays dependency-free on purpose: vectors are produced elsewhere
(e.g. app.services.embedding) and passed in, so the portable core never
imports an embedding model library.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import hashlib
import math
import re

from .clustering import build_event_from_group, note_rank_key, sort_events
from .schemas import MemorySnapshot, OpinionEvent, OpinionNote


# 0.65：聚类黄金集上成对 F1 最优（51.7%→65.7%，P=100%），与 fixture 平台期
# （0.6~0.65）和主项目真实数据标定（0.68）互证；部署侧可经 .env 覆盖。
DEFAULT_CLUSTER_THRESHOLD = 0.65
DEFAULT_ALIGN_THRESHOLD = 0.75

# 1 = 不压制（保持库的历史行为）。部署侧按"事件"的定义抬高（主项目 .env
# EVENT_MIN_CLUSTER_SIZE=2）：一条帖子自己不构成"公共事件"，它只是一条帖子。
DEFAULT_MIN_CLUSTER_SIZE = 1

SEMANTIC_CATEGORY = "semantic"

# 社交平台噪声：小红书话题标签、@提及、零宽/BOM 不可见字符。
# 真实帖满屏 #xx[话题]# 会抬高跨事件相似度（66 条黄金集实测 F1 27.7%→53.7%）。
_SOCIAL_NOISE = re.compile(r"#[^#\[\]]{1,40}\[话题\]#|@[\w一-鿿]{1,24}|[﻿​‌‍]")


def strip_social_noise(text: str) -> str:
    """Remove topic tags, @mentions, and invisible chars before embedding."""

    if not text:
        return text
    return re.sub(r"\s+", " ", _SOCIAL_NOISE.sub(" ", text)).strip()


@dataclass(slots=True)
class SemanticClusterResult:
    events: list[OpinionEvent] = field(default_factory=list)
    # event_key -> 簇中心向量；由调用方写入快照，供下一次运行对齐。
    centroids: dict[str, list[float]] = field(default_factory=dict)
    # 因为成员数 < min_cluster_size 而没有产出事件的簇数（调用方用它报警）。
    suppressed_clusters: int = 0


def cluster_notes_semantic(
    notes: list[OpinionNote],
    vectors: list[list[float]],
    *,
    cluster_threshold: float = DEFAULT_CLUSTER_THRESHOLD,
    previous: MemorySnapshot | None = None,
    align_threshold: float = DEFAULT_ALIGN_THRESHOLD,
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
) -> SemanticClusterResult:
    if len(notes) != len(vectors):
        raise ValueError(f"notes/vectors length mismatch: {len(notes)} != {len(vectors)}")
    if not notes:
        return SemanticClusterResult()

    clusters = _greedy_cluster(notes, vectors, cluster_threshold)
    # 压制发生在"建事件"之前：不够大的簇不进对齐、不产出事件、也不留簇中心——
    # 否则它会被写进快照，下一轮再被对齐成"老事件"复活。
    minimum = max(int(min_cluster_size), 1)
    kept = [cluster for cluster in clusters if len(cluster["notes"]) >= minimum]
    suppressed = len(clusters) - len(kept)
    inherited = _align_with_previous(kept, previous, align_threshold)

    events: list[OpinionEvent] = []
    centroids: dict[str, list[float]] = {}
    for index, cluster in enumerate(kept):
        group_notes = cluster["notes"]
        event_key, title = inherited.get(index) or _new_key_and_title(group_notes)
        events.append(build_event_from_group(event_key, title, SEMANTIC_CATEGORY, group_notes))
        centroids[event_key] = cluster["centroid"]

    return SemanticClusterResult(
        events=sort_events(events),
        centroids=centroids,
        suppressed_clusters=suppressed,
    )


def assign_clusters(
    notes: list[OpinionNote],
    vectors: list[list[float]],
    *,
    cluster_threshold: float = DEFAULT_CLUSTER_THRESHOLD,
) -> list[int]:
    """Return the cluster index of each note, aligned with input order.

    评测用：事件里的 representative_notes 截断到 5 条，拿不到全量簇成员，
    这里直接暴露逐条标签。
    """

    if len(notes) != len(vectors):
        raise ValueError(f"notes/vectors length mismatch: {len(notes)} != {len(vectors)}")
    labels = [0] * len(notes)
    for index, cluster in enumerate(_greedy_cluster(notes, vectors, cluster_threshold)):
        for note_index in cluster["indices"]:
            labels[note_index] = index
    return labels


def _greedy_cluster(
    notes: list[OpinionNote],
    vectors: list[list[float]],
    threshold: float,
) -> list[dict]:
    # 谁先当簇种子是"选择"，按可跨平台比较的 heat_rank 排（高互动量平台不再天然占先）。
    order = sorted(range(len(notes)), key=lambda i: note_rank_key(notes[i]), reverse=True)
    clusters: list[dict] = []
    for i in order:
        vector = _normalize(vectors[i])
        best_cluster = None
        best_similarity = 0.0
        for cluster in clusters:
            similarity = _dot(vector, cluster["centroid"])
            if similarity > best_similarity:
                best_cluster, best_similarity = cluster, similarity
        if best_cluster is None or best_similarity < threshold:
            clusters.append(
                {"notes": [notes[i]], "indices": [i], "sum": list(vector), "centroid": list(vector)}
            )
        else:
            best_cluster["notes"].append(notes[i])
            best_cluster["indices"].append(i)
            best_cluster["sum"] = [a + b for a, b in zip(best_cluster["sum"], vector)]
            best_cluster["centroid"] = _normalize(best_cluster["sum"])
    return clusters


def _align_with_previous(
    clusters: list[dict],
    previous: MemorySnapshot | None,
    align_threshold: float,
) -> dict[int, tuple[str, str]]:
    """Match cluster centroids to the previous snapshot; best pairs win once."""

    if previous is None:
        return {}
    candidates = [
        (key, snapshot, _normalize(snapshot.centroid))
        for key, snapshot in previous.events.items()
        if snapshot.centroid
    ]
    if not candidates:
        return {}

    pairs: list[tuple[float, int, int]] = []
    for cluster_index, cluster in enumerate(clusters):
        for candidate_index, (_key, _snapshot, centroid) in enumerate(candidates):
            similarity = _dot(cluster["centroid"], centroid)
            if similarity >= align_threshold:
                pairs.append((similarity, cluster_index, candidate_index))

    inherited: dict[int, tuple[str, str]] = {}
    used_candidates: set[int] = set()
    for _similarity, cluster_index, candidate_index in sorted(pairs, reverse=True):
        if cluster_index in inherited or candidate_index in used_candidates:
            continue
        key, snapshot, _centroid = candidates[candidate_index]
        fallback_title = _new_key_and_title(clusters[cluster_index]["notes"])[1]
        inherited[cluster_index] = (key, snapshot.title or fallback_title)
        used_candidates.add(candidate_index)
    return inherited


def _new_key_and_title(group_notes: list[OpinionNote]) -> tuple[str, str]:
    top_note = max(group_notes, key=note_rank_key)
    digest = hashlib.sha1(top_note.title.encode("utf-8")).hexdigest()[:8]
    keyword_counter: Counter[str] = Counter()
    for note in group_notes:
        keyword_counter.update(word for word in [*note.keywords, *note.tags] if word)
    if keyword_counter:
        base = keyword_counter.most_common(1)[0][0]
    else:
        base = top_note.title
    # 无关键词时代表帖标题可能是整段原文，截断后再做事件标题。
    if len(base) > 20:
        base = base[:20] + "…"
    return f"sem:{digest}", f"{base}相关讨论"


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return list(vector)
    return [value / norm for value in vector]


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))
