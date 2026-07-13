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
from .concurrency import DEFAULT_LLM_CONCURRENCY
from .llm_refine import DEFAULT_REFINE_MIN_SIZE, ClusterRefiner, refine_clusters
from .recency import note_time
from .schemas import MemorySnapshot, OpinionEvent, OpinionNote


# 一个事件的成员帖，时间跨度不得超过这么多天。
#
# 为什么需要它：embedding 只问"像不像"，从不问"是不是同一时候发生的"。真实事故——
# 一条 **2021 年**的「中山大学东校区封闭管理」（疫情封校，热度 9839）和 2026 年的
# 「东校区宿舍搬迁」被聚成了一个事件，跨度 **1782 天**。语义上它俩确实接近（都是
# "东校区 + 管理措施 + 影响学生"），但**一个事件是某个时候发生的一件事**。
# 后果：该事件对外宣称的热度 10982，其中 90% 来自那条 5 年前的疫情帖。
# EVT-57「作息调整争议」同病，跨度 1666 天。
#
# 为什么用算术而不是 LLM：项目的原则是「可测量的用算术，需要判断的用 AI」。
# "这两条帖子是不是一个话题"需要判断 → embedding；"它们差了 5 年吗"**可测量** → 减法。
# （LLM 精修也拆不掉它：送进模型的只有标题，模型根本不知道哪条是 2021 年的。）
#
# 90 天怎么来的：线上 5 个健康事件的跨度是 0 / 2 / 2 / 5 / 42 天，最宽的是
# EVT-77「东校区宿舍火情」的 42 天。取 2 倍余量，既容得下真实的慢燃事件，
# 又足以把 1782 天和 1666 天那两个拆开。
# 0 或负数 = 关闭（消融基线 / 答辩现场开关）。
DEFAULT_MAX_SPAN_DAYS = 90.0
MAX_SPAN_DAYS_ENV = "EVENT_MAX_SPAN_DAYS"


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
    # 被 LLM 成功精修（拆分/改名）的簇数；0 = 纯 embedding 结果。
    refined_clusters: int = 0
    # 被 LLM 判为"哪个话题都不属于"而移出事件的帖子数（离群剔除）。帖子本身不删，
    # 只是不再充当事件证据；它们各自单独成簇后由 min_cluster_size 压制掉。
    ejected_notes: int = 0
    # 精修过程中的降级记录（超时、幻觉编号、漏帖……），由调用方并进 warnings。
    refine_warnings: list[str] = field(default_factory=list)


