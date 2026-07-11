# 分布式协同爬取 + 限速抖动 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 N 名成员在各自电脑同时跑爬虫、通过共享 MySQL 的认领队列自动分工爬互不重叠的关键词，写共享库不冲突不重复；并把固定限速间隔改为随机抖动以降低风控指纹。

**Architecture:** 共享库建 `crawl_task_queue` 任务表；MediaCrawler 侧新增队列认领模块（乐观条件更新 + 租约，版本无关）与队列驱动循环（登录一次后循环认领关键词调既有 `search()`）；主项目侧三个 CLI 脚本播种/监控/重置。抖动为一个 `utils` helper 替换五平台固定 sleep。设计文档：`docs/superpowers/specs/2026-07-11-distributed-crawl-design.md`。

**Tech Stack:** Python（SQLAlchemy async/sync、pytest、unittest、Typer CLI）、MySQL（阿里云共享 RDS）。

---

## 环境与纪律（每个任务开始前先读）

- 仓库根：`D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main`（下文 `<ROOT>`）。命令用 PowerShell。
- **两个 venv**：
  - MediaCrawler 测试：`cd "<ROOT>\MediaCrawler"; .\.venv\Scripts\python.exe -m pytest tests -q`
    基线：**154 passed + 1 failed**（`test_store_factory.py::TestXhsStoreFactory::test_create_excel_store` 是既有失败，不许修、不许弄丢这个认知）。
  - 主项目测试：`cd "<ROOT>"; $env:PYTHONIOENCODING="utf-8"; .\.venv\Scripts\python.exe -m unittest discover -s backend/tests -t . -q`
    基线：**202 tests OK**。
- **冒烟配置纪律**：`MediaCrawler/config/base_config.py` 工作区有两处**未提交**的本地调参（`CDP_CONNECT_EXISTING=False`、`CRAWLER_MAX_NOTES_COUNT=40`），**绝不能进任何提交**。凡要提交该文件的任务（Task 6、Task 8）必须走 stash 舞步（见任务内步骤）。其余任务只 `git add <明确路径>`，永不用 `git add -A`/`git add .`。
- 工作分支：`feature/distributed-crawl`（Task 1 创建，Task 12 ff 合回 main 后删除）。
- TDD 铁律：先写测试看 RED（原因正确），再写最小实现看 GREEN。失败原因不对（import 错误等）先修再继续。
- **不连真实数据库**：所有单测用 mock session / sqlite 内存库；迁移脚本除 `--dry-run` 外一律不在实现期跑（线上执行留到 Task 13 由协调者带用户确认）。

## 文件结构总览

| 文件 | 动作 | 职责 |
|---|---|---|
| `MediaCrawler/database/models.py` | 改 | 新增 `CrawlTaskQueue` 模型 |
| `MediaCrawler/config/base_config.py` | 改 | 队列/抖动配置项（stash 舞步） |
| `MediaCrawler/store/crawl_queue.py` | 新建 | 认领/完成/租约回收/结果回填（异步、raw SQL、优雅降级） |
| `MediaCrawler/tools/crawl_queue_runner.py` | 新建 | 队列驱动循环 `run_keyword_queue(crawler)` |
| `MediaCrawler/tools/utils.py` | 改 | 抖动 helper `random_crawl_sleep()` |
| `MediaCrawler/cmd_arg/arg.py` | 改 | `--from-queue` / `--worker` 两个 CLI 选项 |
| `MediaCrawler/media_platform/{xhs,weibo,tieba,zhihu,kuaishou}/core.py` | 改 | start() 队列分支 + 抖动替换 |
| `MediaCrawler/tests/test_crawl_queue.py` | 新建 | 认领/完成/回填 mock 测试 |
| `MediaCrawler/tests/test_crawl_queue_runner.py` | 新建 | 队列驱动循环 fake 测试 |
| `MediaCrawler/tests/test_random_crawl_sleep.py` | 新建 | 抖动区间/回退测试 |
| `scripts/create_crawl_task_queue.py` | 新建 | 建表迁移（幂等、dry-run） |
| `scripts/seed_crawl_queue.py` | 新建 | 双来源播种 |
| `scripts/crawl_queue_status.py` | 新建 | 监控汇总 |
| `scripts/reset_crawl_queue.py` | 新建 | 重置/回收 |
| `backend/tests/test_create_crawl_task_queue.py` | 新建 | 建表脚本纯逻辑 |
| `backend/tests/test_seed_crawl_queue.py` | 新建 | 播种去重/笛卡尔积纯逻辑 |
| `backend/tests/test_crawl_queue_scripts.py` | 新建 | 监控汇总 + 重置目标选择纯逻辑 |
| `MediaCrawler/tools/db_retry.py` | 新建（Task 14，可选尾） | 死锁重试 helper |

---

### Task 1: 建分支与基线确认

**Files:** 无代码改动。

- [ ] **Step 1: 确认工作树并建分支**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
git status --short   # 预期仅 M MediaCrawler/config/base_config.py + 未跟踪 docs 文件
git checkout -b feature/distributed-crawl
```

- [ ] **Step 2: 跑双侧基线**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\MediaCrawler"
.\.venv\Scripts\python.exe -m pytest tests -q
```
Expected: `1 failed, 154 passed`（失败=excel 既有）。

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -t . -q
```
Expected: `Ran 202 tests ... OK`。基线不符先停下报告。

---

### Task 2: CrawlTaskQueue 模型 + 建表迁移脚本

**Files:**
- Modify: `MediaCrawler/database/models.py`（新增类 + 确保 `Index` 已导入）
- Create: `scripts/create_crawl_task_queue.py`
- Test: `backend/tests/test_create_crawl_task_queue.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_create_crawl_task_queue.py`：

```python
"""create_crawl_task_queue 纯逻辑测试：建表/跳过计划（不连库）。"""

import unittest

from scripts.create_crawl_task_queue import CREATE_DDL, TABLE, plan_actions


class PlanActionsTests(unittest.TestCase):
    def test_table_constant(self):
        self.assertEqual(TABLE, "crawl_task_queue")

    def test_missing_table_planned_create(self):
        plans = plan_actions(existing_tables=set())
        self.assertEqual([(p.table, p.action) for p in plans], [("crawl_task_queue", "create")])

    def test_existing_table_skipped(self):
        plans = plan_actions(existing_tables={"crawl_task_queue"})
        self.assertEqual([(p.table, p.action) for p in plans], [("crawl_task_queue", "skip_exists")])


class DdlTests(unittest.TestCase):
    def test_ddl_columns_in_order(self):
        cols = [
            "id", "platform", "keyword", "status", "priority", "claimed_by",
            "claimed_at", "lease_expires_at", "finished_at", "items_stored",
            "stop_reason", "created_at",
        ]
        last = -1
        for col in cols:
            pos = CREATE_DDL.find(col)
            self.assertGreater(pos, last, f"列 {col} 缺失或顺序错")
            last = pos

    def test_ddl_index_and_engine(self):
        self.assertIn("INDEX ix_crawl_task_queue_platform_status (platform, status)", CREATE_DDL)
        self.assertIn("ENGINE=InnoDB DEFAULT CHARSET=utf8mb4", CREATE_DDL)
        self.assertIn("PRIMARY KEY (id)", CREATE_DDL)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe -m unittest backend.tests.test_create_crawl_task_queue -v
```
Expected: `ModuleNotFoundError: No module named 'scripts.create_crawl_task_queue'`。

- [ ] **Step 3: 新增模型**

`MediaCrawler/database/models.py`：先确认文件顶部 sqlalchemy 导入是否含 `Index`。若无，在 `from sqlalchemy import (...)` 中加入 `Index`。然后在 `CrawlerRunHistory` 类之后新增：

```python
class CrawlTaskQueue(Base):
    """分布式协同爬取任务队列：任务 =（平台, 裸关键词）。乐观条件更新认领，租约防卡死。"""
    __tablename__ = 'crawl_task_queue'
    id = Column(Integer, primary_key=True, comment='主键ID')
    platform = Column(String(16), comment='平台码 xhs/wb/tieba/zhihu/ks')
    keyword = Column(String(255), comment='裸关键词')
    status = Column(String(16), default='pending', comment='pending/claimed/done/failed')
    priority = Column(Integer, default=0, comment='优先级，大者优先')
    claimed_by = Column(String(64), comment='认领 worker id')
    claimed_at = Column(BigInteger, comment='认领时间戳(ms)')
    lease_expires_at = Column(BigInteger, comment='租约到期(ms)')
    finished_at = Column(BigInteger, comment='完成时间戳(ms)')
    items_stored = Column(Integer, default=0, comment='新增入库条数')
    stop_reason = Column(String(32), comment='停止原因')
    created_at = Column(BigInteger, comment='播种时间戳(ms)')
    __table_args__ = (
        Index('ix_crawl_task_queue_platform_status', 'platform', 'status'),
    )
