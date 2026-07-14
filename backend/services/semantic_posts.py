"""帖子层语义检索：离线算好的帖子向量 + 在线一次查询 embed + 暴力余弦。

LIKE 的死穴是改写说法：「饭堂涨价」搜不到「食堂调价」，「宿舍太吵」搜不到
「半夜宿舍楼道有噪音」。事件层早有语义兜底（标题匹配，见 event_read_model），
帖子层一直是裸的——而帖子层恰恰是没有已发布事件的话题的唯一出路。

规模判断：语料几百到几千条，bge-small-zh 512 维，暴力点积毫秒级——
不需要向量库，一个 npz 文件 + numpy 足够（到 5 万条之前都不用换）。

    离线：scripts/build_post_vectors.py 全量重建 data/post_vectors.npz
          （每轮爬取入库后跑一次；两轮之间的新帖只是暂时没有语义覆盖，
          字面检索照常，不影响正确性）
    在线：semantic_post_ids(query) → 阈值之上按相似度排序的 processed_post_id

降级语义（任何一环失败都返回空 → 调用方退回纯字面检索，绝不报错）：
向量文件缺失 / sentence-transformers 未装 / 模型抛异常。

阈值是防语义假阳性的唯一闸门（本功能仅有的发散风险）：阈值之下宁可漏，
不能把不相关的帖捞进 prompt——那是静默错误答案。默认值来自真库实测
（见 POST_SEMANTIC_THRESHOLD 的注释），可用环境变量热调。
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from backend.services.embedding import get_embedder


logger = logging.getLogger(__name__)

# 真库实测（2026-07-15，406 条语料）的分数形状：
#   真改写命中：  饭堂涨价→食堂价格帖 0.603/0.607/0.634；宿舍太吵→搬宿舍 0.587
#   假阳性：      校车预约→升学宴/参观攻略 0.576/0.546（语料里没有校车帖）
#   域外：        写一首爱情诗 ≤0.503；股票行情 ≤0.441；操场翻新 ≤0.425
# 两档阈值 = 孤证从严：字面有命中时语义只是补充（0.55，有佐证兜底）；
# 字面零命中时语义要独自作证（0.60，卡在真改写 0.60+ 与假阳性 ≤0.587 之间）。
# 语料变大后建议用 build 脚本的 --probe 重扫再调（环境变量可热调）。
DEFAULT_THRESHOLD = 0.55
ALONE_THRESHOLD = 0.60
DEFAULT_TOP_K = 30

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# (mtime, ids, matrix) —— 文件不大，进程内整份缓存；mtime 变了自动重载。
_cache: tuple[float, object, object] | None = None
_cache_lock = threading.Lock()


def _vectors_path() -> Path:
    return Path(os.getenv("POST_VECTORS_PATH") or (_DATA_DIR / "post_vectors.npz"))


def reset_vector_cache() -> None:
    global _cache
    with _cache_lock:
        _cache = None


def _load_vectors():
    """(ids, matrix) 或 None。mtime 缓存：重建向量文件后不用重启服务。"""

    global _cache
    path = _vectors_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    with _cache_lock:
        if _cache is not None and _cache[0] == mtime:
            return _cache[1], _cache[2]
    try:
        import numpy as np

        data = np.load(path)
        ids, matrix = data["ids"], data["vectors"]
    except Exception as exc:
        logger.warning("post vectors unreadable (%s); semantic posts degrade to literal", exc)
        return None
    with _cache_lock:
        _cache = (mtime, ids, matrix)
    return ids, matrix


def top_ids_by_cosine(matrix, ids, query_vector, *, top_k: int, threshold: float) -> list[int]:
    """阈值之上、按余弦从高到低的 id。向量已归一化，余弦 == 点积。"""

    import numpy as np

    scores = matrix @ np.asarray(query_vector, dtype=matrix.dtype)
    order = np.argsort(scores)[::-1][: max(top_k, 0)]
    return [int(ids[i]) for i in order if float(scores[i]) >= threshold]


def semantic_post_ids(
    query: str,
    *,
    top_k: int | None = None,
    threshold: float | None = None,
    corroborated: bool = True,
) -> list[int]:
    """查询 → 语义相似的 processed_post_id（阈值之上，按相似度降序）。

    ``corroborated=False`` = 字面检索零命中、语义在孤证作答——用更严的阈值
    （见文件头的实测形状：孤证放行 0.55 会把「校车预约」答成升学宴）。
    """

    query = (query or "").strip()
    if not query:
        return []
    embedder = get_embedder()
    if embedder is None:
        return []
    loaded = _load_vectors()
    if loaded is None:
        return []
    ids, matrix = loaded
    if top_k is None:
        top_k = int(os.getenv("POST_SEMANTIC_TOP_K") or DEFAULT_TOP_K)
    if threshold is None:
        threshold = (
            float(os.getenv("POST_SEMANTIC_THRESHOLD") or DEFAULT_THRESHOLD)
            if corroborated
            else float(os.getenv("POST_SEMANTIC_THRESHOLD_ALONE") or ALONE_THRESHOLD)
        )
    try:
        query_vector = embedder([query])[0]
        return top_ids_by_cosine(matrix, ids, query_vector, top_k=top_k, threshold=threshold)
    except Exception as exc:
        logger.warning("semantic post search failed (%s); degrade to literal", exc)
        return []
