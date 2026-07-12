"""Semantic event clustering on injected embedding vectors.

两段式聚类：

1. **贪心分配**（``_greedy_cluster``）：帖子按热度序处理，每条加入质心最相似
   （余弦；向量已归一化，故余弦 == 点积）且超过 ``cluster_threshold`` 的簇，否则新开一簇。
2. **质心合并**（``_merge_clusters``）：反复把质心相似度 ≥ ``merge_threshold`` 的一对簇
   合成一个并重算质心，直到没有可合的一对（凝聚式后合并）。

第 2 步不是锦上添花，是补一个缺口：贪心是**单趟**的，帖子只跟"当时已存在的簇"比，
之后再没有回头的机会——同一个话题只要在输入里被别的帖子隔开就会裂成好几个簇，
而且裂法取决于输入顺序。调 ``cluster_threshold`` 治不了（调高裂得更碎，调低直接塌成巨簇），
缺的就是"回头把质心相近的簇缝回去"这一步。

聚类结果与**输入顺序无关**（换个顺序喂同一批帖子必须得到同一批簇）：种子顺序用
``(note_rank_key, note_id)`` 全序排（光靠三个浮点数会大量并列，并列时稳定排序 = 输入顺序）；
质心按成员的规范顺序求和（浮点加法不满足结合律）；合并每轮取全局最相似的一对，
并列时用簇签名裁决。见 test_cluster_merge.py::OrderIndependenceTest。

Cross-run event alignment matches new centroids against the previous
MemorySnapshot's stored centroids so a recurring event keeps its event_key and
the memory module's trend annotations stay connected.

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

# 0.86：主项目 297 条真实语料上扫出来的（cluster_threshold=0.70，见报告）。
#   ≥0.88 合并不动（事件数 14，与不合并等同）；0.86 → 11 个事件，最大簇 104（35%），
#   把裂开的「中山大学」质心缝回去；**0.85 就塌方**（最大簇 179 = 60% 语料），
#   0.84 更是 236（80%）。可用窗口窄，悬崖在 0.855↘0.85 之间——往下调之前先重跑扫描。
# 1.0 = 关闭合并（只有完全相同的质心才合并）。
DEFAULT_MERGE_THRESHOLD = 0.86
MERGE_THRESHOLD_ENV = "EMBEDDING_MERGE_THRESHOLD"

# 相似度比较的并列带：数学上相等的余弦在浮点里未必逐位相等（见 _merge_clusters）。
_EPSILON = 1e-9

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
    merge_threshold: float = DEFAULT_MERGE_THRESHOLD,
    previous: MemorySnapshot | None = None,
    align_threshold: float = DEFAULT_ALIGN_THRESHOLD,
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
) -> SemanticClusterResult:
    if len(notes) != len(vectors):
        raise ValueError(f"notes/vectors length mismatch: {len(notes)} != {len(vectors)}")
    if not notes:
        return SemanticClusterResult()

    clusters = _cluster(notes, vectors, cluster_threshold, merge_threshold)
    # 压制发生在"建事件"之前：不够大的簇不进对齐、不产出事件、也不留簇中心——
    # 否则它会被写进快照，下一轮再被对齐成"老事件"复活。
    minimum = max(int(min_cluster_size), 1)
    kept = [cluster for cluster in clusters if len(cluster["notes"]) >= minimum]
    suppressed = len(clusters) - len(kept)
    inherited = _align_with_previous(kept, previous, align_threshold)

    events: list[OpinionEvent] = []
    centroids: dict[str, list[float]] = {}
    used_titles: set[str] = set()
    for index, cluster in enumerate(kept):
        group_notes = cluster["notes"]
        event_key, title = inherited.get(index) or _new_key_and_title(group_notes)
        # 合并之后仍然重名的两个事件，对读列表的人来说和没修一样。
        title = _disambiguate_title(title, group_notes, used_titles)
        used_titles.add(title)
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
    merge_threshold: float = DEFAULT_MERGE_THRESHOLD,
) -> list[int]:
    """Return the cluster index of each note, aligned with input order.

    评测用：事件里的 representative_notes 截断到 5 条，拿不到全量簇成员，
    这里直接暴露逐条标签。
    """

    if len(notes) != len(vectors):
        raise ValueError(f"notes/vectors length mismatch: {len(notes)} != {len(vectors)}")
    labels = [0] * len(notes)
    for index, cluster in enumerate(_cluster(notes, vectors, cluster_threshold, merge_threshold)):
        for note_index in cluster["indices"]:
            labels[note_index] = index
    return labels


def _cluster(
    notes: list[OpinionNote],
    vectors: list[list[float]],
    threshold: float,
    merge_threshold: float,
) -> list[dict]:
    """贪心分配 + 质心合并，直到没有可合的一对。"""

    return _merge_clusters(_greedy_cluster(notes, vectors, threshold), merge_threshold)


def _merge_clusters(clusters: list[dict], merge_threshold: float) -> list[dict]:
    """凝聚式后合并：反复把质心最像的一对簇合成一个，直到没有一对达到 merge_threshold。

    贪心是**单趟**的：每条帖子只在"当时已经存在的簇"里挑一个最像的，挑不到就新开一簇，
    此后再没有回头的机会。于是同一个话题只要在输入里被别的帖子隔开，就会裂成好几个簇，
    而这些簇彼此的质心其实高度相似——没人再去看一眼。真实数据上这直接表现为
    4 个「宿舍相关讨论」、3 个「食堂相关讨论」并列出现在事件列表里。

    每轮取**全局最相似**的一对（而不是碰到一对合一对），所以合并顺序不依赖簇的排列；
    相似度并列时用簇的规范签名（成员 note_id 排序）打破平局，保证结果唯一、可复现。
    """

    if merge_threshold > 1.0 or len(clusters) < 2:
        return clusters

    working = list(clusters)
    while len(working) > 1:
        best_pair: tuple[int, int] | None = None
        best_similarity = merge_threshold - _EPSILON
        best_tiebreak: tuple[str, str] | None = None
        for left in range(len(working)):
            for right in range(left + 1, len(working)):
                similarity = _dot(working[left]["centroid"], working[right]["centroid"])
                if similarity < best_similarity - _EPSILON:
                    continue
                tiebreak = (_signature(working[left]), _signature(working[right]))
                # 数学上并列的相似度（比如三对夹角都是 20°）在浮点里并不逐位相等，
                # 用 == 打平局等于把胜负交给最后几位的噪声。留一个 epsilon 带，
                # 带内视作并列、交给签名裁决——结果才真正只由簇的内容决定。
                if (
                    best_pair is None
                    or similarity > best_similarity + _EPSILON
                    or (abs(similarity - best_similarity) <= _EPSILON and tiebreak < best_tiebreak)
                ):
                    best_pair, best_similarity, best_tiebreak = (left, right), similarity, tiebreak
        if best_pair is None:
            break

        left, right = best_pair
        merged = _combine(working[left], working[right])
        working = [cluster for i, cluster in enumerate(working) if i not in best_pair]
        working.append(merged)

    # 输出顺序也必须唯一：按（成员数降序, 签名）排，换个输入顺序拿到的是同一个列表。
    return sorted(working, key=lambda cluster: (-len(cluster["notes"]), _signature(cluster)))


def _combine(left: dict, right: dict) -> dict:
    """合并两簇：成员并起来，质心按规范顺序重算。"""

    return _make_cluster(left["members"] + right["members"])


def _make_cluster(members: list[tuple[OpinionNote, int, list[float]]]) -> dict:
    """簇 = 成员集合；质心 = 成员（已归一化）向量之和再归一化，**按规范顺序求和**。

    浮点加法不满足结合律：换个成员加入顺序，累加出来的质心会有最后几位的差别，
    而一次"差不多相等"的合并判定就可能因此翻面——顺序依赖会从算法层掉到浮点层继续存在。
    按 (note_id, 输入下标) 规范排序求和，质心就成了成员集合的纯函数。
    （排序里带上下标：note_id 理论上可能重复，只按 note_id 排不是全序。）
    """

    ordered = sorted(members, key=lambda member: (member[0].note_id, member[1]))
    total = [0.0] * len(ordered[0][2])
    for _note, _index, vector in ordered:
        for dimension, value in enumerate(vector):
            total[dimension] += value
    return {
        "members": ordered,
        "notes": [note for note, _index, _vector in ordered],
        "indices": [index for _note, index, _vector in ordered],
        "centroid": _normalize(total),
    }


def _signature(cluster: dict) -> tuple[str, ...]:
    """簇的规范签名：成员 note_id 排序后的元组。

    只用 note_id，**不带输入下标**：下标会随输入顺序改变，拿它打平局等于把顺序依赖
    从贪心搬到合并里。note_id 是帖子自己的身份，换个顺序喂进来它不变。
    """

    return tuple(sorted(note.note_id for note in cluster["notes"]))


def _greedy_cluster(
    notes: list[OpinionNote],
    vectors: list[list[float]],
    threshold: float,
) -> list[dict]:
    # 谁先当簇种子是"选择"，按可跨平台比较的 heat_rank 排（高互动量平台不再天然占先）。
    # 末位加 note_id：note_rank_key 是三个浮点数，真实数据里大量并列（老数据全是 0），
    # 并列时 sorted 是稳定排序 = 按输入顺序，于是"同一批帖子换个顺序喂进来得到不同的簇"。
    # 补一个全序的 tiebreak，种子顺序就只由帖子本身决定了。
    order = sorted(
        range(len(notes)),
        key=lambda i: (note_rank_key(notes[i]), notes[i].note_id),
        reverse=True,
    )
    clusters: list[dict] = []
    for i in order:
        vector = _normalize(vectors[i])
        best_index = None
        best_similarity = 0.0
        for index, cluster in enumerate(clusters):
            similarity = _dot(vector, cluster["centroid"])
            if similarity > best_similarity:
                best_index, best_similarity = index, similarity
        member = (notes[i], i, vector)
        if best_index is None or best_similarity < threshold:
            clusters.append(_make_cluster([member]))
        else:
            # 质心按成员集合重算（见 _make_cluster），不做增量累加：
            # 增量累加的结果取决于成员加入顺序，那正是这次要拆掉的东西。
            clusters[best_index] = _make_cluster(clusters[best_index]["members"] + [member])
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


TITLE_SUFFIX = "相关讨论"


def _ranked_keywords(group_notes: list[OpinionNote]) -> list[str]:
    """簇内关键词按（词频降序, 词面）排。

    不用 Counter.most_common()：并列时它按插入顺序返回，而插入顺序取决于成员顺序——
    同一个簇会因为帖子的排列不同而拿到不同的标题。这里排成全序，标题才是簇的函数。
    """

    counter: Counter[str] = Counter()
    for note in group_notes:
        counter.update(word for word in [*note.keywords, *note.tags] if word)
    return [word for word, _count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))]


def _disambiguate_title(title: str, group_notes: list[OpinionNote], used: set[str]) -> str:
    """同名事件是这次要消灭的缺陷本身：重名时把两个事件区分开。

    「宿舍相关讨论」×2 并列在公开列表里，读者无从分辨该点哪个。降级顺序：
      1. 次要关键词：「宿舍·搬迁相关讨论」——仍然一眼看出是宿舍的事；
      2. 代表帖标题：关键词只有一个（抽取噪声大，真实数据里一条"学生被开除"的帖子
         也会被标上「宿舍」）时，用帖子自己的标题命名，至少说清了这是哪一件事；
      3. 序号：只有前两条都撞车才用，纯粹为了保证一次运行内标题唯一。
    """

    if title not in used:
        return title

    base = title[: -len(TITLE_SUFFIX)] if title.endswith(TITLE_SUFFIX) else title
    for word in _ranked_keywords(group_notes):
        if word and word not in base:
            candidate = f"{base}·{word}{TITLE_SUFFIX}"
            if candidate not in used:
                return candidate

    top_note = max(group_notes, key=lambda note: (note_rank_key(note), note.note_id))
    candidate = f"{_truncate(top_note.title)}{TITLE_SUFFIX}"
    if top_note.title and candidate not in used:
        return candidate

    ordinal = 2
    while f"{base}（{ordinal}）{TITLE_SUFFIX}" in used:
        ordinal += 1
    return f"{base}（{ordinal}）{TITLE_SUFFIX}"


def _truncate(base: str) -> str:
    # 无关键词时代表帖标题可能是整段原文，截断后再做事件标题。
    return base[:20] + "…" if len(base) > 20 else base


def _new_key_and_title(group_notes: list[OpinionNote]) -> tuple[str, str]:
    top_note = max(group_notes, key=lambda note: (note_rank_key(note), note.note_id))
    digest = hashlib.sha1(top_note.title.encode("utf-8")).hexdigest()[:8]
    keywords = _ranked_keywords(group_notes)
    base = keywords[0] if keywords else top_note.title
    return f"sem:{digest}", f"{_truncate(base)}{TITLE_SUFFIX}"


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return list(vector)
    return [value / norm for value in vector]


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))