```

- [ ] **Step 4: 新建 create_crawl_task_queue.py**

参照 `scripts/create_ks_tables.py` 的结构（plan/apply 分离、--dry-run、退出码），单表、只有 create/skip：

```python
"""共享 MySQL 建 crawl_task_queue 分布式爬取任务队列表（幂等，plan/apply）。

用法：.venv/Scripts/python.exe scripts/create_crawl_task_queue.py [--dry-run]

DDL 与 MediaCrawler/database/models.py::CrawlTaskQueue 逐列一致（utf8mb4、InnoDB）。
结构照抄 scripts/create_ks_tables.py。设计见
docs/superpowers/specs/2026-07-11-distributed-crawl-design.md §2。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Sequence, Set

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from sqlalchemy import inspect, text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from backend.database import engine  # noqa: E402

TABLE = "crawl_task_queue"

CREATE_DDL = """\
CREATE TABLE crawl_task_queue (
    id INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    platform VARCHAR(16) COMMENT '平台码 xhs/wb/tieba/zhihu/ks',
    keyword VARCHAR(255) COMMENT '裸关键词',
    status VARCHAR(16) DEFAULT 'pending' COMMENT 'pending/claimed/done/failed',
    priority INT DEFAULT 0 COMMENT '优先级，大者优先',
    claimed_by VARCHAR(64) COMMENT '认领 worker id',
    claimed_at BIGINT COMMENT '认领时间戳(ms)',
    lease_expires_at BIGINT COMMENT '租约到期(ms)',
    finished_at BIGINT COMMENT '完成时间戳(ms)',
    items_stored INT DEFAULT 0 COMMENT '新增入库条数',
    stop_reason VARCHAR(32) COMMENT '停止原因',
    created_at BIGINT COMMENT '播种时间戳(ms)',
    PRIMARY KEY (id),
    INDEX ix_crawl_task_queue_platform_status (platform, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='分布式协同爬取任务队列'"""


@dataclass
class TablePlan:
    table: str
    action: str  # "create" | "skip_exists"


def plan_actions(existing_tables: Set[str], tables: Iterable[str] = (TABLE,)) -> List[TablePlan]:
    """纯逻辑：给定现有表名快照决定动作。不触碰真实 DB。"""
    plans: List[TablePlan] = []
    for table in tables:
        plans.append(TablePlan(table, "skip_exists" if table in existing_tables else "create"))
    return plans


@dataclass
class ApplyOutcome:
    plan: TablePlan
    status: str  # "created" | "would_create" | "skipped" | "failed"
    error: str = ""


def apply_plans(plans: List[TablePlan], apply_fn: Callable[[TablePlan], None], dry_run: bool = False) -> List[ApplyOutcome]:
    outcomes: List[ApplyOutcome] = []
    for plan in plans:
        if plan.action == "skip_exists":
            outcomes.append(ApplyOutcome(plan, "skipped"))
        elif plan.action == "create":
            if dry_run:
                outcomes.append(ApplyOutcome(plan, "would_create"))
                continue
            try:
                apply_fn(plan)
            except SQLAlchemyError as exc:
                outcomes.append(ApplyOutcome(plan, "failed", error=str(exc)))
            else:
                outcomes.append(ApplyOutcome(plan, "created"))
        else:
            raise ValueError(f"未知 action: {plan.action}")
    return outcomes


def exit_code_for(outcomes: List[ApplyOutcome]) -> int:
    return 1 if any(o.status == "failed" for o in outcomes) else 0


def _apply_ddl(plan: TablePlan) -> None:
    print(f"执行: CREATE TABLE {plan.table} ...")
    with engine.begin() as conn:
        conn.execute(text(CREATE_DDL))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="共享 MySQL 建 crawl_task_queue（幂等）")
    parser.add_argument("--dry-run", action="store_true", help="只打印 DDL，不建表")
    args = parser.parse_args(argv)

    existing_tables = set(inspect(engine).get_table_names())
    plans = plan_actions(existing_tables)

    for plan in plans:
        if plan.action == "skip_exists":
            print(f"[跳过] {plan.table}: 表已存在，跳过（幂等）")
        elif args.dry_run:
            print(f"[dry-run] 将执行:\n{CREATE_DDL}")

    outcomes = apply_plans(plans, _apply_ddl, dry_run=args.dry_run)
    for outcome in outcomes:
        if outcome.status == "failed":
            print(f"[失败] {outcome.plan.table}: {outcome.error}")

    counts = {}
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    print(f"完成：{counts}")
    return exit_code_for(outcomes)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 跑测试 GREEN + 主项目全量**

```powershell
.\.venv\Scripts\python.exe -m unittest backend.tests.test_create_crawl_task_queue -v
$env:PYTHONIOENCODING="utf-8"; .\.venv\Scripts\python.exe -m unittest discover -s backend/tests -t . -q
```
Expected: 新测试 5 passed；全量 `Ran 207 tests OK`（202 + 5）。

- [ ] **Step 6: 验证模型导入不破坏 MediaCrawler**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\MediaCrawler"
.\.venv\Scripts\python.exe -c "from database.models import CrawlTaskQueue; print(CrawlTaskQueue.__tablename__)"
```
Expected: 打印 `crawl_task_queue`，无 ImportError。

- [ ] **Step 7: 提交**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
git add MediaCrawler/database/models.py scripts/create_crawl_task_queue.py backend/tests/test_create_crawl_task_queue.py
git commit -m "feat(queue): CrawlTaskQueue 模型 + 建表迁移脚本"
```

---

### Task 3: 队列认领模块 store/crawl_queue.py

**Files:**
- Create: `MediaCrawler/store/crawl_queue.py`
- Test: `MediaCrawler/tests/test_crawl_queue.py`（新建）

**接口契约（后续 Task 4 依赖，签名固定；已含多成员同平台正确性修正）：**
- `async claim_task(platform: str, worker_id: str) -> Optional[dict]` → `{"id": int, "keyword": str}` 或 None
- `async complete_task(task_id: int, worker_id: str, status: str, items_stored: int, stop_reason: str) -> None`
  （`WHERE id=? AND claimed_by=worker_id` 持有者守卫，租约被回收后本 worker 的迟到完成被拒绝并告警）
- `async max_run_history_id(platform: str) -> int`
- `async run_history_delta(platform: str, before_id: int, source_keyword: str) -> tuple[int, str]`
  （按 `source_keyword` 过滤，避免多成员同平台并发把别的 worker 的 run_history 行算进本任务统计）

- [ ] **Step 1: 写失败测试**

新建 `MediaCrawler/tests/test_crawl_queue.py`：

```python
# -*- coding: utf-8 -*-
"""队列认领模块 mock 测试：乐观条件更新竞态、租约回收、重试耗尽、结果回填、降级。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

import config
from store import crawl_queue


def _fake_get_session_factory(session):
    @asynccontextmanager
    async def _fake_get_session():
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
    return _fake_get_session


def _result(*, first=None, scalar=None, all_rows=None, rowcount=0):
    r = MagicMock(name="result")
    r.first.return_value = first
    r.scalar.return_value = scalar
    r.all.return_value = all_rows or []
    r.rowcount = rowcount
    return r


@pytest.fixture(autouse=True)
def _db_mode(monkeypatch):
    monkeypatch.setattr(config, "SAVE_DATA_OPTION", "db")
    monkeypatch.setattr(config, "CRAWL_QUEUE_LEASE_SEC", 1800, raising=False)
    monkeypatch.setattr(config, "CRAWL_QUEUE_CLAIM_RETRY", 5, raising=False)


@pytest.mark.asyncio
async def test_claim_success_first_candidate(monkeypatch):
    session = MagicMock()
    session.rollback = AsyncMock()
    session.commit = AsyncMock()
    # execute 序列：回收租约(update) → 选候选(select) → 条件认领(update rowcount=1)
    session.execute = AsyncMock(side_effect=[
        _result(rowcount=0),                       # reclaim
        _result(first=(7, "宿舍")),                # candidate
        _result(rowcount=1),                       # claim success
    ])
    monkeypatch.setattr("store.crawl_queue.get_session", _fake_get_session_factory(session))

    task = await crawl_queue.claim_task("ks", "worker-A")

    assert task == {"id": 7, "keyword": "宿舍"}


@pytest.mark.asyncio
async def test_claim_retries_when_first_candidate_taken(monkeypatch):
    session = MagicMock()
    session.rollback = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        _result(rowcount=0),                       # reclaim
        _result(first=(7, "宿舍")),                # candidate 1
        _result(rowcount=0),                       # claim 1 lost (someone else)
        _result(first=(8, "食堂")),                # candidate 2
        _result(rowcount=1),                       # claim 2 success
    ])
    monkeypatch.setattr("store.crawl_queue.get_session", _fake_get_session_factory(session))

    task = await crawl_queue.claim_task("ks", "worker-A")

    assert task == {"id": 8, "keyword": "食堂"}


