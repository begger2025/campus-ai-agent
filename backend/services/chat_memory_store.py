"""会话记忆的本地持久层：进程内字典的写穿备份（stdlib sqlite3，不碰共享库）。

进程内记忆（opinion_chat_service 的三个字典）重启即失忆——用户聊到一半重启
服务，下一句追问就答非所问。这里做写穿：每轮落一行本地 SQLite，进程字典
miss 时水合回来。

刻意的边界：
- **本地文件**（data/chat_memory.sqlite3），绝不写共享 MySQL——会话记忆是
  单机部署的运行时状态，不是业务数据；多 worker 部署时再换 Redis。
- TTL 24 小时：舆情对话没有隔周续聊的语境，过期即弃。
- 所有操作 try/except 吞错：持久层坏了顶多退回"重启失忆"的老行为，
  绝不让对话报错。
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path


logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DEFAULT_TTL_HOURS = 24.0


def _db_path() -> Path:
    return Path(os.getenv("CHAT_MEMORY_DB_PATH") or (_DATA_DIR / "chat_memory.sqlite3"))


def _ttl_seconds() -> float:
    return float(os.getenv("CHAT_MEMORY_TTL_HOURS") or DEFAULT_TTL_HOURS) * 3600.0


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS chat_memory ("
        "user_id TEXT PRIMARY KEY, last_keyword TEXT, last_intent TEXT, "
        "history_json TEXT, topic_trail_json TEXT, updated_at REAL)"
    )
    return conn


def save(user_id: str, *, last_keyword: str, last_intent: str, history: list, topic_trail: list) -> None:
    if not user_id:
        return
    try:
        # closing 必须有：sqlite3 的 with 只管事务提交，不关连接——
        # Windows 上文件被锁住删不掉，长进程里则是连接泄漏。
        with closing(_connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO chat_memory VALUES (?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    last_keyword,
                    last_intent,
                    json.dumps(list(history), ensure_ascii=False),
                    json.dumps(list(topic_trail), ensure_ascii=False),
                    time.time(),
                ),
            )
    except Exception as exc:
        logger.warning("chat memory save failed (%s); in-process memory still works", exc)


def load(user_id: str) -> dict | None:
    """{last_keyword, last_intent, history, topic_trail} 或 None（无记录/过期/持久层故障）。"""

    if not user_id:
        return None
    try:
        with closing(_connect()) as conn:
            row = conn.execute(
                "SELECT last_keyword, last_intent, history_json, topic_trail_json, updated_at "
                "FROM chat_memory WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        if time.time() - float(row[4] or 0) > _ttl_seconds():
            clear(user_id)  # 过期即弃：舆情对话没有隔周续聊的语境
            return None
        return {
            "last_keyword": row[0] or "",
            "last_intent": row[1] or "",
            "history": [tuple(item) for item in json.loads(row[2] or "[]")],
            "topic_trail": list(json.loads(row[3] or "[]")),
        }
    except Exception as exc:
        logger.warning("chat memory load failed (%s); degrade to process memory", exc)
        return None


def clear(user_id: str) -> None:
    if not user_id:
        return
    try:
        with closing(_connect()) as conn, conn:
            conn.execute("DELETE FROM chat_memory WHERE user_id = ?", (user_id,))
    except Exception:
        pass


def clear_all() -> None:
    """清空全部持久记忆（reset_chat_memory / 测试隔离用）。"""

    try:
        with closing(_connect()) as conn, conn:
            conn.execute("DELETE FROM chat_memory")
    except Exception:
        pass