def cluster_notes_semantic(
    notes: list[OpinionNote],
    vectors: list[list[float]],
    *,
    cluster_threshold: float = DEFAULT_CLUSTER_THRESHOLD,
    merge_threshold: float = DEFAULT_MERGE_THRESHOLD,
    previous: MemorySnapshot | None = None,
    align_threshold: float = DEFAULT_ALIGN_THRESHOLD,
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
    refiner: ClusterRefiner | None = None,
    refine_min_size: int = DEFAULT_REFINE_MIN_SIZE,
    refine_concurrency: int | None = DEFAULT_LLM_CONCURRENCY,
    max_span_days: float = DEFAULT_MAX_SPAN_DAYS,
) -> SemanticClusterResult:
    if len(notes) != len(vectors):
        raise ValueError(f"notes/vectors length mismatch: {len(notes)} != {len(vectors)}")
    if not notes:
        return SemanticClusterResult()

    clusters = _cluster(notes, vectors, cluster_threshold, merge_threshold, max_span_days)

    # LLM 精修：embedding 只会看"像不像"，不会看"是不是一件事"。它把 91 条帖子压成一个簇
    # 并按词频 top-1 命名成「饭堂相关讨论」（里面没有一条食堂帖）。精修在**压制之前**跑：
    # 拆出来的子话题要和别的簇一样，接受 min_cluster_size 的检验（1 帖的话题不是公共事件）。
    # refiner is None（未配 key / 关闭）时这一步是恒等变换，结果与纯 embedding 完全一致。
    # 精修还负责**离群剔除**：模型判为"哪个话题都不属于"的帖子（火灾簇里那张 2023 年的
    # 宿舍照片）被移出事件、各自单独成簇，随即被下面的 min_cluster_size 压制——
    # 一条无关的帖子不是公共事件。帖子本身仍在语料里（情感/热度照算），只是不再当证据。
    # 簇与簇之间互不依赖，精修调用并发跑（结果按簇序回填，与串行逐位一致——见 llm_refine）。
    refine_warnings: list[str] = []
    clusters, refined, ejected = refine_clusters(
        clusters,
        refiner,
        make_cluster=_make_cluster,
        min_size=refine_min_size,
        warnings=refine_warnings,
        concurrency=refine_concurrency,
        # 精修的**跨父簇同名合并**是时间约束的最后一个洞：贪心和质心合并都在父簇层面守住了
        # 窗，而它是跨父簇拼子簇的。真实干跑里它漏了「中大招生宣传」（384 天）和
        # 「零散杂项帖」（94 天）出去。模型看不见日期，拦不住——只能在这里用减法拦。
        max_span_days=max_span_days,
    )

    # 压制发生在"建事件"之前：不够大的簇不进对齐、不产出事件、也不留簇中心——
    # 否则它会被写进快照，下一轮再被对齐成"老事件"复活。
    minimum = max(int(min_cluster_size), 1)
    kept = [cluster for cluster in clusters if len(cluster["notes"]) >= minimum]
    suppressed = len(clusters) - len(kept)
    inherited = _align_with_previous(kept, previous, align_threshold)

    events: list[OpinionEvent] = []
    centroids: dict[str, list[float]] = {}
    used_titles: set[str] = set()
    # 继承来的 key 先占坑：它们是跨轮次身份的锚（一个已发布事件靠它保住 status）。
    # 若让新 key 先来先得，一个新簇可能抢走某个已发布事件的 key，把后者挤成带后缀的
    # 陌生 key —— 那个事件就在看板上变成孤儿了。
    used_keys: set[str] = {key for key, _title in inherited.values()}

    for index, cluster in enumerate(kept):
        group_notes = cluster["notes"]
        event_key, title = inherited.get(index) or _new_key_and_title(group_notes)
        # key 必须在本轮内唯一：persist_public_events 拿 event_key 做 upsert 主键，
        # 撞车 = 事件行互相覆盖 + 两个簇的链接叠加进同一个事件（见 _disambiguate_key）。
        if index not in inherited:
            event_key = _disambiguate_key(event_key, group_notes, used_keys)
        used_keys.add(event_key)
        # LLM 给的标题优先于词频标题、也优先于快照里继承来的旧标题：event_key 负责"还是同一件事"，
        # 标题负责"这件事是什么"——而旧快照里存的正是本次要修掉的那批错标题。
        title = cluster.get("llm_title") or title
        # 合并之后仍然重名的两个事件，对读列表的人来说和没修一样。
        title = _disambiguate_title(title, group_notes, used_titles)
        used_titles.add(title)
        event = build_event_from_group(event_key, title, SEMANTIC_CATEGORY, group_notes)
        # 全量成员（representative_notes 只留 top 5）：消融实验和守恒检查要能看到每条帖子的去向。
        event.extra["note_ids"] = [note.note_id for note in group_notes]
        if cluster.get("llm_title"):
            event.extra["refined_by"] = "llm"
            event.extra["miscellaneous"] = bool(cluster.get("llm_miscellaneous"))
        events.append(event)
        centroids[event_key] = cluster["centroid"]

    return SemanticClusterResult(
        events=sort_events(events),
        centroids=centroids,
        suppressed_clusters=suppressed,
        refined_clusters=refined,
        refine_warnings=refine_warnings,
        ejected_notes=ejected,
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
    max_span_days: float = DEFAULT_MAX_SPAN_DAYS,
) -> list[dict]:
    """贪心分配 + 质心合并，直到没有可合的一对。"""

    return _merge_clusters(
        _greedy_cluster(notes, vectors, threshold, max_span_days),
        merge_threshold,
        max_span_days,
    )


def _merge_clusters(
    clusters: list[dict],
    merge_threshold: float,
    max_span_days: float = DEFAULT_MAX_SPAN_DAYS,
) -> list[dict]:
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
                # 合并趟也守时间窗——否则贪心刚按年份拆开的两个簇，这里又给缝回去。
                if not _within_span(
                    working[left]["members"] + working[right]["members"], max_span_days
                ):
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


def _span_days(members: list[tuple[OpinionNote, int, list[float]]]) -> float | None:
    """一组成员的时间跨度（天）。没有任何可解析时间戳时返回 None。"""

    times = [t for t in (note_time(note) for note, _index, _vector in members) if t is not None]
    if len(times) < 2:
        return None
    return (max(times) - min(times)).total_seconds() / 86400.0