@pytest.mark.asyncio
async def test_claim_returns_none_when_queue_empty(monkeypatch):
    session = MagicMock()
    session.rollback = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        _result(rowcount=0),                       # reclaim
        _result(first=None),                       # no candidate
    ])
    monkeypatch.setattr("store.crawl_queue.get_session", _fake_get_session_factory(session))

    assert await crawl_queue.claim_task("ks", "worker-A") is None


@pytest.mark.asyncio
async def test_claim_degrades_for_non_db_backend(monkeypatch):
    monkeypatch.setattr(config, "SAVE_DATA_OPTION", "json")
    # 不应触碰 get_session
    monkeypatch.setattr("store.crawl_queue.get_session",
                        _fake_get_session_factory(MagicMock(execute=AsyncMock(side_effect=AssertionError))))
    assert await crawl_queue.claim_task("ks", "worker-A") is None


@pytest.mark.asyncio
async def test_complete_task_updates_row(monkeypatch):
    session = MagicMock()
    session.rollback = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(return_value=_result(rowcount=1))
    monkeypatch.setattr("store.crawl_queue.get_session", _fake_get_session_factory(session))

    await crawl_queue.complete_task(7, "done", 12, "quota_reached")

    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_history_delta_sums_new_rows(monkeypatch):
    session = MagicMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock(return_value=_result(all_rows=[(5, "completed"), (7, "quota_reached")]))
    monkeypatch.setattr("store.crawl_queue.get_session", _fake_get_session_factory(session))

    total, reason = await crawl_queue.run_history_delta("ks", before_id=10)

    assert total == 12
    assert reason == "quota_reached"  # 取新增行里最后一行的 stop_reason


@pytest.mark.asyncio
async def test_run_history_delta_no_new_rows_returns_skipped(monkeypatch):
    session = MagicMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock(return_value=_result(all_rows=[]))
    monkeypatch.setattr("store.crawl_queue.get_session", _fake_get_session_factory(session))

    total, reason = await crawl_queue.run_history_delta("ks", before_id=10)

    assert total == 0
    assert reason == "skipped"
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\MediaCrawler"
.\.venv\Scripts\python.exe -m pytest tests/test_crawl_queue.py -v
```
Expected: `ModuleNotFoundError: No module named 'store.crawl_queue'`。

- [ ] **Step 3: 实现 store/crawl_queue.py**

```python
# -*- coding: utf-8 -*-
"""分布式协同爬取：任务队列的认领/完成/租约回收/结果回填（异步、raw SQL）。

并发正确性核心：认领用"乐观条件更新"——SELECT 一个 pending 候选，再
`UPDATE ... WHERE id=? AND status='pending'`，受影响行数==1 才算抢到；否则换候选重试。
行级条件 UPDATE 的 status 守卫保证两台机器绝不认领同一行，无需 8.0 专属的 SKIP LOCKED。
非 db 系存储优雅降级（claim 返回 None、complete no-op），保证队列模式在本地文件配置下不崩。
"""

from typing import Optional, Tuple

from sqlalchemy import text

import config
from database.db_session import get_session
from tools import utils

_DB_BACKENDS = {"db", "sqlite", "postgres"}


def _is_db_backend() -> bool:
    return config.SAVE_DATA_OPTION in _DB_BACKENDS


async def claim_task(platform: str, worker_id: str) -> Optional[dict]:
    """认领一个该平台的 pending 任务；成功返回 {"id","keyword"}，队列空返回 None。"""
    if not _is_db_backend():
        return None
    now = int(utils.get_current_timestamp())
    lease_ms = int(getattr(config, "CRAWL_QUEUE_LEASE_SEC", 1800)) * 1000
    retries = max(int(getattr(config, "CRAWL_QUEUE_CLAIM_RETRY", 5)), 1)

    async with get_session() as session:
        # 1) 回收过期租约（幂等）
        await session.execute(
            text(
                "UPDATE crawl_task_queue SET status='pending', claimed_by=NULL "
                "WHERE platform=:p AND status='claimed' AND lease_expires_at < :now"
            ),
            {"p": platform, "now": now},
        )
        await session.commit()

        for _ in range(retries):
            # 2) 读候选
            row = (
                await session.execute(
                    text(
                        "SELECT id, keyword FROM crawl_task_queue "
                        "WHERE platform=:p AND status='pending' "
                        "ORDER BY priority DESC, id ASC LIMIT 1"
                    ),
                    {"p": platform},
                )
            ).first()
            if row is None:
                return None
            task_id, keyword = int(row[0]), str(row[1])
            # 3) 条件认领（行级原子）
            result = await session.execute(
                text(
                    "UPDATE crawl_task_queue "
                    "SET status='claimed', claimed_by=:w, claimed_at=:now, lease_expires_at=:exp "
                    "WHERE id=:id AND status='pending'"
                ),
                {"w": worker_id, "now": now, "exp": now + lease_ms, "id": task_id},
            )
            await session.commit()
            if result.rowcount == 1:
                utils.logger.info(
                    f"[store.crawl_queue.claim_task] claimed id={task_id} keyword={keyword} by={worker_id}"
                )
                return {"id": task_id, "keyword": keyword}
            # 被别人抢先，换下一个候选
        return None


async def complete_task(task_id: int, status: str, items_stored: int, stop_reason: str) -> None:
    """把任务标记为 done/failed 并回填结果统计。"""
    if not _is_db_backend():
        return
    now = int(utils.get_current_timestamp())
    async with get_session() as session:
        await session.execute(
            text(
                "UPDATE crawl_task_queue SET status=:st, finished_at=:now, "
                "items_stored=:n, stop_reason=:r WHERE id=:id"
            ),
            {"st": status, "now": now, "n": int(items_stored), "r": str(stop_reason)[:32], "id": int(task_id)},
        )
        await session.commit()


async def max_run_history_id(platform: str) -> int:
    """结果回填基准：该平台 crawler_run_history 当前最大 id（无则 0）。"""
    if not _is_db_backend():
        return 0
    async with get_session() as session:
        val = (
            await session.execute(
                text("SELECT COALESCE(MAX(id), 0) FROM crawler_run_history WHERE platform=:p"),
                {"p": platform},
            )
        ).scalar()
    return int(val or 0)


async def run_history_delta(platform: str, before_id: int) -> Tuple[int, str]:
    """取 id>before_id 的新增 run_history 行：返回（items_stored 之和, 最后一行 stop_reason）。

    宽泛词被拦截时 search 不写行 → 无新增行 → 返回 (0, "skipped")。
    """
    if not _is_db_backend():
        return 0, ""
    async with get_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT items_stored, stop_reason FROM crawler_run_history "
                    "WHERE platform=:p AND id > :bid ORDER BY id ASC"
                ),
                {"p": platform, "bid": int(before_id)},
            )
        ).all()
    if not rows:
        return 0, "skipped"
    total = sum(int(r[0] or 0) for r in rows)
    reason = str(rows[-1][1] or "completed")
    return total, reason
```

- [ ] **Step 4: 跑测试 GREEN + 全量**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_crawl_queue.py -v
.\.venv\Scripts\python.exe -m pytest tests -q
```
Expected: 新文件 7 passed；全量 `1 failed, 161 passed`（唯一失败=excel）。

- [ ] **Step 5: 提交**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
git add MediaCrawler/store/crawl_queue.py MediaCrawler/tests/test_crawl_queue.py
git commit -m "feat(queue): 认领/完成/租约回收/结果回填模块（乐观条件更新，版本无关）"
```

---

### Task 4: 队列驱动循环 run_keyword_queue

**Files:**
- Create: `MediaCrawler/tools/crawl_queue_runner.py`
- Test: `MediaCrawler/tests/test_crawl_queue_runner.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `MediaCrawler/tests/test_crawl_queue_runner.py`：

