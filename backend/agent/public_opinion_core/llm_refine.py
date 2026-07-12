"""LLM 精修 embedding 聚出来的簇：拆开误合并的大桶，给每个话题一个具体标题。

**为什么 embedding 到这里就到头了。** 297 条真实语料上，语义聚类产出一个 91 帖的簇，
标题「饭堂相关讨论」，里面一条食堂的帖子都没有：

    中山大学三大校区 哪个更好？ #升学规划
    中山大学拟调整作息引争议！校方回应：已关注此事，会回应师生关切
    吃饭，睡觉，骂校长，这都快成了中山学子的日常了！

两个结构性成因：(1) 每条帖子都含「中山大学」，向量空间被这个共同词压平，子话题的夹角
不够分开；(2) 事件标题取的是**簇内词频 top-1**，词频不理解语义，于是抽中噪声词「饭堂」
（另一处从一份*物理*试卷里抽出了「压力」）。调阈值治不了：调低塌成 191 帖的巨桶，
调高碎成 33 个重名事件——缺的不是阈值，是**对内容的理解**。

后果是具体的：「中山大学作息调整」是这批语料里一个 20 帖的真实校园争议，它被埋在那个
错标的桶里，从来没有作为一个事件出现过。

**这一层做的事**：把够大的簇的帖子标题交给 LLM，问它"这里面其实是几件事"，按它给的分组
把簇拆开，并用它给的标题。核心包保持零依赖：refiner 是**注入**的 Callable（同 service.py
的 Embedder / SentimentClassifier），None = 跳过精修、保留 embedding 结果。

**模型会失败，失败不许拖垮流水线。** LLM 的输出在被信任之前必须先对着**真实输入**验证一遍：

  - 编造的帖子编号（返回第 99 号，可这个簇只有 8 条）→ 整簇精修作废，退回 embedding 结果；
  - 同一条帖子被塞进两个话题 → 作废（真实数据不能因为模型的幻觉被复制）；
  - 空标题 / 非整数编号 / 非列表 / 空列表 / 抛异常 → 作废；
  - 漏掉了几条帖子 → **不作废**，漏掉的原样留在一个残余簇里（一条帖子都不许在精修中消失）。

每一种失败都记一条 warning（进 agent_run_logs），退回的是"能用的旧结果"而不是空结果。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .schemas import OpinionNote


# (一个簇的帖子文本，规范顺序) -> 话题列表；每个话题是
#   {"title": str, "members": [1-based 编号...], "miscellaneous": bool}
# 由运行环境注入（见 backend/services/event_refiner.py），核心不认识 HTTP、模型名和 API key。
# 返回 None / 抛异常 = 本次精修不可用，调用方保留 embedding 的簇。
ClusterRefiner = Callable[[list[str]], "Sequence[Mapping[str, Any]] | None"]

# 只精修够大的簇。8 的来由（297 条语料实测，簇大小 91/59/24/15/13/11/10 | 7/7/6/3/3/2/2）：
#   - 下界是**算术**决定的：一个簇要能拆出两个"公共事件"，至少得有 2 × EVENT_MIN_CLUSTER_SIZE
#     （=4）条帖子，再小的簇精修只能改名、不可能拆分；
#   - 8 正落在真实分布的天然缺口（7 → 10）上，选中的 7 个簇覆盖 223/297 = 75% 的语料，
#     共 7 次 LLM 调用；把门槛降到 4 要多花 4 次调用（+57%）去覆盖多出来的 26 条帖子（8.8%），
#     而错标的严重程度是随簇变大而放大的（「饭堂」桶 91 帖，一条食堂帖都没有）；
#   - 给 2 帖的簇打一次 LLM 调用是纯浪费：两条帖子本来就分不出"几个话题"。
# 部署侧可经 .env EVENT_REFINE_MIN_SIZE 覆盖。
DEFAULT_REFINE_MIN_SIZE = 8

# 一次送给模型的帖子上限：token 成本与"编号越多越容易数错"都随规模涨。超过就不精修
# （而不是只送前 N 条——那会让"漏掉的帖子"变成常态）。91 帖的最大簇远在此之下。
DEFAULT_REFINE_MAX_MEMBERS = 150

# 送给模型的每条帖子截断长度：判断话题归属不需要全文。
TEXT_MAX_CHARS = 60


def refiner_input_texts(notes: list[OpinionNote]) -> list[str]:
    """簇成员送给模型的文本：标题优先（没标题的用正文），截断。

    顺序即编号：调用方必须按簇的规范成员顺序传入，模型返回的 1-based 编号才有稳定含义。
    """

    texts: list[str] = []
    for note in notes:
        text = (note.title or note.content or "").strip()
        texts.append(text[:TEXT_MAX_CHARS])
    return texts


def refine_clusters(
    clusters: list[dict],
    refiner: ClusterRefiner | None,
    *,
    make_cluster: Callable[[list[tuple[OpinionNote, int, list[float]]]], dict],
    min_size: int = DEFAULT_REFINE_MIN_SIZE,
    max_members: int = DEFAULT_REFINE_MAX_MEMBERS,
    warnings: list[str] | None = None,
) -> tuple[list[dict], int]:
    """把够大的簇交给 LLM 重新分组；返回（新的簇列表, 被成功精修的簇数）。

    ``make_cluster`` 由 semantic_clustering 注入（本模块不 import 它，避免循环依赖）：
    拆出来的子簇必须**重算质心**——质心要写进记忆快照供下一次运行对齐，拿父簇的质心
    冒充子簇的，下一轮就会把三个话题又对齐回同一个老事件上。
    """

    warnings = warnings if warnings is not None else []
    if refiner is None or not clusters:
        return clusters, 0

    refined_count = 0
    result: list[dict] = []
    for cluster in clusters:
        notes = cluster["notes"]
        if len(notes) < max(int(min_size), 2):
            result.append(cluster)
            continue
        if len(notes) > max_members:
            warnings.append(
                f"llm refine skipped a {len(notes)}-note cluster (over max_members={max_members})"
            )
            result.append(cluster)
            continue

        groups = _refine_one(cluster, refiner, warnings, make_cluster)
        if groups is None:
            result.append(cluster)
            continue
        result.extend(groups)
        refined_count += 1

    result = _merge_same_topic(result, make_cluster)
    # 输出顺序必须唯一（和 _merge_clusters 出口一致）：按（成员数降序, 签名）排。
    result.sort(key=lambda item: (-len(item["notes"]), _signature(item)))
    return result, refined_count


def _merge_same_topic(
    clusters: list[dict],
    make_cluster: Callable[[list[tuple[OpinionNote, int, list[float]]]], dict],
) -> list[dict]:
    """标题相同的话题合成一个事件（模型是一簇一簇看的，看不见别的簇）。

    真实数据上：两个 embedding 簇各自被认出「中大作息调整争议」——同一件校园争议本来就
    被切在两个簇里。不合的话事件列表里并排站着两个同名事件，和这次要修的缺陷（4 个
    「宿舍相关讨论」）是同一个毛病，只是换了个来源。质心按合并后的成员重算。
    """

    by_title: dict[str, list[dict]] = {}
    merged: list[dict] = []
    for cluster in clusters:
        title = cluster.get("llm_title")
        if not title:  # 未精修的簇、残余簇：标题不是模型给的，不参与按标题合并
            merged.append(cluster)
            continue
        by_title.setdefault(title, []).append(cluster)

    for title, group in by_title.items():
        if len(group) == 1:
            merged.append(group[0])
            continue
        combined = make_cluster([member for cluster in group for member in cluster["members"]])
        combined["llm_title"] = title
        combined["llm_miscellaneous"] = any(cluster.get("llm_miscellaneous") for cluster in group)
        merged.append(combined)
    return merged


def _refine_one(
    cluster: dict,
    refiner: ClusterRefiner,
    warnings: list[str],
    make_cluster: Callable[[list[tuple[OpinionNote, int, list[float]]]], dict],
) -> list[dict] | None:
    """精修一个簇；None = 这次不可信，调用方保留原簇。"""

    members = cluster["members"]
    notes = cluster["notes"]
    try:
        raw = refiner(refiner_input_texts(notes))
    except Exception as exc:  # 超时、网络、SDK 里任何东西
        warnings.append(
            f"llm refine unavailable for a {len(notes)}-note cluster, "
            f"kept embedding clusters: {type(exc).__name__}: {exc}"
        )
        return None

    topics = _validate_topics(raw, len(notes))
    if topics is None:
        warnings.append(
            f"llm refine returned unusable output for a {len(notes)}-note cluster, "
            "kept embedding clusters"
        )
        return None

    assigned: set[int] = set()
    groups: list[dict] = []
    for title, indices, miscellaneous in topics:
        assigned.update(indices)
        group = make_cluster([members[index - 1] for index in indices])
        group["llm_title"] = title
        group["llm_miscellaneous"] = miscellaneous
        groups.append(group)

    # 模型漏掉的帖子：一条都不许消失，原样留成一个残余簇（沿用 embedding 的命名口径）。
    leftover = [index for index in range(1, len(notes) + 1) if index not in assigned]
    if leftover:
        warnings.append(
            f"llm refine left {len(leftover)} of {len(notes)} notes unassigned "
            f"（未分配帖子已原样保留为残余簇）"
        )
        groups.append(make_cluster([members[index - 1] for index in leftover]))
    return groups


def _validate_topics(raw: Any, member_count: int) -> list[tuple[str, list[int], bool]] | None:
    """把模型的原始输出对着**真实簇成员**验一遍；None = 不可信。

    这是本模块的安全边界：编号只有落在 [1, member_count] 且互不重复时才允许动真实数据。
    """

    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or not raw:
        return None

    seen: set[int] = set()
    topics: list[tuple[str, list[int], bool]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            return None
        title = str(item.get("title") or "").strip()
        if not title:
            return None
        members = item.get("members")
        if not isinstance(members, Sequence) or isinstance(members, (str, bytes)):
            return None

        indices: list[int] = []
        for value in members:
            # bool 是 int 的子类，别把 True 当成 1 号帖。
            if isinstance(value, bool) or not isinstance(value, int):
                return None
            if not 1 <= value <= member_count:  # 编造出来的帖子编号
                return None
            if value in seen:  # 同一条帖子被塞进两个话题
                return None
            seen.add(value)
            indices.append(value)
        if not indices:  # 空话题：无成员的标题不构成事件
            continue
        topics.append((title, sorted(indices), bool(item.get("miscellaneous"))))

    return topics or None


def _signature(cluster: dict) -> tuple[str, ...]:
    return tuple(sorted(note.note_id for note in cluster["notes"]))