def _within_span(
    members: list[tuple[OpinionNote, int, list[float]]], max_span_days: float
) -> bool:
    """这组成员放在一个事件里，时间上说得通吗？

    约束的是**整簇的跨度**（max - min），不是"离某个成员有多远"。后者可以被接力绕过：
    A(第0天) - B(第80天) - C(第160天)，每一步都在窗口内，但 A 和 C 差了 160 天。

    没有时间戳的帖子**不参与判定、也不被排除**——"不知道多老" ≠ "很老"
    （与 recency.age_in_days 的 None 语义一致）。
    """

    if max_span_days <= 0:
        return True  # 关掉时间约束（消融基线 / 现场开关）
    span = _span_days(members)
    return span is None or span <= max_span_days


def _greedy_cluster(
    notes: list[OpinionNote],
    vectors: list[list[float]],
    threshold: float,
    max_span_days: float = DEFAULT_MAX_SPAN_DAYS,
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
        member = (notes[i], i, vector)

        # 候选簇按相似度降序试：最像的那个若时间上说不通（并簇之后跨度会超窗），
        # **退而求其次试下一个**，而不是直接另开新簇——同一个话题在不同年份各自成事件，
        # 新帖该落到同期的那个事件上，而不是因为最像的是那个老事件就被迫独立。
        candidates = sorted(
            (
                (_dot(vector, cluster["centroid"]), index)
                for index, cluster in enumerate(clusters)
            ),
            key=lambda pair: (-pair[0], pair[1]),
        )

        joined = False
        for similarity, index in candidates:
            if similarity < threshold:
                break  # 已按相似度降序，后面只会更低
            if not _within_span(clusters[index]["members"] + [member], max_span_days):
                continue  # 语义像，但差了好几年——不是同一件事
            # 质心按成员集合重算（见 _make_cluster），不做增量累加：
            # 增量累加的结果取决于成员加入顺序，那正是这次要拆掉的东西。
            clusters[index] = _make_cluster(clusters[index]["members"] + [member])
            joined = True
            break

        if not joined:
            clusters.append(_make_cluster([member]))
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

    # 词频标题带「相关讨论」的尾巴，消歧后保持原样；**LLM 精修出来的标题没有这条尾巴，
    # 消歧时也绝不许粘上去**——「作息调整争议」被消歧成「作息调整争议·中山大学相关讨论」
    # 的话，这一整个功能就白做了（那正是要消灭的套话标题）。
    boilerplate = title.endswith(TITLE_SUFFIX)
    base = title[: -len(TITLE_SUFFIX)] if boilerplate else title
    suffix = TITLE_SUFFIX if boilerplate else ""
    for word in _ranked_keywords(group_notes):
        if word and word not in base:
            candidate = f"{base}·{word}{suffix}"
            if candidate not in used:
                return candidate

    top_note = max(group_notes, key=lambda note: (note_rank_key(note), note.note_id))
    candidate = f"{_truncate(top_note.title)}{suffix}"
    if top_note.title and candidate not in used:
        return candidate

    ordinal = 2
    while f"{base}（{ordinal}）{suffix}" in used:
        ordinal += 1
    return f"{base}（{ordinal}）{suffix}"


def _truncate(base: str) -> str:
    # 无关键词时代表帖标题可能是整段原文，截断后再做事件标题。
    return base[:20] + "…" if len(base) > 20 else base


def _disambiguate_key(key: str, group_notes: list[OpinionNote], used: set[str]) -> str:
    """撞车的 event_key 用**成员集合**消歧；没撞车的原样返回。

    为什么会撞：``_new_key_and_title`` 只哈希"热度最高那条成员帖的标题"。两个不同的簇
    完全可能有同名的头帖（同一篇文章在不同年份被转发）——改造前它俩本来在一个簇里、
    不会撞，**时间窗按年份把它们拆开之后，两个簇各自拿同一个标题去算 key，撞了**。
    真实数据上重跑出 65 个事件却只有 60 个不同的 key。

    撞车的代价不是"标题重复"这么轻：``persist_public_events`` 拿 event_key 做 upsert
    主键，于是**事件行互相覆盖**（source_count 只剩一个）、**两个簇的链接全写进同一个
    事件**（3 + 2 = 5 条）。线上表现是已发布的「项飙中大对谈」里混进了「广州雨天好去处」。

    为什么不干脆全部改成按成员集合哈希：那会让**每一个** key 都变，跨轮次记忆对齐全部
    失效，已发布事件一夜之间变成孤儿。所以保留按标题的 key（稳定性），只在真撞车时加后缀。
    """

    if key not in used:
        return key
    members = "\n".join(sorted(note.note_id for note in group_notes))
    suffix = hashlib.sha1(members.encode("utf-8")).hexdigest()[:6]
    return f"{key}-{suffix}"


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