```python
# -*- coding: utf-8 -*-
"""队列驱动循环测试：认领顺序、单任务失败不中断、结果回填、排空退出。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import config
from store import crawl_queue
from tools import crawl_queue_runner


class FakeCrawler:
    def __init__(self, fail_on=()):
        self.fail_on = set(fail_on)
        self.searched = []

    async def search(self):
        kw = config.KEYWORDS
        self.searched.append(kw)
        if kw in self.fail_on:
            raise RuntimeError("boom")


@pytest.fixture
def queue_env(monkeypatch):
    monkeypatch.setattr(config, "PLATFORM", "ks")
    monkeypatch.setattr(config, "CRAWL_WORKER_ID", "worker-A", raising=False)
    completed = []

    async def fake_complete(task_id, worker_id, status, items_stored, stop_reason):
        completed.append((task_id, status, items_stored, stop_reason))

    async def fake_max_id(platform):
        return 100

    async def fake_delta(platform, before_id, source_keyword):
        return 5, "completed"

    monkeypatch.setattr(crawl_queue, "complete_task", fake_complete)
    monkeypatch.setattr(crawl_queue, "max_run_history_id", fake_max_id)
    monkeypatch.setattr(crawl_queue, "run_history_delta", fake_delta)
    return completed


@pytest.mark.asyncio
async def test_loops_claimed_keywords_until_drained(queue_env, monkeypatch):
    completed = queue_env
    tasks = [{"id": 1, "keyword": "宿舍"}, {"id": 2, "keyword": "食堂"}, None]
    monkeypatch.setattr(crawl_queue, "claim_task", AsyncMock(side_effect=tasks))

    crawler = FakeCrawler()
    await crawl_queue_runner.run_keyword_queue(crawler)

    assert crawler.searched == ["宿舍", "食堂"]
    assert completed == [(1, "done", 5, "completed"), (2, "done", 5, "completed")]


@pytest.mark.asyncio
async def test_failed_task_marked_and_loop_continues(queue_env, monkeypatch):
    completed = queue_env
    tasks = [{"id": 1, "keyword": "宿舍"}, {"id": 2, "keyword": "食堂"}, None]
    monkeypatch.setattr(crawl_queue, "claim_task", AsyncMock(side_effect=tasks))

    crawler = FakeCrawler(fail_on={"宿舍"})
    await crawl_queue_runner.run_keyword_queue(crawler)

    # 宿舍 search 抛异常 → 标 failed；循环继续到食堂
    assert crawler.searched == ["宿舍", "食堂"]
    assert completed[0] == (1, "failed", 0, "exception")
    assert completed[1] == (2, "done", 5, "completed")


@pytest.mark.asyncio
async def test_empty_queue_no_search(queue_env, monkeypatch):
    completed = queue_env
    monkeypatch.setattr(crawl_queue, "claim_task", AsyncMock(return_value=None))

    crawler = FakeCrawler()
    await crawl_queue_runner.run_keyword_queue(crawler)

    assert crawler.searched == []
    assert completed == []
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_crawl_queue_runner.py -v
```
Expected: `ModuleNotFoundError: No module named 'tools.crawl_queue_runner'`。

- [ ] **Step 3: 实现 tools/crawl_queue_runner.py**

```python
# -*- coding: utf-8 -*-
"""队列驱动运行：登录后循环认领一个关键词、调既有 search()、回填结果、标记完成。"""

import socket

import config
from store import crawl_queue
from tools import utils
from tools.topic_scope import compose_topic_keyword


async def run_keyword_queue(crawler) -> None:
    """循环：认领 → 设单关键词 → crawler.search() → 回填 → done/failed，直到队列排空。

    单任务 search 抛异常 → 标 failed 并继续下一个（不让一个坏关键词终止整台机器）。
    """
    worker = str(getattr(config, "CRAWL_WORKER_ID", "") or socket.gethostname())
    platform = config.PLATFORM
    utils.logger.info(f"[run_keyword_queue] start worker={worker} platform={platform}")

    while True:
        task = await crawl_queue.claim_task(platform, worker)
        if task is None:
            utils.logger.info("[run_keyword_queue] queue drained, exit")
            break
        before_id = await crawl_queue.max_run_history_id(platform)
        config.KEYWORDS = task["keyword"]
        # 与 search() 内部一致的主题限定组合（纯函数、同 config 结果一致）——
        # 结果回填按 source_keyword 精确定位本任务的 run_history 行
        composed_keyword = compose_topic_keyword(
            task["keyword"],
            getattr(config, "CRAWL_TOPIC_QUALIFIER", ""),
            getattr(config, "TOPIC_RELEVANCE_TERMS", []),
        )
        try:
            await crawler.search()
            stored, reason = await crawl_queue.run_history_delta(platform, before_id, composed_keyword)
            await crawl_queue.complete_task(task["id"], worker, "done", stored, reason)
            utils.logger.info(
                f"[run_keyword_queue] done id={task['id']} keyword={task['keyword']} stored={stored}"
            )
        except Exception as ex:  # noqa: BLE001 —— 单任务失败隔离，不中断整台机器采集
            await crawl_queue.complete_task(task["id"], worker, "failed", 0, "exception")
            utils.logger.error(
                f"[run_keyword_queue] failed id={task['id']} keyword={task['keyword']} error={ex}"
            )
```

- [ ] **Step 4: 跑测试 GREEN + 全量**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_crawl_queue_runner.py -v
.\.venv\Scripts\python.exe -m pytest tests -q
```
Expected: 新文件 3 passed；全量 `1 failed, 164 passed`。

- [ ] **Step 5: 提交**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
git add MediaCrawler/tools/crawl_queue_runner.py MediaCrawler/tests/test_crawl_queue_runner.py
git commit -m "feat(queue): 队列驱动循环 run_keyword_queue（失败隔离、结果回填）"
```

---

### Task 5: 随机抖动 helper + 五平台替换

**Files:**
- Modify: `MediaCrawler/tools/utils.py`（新增 `random_crawl_sleep`）
- Test: `MediaCrawler/tests/test_random_crawl_sleep.py`（新建）
- Modify（Task 6 处理 config 与 core 替换；本任务只做 helper + 测试）

- [ ] **Step 1: 写失败测试**

新建 `MediaCrawler/tests/test_random_crawl_sleep.py`：

```python
# -*- coding: utf-8 -*-
"""抖动 helper 测试：区间内取值、min>max 回退、非法值回退。"""

from unittest.mock import AsyncMock

import pytest

import config
from tools import utils


@pytest.mark.asyncio
async def test_sleeps_within_range(monkeypatch):
    monkeypatch.setattr(config, "CRAWLER_MIN_SLEEP_SEC", 8, raising=False)
    monkeypatch.setattr(config, "CRAWLER_MAX_SLEEP_SEC", 18, raising=False)
    slept = []
    monkeypatch.setattr(utils.asyncio, "sleep", AsyncMock(side_effect=lambda s: slept.append(s)))
    monkeypatch.setattr(utils.random, "uniform", lambda a, b: (a + b) / 2)

    await utils.random_crawl_sleep()

    assert slept == [13.0]  # (8+18)/2


@pytest.mark.asyncio
async def test_min_gt_max_falls_back_to_max(monkeypatch):
    monkeypatch.setattr(config, "CRAWLER_MIN_SLEEP_SEC", 30, raising=False)
    monkeypatch.setattr(config, "CRAWLER_MAX_SLEEP_SEC", 18, raising=False)
    slept = []
    monkeypatch.setattr(utils.asyncio, "sleep", AsyncMock(side_effect=lambda s: slept.append(s)))

    await utils.random_crawl_sleep()

    assert slept == [18]  # min>max → 固定睡 max


@pytest.mark.asyncio
async def test_invalid_config_falls_back_to_max(monkeypatch):
    monkeypatch.setattr(config, "CRAWLER_MIN_SLEEP_SEC", "oops", raising=False)
    monkeypatch.setattr(config, "CRAWLER_MAX_SLEEP_SEC", 18, raising=False)
    slept = []
    monkeypatch.setattr(utils.asyncio, "sleep", AsyncMock(side_effect=lambda s: slept.append(s)))

    await utils.random_crawl_sleep()

    assert slept == [18]
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_random_crawl_sleep.py -v
```
Expected: `AttributeError: module 'tools.utils' has no attribute 'random_crawl_sleep'`。

- [ ] **Step 3: 实现 helper**

`MediaCrawler/tools/utils.py`：确认文件顶部已 `import asyncio`、`import random`（若缺则补）。在文件末尾追加：

