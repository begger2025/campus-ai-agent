"""清理与中山大学无关的脏数据（全链路，含原生表与评论）。

## 为什么会有脏数据（2026-07-14 审核，两条实例）

    ① 床垫集采招标广告（weibo，爬于 2026-07-11 02:51）
       蹭校名的地产 B 端营销。拦它的词（集采 / 招标方）**就是 7-11 那天才加进
       TOPIC_NEGATIVE_TERMS 的**——它正是当时发现问题的那条样本。
       过滤器补上了，**存量数据从没回溯清理过**。

    ② 台湾国立中山大学选课（zhihu，爬于 2026-07-11 01:08）
       TOPIC_RELEVANCE_TERMS 里有「中山大学」，而"台湾国立**中山大学**"含这个子串，
       相关性过滤放行。**同名不同校**——词表天生分不开。
       （证据采集那边靠域名白名单正确挡住了 nsysu.edu.tw，爬虫侧的词表挡不住。）

结论：过滤器只管**新爬取**。存量要靠这个脚本回溯清。

## 纪律

**默认干跑，不写库。** 预览 → 人工确认 → `--apply` → 幂等复跑验证。
删共享库前必须先查外键牵连（历史教训：event_review_logs 曾挡下一次删除，
事务自动回滚，库没坏）。

    python scripts/purge_offtopic_posts.py            # 干跑预览
    python scripts/purge_offtopic_posts.py --apply    # 真删
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from backend.database import SessionLocal  # noqa: E402


# 要清理的 processed_posts.id。**写死 ID 而不是写死匹配规则**：
# 规则匹配会误删（"招标"可能出现在真实的校园吐槽里），而人工确认过的 ID 不会。
# 新发现的脏数据往这里加，每次都要人工过目。
TARGET_PROCESSED_IDS = [
    283,  # 台湾国立中山大学有什么最值得选的课程推荐？（zhihu · 同名不同校）
    287,  # 酒店/地产/床垫集采避坑…（weibo · 蹭校名的 B 端招标广告）
]

# 原生爬虫表：processed → raw → 原生表。note_id 带平台前缀（"zhihu:xxx"），原生表是裸 ID。
NATIVE_SPEC = {
    "zhihu": [("zhihu_content", "content_id"), ("zhihu_comment", "content_id")],
    "weibo": [("weibo_note", "note_id"), ("weibo_note_comment", "note_id")],
    "xhs": [("xhs_note", "note_id"), ("xhs_note_comment", "note_id")],
    "ks": [("kuaishou_video", "video_id"), ("kuaishou_video_comment", "video_id")],
    "tieba": [("tieba_note", "note_id"), ("tieba_comment", "note_id")],
}


def bare(note_id: str) -> str:
    return (note_id or "").split(":", 1)[-1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正执行删除（默认只干跑）")
    parser.add_argument(
        "--backup",
        default="data/backup_offtopic_posts.json",
        help="删除前把整行备份到这里（可回滚）",
    )
    args = parser.parse_args()

    db = SessionLocal()
    plan: dict = {"targets": [], "deletes": {}, "blocked": []}
    try:
        rows = db.execute(
            text(
                "SELECT p.id, p.raw_post_id, p.platform, p.note_id, p.title "
                "FROM processed_posts p WHERE p.id IN :ids"
            ),
            {"ids": tuple(TARGET_PROCESSED_IDS)},
        ).fetchall()

        if not rows:
            print("目标帖子已不存在（可能已经清理过）——幂等，无事可做。")
            return

        raw_ids = []
        for pid, raw_id, platform, note_id, title in rows:
            plan["targets"].append(
                {
                    "processed_id": pid,
                    "raw_post_id": raw_id,
                    "platform": platform,
                    "note_id": note_id,
                    "bare_id": bare(note_id),
                    "title": (title or "")[:60],
                }
            )
            if raw_id:
                raw_ids.append(raw_id)

        pids = tuple(t["processed_id"] for t in plan["targets"])

        # —— 外键牵连体检：删之前先看谁在引用它们 ——
        n_links = db.execute(
            text("SELECT COUNT(*) FROM event_post_links WHERE processed_post_id IN :ids"),
            {"ids": pids},
        ).scalar()
        plan["deletes"]["event_post_links"] = n_links

        n_src = db.execute(
            text("SELECT COUNT(*) FROM public_events WHERE source_post_id IN :ids"),
            {"ids": pids},
        ).scalar()
        if n_src:
            # 事件把它当头帖——不能直接删，会留下悬挂引用。人工先处理事件。
            plan["blocked"].append(
                f"public_events.source_post_id 引用了 {n_src} 次：先处理这些事件再删帖子"
            )

        plan["deletes"]["processed_posts"] = len(pids)
        plan["deletes"]["raw_posts"] = len(raw_ids)

        # 原生表 + 评论
        for target in plan["targets"]:
            for table, col in NATIVE_SPEC.get(target["platform"], []):
                try:
                    n = db.execute(
                        text(f"SELECT COUNT(*) FROM {table} WHERE {col} = :v"),
                        {"v": target["bare_id"]},
                    ).scalar()
                except Exception as exc:  # 表不存在等
                    plan["blocked"].append(f"{table} 查询失败（跳过）：{type(exc).__name__}")
                    continue
                if n:
                    plan["deletes"][table] = plan["deletes"].get(table, 0) + n

        print(json.dumps(plan, ensure_ascii=False, indent=2))

        if plan["blocked"]:
            print("\n⚠️  有阻塞项，未执行任何删除：")
            for item in plan["blocked"]:
                print(f"   - {item}")
            return

        if not args.apply:
            print("\nDRY-RUN：未写入任何内容。确认无误后加 --apply 真正执行。")
            return

        # —— 删之前先备份整行：共享库的删除必须可回滚 ——
        backup: dict = {"processed_posts": [], "raw_posts": []}
        for row in db.execute(
            text("SELECT * FROM processed_posts WHERE id IN :ids"), {"ids": pids}
        ).mappings():
            backup["processed_posts"].append({k: str(v) for k, v in row.items()})
        if raw_ids:
            for row in db.execute(
                text("SELECT * FROM raw_posts WHERE id IN :ids"), {"ids": tuple(raw_ids)}
            ).mappings():
                backup["raw_posts"].append({k: str(v) for k, v in row.items()})
        backup_path = Path(args.backup)
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已备份被删行 -> {backup_path}")

        # —— 执行：从叶子往根删，一个事务包住 ——
        for target in plan["targets"]:
            for table, col in NATIVE_SPEC.get(target["platform"], []):
                db.execute(
                    text(f"DELETE FROM {table} WHERE {col} = :v"), {"v": target["bare_id"]}
                )
        db.execute(
            text("DELETE FROM event_post_links WHERE processed_post_id IN :ids"), {"ids": pids}
        )
        db.execute(text("DELETE FROM processed_posts WHERE id IN :ids"), {"ids": pids})
        if raw_ids:
            db.execute(
                text("DELETE FROM raw_posts WHERE id IN :ids"), {"ids": tuple(raw_ids)}
            )
        db.commit()

        left = db.execute(
            text("SELECT COUNT(*) FROM processed_posts WHERE id IN :ids"), {"ids": pids}
        ).scalar()
        total = db.execute(text("SELECT COUNT(*) FROM processed_posts")).scalar()
        print(f"\n已执行。目标残留 {left} 条（应为 0）；processed_posts 现有 {total} 条。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
