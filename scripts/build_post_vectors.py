"""离线构建帖子向量：processed_posts（未剔除）→ data/post_vectors.npz。

舆情助手帖子层语义检索的物料（见 backend/services/semantic_posts.py）。
**每轮爬取入库（sync → process）之后跑一次**；两轮之间的新帖只是暂时没有
语义覆盖，字面检索照常。全量重建、幂等：几百到几千条语料就是几秒到几十秒，
不值得为增量引入状态。

只读数据库；唯一的写出是本地 npz 文件（不进 git，见 .gitignore）。

    .venv/Scripts/python.exe scripts/build_post_vectors.py
    .venv/Scripts/python.exe scripts/build_post_vectors.py --probe "饭堂涨价"  # 顺手看某个查询的分数形状
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from backend.database import SessionLocal  # noqa: E402
from backend.models import ProcessedPost  # noqa: E402
from backend.services.embedding import get_embedder  # noqa: E402


OUT_PATH = ROOT / "data" / "post_vectors.npz"

# 标题是最强的话题信号，正文截前 256 字补语境——再长的正文对"这帖在讲什么"
# 的增益极小，还会稀释向量。
CONTENT_CHARS = 256
BATCH = 64


def post_text(title: str, content: str) -> str:
    return f"{title or ''}\n{(content or '')[:CONTENT_CHARS]}".strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="构建帖子语义向量")
    parser.add_argument("--probe", default="", help="构建后顺手打印该查询的 top-10 分数形状")
    args = parser.parse_args()

    embedder = get_embedder()
    if embedder is None:
        print("sentence-transformers 未安装或 EMBEDDING_ENABLED=false，无事可做（检索会退回纯字面）")
        return 1

    import numpy as np

    db = SessionLocal()
    try:
        rows = (
            db.query(ProcessedPost.id, ProcessedPost.title, ProcessedPost.content)
            .filter(ProcessedPost.excluded.is_(False))  # 剔除切断所有下游，包括语义索引
            .order_by(ProcessedPost.id)
            .all()
        )
    finally:
        db.close()
    if not rows:
        print("processed_posts 为空，不写文件")
        return 1

    started = time.perf_counter()
    ids = [row.id for row in rows]
    vectors: list[list[float]] = []
    for offset in range(0, len(rows), BATCH):
        batch = rows[offset : offset + BATCH]
        vectors.extend(embedder([post_text(row.title, row.content) for row in batch]))
        print(f"  embed {min(offset + BATCH, len(rows))}/{len(rows)}", end="\r")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        OUT_PATH,
        ids=np.array(ids, dtype=np.int64),
        vectors=np.array(vectors, dtype=np.float32),
    )
    seconds = time.perf_counter() - started
    print(f"\n已写 {OUT_PATH.name}：{len(ids)} 条 × {len(vectors[0])} 维，{seconds:.1f}s")

    if args.probe:
        from backend.services.semantic_posts import reset_vector_cache, top_ids_by_cosine

        reset_vector_cache()
        matrix = np.array(vectors, dtype=np.float32)
        query_vector = np.array(embedder([args.probe])[0], dtype=np.float32)
        scores = matrix @ query_vector
        order = np.argsort(scores)[::-1][:10]
        title_by_id = {row.id: (row.title or "")[:24] for row in rows}
        print(f"probe「{args.probe}」top-10：")
        for i in order:
            print(f"  {scores[i]:.3f}  #{ids[i]}  {title_by_id[ids[i]]}")
        _ = top_ids_by_cosine  # 提醒：线上取数走 semantic_posts，阈值见那边
    return 0


if __name__ == "__main__":
    sys.exit(main())