```python
async def random_crawl_sleep() -> None:
    """请求间随机抖动睡眠：在 [CRAWLER_MIN_SLEEP_SEC, CRAWLER_MAX_SLEEP_SEC] 均匀取值。

    固定间隔比随机更易被识别为机器人；本 helper 用抖动降低行为指纹。
    配置非法（min>max 或非数字）时回退到固定睡 CRAWLER_MAX_SLEEP_SEC，防误配。
    """
    max_s = getattr(config, "CRAWLER_MAX_SLEEP_SEC", 18)
    min_s = getattr(config, "CRAWLER_MIN_SLEEP_SEC", max_s)
    try:
        lo, hi = float(min_s), float(max_s)
    except (TypeError, ValueError):
        await asyncio.sleep(max_s)
        return
    if lo > hi or lo < 0:
        await asyncio.sleep(max_s)
        return
    await asyncio.sleep(random.uniform(lo, hi))
```

注意：`tools/utils.py` 是否 `import config`？确认；若无则补 `import config`（其余模块广泛这样用）。

- [ ] **Step 4: 跑测试 GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_random_crawl_sleep.py -v
.\.venv\Scripts\python.exe -m pytest tests -q
```
Expected: 新文件 3 passed；全量 `1 failed, 167 passed`。

- [ ] **Step 5: 提交**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
git add MediaCrawler/tools/utils.py MediaCrawler/tests/test_random_crawl_sleep.py
git commit -m "feat(crawl): 请求间随机抖动 helper random_crawl_sleep"
```

---

### Task 6: config 项 + 五平台 core 替换（抖动 + start 队列分支）+ cmd_arg

**Files:**
- Modify: `MediaCrawler/config/base_config.py`（stash 舞步）
- Modify: `MediaCrawler/cmd_arg/arg.py`
- Modify: `MediaCrawler/media_platform/{xhs,weibo,tieba,zhihu,kuaishou}/core.py`（抖动替换 + start 分支）
- Modify: `MediaCrawler/media_platform/tieba/client.py`（抖动替换）
- Test: `MediaCrawler/tests/test_cmd_arg.py`（追加 `--from-queue`/`--worker` 解析测试）

- [ ] **Step 1: 写 cmd_arg 标志解析测试（RED）**

在 `MediaCrawler/tests/test_cmd_arg.py` 末尾追加（复用文件已有的 `restore_config` fixture 与 `BASE_ARGS`）：

```python
class TestQueueFlags:
    @pytest.mark.asyncio
    async def test_from_queue_and_worker_parsed(self, restore_config):
        config.CRAWL_FROM_QUEUE = False
        config.CRAWL_WORKER_ID = ""
        await parse_cmd(BASE_ARGS + ["--from-queue", "yes", "--worker", "member-A"])
        assert config.CRAWL_FROM_QUEUE is True
        assert config.CRAWL_WORKER_ID == "member-A"

    @pytest.mark.asyncio
    async def test_from_queue_defaults_off(self, restore_config):
        config.CRAWL_FROM_QUEUE = True
        await parse_cmd(BASE_ARGS)
        assert config.CRAWL_FROM_QUEUE is False
```

跑：`cd "...\MediaCrawler"; .\.venv\Scripts\python.exe -m pytest tests/test_cmd_arg.py::TestQueueFlags -v`
Expected: FAIL/ERROR —— `--from-queue` 尚不是合法选项（Typer 报 no such option）。Step 5 实现后转 GREEN。

- [ ] **Step 2: stash 冒烟调参**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
git stash push -- MediaCrawler/config/base_config.py
git diff --stat
```

- [ ] **Step 3: 加配置项**

`MediaCrawler/config/base_config.py`：找到 `CRAWLER_MAX_SLEEP_SEC = 18` 那行，在其**上方**插入：

```python
# 请求间随机抖动下界（秒）：间隔在 [MIN, MAX] 均匀取；固定间隔更像机器人，抖动降风险
CRAWLER_MIN_SLEEP_SEC = 8
```

在文件末尾（或"发布时间窗口"块之后合适处）追加分布式队列配置：

```python
# ==================== 分布式协同爬取（认领队列） ====================
# 队列模式：多成员各自机器同时跑、从共享库认领互不重叠关键词（--from-queue yes 开启）
CRAWL_FROM_QUEUE = False
# worker 标识（空 → 运行时取主机名）；监控里显示谁在爬哪个
CRAWL_WORKER_ID = ""
# 认领租约（秒）：认领后 N 秒内没完成即视为卡死，可被其他机器回收重认领
CRAWL_QUEUE_LEASE_SEC = 1800
# 认领乐观重试次数（候选被别人抢先时换下一个候选的最大尝试数）
CRAWL_QUEUE_CLAIM_RETRY = 5
```

- [ ] **Step 4: 提交 config 并恢复冒烟调参**

```powershell
git add MediaCrawler/config/base_config.py
git commit -m "feat(crawl): 抖动下界 + 分布式队列配置项"
git stash pop
git diff MediaCrawler/config/base_config.py   # 确认只剩 CDP_CONNECT_EXISTING=False 与 CRAWLER_MAX_NOTES_COUNT=40 两处冒烟差异
```

- [ ] **Step 5: cmd_arg 加两个选项**

`MediaCrawler/cmd_arg/arg.py`：仿现有 `--fresh` 选项（`fresh: Annotated[str, typer.Option("--fresh", ...)] = "no"`）。在 `main()` 签名里 `fresh` 之后加两个参数：

```python
        from_queue: Annotated[
            str,
            typer.Option(
                "--from-queue",
                help="Queue-driven mode: claim keywords from shared crawl_task_queue (yes/no)",
                rich_help_panel="Basic Configuration",
                show_default=True,
            ),
        ] = "no",
        worker: Annotated[
            str,
            typer.Option(
                "--worker",
                help="Worker id for queue mode (empty = hostname)",
                rich_help_panel="Basic Configuration",
            ),
        ] = "",
```

在函数体设置 config 的区块（`config.CRAWL_PUBLISH_TIME_END = end_date` 附近）加：

```python
        config.CRAWL_FROM_QUEUE = _to_bool(from_queue)
        config.CRAWL_WORKER_ID = worker
```

- [ ] **Step 6: 五平台 start() 队列分支**

对 `xhs`、`weibo`、`tieba`、`zhihu`、`kuaishou` 五个 `core.py`：定位 `start()` 里的
```python
            if config.CRAWLER_TYPE == "search":
```
块（各平台注释文案不同，保留原注释），把紧随其后的 `await self.search()` 一行改为：

```python
                if config.CRAWL_FROM_QUEUE:
                    from tools.crawl_queue_runner import run_keyword_queue
                    await run_keyword_queue(self)
                else:
                    await self.search()
```

（缩进对齐各平台原有层级。用函数内 import 避免循环导入风险。其余 detail/creator 分支不动。）

- [ ] **Step 7: 抖动替换（五平台 core + tieba client）**

在这些文件里，把**每一处** `await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)` 精确替换为
`await utils.random_crawl_sleep()`（每个文件用 replace_all）：
- `media_platform/xhs/core.py`（2 处）
- `media_platform/weibo/core.py`（5 处）
- `media_platform/zhihu/core.py`（5 处）
- `media_platform/kuaishou/core.py`（3 处）
- `media_platform/tieba/core.py`（6 处）
- `media_platform/tieba/client.py`（7 处）

每个文件替换后确认已 `from tools import utils`（五个 core 均有；`tieba/client.py` 亦有）。
**不动** `douyin`/`bilibili`（范围外）、小红书详情自身的 `XHS_DETAIL_*_SLEEP_*` 随机区间、
以及以 `crawl_interval=` 参数传入 client 方法后在内部 `asyncio.sleep(crawl_interval)` 的调用
（那是逐评论微节流，不在本次抖动范围；保持不变）。

- [ ] **Step 8: cmd_arg 测试转 GREEN + 语法导入验证 + 全量回归**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\MediaCrawler"
.\.venv\Scripts\python.exe -m pytest tests/test_cmd_arg.py::TestQueueFlags -v
.\.venv\Scripts\python.exe -c "import media_platform.xhs.core, media_platform.weibo.core, media_platform.tieba.core, media_platform.tieba.client, media_platform.zhihu.core, media_platform.kuaishou.core, cmd_arg.arg; print('import ok')"
.\.venv\Scripts\python.exe -m pytest tests -q
```
Expected: `TestQueueFlags` 2 passed；`import ok`；全量 `1 failed, 169 passed`（Task 3/4/5 的 +13 + 本任务 cmd_arg +2；无新失败）。

