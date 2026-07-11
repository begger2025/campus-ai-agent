"""平台内归一化排序分（heat_rank）与 web 证据行的来源权威度热度。

**为什么需要它**（在共享库 331 行 `processed_posts` 上实测）：

    平台     行数   heat_score 中位数
    xhs      182    3924
    ks        38     998
    weibo     10       3
    zhihu    101       5
    web        -       0（网页没有互动量，恒为 0）

`heat_score` 是原始互动量的加权和（赞 1.0 + 藏 1.5 + 评 3.0 + 转 2.5），它是一个
真实、可解释、要展示给用户看的数——但**跨平台不可比**：各平台互动量量级差约 3 个
数量级。任何按 `heat_score` 排序/取 top-N 的视图都会被 xhs/ks 占满，把 weibo（最重要
的舆情平台）、zhihu 和人工审核过的 web 官方通知整个埋掉。

**做法**：`heat_score` 原样保留（展示用），另加 `heat_rank`——该帖 `heat_score` 在
**它自己平台内**的百分位（0-100）。跨平台比较一律用 `heat_rank`，于是 weibo 的头部帖
可以和 xhs 的头部帖公平竞争。

百分位是**语料相对**的，不是逐行函数，所以它在批处理脚本
（`scripts/process_raw_posts.py`）处理完之后做一次全量归一化 pass：按平台重算该平台
所有行的 `heat_rank`。331 行的规模下 O(n log n) 全量重算的成本可以忽略，且避免了增量
更新必然产生的漂移。纯函数（`percentile_ranks` / `calculate_web_heat_score`）与 DB pass
分开，前者可单测，后者只剩薄薄一层。
"""

from __future__ import annotations

from typing import Iterable, Sequence
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from backend.models import ProcessedPost, RawPost
from backend.services.evidence.scope_policy import (
    NEWS_DOMAIN_ALLOWLIST,
    SYSU_OFFICIAL_DOMAIN_ALLOWLIST,
    _domain_allowed,
)


# 证据交付写入 raw_posts 用的平台码（见 evidence/review_delivery.py::DELIVERY_PLATFORM）。
# 这里重新声明而不 import，是为了不让 heat_ranking 依赖交付模块（反向依赖会成环）。
WEB_PLATFORM = "web"
EVIDENCE_SOURCE_TABLE = "evidence_items"

# web 热度 = 来源权威度 + 核验强度，值域 0-100。
# 绝对刻度无所谓（heat_rank 会在 web 平台内部再归一化一次），只有 web 内部的**顺序**要有意义：
# 官方+已核验 100 分封顶，未知域名+未核验 0 分垫底。权威度权重更大，因为"谁说的"比
# "核验到什么程度"更能决定一条网页证据的分量。
_AUTHORITY_OFFICIAL = 60.0
_AUTHORITY_NEWS = 30.0
_AUTHORITY_OTHER = 0.0

_VERIFICATION_WEIGHTS = {
    "verified": 40.0,
    "needs_review": 15.0,
}
_VERIFICATION_DEFAULT = 0.0

# 单条帖子的百分位：0/100 都不给。只有一条的平台拿 50（中性），而不是 0（那等于又把它埋了）
# 或 100（白送头名）。
_NEUTRAL_PERCENTILE = 50.0


def percentile_ranks(scores: Sequence[float]) -> list[float]:
    """一组分数 -> 各自的百分位（0-100 float），顺序与入参一一对应。

    用**中位秩**（mid-rank）：一个分数的百分位 = 100 * (比它小的个数 + 并列的个数/2) / 总数。

    并列的处理：完全相同的分数拿到**完全相同**的百分位（它们所占名次的平均），绝不靠
    id/插入顺序偷偷分先后。由此还得到两个好性质：
      - 单条（n=1）-> 50.0；全平台同分 -> 全部 50.0（中性，而不是 0 或 100）。
      - 任何分数的百分位都严格落在 (0, 100) 开区间内，没有哪一条会被判 0 分而彻底沉底。

    纯函数：不碰 DB、不看平台、不排序副作用。O(n log n)。
    """

    values = [float(score or 0.0) for score in scores]
    total = len(values)
    if total == 0:
        return []

    # 同一分数的所有行共享一个中位秩：先按值分组，组内名次取平均。
    ordered = sorted(values)
    less_than: dict[float, int] = {}
    equal_count: dict[float, int] = {}
    index = 0
    while index < total:
        value = ordered[index]
        run = 1
        while index + run < total and ordered[index + run] == value:
            run += 1
        less_than[value] = index
        equal_count[value] = run
        index += run

    return [
        round(100.0 * (less_than[value] + equal_count[value] / 2.0) / total, 2)
        for value in values
    ]


def _url_domain(url: str | None) -> str:
    """从 raw_posts.url 取主机名。只认 http(s)；其它一律视作未知域名。"""

    if not isinstance(url, str) or not url.strip():
        return ""
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"}:
        return ""
    hostname = parsed.hostname or ""
    return hostname.strip().lower().rstrip(".")


