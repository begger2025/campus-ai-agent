"""平台先验权重：`ranking_score = platform_weight[platform] × heat_rank`。

**为什么在百分位之上还要乘一个权重**

上一层（`heat_rank`，见 `backend/services/heat_ranking.py`）把 `heat_score` 换成了
**平台内百分位**，修好了"跨平台不可比"——实测中位数 xhs 3924 / ks 998 / weibo 3 /
zhihu 5，直接按 heat_score 排序会把 weibo/zhihu/web 整个埋掉。

但纯百分位**矫枉过正**：它把**量级**整个丢了。一条 3 个赞、排在 weibo 95 分位的帖子，
和一条 10 万赞、排在 xhs 95 分位的帖子，拿到完全相同的排序分——可它们的真实触达差了三个
数量级。项目负责人人工过了一遍抓到的帖子：对校园舆情这个场景，**xhs/ks 的触达和数据质量
都明显高于 weibo/zhihu**。

所以分三层，各司其职：

    heat_score（原始加权互动量，展示给用户看，不动）
      -> heat_rank（该帖在**它自己平台内**的百分位 0-100，保平台内公平）
        -> ranking_score = platform_weight × heat_rank（还回跨平台的触达/质量差异）

平台内百分位保住平台内公平：weibo 的头部帖依然稳赢 weibo 的长尾帖（权重是常数倍，不改平台
内的相对顺序）。平台权重则让 zhihu 的 99 分位帖（0.5 × 99 = 49.5）落在 xhs 的中位数
（1.0 × 50 = 50）附近——**它能冒头，但压不住 xhs 的头部帖**（1.0 × 90 = 90）。

**权重必须不改数据库就能调**：所以 `ranking_score` 不是 `processed_posts` 的新列，而是
`(platform, heat_rank)` 的**纯函数**，在排序发生的地方现算。要调权重，改配置即可，
既不用迁移、也不用重跑归一化 pass。
"""

from __future__ import annotations

import json
import os

from .schemas import OpinionNote


# 负责人钦定的默认权重（人工审阅抓取样本后给的触达 + 数据质量排序）。
#
# tieba 是受支持的爬虫平台，但库里目前一行数据都没有，无从实测。给 0.6：排在 web(0.8) 与
# zhihu(0.5) 之间的中游位置——贴吧有真实的校园讨论浓度（高于微博的泛化广场），但内容质量
# 和触达都未经样本验证，所以不给它 ks/xhs 那一档。有数据之后按实测重调（改配置即可）。
DEFAULT_PLATFORM_WEIGHTS: dict[str, float] = {
    "xhs": 1.0,
    "ks": 0.9,
    "web": 0.8,
    "tieba": 0.6,
    "zhihu": 0.5,
    "weibo": 0.4,
}

# 表里没有的平台一律 1.0——**绝不**默默把一条帖子的排序分打成 0 沉底。新接一个爬虫平台时，
# 它在被正式定权之前会以"满权重"参与排序（宁可多冒头，不可凭空消失）。
UNKNOWN_PLATFORM_WEIGHT = 1.0

# 覆盖用环境变量（.env 由 backend.database / backend.services.llm_config 在进程启动时加载，
# 与项目现有配置约定一致）。两种写法都认：
#     HEAT_PLATFORM_WEIGHTS={"weibo": 0.6, "zhihu": 0.7}
#     HEAT_PLATFORM_WEIGHTS=weibo=0.6,zhihu=0.7
# **增量覆盖**：只写要改的平台，其余保持默认。配置写坏（非法 JSON / 负数 / 非数字）时整体退回
# 默认表——排序降级成"没调过"，而不是让整条流水线炸掉。
PLATFORM_WEIGHTS_ENV = "HEAT_PLATFORM_WEIGHTS"

# 每次排序比较都要查权重，但环境变量在一个进程里几乎不变：按环境变量的**原始字符串**缓存
# 解析结果。字符串一变（测试里 patch os.environ、线上改配置重启）缓存自动失效。
_cache: tuple[str, dict[str, float]] | None = None


def _parse_overrides(raw: str) -> dict[str, float]:
    """解析覆盖配置。任何一处不合法 -> 抛 ValueError，调用方整体退回默认表。"""

    text = raw.strip()
    if not text:
        raise ValueError("empty")

    if text.startswith("{"):
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("not a mapping")
        pairs = parsed.items()
    else:
        pairs = []
        for chunk in text.split(","):
            if not chunk.strip():
                continue
            name, separator, value = chunk.partition("=")
            if not separator:
                raise ValueError(f"expected key=value, got {chunk!r}")
            pairs.append((name, value))

    overrides: dict[str, float] = {}
    for name, value in pairs:
        platform = str(name).strip().lower()
        if not platform:
            raise ValueError("empty platform name")
        weight = float(value)  # bool/str/None 走这里会 ValueError/TypeError
        if weight < 0.0:
            raise ValueError(f"negative weight for {platform}: {weight}")
        overrides[platform] = weight
    if not overrides:
        raise ValueError("no overrides")
    return overrides


def platform_weights() -> dict[str, float]:
    """当前生效的权重表：默认表 叠加 环境变量里的增量覆盖。"""

    global _cache

    raw = os.getenv(PLATFORM_WEIGHTS_ENV, "")
    if _cache is not None and _cache[0] == raw:
        return _cache[1]

    weights = dict(DEFAULT_PLATFORM_WEIGHTS)
    if raw.strip():
        try:
            weights.update(_parse_overrides(raw))
        except (ValueError, TypeError, json.JSONDecodeError):
            # 配置写坏了：用默认表继续跑，不让排序（进而整个分析流水线）挂掉。
            weights = dict(DEFAULT_PLATFORM_WEIGHTS)

    _cache = (raw, weights)
    return weights


def platform_weight(platform: str | None) -> float:
    """某平台的先验权重。未知/空平台 -> 1.0（永远不把帖子打成 0）。"""

    if not isinstance(platform, str):
        return UNKNOWN_PLATFORM_WEIGHT
    key = platform.strip().lower()
    if not key:
        return UNKNOWN_PLATFORM_WEIGHT
    return platform_weights().get(key, UNKNOWN_PLATFORM_WEIGHT)


def ranking_score(platform: str | None, heat_rank: float) -> float:
    """跨平台排序分 = 平台先验权重 × 平台内百分位。纯函数，不落库。

    未归一化的老数据 heat_rank 为 0 -> ranking_score 为 0，排序键随之退回 heat_rank /
    heat_score（见 `clustering.note_rank_key`），不会把既有顺序打乱成随机。
    """

    return round(platform_weight(platform) * float(heat_rank or 0.0), 4)


def note_ranking_score(note: OpinionNote) -> float:
    """一条帖子的跨平台排序分。"""

    return ranking_score(note.platform, note.heat_rank)


__all__ = [
    "DEFAULT_PLATFORM_WEIGHTS",
    "PLATFORM_WEIGHTS_ENV",
    "UNKNOWN_PLATFORM_WEIGHT",
    "note_ranking_score",
    "platform_weight",
    "platform_weights",
    "ranking_score",
]