- [ ] **Step 9: 提交**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
git add MediaCrawler/cmd_arg/arg.py MediaCrawler/tests/test_cmd_arg.py MediaCrawler/media_platform/xhs/core.py MediaCrawler/media_platform/weibo/core.py MediaCrawler/media_platform/tieba/core.py MediaCrawler/media_platform/tieba/client.py MediaCrawler/media_platform/zhihu/core.py MediaCrawler/media_platform/kuaishou/core.py
git commit -m "feat(crawl): --from-queue/--worker 接线 + 五平台 start 队列分支 + 抖动替换"
```

---

### Task 7: seed_crawl_queue.py 双来源播种

**Files:**
- Create: `scripts/seed_crawl_queue.py`
- Test: `backend/tests/test_seed_crawl_queue.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_seed_crawl_queue.py`：

```python
"""播种纯逻辑测试：笛卡尔积、去重（当前 pending/claimed）、行构造。"""

import unittest

from scripts.seed_crawl_queue import build_seed_rows, filter_new_rows, parse_platforms


class ParsePlatformsTests(unittest.TestCase):
    def test_splits_and_trims(self):
        self.assertEqual(parse_platforms("ks, zhihu ,wb"), ["ks", "zhihu", "wb"])

    def test_rejects_unknown(self):
        with self.assertRaises(ValueError):
            parse_platforms("ks,douyin")


class BuildSeedRowsTests(unittest.TestCase):
    def test_cartesian_product(self):
        rows = build_seed_rows(["ks", "zhihu"], ["宿舍", "食堂"], priority=3, now_ms=1000)
        keys = {(r["platform"], r["keyword"]) for r in rows}
        self.assertEqual(
            keys, {("ks", "宿舍"), ("ks", "食堂"), ("zhihu", "宿舍"), ("zhihu", "食堂")}
        )
        for r in rows:
            self.assertEqual(r["status"], "pending")
            self.assertEqual(r["priority"], 3)
            self.assertEqual(r["created_at"], 1000)

    def test_dedup_keywords_within_input(self):
        rows = build_seed_rows(["ks"], ["宿舍", "宿舍", " 宿舍 "], priority=0, now_ms=1)
        self.assertEqual(len(rows), 1)