def source_authority_score(url: str | None) -> float:
    """来源权威度：中大官方域 > 允许的新闻域 > 其它。

    点边界逻辑（``evil-sysu.edu.cn`` 不能命中 ``sysu.edu.cn``）直接复用
    ``scope_policy._domain_allowed``，不在这里重写一份。
    """

    domain = _url_domain(url)
    if not domain:
        return _AUTHORITY_OTHER
    if _domain_allowed(domain, SYSU_OFFICIAL_DOMAIN_ALLOWLIST):
        return _AUTHORITY_OFFICIAL
    if _domain_allowed(domain, NEWS_DOMAIN_ALLOWLIST):
        return _AUTHORITY_NEWS
    return _AUTHORITY_OTHER


def verification_strength_score(verification_status: str | None) -> float:
    """核验强度：verified > needs_review > 其它（pending/rejected/failed/未知）。"""

    if not isinstance(verification_status, str):
        return _VERIFICATION_DEFAULT
    return _VERIFICATION_WEIGHTS.get(verification_status.strip().lower(), _VERIFICATION_DEFAULT)


def calculate_web_heat_score(
    *,
    url: str | None,
    verification_status: str | None = None,
) -> float:
    """web 证据行的"热度"：来源权威度 + 核验强度（0-100）。

    网页没有点赞/收藏/评论/转发，用 ``calculate_heat_score`` 算出来恒为 0——一条人工
    审核过的中大官方通知会排在任何一条无聊帖子后面。所以 web 的原始热度必须来自别的
    真实信号：**谁发的**（域名）和**核验到什么程度**。

    两个字段都不是凭空造的：``url`` 是 ``raw_posts.url``（交付时写入的 canonical_url），
    ``verification_status`` 由调用方从 ``evidence_items`` 查出（``raw_posts.source_raw_id``
    存着 evidence item 的主键）。见本模块 ``_web_verification_status``。
    """

    return round(
        source_authority_score(url) + verification_strength_score(verification_status),
        2,
    )


def _web_verification_status(db: Session, raw_posts: Iterable[RawPost]) -> dict[int, str]:
    """批量取 web 行对应 evidence_items 的当前 verification_status。

    交付时 ``review_delivery._raw_post_for`` 写了 ``source_table='evidence_items'`` 和
    ``source_raw_id=str(item.id)``——这两个字段是**真实写入**的，所以核验状态可以在这里
    实打实地查出来，不需要给 raw_posts 新增字段、也不需要改交付步骤。

    注意它不是恒等于 "verified"：交付门槛（``eligible_items``）只保证**交付那一刻**是
    verified，之后 ``verify_item`` 仍可能把某条改成 rejected/failed，这里取的是当前值。
    """

    ids: dict[int, int] = {}
    for raw in raw_posts:
        if (raw.source_table or "") != EVIDENCE_SOURCE_TABLE:
            continue
        try:
            ids[raw.id] = int(raw.source_raw_id)
        except (TypeError, ValueError):
            continue
    if not ids:
        return {}

    from backend.models_evidence import EvidenceItem  # 局部导入：避免模块级循环依赖

    rows = (
        db.query(EvidenceItem.id, EvidenceItem.verification_status)
        .filter(EvidenceItem.id.in_(set(ids.values())))
        .all()
    )
    status_by_item = {item_id: status for item_id, status in rows}
    return {
        raw_id: status_by_item[item_id]
        for raw_id, item_id in ids.items()
        if item_id in status_by_item
    }


def refresh_web_heat_scores(db: Session) -> int:
    """给 platform='web' 的 processed_posts 行重算 heat_score（来源权威度 + 核验强度）。

    返回实际改动的行数。只碰 web，其它五个爬虫平台的 heat_score 一个字都不动。
    """

    posts = db.query(ProcessedPost).filter(ProcessedPost.platform == WEB_PLATFORM).all()
    if not posts:
        return 0

    raw_by_id = {post.raw_post_id: post.raw_post for post in posts if post.raw_post is not None}
    status_by_raw_id = _web_verification_status(db, raw_by_id.values())

    changed = 0
    for post in posts:
        raw = raw_by_id.get(post.raw_post_id)
        score = calculate_web_heat_score(
            url=raw.url if raw is not None else "",
            verification_status=status_by_raw_id.get(post.raw_post_id),
        )
        if post.heat_score != score:
            post.heat_score = score
            changed += 1
    return changed


def recompute_heat_ranks(db: Session, platforms: Iterable[str] | None = None) -> int:
    """归一化 pass：按平台把该平台**所有**行的 heat_score 重算成 heat_rank 百分位。

    全量重算（而不是增量更新）：语料一变，每一行的百分位都会变，增量必然漂移。
    331 行的规模下这点成本可以忽略。返回实际改动的行数（重跑一次应当返回 0）。
    """

    query = db.query(ProcessedPost)
    platform_list = [str(item).strip() for item in platforms or [] if str(item).strip()]
    if platform_list:
        query = query.filter(ProcessedPost.platform.in_(platform_list))

    by_platform: dict[str, list[ProcessedPost]] = {}
    for post in query.all():
        by_platform.setdefault(post.platform or "", []).append(post)

    changed = 0
    for posts in by_platform.values():
        ranks = percentile_ranks([post.heat_score or 0.0 for post in posts])
        for post, rank in zip(posts, ranks):
            if post.heat_rank != rank:
                post.heat_rank = rank
                changed += 1
    return changed


__all__ = [
    "WEB_PLATFORM",
    "calculate_web_heat_score",
    "percentile_ranks",
    "recompute_heat_ranks",
    "refresh_web_heat_scores",
    "source_authority_score",
    "verification_strength_score",
]