class FilterNewRowsTests(unittest.TestCase):
    def test_skips_active_pairs(self):
        candidate = build_seed_rows(["ks", "zhihu"], ["宿舍"], priority=0, now_ms=1)
        # ks/宿舍 已在队列且 pending → 跳过；zhihu/宿舍 是新的 → 保留
        active = {("ks", "宿舍")}
        new_rows = filter_new_rows(candidate, active)
        self.assertEqual([(r["platform"], r["keyword"]) for r in new_rows], [("zhihu", "宿舍")])

    def test_done_pairs_not_active_so_requeued(self):
        candidate = build_seed_rows(["ks"], ["宿舍"], priority=0, now_ms=1)
        active = set()  # done/failed 不在 active 集 → 允许重新入队
        self.assertEqual(len(filter_new_rows(candidate, active)), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe -m unittest backend.tests.test_seed_crawl_queue -v
```
Expected: `ModuleNotFoundError: No module named 'scripts.seed_crawl_queue'`。

- [ ] **Step 3: 实现 seed_crawl_queue.py**

```python
"""分布式协同爬取：向 crawl_task_queue 播种任务（双来源：智能选题推荐 / 手动）。

用法：
  # 手动关键词，平台 × 关键词笛卡尔积
  .venv/Scripts/python.exe scripts/seed_crawl_queue.py --platform ks,zhihu --keywords "宿舍,食堂"
  # 从智能选题推荐取 top-N 灌单平台
  .venv/Scripts/python.exe scripts/seed_crawl_queue.py --platform ks --from-recommendations --top 20
  # 预览不写
  .venv/Scripts/python.exe scripts/seed_crawl_queue.py --platform ks --keywords "宿舍" --dry-run

去重：只跳过当前 status ∈ {pending, claimed} 的 (platform, keyword)；done/failed 过的可重入队。
设计见 docs/superpowers/specs/2026-07-11-distributed-crawl-design.md §5。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from sqlalchemy import text  # noqa: E402

from backend.database import SessionLocal, engine  # noqa: E402
from backend.services.keyword_suggestion_adapter import get_keyword_suggestions  # noqa: E402

VALID_PLATFORMS = {"xhs", "wb", "tieba", "zhihu", "ks"}


def parse_platforms(raw: str) -> list[str]:
    items = [p.strip() for p in str(raw).split(",") if p.strip()]
    bad = [p for p in items if p not in VALID_PLATFORMS]
    if bad:
        raise ValueError(f"unsupported platform(s): {bad}; valid={sorted(VALID_PLATFORMS)}")
    # 去重保序
    seen: list[str] = []
    for p in items:
        if p not in seen:
            seen.append(p)
    return seen


def _clean_keywords(keywords: Iterable[str]) -> list[str]:
    out: list[str] = []
    for kw in keywords:
        k = str(kw or "").strip()
        if k and k not in out:
            out.append(k)
    return out


def build_seed_rows(platforms: list[str], keywords: Iterable[str], priority: int, now_ms: int) -> list[dict[str, Any]]:
    """平台 × 关键词笛卡尔积 → pending 行（关键词内部去重）。纯逻辑。"""
    kws = _clean_keywords(keywords)
    rows: list[dict[str, Any]] = []
    for platform in platforms:
        for kw in kws:
            rows.append({
                "platform": platform,
                "keyword": kw,
                "status": "pending",
                "priority": int(priority),
                "created_at": int(now_ms),
            })
    return rows


def filter_new_rows(candidate_rows: list[dict[str, Any]], active_pairs: set[tuple[str, str]]) -> list[dict[str, Any]]:
    """去重：跳过当前 pending/claimed 的 (platform, keyword)。纯逻辑。"""
    return [r for r in candidate_rows if (r["platform"], r["keyword"]) not in active_pairs]


def _load_active_pairs(conn) -> set[tuple[str, str]]:
    rows = conn.execute(text(
        "SELECT platform, keyword FROM crawl_task_queue WHERE status IN ('pending','claimed')"
    )).all()
    return {(r[0], r[1]) for r in rows}


def _recommendation_keywords(top: int) -> list[str]:
    db = SessionLocal()
    try:
        result = get_keyword_suggestions(db, days=30, top=top)
    finally:
        db.close()
    return [s.get("keyword") for s in result.get("suggestions", []) if s.get("keyword")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="向 crawl_task_queue 播种任务")
    parser.add_argument("--platform", required=True, help="平台码，逗号分隔（xhs,wb,tieba,zhihu,ks）")
    parser.add_argument("--keywords", default="", help="手动关键词，逗号分隔")
    parser.add_argument("--from-recommendations", action="store_true", help="从智能选题推荐取关键词")
    parser.add_argument("--top", type=int, default=10, help="推荐取 top-N（配合 --from-recommendations）")
    parser.add_argument("--priority", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    platforms = parse_platforms(args.platform)
    keywords = _clean_keywords(args.keywords.split(",")) if args.keywords else []
    if args.from_recommendations:
        keywords += _recommendation_keywords(args.top)
    keywords = _clean_keywords(keywords)
    if not keywords:
        parser.error("no keywords (use --keywords and/or --from-recommendations)")

    now_ms = int(time.time() * 1000)
    candidate = build_seed_rows(platforms, keywords, args.priority, now_ms)

    with engine.begin() as conn:
        active = _load_active_pairs(conn)
        new_rows = filter_new_rows(candidate, active)
        skipped = len(candidate) - len(new_rows)
        print(f"候选 {len(candidate)} 条，跳过已在队列 {skipped} 条，待插入 {len(new_rows)} 条")
        if args.dry_run:
            for r in new_rows:
                print(f"  [dry-run] {r['platform']} / {r['keyword']} (priority={r['priority']})")
            return 0
        for r in new_rows:
            conn.execute(text(
                "INSERT INTO crawl_task_queue (platform, keyword, status, priority, created_at) "
                "VALUES (:platform, :keyword, :status, :priority, :created_at)"
            ), r)
    print(f"完成：插入 {len(new_rows)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 跑测试 GREEN + 全量**

```powershell
.\.venv\Scripts\python.exe -m unittest backend.tests.test_seed_crawl_queue -v
$env:PYTHONIOENCODING="utf-8"; .\.venv\Scripts\python.exe -m unittest discover -s backend/tests -t . -q
```
Expected: 新测试 7 passed；全量 `Ran 214 tests OK`（207 + 7）。

- [ ] **Step 5: 提交**

```powershell
git add scripts/seed_crawl_queue.py backend/tests/test_seed_crawl_queue.py
git commit -m "feat(queue): seed_crawl_queue 双来源播种（推荐/手动 + 去重）"
```

---

### Task 8: crawl_queue_status.py + reset_crawl_queue.py

**Files:**
- Create: `scripts/crawl_queue_status.py`
- Create: `scripts/reset_crawl_queue.py`
- Test: `backend/tests/test_crawl_queue_scripts.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_crawl_queue_scripts.py`：

```python
"""监控汇总 + 重置目标选择纯逻辑测试。"""

import unittest

from scripts.crawl_queue_status import summarize
from scripts.reset_crawl_queue import select_target_ids


def _row(id, platform, status, keyword="kw", claimed_by=None, lease_expires_at=0):
    return {
        "id": id, "platform": platform, "status": status, "keyword": keyword,
        "claimed_by": claimed_by, "lease_expires_at": lease_expires_at,
    }


class SummarizeTests(unittest.TestCase):
    def test_counts_by_platform_and_status(self):
        rows = [
            _row(1, "ks", "pending"), _row(2, "ks", "done"), _row(3, "ks", "done"),
            _row(4, "zhihu", "claimed"), _row(5, "zhihu", "failed"),
        ]
        summary = summarize(rows)
        self.assertEqual(summary["ks"], {"pending": 1, "claimed": 0, "done": 2, "failed": 0})
        self.assertEqual(summary["zhihu"], {"pending": 0, "claimed": 1, "done": 0, "failed": 1})


class SelectTargetIdsTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            _row(1, "ks", "claimed"), _row(2, "ks", "failed"),
            _row(3, "ks", "done"), _row(4, "zhihu", "claimed"),
        ]

    def test_requeue_claimed(self):
        ids = select_target_ids(self.rows, requeue_claimed=True, requeue_failed=False,
                                clear_done=False, platform=None)
        self.assertEqual(sorted(ids), [1, 4])

    def test_requeue_failed(self):
        ids = select_target_ids(self.rows, requeue_claimed=False, requeue_failed=True,
                                clear_done=False, platform=None)
        self.assertEqual(sorted(ids), [2])

    def test_clear_done(self):
        ids = select_target_ids(self.rows, requeue_claimed=False, requeue_failed=False,
                                clear_done=True, platform=None)
        self.assertEqual(sorted(ids), [3])

    def test_platform_filter(self):
        ids = select_target_ids(self.rows, requeue_claimed=True, requeue_failed=False,
                                clear_done=False, platform="ks")
        self.assertEqual(sorted(ids), [1])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
$env:PYTHONIOENCODING="utf-8"; .\.venv\Scripts\python.exe -m unittest backend.tests.test_crawl_queue_scripts -v
```
Expected: `ModuleNotFoundError: No module named 'scripts.crawl_queue_status'`。

- [ ] **Step 3: 实现 crawl_queue_status.py**

```python
"""分布式协同爬取：监控 crawl_task_queue（按平台汇总 + claimed 明细 + 卡死提示）。

用法：.venv/Scripts/python.exe scripts/crawl_queue_status.py [--platform ks]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from sqlalchemy import text  # noqa: E402

from backend.database import engine  # noqa: E402

_STATUSES = ("pending", "claimed", "done", "failed")


def summarize(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """按平台聚合各状态计数。纯逻辑。"""
    summary: dict[str, dict[str, int]] = {}
    for row in rows:
        platform = row["platform"]
        bucket = summary.setdefault(platform, {s: 0 for s in _STATUSES})
        status = row["status"]
        if status in bucket:
            bucket[status] += 1
    return summary


def _load_rows(conn, platform: str | None) -> list[dict[str, Any]]:
    sql = "SELECT id, platform, keyword, status, claimed_by, lease_expires_at FROM crawl_task_queue"
    params: dict[str, Any] = {}
    if platform:
        sql += " WHERE platform=:p"
        params["p"] = platform
    return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="监控 crawl_task_queue")
    parser.add_argument("--platform", default=None)
    args = parser.parse_args(argv)

    now_ms = int(time.time() * 1000)
    with engine.connect() as conn:
        rows = _load_rows(conn, args.platform)

    summary = summarize(rows)
    print("=== 队列汇总（按平台）===")
    for platform in sorted(summary):
        c = summary[platform]
        print(f"  {platform}: pending={c['pending']} claimed={c['claimed']} done={c['done']} failed={c['failed']}")

    claimed = [r for r in rows if r["status"] == "claimed"]
    if claimed:
        print("\n=== 认领中（claimed）===")
        for r in claimed:
            stuck = " [卡死待回收]" if (r["lease_expires_at"] or 0) < now_ms else ""
            print(f"  #{r['id']} {r['platform']} / {r['keyword']} by {r['claimed_by']}{stuck}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 实现 reset_crawl_queue.py**

```python
"""分布式协同爬取：重置 crawl_task_queue（回收卡死/失败任务、清完成行）。

用法：
  .venv/Scripts/python.exe scripts/reset_crawl_queue.py --requeue-claimed [--platform ks] [--dry-run]
  .venv/Scripts/python.exe scripts/reset_crawl_queue.py --requeue-failed
  .venv/Scripts/python.exe scripts/reset_crawl_queue.py --clear-done
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from sqlalchemy import text  # noqa: E402

from backend.database import engine  # noqa: E402


def select_target_ids(rows: list[dict[str, Any]], *, requeue_claimed: bool, requeue_failed: bool,
                      clear_done: bool, platform: str | None) -> list[int]:
    """纯逻辑：给定行快照与开关，选出目标 id 列表。"""
    targets: list[int] = []
    for row in rows:
        if platform and row["platform"] != platform:
            continue
        status = row["status"]
        if (requeue_claimed and status == "claimed") or \
           (requeue_failed and status == "failed") or \
           (clear_done and status == "done"):
            targets.append(int(row["id"]))
    return targets


def _load_rows(conn, platform: str | None) -> list[dict[str, Any]]:
    sql = "SELECT id, platform, status FROM crawl_task_queue"
    params: dict[str, Any] = {}
    if platform:
        sql += " WHERE platform=:p"
        params["p"] = platform
    return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="重置 crawl_task_queue")
    parser.add_argument("--requeue-claimed", action="store_true", help="claimed → pending（回收卡死）")
    parser.add_argument("--requeue-failed", action="store_true", help="failed → pending")
    parser.add_argument("--clear-done", action="store_true", help="删除 done 行")
    parser.add_argument("--platform", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if not (args.requeue_claimed or args.requeue_failed or args.clear_done):
        parser.error("需指定 --requeue-claimed / --requeue-failed / --clear-done 至少一个")

    with engine.begin() as conn:
        rows = _load_rows(conn, args.platform)
        target_ids = select_target_ids(
            rows, requeue_claimed=args.requeue_claimed, requeue_failed=args.requeue_failed,
            clear_done=args.clear_done, platform=args.platform,
        )
        print(f"将影响 {len(target_ids)} 行" + (" [dry-run]" if args.dry_run else ""))
        if args.dry_run or not target_ids:
            return 0
        ids_csv = ",".join(str(i) for i in target_ids)
        if args.clear_done:
            conn.execute(text(f"DELETE FROM crawl_task_queue WHERE id IN ({ids_csv})"))
        else:
            conn.execute(text(
                f"UPDATE crawl_task_queue SET status='pending', claimed_by=NULL, "
                f"lease_expires_at=NULL WHERE id IN ({ids_csv})"
            ))
    print("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

注：`ids_csv` 由整数 join 而成（`select_target_ids` 保证是 int），无注入面；行数受队列规模约束。

- [ ] **Step 5: 跑测试 GREEN + 全量**

```powershell
.\.venv\Scripts\python.exe -m unittest backend.tests.test_crawl_queue_scripts -v
$env:PYTHONIOENCODING="utf-8"; .\.venv\Scripts\python.exe -m unittest discover -s backend/tests -t . -q
```
Expected: 新测试 7 passed；全量 `Ran 221 tests OK`（214 + 7）。

- [ ] **Step 6: 提交**

```powershell
git add scripts/crawl_queue_status.py scripts/reset_crawl_queue.py backend/tests/test_crawl_queue_scripts.py
git commit -m "feat(queue): crawl_queue_status 监控 + reset_crawl_queue 重置"
```

---

### Task 9: 全量回归 + 合并 main

- [ ] **Step 1: 双侧全量回归**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\MediaCrawler"
.\.venv\Scripts\python.exe -m pytest tests -q
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -t . -q
```
Expected: MediaCrawler `1 failed, 169 passed`（唯一失败=excel）；主项目 `Ran 221 tests OK`。任何新失败先修再合并。

- [ ] **Step 2: stash 舞步合并**

```powershell
git stash push -- MediaCrawler/config/base_config.py
git checkout main
git merge --ff-only feature/distributed-crawl
git branch -d feature/distributed-crawl
git stash pop
git status --short   # 预期回到：仅 M MediaCrawler/config/base_config.py（冒烟调参）
git log --oneline -10
```

---

### Task 10: 线上迁移（需用户确认，不可跳过确认环节）

前提：`.env` 指向共享阿里云 MySQL；代理已按 crawl-runbook §1.2 处理。

- [ ] **Step 1: dry-run 呈用户**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
.\.venv\Scripts\python.exe scripts\create_crawl_task_queue.py --dry-run
```
预期 `would_create=1`（表不存在）或 `[跳过]`（已存在）。**输出呈用户确认后**再执行。

- [ ] **Step 2: 执行 + 幂等复跑**

```powershell
.\.venv\Scripts\python.exe scripts\create_crawl_task_queue.py
.\.venv\Scripts\python.exe scripts\create_crawl_task_queue.py   # 幂等复跑，预期 skipped
```

---

### Task 11: 冒烟指引 + runbook + 记忆

- [ ] **Step 1: 冒烟命令（呈用户，多机需真人协作，无法代跑）**

```powershell
# 一台机先播种 4 个 ks 任务
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
.\.venv\Scripts\python.exe scripts\seed_crawl_queue.py --platform ks --keywords "宿舍,食堂,图书馆,体育馆"
# 你 + 队友两台机各自（先关代理三行 + 关 Clash）：
cd "...\MediaCrawler"
.\.venv\Scripts\python.exe main.py --platform ks --from-queue yes --get_comment yes
# 任一台机随时看进度：
.\.venv\Scripts\python.exe scripts\crawl_queue_status.py --platform ks
```
验收：两机各认领不重叠子集、无一任务被双认领、库内无重复行、队列最终全 done。

- [ ] **Step 2: 更新 docs/crawl-runbook.md**——新增一节「多机协同爬取」：播种 → 各机 `--from-queue yes` → 监控/重置三脚本用法 + 抖动配置说明（`CRAWLER_MIN/MAX_SLEEP_SEC`）。提交：

```powershell
git add docs/crawl-runbook.md
git commit -m "docs: 爬取手册补多机协同 + 抖动配置"
```

---

### Task 12（可选尾）: 并发写死锁重试保险丝

> **说明（协调者在此任务前决定是否执行）**：设计 §7 的死锁重试比初看更侵入——正确的死锁重试须
> 重放**整个事务**（select+insert），而非只重试 commit（死锁已回滚事务、session 失效），需把五平台
> 各自 `store_content`/`store_comment` 主体拆成"一次工作单元 + 重试外壳"（5×2 处）。而现实争用
> 极低（不同成员爬不同关键词 → 不同行；同帖争用已由唯一索引自愈覆盖）。**建议**：先合并 Task 1-11
> 的核心能力，本任务作为可选加固，由协调者与用户确认后再做。若做，如下。

**Files:**
- Create: `MediaCrawler/tools/db_retry.py`
- Test: `MediaCrawler/tests/test_db_retry.py`（新建）
- Modify: `MediaCrawler/store/{xhs,weibo,tieba,zhihu,kuaishou}/_store_impl.py`（把主体包进重试外壳）

- [ ] **Step 1: 写失败测试**

新建 `MediaCrawler/tests/test_db_retry.py`：

```python
# -*- coding: utf-8 -*-
"""死锁重试 helper 测试：瞬时错误重试后成功、耗尽跳过、非瞬时错误直接抛。"""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError

from tools.db_retry import with_write_retry


def _deadlock():
    # MySQL 1213 deadlock：OperationalError.orig.args[0] == 1213
    err = OperationalError("stmt", {}, Exception())
    err.orig = type("O", (), {"args": (1213, "Deadlock found")})()
    return err


@pytest.mark.asyncio
async def test_retries_then_succeeds():
    calls = {"n": 0}

    async def work():
        calls["n"] += 1
        if calls["n"] < 2:
            raise _deadlock()
        return "ok"

    result = await with_write_retry(work, retries=2)
    assert result == "ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_exhausts_and_swallows(caplog):
    async def work():
        raise _deadlock()

    # 耗尽后不抛（记警跳过该条），返回 None
    result = await with_write_retry(work, retries=2)
    assert result is None


@pytest.mark.asyncio
async def test_non_transient_error_propagates():
    async def work():
        raise ValueError("not a deadlock")

    with pytest.raises(ValueError):
        await with_write_retry(work, retries=2)
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\MediaCrawler"
.\.venv\Scripts\python.exe -m pytest tests/test_db_retry.py -v
```
Expected: `ModuleNotFoundError: No module named 'tools.db_retry'`。

- [ ] **Step 3: 实现 tools/db_retry.py**

```python
# -*- coding: utf-8 -*-
"""并发写保险丝：把一次 DB 工作单元包进"瞬时错误（死锁/锁等待超时）重试"外壳。

正确的死锁重试须重放整个事务（死锁已回滚、session 失效），故接受一个"每次都新建
session 执行完整工作单元"的无参 async 工厂 work()。瞬时错误重试至多 retries 次，
仍失败则记警跳过该条（返回 None，不让并发写崩掉整场爬取）；非瞬时错误直接上抛。
"""

import asyncio

from sqlalchemy.exc import OperationalError

from tools import utils

_TRANSIENT_MYSQL_CODES = {1213, 1205}  # 1213 死锁 / 1205 锁等待超时


def _is_transient(exc: OperationalError) -> bool:
    orig = getattr(exc, "orig", None)
    code = getattr(orig, "args", (None,))[0] if orig is not None else None
    return code in _TRANSIENT_MYSQL_CODES


async def with_write_retry(work, retries: int = 2, backoff_sec: float = 0.2):
    """执行 work()（无参 async 工厂，内部自建 session 完成完整工作单元）。

    命中瞬时错误 → 退避后重试至多 retries 次；耗尽 → 记警跳过返回 None；非瞬时 → 上抛。
    """
    attempt = 0
    while True:
        try:
            return await work()
        except OperationalError as exc:
            if not _is_transient(exc):
                raise
            attempt += 1
            if attempt > retries:
                utils.logger.warning(
                    f"[db_retry] transient DB error persisted after {retries} retries, skip this row: {exc}"
                )
                return None
            await asyncio.sleep(backoff_sec * attempt)
```

- [ ] **Step 4: 接入五平台 store（每处：主体抽成 `_*_once`，外层包 with_write_retry）**

对 `store/{xhs,weibo,tieba,zhihu,kuaishou}/_store_impl.py` 的 `KuaishouDbStoreImplement` 等
DB 实现类：把 `store_content` 主体改名为 `async def _store_content_once(self, content_item)`，
新增薄外壳：

```python
    async def store_content(self, content_item):
        from tools.db_retry import with_write_retry
        await with_write_retry(lambda: self._store_content_once(content_item))
```

`store_comment` 同法（`_store_comment_once`）。注意：每次重试都会走一遍完整
`async with get_session()`，满足"重放整个事务"。**不改** `batch_get_existing_note_ids` 等只读方法。
逐平台改完各跑一次该平台既有 store 测试确认不回归。

- [ ] **Step 5: 跑测试 GREEN + 全量**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_db_retry.py -v
.\.venv\Scripts\python.exe -m pytest tests -q
```
Expected: 新文件 3 passed；全量既有 store 测试全绿（自愈用例仍过）、唯一失败仍是 excel。

- [ ] **Step 6: 提交（在 feature 分支上做，或单独小分支；完成后同 Task 9 合并）**

```powershell
git add MediaCrawler/tools/db_retry.py MediaCrawler/tests/test_db_retry.py MediaCrawler/store/xhs/_store_impl.py MediaCrawler/store/weibo/_store_impl.py MediaCrawler/store/tieba/_store_impl.py MediaCrawler/store/zhihu/_store_impl.py MediaCrawler/store/kuaishou/_store_impl.py
git commit -m "feat(store): 并发写死锁/锁等待瞬时错误重试保险丝"
```

---

## 完成定义（Definition of Done）

1. MediaCrawler pytest：既有 154 全过 + 新增（queue 7 + runner 3 + sleep 3 + cmd_arg 2 = 15，Task 12 另 +3）全过 = 169（+Task12=172），唯一失败仍是 excel。
2. 主项目 unittest：≥221 全绿。
3. main 分支含 Task 1-9 全部提交，feature 分支已删，工作区只剩 base_config 两处冒烟调参。
4. 线上：crawl_task_queue 表在位，建表脚本幂等复跑 skip。
5. 冒烟通过：两台机 `--from-queue yes` 各认领不重叠关键词、零重复认领、库内零重复行、队列最终全 done。
6. runbook 有「多机协同」小节。
7. （若做 Task 12）并发写死锁重试接入五平台 store，既有自愈测试不回归。
