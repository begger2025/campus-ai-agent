# 快手爬虫深度改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把快手（ks）爬虫从上游裸版本改造成与 xhs/weibo/tieba/zhihu 对齐的舆情管线（过滤/配额/历史/去重），并端到端接入主项目（sync/process/评论加载/前端），平台码全链路 `ks`。

**Architecture:** 爬取端照知乎 `_filter_and_store_page` 模式重写 `KuaishouCrawler.search()`（微博整页管线，纯客户端过滤，无服务端排序/时间参数）；存储层加唯一约束 + IntegrityError 自愈 + 批量已存查询；主项目侧注册 `_map_ks` 映射、评论路由、平台归一化与前端枚举。设计文档：`docs/superpowers/specs/2026-07-11-ks-crawler-retrofit-design.md`。

**Tech Stack:** Python (SQLAlchemy async / pytest / unittest)、Vue3、MySQL（阿里云共享 RDS）。

---

## 环境与纪律（每个任务开始前先读这段）

- 仓库根：`D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main`（下文 `<ROOT>`）。所有命令用 PowerShell。
- **两个 venv**：
  - MediaCrawler 测试：`cd "<ROOT>\MediaCrawler"; .\.venv\Scripts\python.exe -m pytest tests -q`
    基线：**133 passed + 1 failed**（`test_store_factory.py::test_create_excel_store` 是既有失败，与我们无关，不许修也不许弄丢这个认知）。
  - 主项目测试：`cd "<ROOT>"; $env:PYTHONIOENCODING="utf-8"; .\.venv\Scripts\python.exe -m unittest discover -s backend/tests -t . -q`
    基线：**176 tests OK**。
- **冒烟配置纪律**：`MediaCrawler/config/base_config.py` 工作区有两处**未提交**的本地调参（`CDP_CONNECT_EXISTING = False`、`CRAWLER_MAX_NOTES_COUNT = 40`）。它们**绝不能进任何提交**。凡是要提交该文件的任务（Task 4）与分支切换任务（Task 11），必须按任务里写的 stash 舞步操作。其余任务提交时只 `git add <明确路径>`，永远不用 `git add -A` / `git add .`。
- 工作分支：`feature/ks-crawler-retrofit`（Task 1 创建，Task 12 ff 合回 main 后删除）。
- TDD 铁律：先写测试看它 FAIL（原因正确），再写最小实现看它 PASS。测试失败原因不对（如 import 错误）先修再继续。

## 文件结构总览

| 文件 | 动作 | 职责 |
|---|---|---|
| `MediaCrawler/database/models.py` | 改 | ks 两表唯一约束 + `comment_count` 列 |
| `MediaCrawler/store/kuaishou/__init__.py` | 改 | 持久化 commentCount；`batch_get_existing_note_ids` 模块包装 |
| `MediaCrawler/store/kuaishou/_store_impl.py` | 改 | Db store 自愈 + 批量已存查询方法 |
| `MediaCrawler/media_platform/kuaishou/help.py` | 改 | 新增纯函数 `resolve_next_pcursor` |
| `MediaCrawler/media_platform/kuaishou/core.py` | 改 | `search()` 重写 + `_filter_and_store_page` |
| `MediaCrawler/config/base_config.py` | 改 | `KS_SKIP_EXISTING_NOTES = True` |
| `MediaCrawler/tests/test_kuaishou_store.py` | 新建 | comment_count 透传 + 批量已存查询测试 |
| `MediaCrawler/tests/test_store_integrity_fallback.py` | 改 | 追加 ks 自愈测试类 |
| `MediaCrawler/tests/test_kuaishou_help.py` | 新建 | `resolve_next_pcursor` 单测 |
| `MediaCrawler/tests/test_kuaishou_search_flow.py` | 新建 | 单页过滤管线 + search 级停止语义测试 |
| `scripts/add_crawler_unique_indexes.py` | 改 | TARGETS 加 ks 两表 |
| `scripts/create_ks_tables.py` | 新建 | 建表/补列两态幂等迁移脚本 |
| `scripts/sync_media_to_raw_posts.py` | 改 | `_map_ks` + 五处注册 |
| `scripts/process_raw_posts.py` | 改 | `--platform` choices 加 ks |
| `backend/services/comment_loader.py` | 改 | `PLATFORM_COMMENT_SPEC["ks"]` |
| `backend/routers/api.py` | 改 | `_normalize_platform` 加 ks 分支 |
| `backend/tests/test_create_ks_tables.py` | 新建 | 迁移脚本纯逻辑测试 |
| `backend/tests/test_ks_sync_mapping.py` | 新建 | `_map_ks` 映射 + 注册面测试 |
| `backend/tests/test_ks_comment_loader.py` | 新建 | ks 评论路由（sqlite 内存库）测试 |
| `backend/tests/test_api_normalize_platform.py` | 改 | 加 ks 归一化用例 |
| `backend/tests/test_crawler_unique_indexes.py` | 改 | 断言 ks TARGETS 在位 |
| `frontend/src/views/AdminKeywordsView.vue` | 改 | 平台选项加快手 |
| `frontend/src/views/AdminRawPostsView.vue` | 改 | 筛选/标签/样式加快手 |
| `frontend/src/utils/postLink.js` | 改 | ks 站内搜索链接 |
| `frontend/src/views/SentimentView.vue` | 改 | 标签色 map 加快手 |

---

### Task 1: 建分支与基线确认

**Files:** 无代码改动。

- [ ] **Step 1: 确认工作树状态并建分支**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
git status --short   # 预期只有 M MediaCrawler/config/base_config.py（冒烟调参）与未跟踪 plans 文档
git checkout -b feature/ks-crawler-retrofit
```

- [ ] **Step 2: 跑两侧基线**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\MediaCrawler"
.\.venv\Scripts\python.exe -m pytest tests -q
```
Expected: `1 failed, 133 passed`（失败的是 `test_store_factory.py::test_create_excel_store`，既有）。

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -t . -q
```
Expected: `Ran 176 tests ... OK`。基线数字如有出入，停下来报告，不要继续。

---

### Task 2: models 唯一约束 + comment_count 列 + 入库持久化

**Files:**
- Modify: `MediaCrawler/database/models.py:187`（video_id）、`:207`（comment_id）、`:193` 后插入新列
- Modify: `MediaCrawler/store/kuaishou/__init__.py:69` 附近
- Test: `MediaCrawler/tests/test_kuaishou_store.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `MediaCrawler/tests/test_kuaishou_store.py`：

```python
# -*- coding: utf-8 -*-
"""快手 store 模块级行为测试：commentCount 持久化透传 + 批量已存查询。

不连真实数据库：store 工厂/get_session 均打桩。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

import config
from store import kuaishou as kuaishou_store
from store.kuaishou._store_impl import KuaishouDbStoreImplement
from var import source_keyword_var


def make_feed(video_id: str, caption: str, ts_ms: int = 1_781_193_600_000) -> dict:
    return {
        "type": 1,
        "author": {"id": "u1", "name": "某同学", "headerUrl": ""},
        "photo": {
            "id": video_id,
            "caption": caption,
            "originCaption": caption,
            "timestamp": ts_ms,
            "realLikeCount": 10,
            "viewCount": 100,
            "commentCount": 3,
            "coverUrl": "",
            "photoUrl": "",
        },
    }


@pytest.mark.asyncio
async def test_update_kuaishou_video_persists_comment_count(monkeypatch):
    """GraphQL 返回的 commentCount 现状被丢弃；改造后应随 content_item 入库。"""
    captured: dict = {}

    class FakeStore:
        async def store_content(self, content_item):
            captured.update(content_item)

    monkeypatch.setattr(
        kuaishou_store.KuaishouStoreFactory, "create_store", staticmethod(lambda: FakeStore())
    )
    source_keyword_var.set("中山大学 宿舍")

    await kuaishou_store.update_kuaishou_video(make_feed("3xabc", "中山大学宿舍vlog"))

    assert captured["video_id"] == "3xabc"
    assert captured["comment_count"] == "3"


def _fake_get_session_factory(session):
    @asynccontextmanager
    async def _fake_get_session():
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

    return _fake_get_session


def _ids_result(ids):
    result = MagicMock(name="fake_result")
    result.scalars.return_value.all.return_value = ids
    return result


class TestKuaishouBatchGetExistingNoteIds:
    @pytest.mark.asyncio
    async def test_returns_existing_ids(self, monkeypatch):
        fake_session = MagicMock(name="fake_session")
        fake_session.execute = AsyncMock(return_value=_ids_result(["3xa", "3xb"]))
        fake_session.rollback = AsyncMock()
        monkeypatch.setattr(
            "store.kuaishou._store_impl.get_session", _fake_get_session_factory(fake_session)
        )
        store = KuaishouDbStoreImplement()

        existing = await store.batch_get_existing_note_ids(["3xa", "3xb", "3xc", " ", ""])

        assert existing == {"3xa", "3xb"}

    @pytest.mark.asyncio
    async def test_empty_input_short_circuits(self, monkeypatch):
        fake_session = MagicMock(name="fake_session")
        fake_session.execute = AsyncMock()
        monkeypatch.setattr(
            "store.kuaishou._store_impl.get_session", _fake_get_session_factory(fake_session)
        )
        store = KuaishouDbStoreImplement()

        assert await store.batch_get_existing_note_ids([]) == set()
        assert await store.batch_get_existing_note_ids(["", "  "]) == set()
        fake_session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_module_wrapper_degrades_when_backend_unsupported(self, monkeypatch):
        """非 db 系后端没有该方法：模块包装优雅降级返回空集，不抛异常。"""
        monkeypatch.setattr(
            kuaishou_store.KuaishouStoreFactory, "create_store", staticmethod(lambda: object())
        )

        assert await kuaishou_store.batch_get_existing_note_ids(["3xa"]) == set()
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\MediaCrawler"
.\.venv\Scripts\python.exe -m pytest tests/test_kuaishou_store.py -v
```
Expected: FAIL —— `test_update_kuaishou_video_persists_comment_count` 报 `KeyError: 'comment_count'`；`TestKuaishouBatchGetExistingNoteIds` 三例报 `AttributeError`（方法/包装不存在）。

- [ ] **Step 3: 改 models.py（三处）**

`MediaCrawler/database/models.py` KuaishouVideo/KuaishouVideoComment：

```python
    video_id = Column(String(255), unique=True, index=True, comment='视频ID')
```
（原 `Column(String(255), index=True, ...)` 加 `unique=True`）

`viewd_count` 行后新增：

```python
    comment_count = Column(Text, comment='评论数')
```

KuaishouVideoComment：

```python
    comment_id = Column(BigInteger, unique=True, index=True, comment='评论ID')
```

- [ ] **Step 4: 改 store/kuaishou/__init__.py**

`update_kuaishou_video` 的 `save_content_item` 字典里、`"viewd_count"` 行后加：

```python
        "comment_count": str(photo_info.get("commentCount") or 0),
```

文件顶部 import 区改为（加 Set、utils 已有）：

```python
from typing import Dict, List, Set
```

（原 `from typing import List`；`Dict`/`utils` 经 `from ._store_impl import *` 已可用，但显式导入更稳。）

文件末尾（`save_creator` 之后）新增模块包装，照抄知乎模式：

```python
async def batch_get_existing_note_ids(note_ids: List[str]) -> Set[str]:
    """批量查询已入库的快手 video_id；非 db 系存储优雅降级返回空集（仿知乎模式）。"""
    normalized_note_ids = list(
        {
            str(note_id).strip()
            for note_id in note_ids
            if str(note_id).strip()
        }
    )
    if not normalized_note_ids:
        return set()

    store = KuaishouStoreFactory.create_store()
    batch_getter = getattr(store, "batch_get_existing_note_ids", None)
    if not callable(batch_getter):
        utils.logger.info(
            f"[store.kuaishou.batch_get_existing_note_ids] Current store backend does not support note existence lookup, "
            f"save option: {config.SAVE_DATA_OPTION}"
        )
        return set()

    existing_note_ids = await batch_getter(normalized_note_ids)
    utils.logger.info(
        f"[store.kuaishou.batch_get_existing_note_ids] Checked {len(normalized_note_ids)} candidate video_ids, "
        f"existing in store: {len(existing_note_ids)}"
    )
    return existing_note_ids
```

- [ ] **Step 5: 给 KuaishouDbStoreImplement 加批量查询方法**

`MediaCrawler/store/kuaishou/_store_impl.py`，`KuaishouDbStoreImplement` 类末尾（`store_comment` 之后）：

```python
    async def batch_get_existing_note_ids(self, note_ids):
        normalized_note_ids = {
            str(note_id).strip()
            for note_id in note_ids
            if str(note_id).strip()
        }
        if not normalized_note_ids:
            return set()

        async with get_session() as session:
            stmt = select(KuaishouVideo.video_id).where(
                KuaishouVideo.video_id.in_(list(normalized_note_ids))
            )
            result = await session.execute(stmt)
            return {
                str(video_id).strip()
                for video_id in result.scalars().all()
                if str(video_id).strip()
            }
```

- [ ] **Step 6: 跑测试确认通过 + 全量回归**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_kuaishou_store.py -v
.\.venv\Scripts\python.exe -m pytest tests -q
```
Expected: 新文件 4 passed；全量 `1 failed, 137 passed`（只多不少，失败仍是 excel 既有）。

- [ ] **Step 7: 提交**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
git add MediaCrawler/database/models.py MediaCrawler/store/kuaishou/__init__.py MediaCrawler/store/kuaishou/_store_impl.py MediaCrawler/tests/test_kuaishou_store.py
git commit -m "feat(ks): 唯一约束+comment_count 列持久化+批量已存查询"
```

---

### Task 3: Db store IntegrityError 自愈

**Files:**
- Modify: `MediaCrawler/store/kuaishou/_store_impl.py:95-136`
- Test: `MediaCrawler/tests/test_store_integrity_fallback.py`（追加类）

- [ ] **Step 1: 写失败测试**

在 `MediaCrawler/tests/test_store_integrity_fallback.py` 末尾追加（该文件已有 `_fake_get_session_factory`/`_select_result` 帮手，顶部 import 区加一行 `from store.kuaishou._store_impl import KuaishouDbStoreImplement`）：

```python
class TestKuaishouIntegrityFallback:
    """ks：改造后走 zhihu 同构自愈——insert flush 冲突 → rollback → 重查 → 转 update。"""

    @pytest.mark.asyncio
    async def test_store_content_falls_back_to_update_on_integrity_error(self, monkeypatch):
        existing_after_race = MagicMock(name="existing_video")
        fake_session = MagicMock(name="fake_session")
        # 第一次 select：不存在（走 insert）；冲突后第二次 select：竞态胜出方已在库
        fake_session.execute = AsyncMock(
            side_effect=[_select_result(None), _select_result(existing_after_race)]
        )
        fake_session.add = MagicMock()
        fake_session.flush = AsyncMock(side_effect=IntegrityError("dup", None, None))
        fake_session.rollback = AsyncMock()
        fake_session.commit = AsyncMock()
        monkeypatch.setattr(
            "store.kuaishou._store_impl.get_session", _fake_get_session_factory(fake_session)
        )

        store = KuaishouDbStoreImplement()
        # 关键断言：异常不逃逸，退化为对已有行的 update
        await store.store_content({"video_id": "3xabc", "title": "t", "add_ts": 1})

        fake_session.flush.assert_awaited_once()
        fake_session.rollback.assert_awaited_once()
        assert fake_session.execute.await_count == 2
        fake_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_store_comment_falls_back_to_update_on_integrity_error(self, monkeypatch):
        existing_after_race = MagicMock(name="existing_comment")
        fake_session = MagicMock(name="fake_session")
        fake_session.execute = AsyncMock(
            side_effect=[_select_result(None), _select_result(existing_after_race)]
        )
        fake_session.add = MagicMock()
        fake_session.flush = AsyncMock(side_effect=IntegrityError("dup", None, None))
        fake_session.rollback = AsyncMock()
        fake_session.commit = AsyncMock()
        monkeypatch.setattr(
            "store.kuaishou._store_impl.get_session", _fake_get_session_factory(fake_session)
        )

        store = KuaishouDbStoreImplement()
        await store.store_comment({"comment_id": "777", "video_id": "3xabc"})

        fake_session.flush.assert_awaited_once()
        fake_session.rollback.assert_awaited_once()
        assert fake_session.execute.await_count == 2
        fake_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_store_content_normal_insert_does_not_flush_fallback(self, monkeypatch):
        """反向对照：无冲突时正常 insert，一次 select、不 rollback。"""
        fake_session = MagicMock(name="fake_session")
        fake_session.execute = AsyncMock(return_value=_select_result(None))
        fake_session.add = MagicMock()
        fake_session.flush = AsyncMock()
        fake_session.rollback = AsyncMock()
        fake_session.commit = AsyncMock()
        monkeypatch.setattr(
            "store.kuaishou._store_impl.get_session", _fake_get_session_factory(fake_session)
        )

        store = KuaishouDbStoreImplement()
        await store.store_content({"video_id": "3xabc"})

        fake_session.add.assert_called_once()
        fake_session.rollback.assert_not_awaited()
        fake_session.commit.assert_awaited_once()
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_store_integrity_fallback.py -v -k Kuaishou
```
Expected: 前两例 FAIL——当前实现没有 flush/自愈，`IntegrityError` 未触发（`flush.assert_awaited_once` 失败）或直接从 commit 逃逸。第三例可能已过（现状即普通 insert 但无 flush，`flush.assert_...` 未涉及故通过）——确认失败集中在前两例即可。

- [ ] **Step 3: 实现自愈**

`MediaCrawler/store/kuaishou/_store_impl.py`：

import 区加：

```python
from sqlalchemy.exc import IntegrityError
```

`KuaishouDbStoreImplement.store_content` 整体替换为：

```python
    async def store_content(self, content_item: Dict):
        """
        Kuaishou content DB storage implementation
        Args:
            content_item: content item dict
        """
        video_id = content_item.get("video_id")
        async with get_session() as session:
            result = await session.execute(select(KuaishouVideo).where(KuaishouVideo.video_id == video_id))
            video_detail = result.scalar_one_or_none()

            if not video_detail:
                content_item["add_ts"] = utils.get_current_timestamp()
                new_content = KuaishouVideo(**content_item)
                session.add(new_content)
                try:
                    # 立即 flush 让唯一约束冲突在 try/except 范围内抛出（仿 xhs/zhihu 自愈模式）
                    await session.flush()
                except IntegrityError:
                    # 并发竞态：另一协程刚插入同一 video_id；唯一约束兜底，这里退化为更新
                    await session.rollback()
                    result = await session.execute(
                        select(KuaishouVideo).where(KuaishouVideo.video_id == video_id)
                    )
                    video_detail = result.scalar_one_or_none()
                    if video_detail:
                        for key, value in content_item.items():
                            if key == "add_ts":
                                # 保留胜出方的首次入库时间，勿被竞态失败方覆盖
                                continue
                            if hasattr(video_detail, key):
                                setattr(video_detail, key, value)
            else:
                for key, value in content_item.items():
                    if hasattr(video_detail, key):
                        setattr(video_detail, key, value)
            await session.commit()
```

`store_comment` 同构替换：

```python
    async def store_comment(self, comment_item: Dict):
        """
        Kuaishou comment DB storage implementation
        Args:
            comment_item: comment item dict
        """
        comment_id = comment_item.get("comment_id")
        async with get_session() as session:
            result = await session.execute(
                select(KuaishouVideoComment).where(KuaishouVideoComment.comment_id == comment_id))
            comment_detail = result.scalar_one_or_none()

            if not comment_detail:
                comment_item["add_ts"] = utils.get_current_timestamp()
                new_comment = KuaishouVideoComment(**comment_item)
                session.add(new_comment)
                try:
                    # 立即 flush 让唯一约束冲突在 try/except 范围内抛出（仿 xhs/zhihu 自愈模式）
                    await session.flush()
                except IntegrityError:
                    # 并发竞态：另一协程刚插入同一 comment_id；唯一约束兜底，这里退化为更新
                    await session.rollback()
                    result = await session.execute(
                        select(KuaishouVideoComment).where(KuaishouVideoComment.comment_id == comment_id)
                    )
                    comment_detail = result.scalar_one_or_none()
                    if comment_detail:
                        for key, value in comment_item.items():
                            if key == "add_ts":
                                # 保留胜出方的首次入库时间，勿被竞态失败方覆盖
                                continue
                            if hasattr(comment_detail, key):
                                setattr(comment_detail, key, value)
            else:
                for key, value in comment_item.items():
                    if hasattr(comment_detail, key):
                        setattr(comment_detail, key, value)
            await session.commit()
```

- [ ] **Step 4: 跑测试确认通过 + 全量**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_store_integrity_fallback.py -v
.\.venv\Scripts\python.exe -m pytest tests -q
```
Expected: 该文件全部 PASS（含既有 xhs/weibo/tieba 用例）；全量 `1 failed, 140 passed`。

- [ ] **Step 5: 提交**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
git add MediaCrawler/store/kuaishou/_store_impl.py MediaCrawler/tests/test_store_integrity_fallback.py
git commit -m "feat(ks): Db store 唯一键冲突自愈（flush+rollback 转 update）"
```

---

### Task 4: base_config 加 KS_SKIP_EXISTING_NOTES（stash 舞步）

**Files:**
- Modify: `MediaCrawler/config/base_config.py:121` 附近

- [ ] **Step 1: stash 冒烟调参**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
git stash push -- MediaCrawler/config/base_config.py
git diff --stat   # 确认 base_config 已无未提交改动
```

- [ ] **Step 2: 加配置行**

`MediaCrawler/config/base_config.py`，找到：

```python
WEIBO_SKIP_EXISTING_NOTES = True
TIEBA_SKIP_EXISTING_NOTES = True
ZHIHU_SKIP_EXISTING_NOTES = True
```

改为：

```python
WEIBO_SKIP_EXISTING_NOTES = True
TIEBA_SKIP_EXISTING_NOTES = True
ZHIHU_SKIP_EXISTING_NOTES = True
KS_SKIP_EXISTING_NOTES = True
```

- [ ] **Step 3: 提交并恢复冒烟调参**

```powershell
git add MediaCrawler/config/base_config.py
git commit -m "feat(ks): 爬取阶段跳过已入库配置 KS_SKIP_EXISTING_NOTES"
git stash pop
git diff MediaCrawler/config/base_config.py   # 确认只剩 CDP_CONNECT_EXISTING=False 与 CRAWLER_MAX_NOTES_COUNT=40 两处冒烟差异
```
若 `stash pop` 冲突（不应发生，两处改动相距 15+ 行）：手动保留提交版 + 重新把那两行改回冒烟值，`git checkout --theirs` 不适用，直接编辑解决。

---

### Task 5: 纯函数 resolve_next_pcursor

**Files:**
- Modify: `MediaCrawler/media_platform/kuaishou/help.py`（文件末尾追加）
- Test: `MediaCrawler/tests/test_kuaishou_help.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `MediaCrawler/tests/test_kuaishou_help.py`：

```python
# -*- coding: utf-8 -*-
"""快手翻页游标决策纯函数测试。

上游原实现把页码当游标传且丢弃服务端真实 pcursor；改造后优先服务端游标，
"no_more" → None（停止翻页），缺失回退页码字符串。
"""

from media_platform.kuaishou.help import resolve_next_pcursor


def test_prefers_server_pcursor():
    assert resolve_next_pcursor("opaque-cursor-xyz", 3) == "opaque-cursor-xyz"


def test_no_more_returns_none():
    assert resolve_next_pcursor("no_more", 3) is None


def test_missing_falls_back_to_page_number():
    assert resolve_next_pcursor(None, 4) == "4"
    assert resolve_next_pcursor("", 4) == "4"
    assert resolve_next_pcursor("   ", 4) == "4"
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_kuaishou_help.py -v
```
Expected: FAIL，`ImportError: cannot import name 'resolve_next_pcursor'`。

- [ ] **Step 3: 实现**

`MediaCrawler/media_platform/kuaishou/help.py` 文件末尾追加：

```python
def resolve_next_pcursor(response_pcursor, next_page: int):
    """决定下一页游标：优先服务端真实 pcursor；"no_more" → None（停止翻页）；缺失回退页码。

    上游原实现把页码当游标传（服务端兼容数字页码），但丢弃了响应里的真实 pcursor，
    也不识别 "no_more" 终止信号。这里两者兼得：有真游标用真游标，没有退回页码。
    """
    value = str(response_pcursor or "").strip()
    if value == "no_more":
        return None
    if value:
        return value
    return str(next_page)
```

- [ ] **Step 4: 跑测试确认通过**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_kuaishou_help.py -v
```
Expected: 3 passed。

- [ ] **Step 5: 提交**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
git add MediaCrawler/media_platform/kuaishou/help.py MediaCrawler/tests/test_kuaishou_help.py
git commit -m "feat(ks): 翻页游标决策纯函数（真游标优先/no_more 停止/页码回退）"
```

---

### Task 6: core.py search() 管线重写

**Files:**
- Modify: `MediaCrawler/media_platform/kuaishou/core.py`（imports + search() 整体替换 + 新增 `_filter_and_store_page`）
- Test: `MediaCrawler/tests/test_kuaishou_search_flow.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `MediaCrawler/tests/test_kuaishou_search_flow.py`：

```python
# -*- coding: utf-8 -*-
"""快手搜索管线测试，仿 test_zhihu_search_flow.py。

_filter_and_store_page：窗口 → 主题相关 → 营销负面 → 跳过已入库 → 入库计数；
page_resolved_ts 在一切跳过/过滤决策之外收集。
search()：游标 no_more 停止、配额按入库数、异常只中断当前关键词，均落 run_history。
词表用真实 config（中山大学相关词 / 考研机构负面词 / 求推荐救回词）。
"""

from typing import Dict, List

import pytest

import config
from media_platform.kuaishou.core import KuaishouCrawler
from media_platform.kuaishou.exception import DataFetchError
from store import kuaishou as kuaishou_store
from store import run_history as run_history_store
from tools.run_history import RunState

TS_MS = 1_781_193_600_000  # 2026-06-12 前后，仅需相对大小正确


def make_feed(video_id: str, caption: str, ts_ms: int = TS_MS) -> Dict:
    return {
        "type": 1,
        "author": {"id": "u1", "name": "某同学", "headerUrl": ""},
        "photo": {
            "id": video_id,
            "caption": caption,
            "originCaption": caption,
            "timestamp": ts_ms,
            "realLikeCount": 10,
            "viewCount": 100,
            "commentCount": 3,
            "coverUrl": "",
            "photoUrl": "",
        },
    }


def make_run_state() -> RunState:
    return RunState(platform="ks", source_keyword="中山大学 宿舍", started_at=0)


@pytest.fixture
def stored_ids(monkeypatch) -> List[str]:
    """默认桩：入库全部成功并记录 video_id；已存查询返回空集。"""
    saved: List[str] = []

    async def fake_update_kuaishou_video(video_item):
        saved.append(video_item["photo"]["id"])

    async def fake_batch_get_existing_note_ids(note_ids):
        return set()

    monkeypatch.setattr(kuaishou_store, "update_kuaishou_video", fake_update_kuaishou_video)
    monkeypatch.setattr(kuaishou_store, "batch_get_existing_note_ids", fake_batch_get_existing_note_ids)
    return saved


# ---------- _filter_and_store_page ----------

@pytest.mark.asyncio
async def test_topic_filter_keeps_relevant_and_drops_unrelated(stored_ids):
    crawler = KuaishouCrawler()
    run_state = make_run_state()
    feeds = [
        make_feed("a1", "中山大学宿舍条件怎么样"),
        make_feed("a2", "北京胡同游玩vlog"),
    ]

    kept_ids, page_resolved_ts = await crawler._filter_and_store_page(
        feeds, None, None, False, run_state
    )

    assert kept_ids == ["a1"]
    assert run_state.items_stored == 1
    assert len(page_resolved_ts) == 2  # 被主题过滤的条目仍贡献发布时间


@pytest.mark.asyncio
async def test_marketing_noise_dropped_but_rescue_terms_keep(stored_ids):
    crawler = KuaishouCrawler()
    run_state = make_run_state()
    feeds = [
        make_feed("m1", "中山大学考研机构春季班火热报名"),
        make_feed("m2", "中山大学有没有靠谱的考研机构求推荐"),
    ]

    kept_ids, _ = await crawler._filter_and_store_page(feeds, None, None, False, run_state)

    assert kept_ids == ["m2"]
    assert run_state.items_stored == 1


@pytest.mark.asyncio
async def test_window_filter_drops_old_but_contributes_page_ts(stored_ids):
    crawler = KuaishouCrawler()
    run_state = make_run_state()
    window_lo = TS_MS
    old_ts = TS_MS - 10 * 24 * 3600 * 1000
    feeds = [
        make_feed("old1", "中山大学宿舍条件怎么样", ts_ms=old_ts),
        make_feed("new1", "中山大学食堂测评", ts_ms=TS_MS + 100),
    ]

    kept_ids, page_resolved_ts = await crawler._filter_and_store_page(
        feeds, window_lo, None, True, run_state
    )

    assert kept_ids == ["new1"]
    assert run_state.items_stored == 1
    assert old_ts in page_resolved_ts  # 窗口过滤的条目仍贡献发布时间


@pytest.mark.asyncio
async def test_skip_existing_not_stored_but_contributes_page_ts(stored_ids, monkeypatch):
    async def fake_batch_get_existing_note_ids(note_ids):
        return {"a1"}

    monkeypatch.setattr(kuaishou_store, "batch_get_existing_note_ids", fake_batch_get_existing_note_ids)
    monkeypatch.setattr(config, "KS_SKIP_EXISTING_NOTES", True, raising=False)

    crawler = KuaishouCrawler()
    run_state = make_run_state()
    feeds = [
        make_feed("a1", "中山大学宿舍条件怎么样", ts_ms=TS_MS),
        make_feed("a2", "中山大学食堂测评", ts_ms=TS_MS + 100),
    ]

    kept_ids, page_resolved_ts = await crawler._filter_and_store_page(
        feeds, None, None, False, run_state
    )

    assert kept_ids == ["a2"]
    assert run_state.items_stored == 1
    assert TS_MS in page_resolved_ts


@pytest.mark.asyncio
async def test_store_failure_not_counted(stored_ids, monkeypatch):
    async def flaky_update(video_item):
        if video_item["photo"]["id"] == "a1":
            raise RuntimeError("db down")
        stored_ids.append(video_item["photo"]["id"])

    monkeypatch.setattr(kuaishou_store, "update_kuaishou_video", flaky_update)

    crawler = KuaishouCrawler()
    run_state = make_run_state()
    feeds = [
        make_feed("a1", "中山大学宿舍条件怎么样"),
        make_feed("a2", "中山大学食堂测评"),
    ]

    kept_ids, _ = await crawler._filter_and_store_page(feeds, None, None, False, run_state)

    assert kept_ids == ["a2"]
    assert run_state.items_stored == 1


# ---------- search() 停止语义 ----------

class FakeKsClient:
    """按预置页序列应答；页数用完后返回 no_more 空页。"""

    def __init__(self, pages: List[Dict]):
        self._pages = list(pages)
        self.calls: List[str] = []

    async def search_info_by_keyword(self, keyword: str, pcursor: str, search_session_id: str = ""):
        self.calls.append(pcursor)
        if self._pages:
            return self._pages.pop(0)
        return {"visionSearchPhoto": {"result": 1, "feeds": [], "pcursor": "no_more"}}


def make_page(feeds: List[Dict], pcursor: str) -> Dict:
    return {"visionSearchPhoto": {"result": 1, "feeds": feeds, "pcursor": pcursor, "searchSessionId": "sid-1"}}


@pytest.fixture
def search_env(monkeypatch, stored_ids):
    """search() 级公共桩：单关键词、无窗口、无 jitter、不抓评论、历史落行捕获。"""
    rows: List[Dict] = []

    async def fake_save_history(row):
        rows.append(row)

    monkeypatch.setattr(run_history_store, "save_crawler_run_history", fake_save_history)
    monkeypatch.setattr(config, "KEYWORDS", "宿舍")
    monkeypatch.setattr(config, "START_PAGE", 1)
    monkeypatch.setattr(config, "CRAWLER_MAX_NOTES_COUNT", 20)
    monkeypatch.setattr(config, "CRAWL_MAX_PAGES_PER_KEYWORD", 10, raising=False)
    monkeypatch.setattr(config, "CRAWLER_MAX_SLEEP_SEC", 0)
    monkeypatch.setattr(config, "ENABLE_GET_COMMENTS", False)
    monkeypatch.setattr(config, "CRAWL_PUBLISH_TIME_START", "", raising=False)
    monkeypatch.setattr(config, "CRAWL_PUBLISH_TIME_END", "", raising=False)
    monkeypatch.setattr(config, "SEARCH_START_PAGE_JITTER_PROB", 0.0, raising=False)
    return rows


@pytest.mark.asyncio
async def test_search_stops_on_no_more_and_saves_history(search_env, stored_ids):
    rows = search_env
    crawler = KuaishouCrawler()
    crawler.ks_client = FakeKsClient(
        [make_page([make_feed("v1", "中山大学宿舍vlog")], pcursor="no_more")]
    )

    await crawler.search()

    assert stored_ids == ["v1"]
    assert len(rows) == 1
    assert rows[0]["platform"] == "ks"
    assert rows[0]["stop_reason"] == "empty_page"  # 服务端明示无更多结果
    assert rows[0]["pages_fetched"] == 1
    assert rows[0]["items_stored"] == 1


@pytest.mark.asyncio
async def test_search_quota_counted_by_stored(search_env, stored_ids):
    rows = search_env
    feeds = [make_feed(f"v{i}", f"中山大学宿舍vlog第{i}期") for i in range(20)]
    crawler = KuaishouCrawler()
    crawler.ks_client = FakeKsClient([make_page(feeds, pcursor="next-cursor")])

    await crawler.search()

    assert len(stored_ids) == 20
    assert rows[0]["stop_reason"] == "quota_reached"
    assert rows[0]["pages_fetched"] == 1  # 配额已满，不再翻第二页


@pytest.mark.asyncio
async def test_search_exception_only_breaks_current_keyword(search_env, stored_ids, monkeypatch):
    rows = search_env
    monkeypatch.setattr(config, "KEYWORDS", "宿舍,食堂")

    class ExplodingThenOkClient(FakeKsClient):
        async def search_info_by_keyword(self, keyword, pcursor, search_session_id=""):
            if "宿舍" in keyword:
                raise DataFetchError("boom")
            return await super().search_info_by_keyword(keyword, pcursor, search_session_id)

    crawler = KuaishouCrawler()
    crawler.ks_client = ExplodingThenOkClient(
        [make_page([make_feed("v1", "中山大学食堂测评")], pcursor="no_more")]
    )

    await crawler.search()

    assert stored_ids == ["v1"]
    assert len(rows) == 2
    assert rows[0]["stop_reason"] == "exception"
    assert rows[1]["stop_reason"] == "empty_page"
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_kuaishou_search_flow.py -v
```
Expected: FAIL——`AttributeError: 'KuaishouCrawler' object has no attribute '_filter_and_store_page'`；search 级用例因旧实现无 run_history/停止语义而断言失败或报错。

- [ ] **Step 3: 重写 core.py**

`MediaCrawler/media_platform/kuaishou/core.py`：

**(a)** import 区补齐——`import random` 加到 `import os` 之后（删除现有第 23 行的 `# import random ...` 注释行）；在 `from store import kuaishou as kuaishou_store` 之后加：

```python
from store import run_history as run_history_store
```

在 `from tools.cdp_browser import CDPBrowserManager` 之后加：

```python
from tools.crawl_quota import should_fetch_next_page
from tools.publish_time_window import is_within_window, parse_window
from tools.run_history import STOP_EMPTY_PAGE, STOP_EXCEPTION, STOP_QUOTA_REACHED, RunState
from tools.topic_scope import compose_topic_keyword, is_broad_keyword, is_marketing_noise, matches_topic
```

`from .help import ...` 行改为：

```python
from .help import parse_video_info_from_url, parse_creator_info_from_url, resolve_next_pcursor
```

**(b)** 在 `search()` 之前新增方法：

```python
    async def _filter_and_store_page(
        self,
        feeds: List[Dict],
        window_lo: Optional[int],
        window_hi: Optional[int],
        window_enabled: bool,
        run_state: RunState,
    ) -> Tuple[List[str], List[int]]:
        """单页搜索结果的过滤与入库：窗口 → 主题相关 → 营销负面 → 跳过已入库 → 逐条入库计数。

        返回（本页实际入库成功的 video_id 列表, page_resolved_ts）；page_resolved_ts 在一切
        跳过/过滤决策之外收集（快手结果非时间序，无整页早停，仅用于日志观测与口径一致）。
        """
        page_resolved_ts: List[int] = []
        kept: List[Dict] = []
        window_filtered = topic_filtered = marketing_filtered = 0
        topic_terms = getattr(config, "TOPIC_RELEVANCE_TERMS", [])
        for feed in feeds:
            photo: Dict = feed.get("photo") or {}
            if not photo.get("id"):
                continue
            # photo.timestamp 为毫秒 epoch（缺失/0 视为 unknown，按 PUBLISH_TIME_KEEP_UNKNOWN 处理）
            ts_ms = int(photo.get("timestamp") or 0) or None
            if ts_ms is not None:
                page_resolved_ts.append(ts_ms)
            if window_enabled and not is_within_window(
                ts_ms, window_lo, window_hi, config.PUBLISH_TIME_KEEP_UNKNOWN
            ):
                window_filtered += 1
                continue
            # 快手搜索结果自带全文文案，主题/营销过滤共用同组文本
            texts = [photo.get("caption", ""), photo.get("originCaption", "")]
            if getattr(config, "ENABLE_TOPIC_RELEVANCE_FILTER", False) and not matches_topic(texts, topic_terms):
                topic_filtered += 1
                continue
            # 营销内容负面词表（第三道防线）：命中负面词且无救回词的推广内容不入库
            if getattr(config, "ENABLE_TOPIC_NEGATIVE_FILTER", False) and is_marketing_noise(
                texts,
                getattr(config, "TOPIC_NEGATIVE_TERMS", []),
                getattr(config, "TOPIC_NEGATIVE_RESCUE_TERMS", []),
            ):
                marketing_filtered += 1
                continue
            kept.append(feed)

        if window_filtered:
            utils.logger.info(f"[KuaishouCrawler.search] 时间窗口过滤：跳过 {window_filtered} 条窗口外内容")
        if topic_filtered:
            utils.logger.info(f"[KuaishouCrawler.search] 主题过滤：跳过 {topic_filtered} 条与主题无关的内容")
        if marketing_filtered:
            utils.logger.info(f"[KuaishouCrawler.search] 营销内容过滤：跳过 {marketing_filtered} 条")

        # 爬取阶段跳过已入库视频（省请求额度）：必须在过滤后、入库与评论抓取之前
        if kept and bool(getattr(config, "KS_SKIP_EXISTING_NOTES", True)):
            existing = await kuaishou_store.batch_get_existing_note_ids(
                [str((feed.get("photo") or {}).get("id") or "").strip() for feed in kept]
            )
            if existing:
                before = len(kept)
                kept = [
                    feed for feed in kept
                    if str((feed.get("photo") or {}).get("id") or "").strip() not in existing
                ]
                if before - len(kept):
                    utils.logger.info(f"[KuaishouCrawler.search] 跳过已入库 {before - len(kept)} 条")

        stored_ids: List[str] = []
        for feed in kept:
            video_id = str((feed.get("photo") or {}).get("id"))
            try:
                await kuaishou_store.update_kuaishou_video(video_item=feed)
                stored_ids.append(video_id)
                run_state.add_stored(1)  # 真正入库条数（过滤/跳过后）
            except Exception as ex:
                utils.logger.error(
                    f"[KuaishouCrawler.search] store failed video_id={video_id}: {ex}"
                )
        return stored_ids, page_resolved_ts
```

**(c)** `search()` 整体替换为：

```python
    async def search(self):
        utils.logger.info("[KuaishouCrawler.search] Begin search kuaishou keywords")
        ks_limit_count = 20  # kuaishou limit page fixed value
        if config.CRAWLER_MAX_NOTES_COUNT < ks_limit_count:
            config.CRAWLER_MAX_NOTES_COUNT = ks_limit_count
        start_page = config.START_PAGE
        window_lo, window_hi = parse_window(config.CRAWL_PUBLISH_TIME_START, config.CRAWL_PUBLISH_TIME_END)
        window_enabled = window_lo is not None or window_hi is not None

        for keyword in config.KEYWORDS.split(","):
            # 宽泛词拦截（用原始词判定，需在主题限定组合之前）：裸主题词对过滤零区分力
            if is_broad_keyword(
                keyword,
                getattr(config, "CRAWL_TOPIC_QUALIFIER", ""),
                getattr(config, "TOPIC_RELEVANCE_TERMS", []),
            ) and not getattr(config, "ALLOW_BROAD_KEYWORDS", False):
                utils.logger.warning(
                    f"[KuaishouCrawler.search] 宽泛词已跳过：{keyword.strip()}（设 ALLOW_BROAD_KEYWORDS=True 可放行）"
                )
                continue
            composed_keyword = compose_topic_keyword(
                keyword,
                getattr(config, "CRAWL_TOPIC_QUALIFIER", ""),
                getattr(config, "TOPIC_RELEVANCE_TERMS", []),
            )
            if composed_keyword != keyword.strip():
                utils.logger.info(f"[KuaishouCrawler.search] 主题限定：{keyword} → {composed_keyword}")
            keyword = composed_keyword
            source_keyword_var.set(keyword)
            utils.logger.info(f"[KuaishouCrawler.search] Current search keyword: {keyword}")

            # 防饥饿：快手无排序参数（恒定综合排序），无条件参与起始页随机偏移；
            # 游标兼容数字页码，偏移直接从偏移后的页码起步（跳过的页不发请求、不计数）
            keyword_start_page = start_page
            if random.random() < float(getattr(config, "SEARCH_START_PAGE_JITTER_PROB", 0.0)):
                jitter = random.randint(1, int(getattr(config, "SEARCH_START_PAGE_JITTER_MAX", 1)))
                keyword_start_page += jitter
                utils.logger.info(f"[KuaishouCrawler.search] 防饥饿起始页偏移 +{jitter} → 从第 {keyword_start_page} 页开始")

            # 通用爬取历史：本关键词一轮搜索写一行，try/except/finally 保证异常路径也落一行
            run_state = RunState(
                platform="ks",
                source_keyword=keyword,
                started_at=int(utils.get_current_timestamp()),
            )
            search_session_id = ""
            page = keyword_start_page
            pcursor: Optional[str] = str(keyword_start_page)
            try:
                # 配额按"新增入库条数"计（不再按页数），被过滤/跳过已入库的内容不烧配额；
                # 页数保护上限防止贫瘠词无限翻页
                while should_fetch_next_page(
                    run_state.items_stored,
                    run_state.pages_fetched,
                    config.CRAWLER_MAX_NOTES_COUNT,
                    int(getattr(config, "CRAWL_MAX_PAGES_PER_KEYWORD", 10)),
                ):
                    utils.logger.info(
                        f"[KuaishouCrawler.search] search kuaishou keyword: {keyword}, page: {page}, pcursor: {pcursor}"
                    )
                    videos_res = await self.ks_client.search_info_by_keyword(
                        keyword=keyword,
                        pcursor=pcursor,
                        search_session_id=search_session_id,
                    )
                    run_state.add_page()
                    vision_search_photo: Dict = (videos_res or {}).get("visionSearchPhoto") or {}
                    feeds = vision_search_photo.get("feeds") or []
                    run_state.add_seen(len(feeds))
                    if not videos_res or vision_search_photo.get("result") != 1 or not feeds:
                        # 原实现此处 continue 且不翻页，是死循环隐患；空页/异常响应一律停止
                        utils.logger.info("[KuaishouCrawler.search] Search result empty or abnormal, stop paging")
                        run_state.mark_stop(STOP_EMPTY_PAGE)
                        break
                    search_session_id = vision_search_photo.get("searchSessionId", "") or search_session_id

                    stored_ids, _page_resolved_ts = await self._filter_and_store_page(
                        feeds, window_lo, window_hi, window_enabled, run_state
                    )

                    # Sleep after page navigation
                    await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                    utils.logger.info(
                        f"[KuaishouCrawler.search] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page}"
                    )

                    # 评论只对本页新入库视频抓取（跟随全局 ENABLE_GET_COMMENTS）
                    await self.batch_get_video_comments(stored_ids)

                    # 游标推进：优先服务端真实 pcursor（"no_more" → 停止），缺失回退页码
                    page += 1
                    next_cursor = resolve_next_pcursor(vision_search_photo.get("pcursor"), page)
                    if next_cursor is None:
                        utils.logger.info("[KuaishouCrawler.search] 服务端返回 no_more，无更多结果")
                        run_state.mark_stop(STOP_EMPTY_PAGE)
                        break
                    pcursor = next_cursor

                # 循环自然退出：入库配额达成归结 quota_reached（页保护上限触发则落 completed）
                if run_state.items_stored >= config.CRAWLER_MAX_NOTES_COUNT:
                    run_state.mark_stop(STOP_QUOTA_REACHED)
            except DataFetchError as ex:
                # 记 exception 落一行历史后继续下一关键词，不中断整场爬取
                run_state.mark_stop(STOP_EXCEPTION)
                utils.logger.error(f"[KuaishouCrawler.search] Search error, keyword: {keyword}, error: {ex}")
            except Exception:
                # 其他异常路径也落一行历史（stop_reason=exception），异常继续上抛
                run_state.mark_stop(STOP_EXCEPTION)
                raise
            finally:
                run_state.finish(int(utils.get_current_timestamp()))
                await run_history_store.save_crawler_run_history(run_state.as_row())
```

注意：`mark_stop` 首个合法原因生效（后续调用被忽略），所以 empty_page break 后走到 quota 判断也不会被覆盖——与微博/知乎口径一致。`Tuple`/`Optional`/`List`/`Dict` 已在文件顶部 typing import 中。

- [ ] **Step 4: 跑测试确认通过 + 全量**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_kuaishou_search_flow.py -v
.\.venv\Scripts\python.exe -m pytest tests -q
```
Expected: 新文件 8 passed；全量 `1 failed, 151 passed`（唯一失败仍是 excel 既有）。

- [ ] **Step 5: 提交**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
git add MediaCrawler/media_platform/kuaishou/core.py MediaCrawler/tests/test_kuaishou_search_flow.py
git commit -m "feat(ks): search() 微博模式管线重写（过滤/配额/历史/游标修正）"
```

---

### Task 7: 唯一索引 TARGETS + create_ks_tables 迁移脚本

**Files:**
- Modify: `scripts/add_crawler_unique_indexes.py:36-45`（TARGETS）
- Create: `scripts/create_ks_tables.py`
- Test: `backend/tests/test_create_ks_tables.py`（新建）、`backend/tests/test_crawler_unique_indexes.py`（追加）

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_create_ks_tables.py`：

```python
"""create_ks_tables 纯逻辑测试：建表/补列两态计划（不连库）。"""

import unittest

from scripts.create_ks_tables import ADD_COLUMN_DDL_BY_TABLE, TABLES, plan_ks_actions


class PlanKsActionsTests(unittest.TestCase):
    def test_tables_constant(self):
        self.assertEqual(TABLES, ("kuaishou_video", "kuaishou_video_comment"))
        self.assertIn("kuaishou_video", ADD_COLUMN_DDL_BY_TABLE)

    def test_missing_tables_planned_create(self):
        plans = plan_ks_actions(existing_tables=set(), columns_by_table={})
        self.assertEqual(
            [(p.table, p.action) for p in plans],
            [("kuaishou_video", "create"), ("kuaishou_video_comment", "create")],
        )

    def test_existing_table_missing_column_planned_add_column(self):
        plans = plan_ks_actions(
            existing_tables={"kuaishou_video", "kuaishou_video_comment"},
            columns_by_table={
                "kuaishou_video": {"id", "video_id", "liked_count"},
                "kuaishou_video_comment": {"id", "comment_id"},
            },
        )
        self.assertEqual(
            [(p.table, p.action) for p in plans],
            [("kuaishou_video", "add_column"), ("kuaishou_video_comment", "skip_exists")],
        )

    def test_existing_with_column_all_skip(self):
        plans = plan_ks_actions(
            existing_tables={"kuaishou_video", "kuaishou_video_comment"},
            columns_by_table={
                "kuaishou_video": {"id", "video_id", "comment_count"},
                "kuaishou_video_comment": {"id", "comment_id"},
            },
        )
        self.assertEqual(
            [(p.table, p.action) for p in plans],
            [("kuaishou_video", "skip_exists"), ("kuaishou_video_comment", "skip_exists")],
        )


if __name__ == "__main__":
    unittest.main()
```

在 `backend/tests/test_crawler_unique_indexes.py` 中找到 TARGETS 相关测试类，追加一个方法（import 区确认已有 `from scripts.add_crawler_unique_indexes import TARGETS`，没有则加）：

```python
    def test_ks_targets_present(self):
        self.assertIn(("kuaishou_video", "video_id", "uk_kuaishou_video_video_id"), TARGETS)
        self.assertIn(
            ("kuaishou_video_comment", "comment_id", "uk_kuaishou_video_comment_comment_id"),
            TARGETS,
        )
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe -m unittest backend.tests.test_create_ks_tables backend.tests.test_crawler_unique_indexes -v
```
Expected: FAIL——`ModuleNotFoundError: No module named 'scripts.create_ks_tables'`；`test_ks_targets_present` 断言失败。

- [ ] **Step 3: 改 TARGETS**

`scripts/add_crawler_unique_indexes.py` 的 TARGETS 列表末尾（zhihu 两行之后）追加：

```python
    ("kuaishou_video", "video_id", "uk_kuaishou_video_video_id"),
    ("kuaishou_video_comment", "comment_id", "uk_kuaishou_video_comment_comment_id"),
```

- [ ] **Step 4: 写 create_ks_tables.py**

新建 `scripts/create_ks_tables.py`（结构照抄 `scripts/create_zhihu_tables.py`，两态：建表 / 已存在则探测补列）：

```python
"""共享 MySQL 建快手两张原生表（幂等，逐表 plan/apply；表已存在时兼作 comment_count 补列迁移）。

用法：
  .venv/Scripts/python.exe scripts/create_ks_tables.py [--dry-run]

行为（单脚本覆盖建表/补列两态）：
  - 表不存在 -> CREATE TABLE ...（含 comment_count 列与唯一索引）。
  - 表已存在且缺 comment_count 列 -> ALTER TABLE ADD COLUMN（仅 kuaishou_video 有此新列需求）。
  - 表已存在且列齐 -> 跳过（幂等，可重复运行）。
  - 单表失败（权限/连接等）-> 记为 failed 继续处理其余表，脚本以退出码 1 结束。

DDL 与 MediaCrawler/database/models.py 的 KuaishouVideo/KuaishouVideoComment 逐列一致
（utf8mb4，InnoDB）；video_id/comment_id 唯一索引随建表自带（索引名沿用 SQLAlchemy 默认
命名 ix_表名_列名）——线上后跑 add_crawler_unique_indexes.py 时自动 skip。
结构照抄 scripts/create_zhihu_tables.py。
设计见 docs/superpowers/specs/2026-07-11-ks-crawler-retrofit-design.md §3。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from sqlalchemy import inspect, text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from backend.database import engine  # noqa: E402

TABLES: Tuple[str, ...] = ("kuaishou_video", "kuaishou_video_comment")

# 与 MediaCrawler/database/models.py::KuaishouVideo 逐列一致；desc 是 MySQL 保留字需反引号。
_KS_VIDEO_DDL = """\
CREATE TABLE kuaishou_video (
    id INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    user_id VARCHAR(64) COMMENT '用户ID',
    nickname TEXT COMMENT '用户昵称',
    avatar TEXT COMMENT '用户头像',
    add_ts BIGINT COMMENT '添加时间戳',
    last_modify_ts BIGINT COMMENT '最后修改时间戳',
    video_id VARCHAR(255) COMMENT '视频ID',
    video_type TEXT COMMENT '视频类型',
    title TEXT COMMENT '视频标题',
    `desc` TEXT COMMENT '视频描述',
    create_time BIGINT COMMENT '创建时间戳',
    liked_count TEXT COMMENT '点赞数',
    viewd_count TEXT COMMENT '观看数',
    comment_count TEXT COMMENT '评论数',
    video_url TEXT COMMENT '视频URL',
    video_cover_url TEXT COMMENT '视频封面URL',
    video_play_url TEXT COMMENT '视频播放URL',
    source_keyword TEXT COMMENT '来源关键词',
    PRIMARY KEY (id),
    UNIQUE INDEX ix_kuaishou_video_video_id (video_id),
    INDEX ix_kuaishou_video_create_time (create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='快手视频'"""

# 与 MediaCrawler/database/models.py::KuaishouVideoComment 逐列一致。
_KS_COMMENT_DDL = """\
CREATE TABLE kuaishou_video_comment (
    id INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    user_id TEXT COMMENT '用户ID',
    nickname TEXT COMMENT '用户昵称',
    avatar TEXT COMMENT '用户头像',
    add_ts BIGINT COMMENT '添加时间戳',
    last_modify_ts BIGINT COMMENT '最后修改时间戳',
    comment_id BIGINT COMMENT '评论ID',
    video_id VARCHAR(255) COMMENT '视频ID',
    content TEXT COMMENT '评论内容',
    create_time BIGINT COMMENT '创建时间戳',
    sub_comment_count TEXT COMMENT '子评论数',
    PRIMARY KEY (id),
    UNIQUE INDEX ix_kuaishou_video_comment_comment_id (comment_id),
    INDEX ix_kuaishou_video_comment_video_id (video_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='快手视频评论'"""

CREATE_DDL_BY_TABLE: Dict[str, str] = {
    "kuaishou_video": _KS_VIDEO_DDL,
    "kuaishou_video_comment": _KS_COMMENT_DDL,
}

# 表已存在时需要探测/补齐的新列（目前只有 kuaishou_video.comment_count）
ADD_COLUMN_DDL_BY_TABLE: Dict[str, Tuple[str, str]] = {
    "kuaishou_video": (
        "comment_count",
        "ALTER TABLE kuaishou_video ADD COLUMN comment_count TEXT COMMENT '评论数'",
    ),
}


@dataclass
class TablePlan:
    table: str
    action: str  # "create" | "add_column" | "skip_exists"


def plan_ks_actions(
    existing_tables: Set[str],
    columns_by_table: Dict[str, Set[str]],
    tables: Iterable[str] = TABLES,
) -> List[TablePlan]:
    """纯逻辑：给定库中现有表名与各表列名快照，逐表决定动作。不触碰真实 DB。"""
    plans: List[TablePlan] = []
    for table in tables:
        if table not in existing_tables:
            plans.append(TablePlan(table, "create"))
            continue
        column_spec = ADD_COLUMN_DDL_BY_TABLE.get(table)
        if column_spec and column_spec[0] not in columns_by_table.get(table, set()):
            plans.append(TablePlan(table, "add_column"))
        else:
            plans.append(TablePlan(table, "skip_exists"))
    return plans


@dataclass
class ApplyOutcome:
    plan: TablePlan
    status: str  # "created" | "would_create" | "column_added" | "would_add_column" | "skipped" | "failed"
    error: str = ""


def apply_plans(
    plans: List[TablePlan],
    apply_fn: Callable[[TablePlan], None],
    dry_run: bool = False,
) -> List[ApplyOutcome]:
    """按 plan 逐表执行并归类结果。create/add_column 调用注入的 apply_fn 落地 DDL。

    单表失败（SQLAlchemyError）不中断整体——记为 failed 后继续处理其余表。
    """
    would_by_action = {"create": "would_create", "add_column": "would_add_column"}
    done_by_action = {"create": "created", "add_column": "column_added"}
    outcomes: List[ApplyOutcome] = []
    for plan in plans:
        if plan.action == "skip_exists":
            outcomes.append(ApplyOutcome(plan, "skipped"))
        elif plan.action in ("create", "add_column"):
            if dry_run:
                outcomes.append(ApplyOutcome(plan, would_by_action[plan.action]))
                continue
            try:
                apply_fn(plan)
            except SQLAlchemyError as exc:
                outcomes.append(ApplyOutcome(plan, "failed", error=str(exc)))
            else:
                outcomes.append(ApplyOutcome(plan, done_by_action[plan.action]))
        else:
            raise ValueError(f"未知 action: {plan.action}")
    return outcomes


def exit_code_for(outcomes: List[ApplyOutcome]) -> int:
    """有任何表执行失败 → 退出码 1，否则 0。"""
    return 1 if any(o.status == "failed" for o in outcomes) else 0


def _ddl_for(plan: TablePlan) -> str:
    if plan.action == "create":
        return CREATE_DDL_BY_TABLE[plan.table]
    return ADD_COLUMN_DDL_BY_TABLE[plan.table][1]


def _apply_ddl(plan: TablePlan) -> None:
    """真正连库执行 DDL。失败抛 SQLAlchemyError，交由 apply_plans 兜住。"""
    print(f"执行: {plan.action} {plan.table} ...")
    with engine.begin() as conn:
        conn.execute(text(_ddl_for(plan)))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="共享 MySQL 建快手两张原生表（幂等；表已存在时兼作 comment_count 补列迁移）"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="只打印将执行的 DDL，不实际执行"
    )
    args = parser.parse_args(argv)

    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    columns_by_table: Dict[str, Set[str]] = {}
    for table in TABLES:
        if table in existing_tables:
            columns_by_table[table] = {col["name"] for col in insp.get_columns(table)}

    plans = plan_ks_actions(existing_tables, columns_by_table)

    for plan in plans:
        if plan.action == "skip_exists":
            print(f"[跳过] {plan.table}: 表已存在且列齐，跳过（幂等）")
        elif args.dry_run:
            print(f"[dry-run] 将执行:\n{_ddl_for(plan)}")

    outcomes = apply_plans(plans, _apply_ddl, dry_run=args.dry_run)

    for outcome in outcomes:
        if outcome.status == "failed":
            print(f"[失败] {outcome.plan.table}: 执行失败：{outcome.error}")

    counts: Dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    print(f"完成：{counts}")
    if counts.get("failed"):
        print("存在执行失败的表（见上方 [失败] 明细），请检查数据库连接与账号 DDL 权限后重跑本脚本。")

    return exit_code_for(outcomes)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 跑测试确认通过 + 全量**

```powershell
.\.venv\Scripts\python.exe -m unittest backend.tests.test_create_ks_tables backend.tests.test_crawler_unique_indexes -v
$env:PYTHONIOENCODING="utf-8"; .\.venv\Scripts\python.exe -m unittest discover -s backend/tests -t . -q
```
Expected: 新增测试 PASS；全量 `Ran 181 tests ... OK` 上下（176 基线 + 新增，只增不减）。

- [ ] **Step 6: 提交**

```powershell
git add scripts/add_crawler_unique_indexes.py scripts/create_ks_tables.py backend/tests/test_create_ks_tables.py backend/tests/test_crawler_unique_indexes.py
git commit -m "feat(ks): 唯一索引 TARGETS + 建表/补列两态迁移脚本"
```

---

### Task 8: sync 入库链路接入

**Files:**
- Modify: `scripts/sync_media_to_raw_posts.py`（六处）
- Test: `backend/tests/test_ks_sync_mapping.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_ks_sync_mapping.py`：

```python
"""快手 sync 映射与注册面测试（不连库，纯映射逻辑）。"""

import unittest

from scripts.sync_media_to_raw_posts import (
    MAPPER_BY_PLATFORM,
    REFRESH_FIELDS_BY_PLATFORM,
    SUPPORTED_PLATFORMS,
    TABLE_BY_PLATFORM,
    _map_ks,
    _normalize_platforms,
)

MS_2026_06_12 = 1_781_193_600_000  # 毫秒 epoch


def make_row(**overrides):
    row = {
        "id": 7,
        "video_id": "3xabc",
        "source_keyword": "中山大学 宿舍",
        "title": "中山大学宿舍vlog",
        "desc": "中山大学宿舍vlog 完整文案",
        "nickname": "某同学",
        "create_time": MS_2026_06_12,
        "liked_count": "1234",
        "comment_count": "56",
        "viewd_count": "9999",
        "video_url": "https://www.kuaishou.com/short-video/3xabc",
        "add_ts": MS_2026_06_12 + 86_400_000,
        "last_modify_ts": MS_2026_06_12 + 86_400_000,
    }
    row.update(overrides)
    return row


class KsPlatformRegistrationTests(unittest.TestCase):
    def test_ks_registered_everywhere(self):
        self.assertIn("ks", SUPPORTED_PLATFORMS)
        self.assertEqual(TABLE_BY_PLATFORM["ks"], "kuaishou_video")
        self.assertIs(MAPPER_BY_PLATFORM["ks"], _map_ks)
        self.assertIn("ks", _normalize_platforms(None))
        self.assertIn("ks", _normalize_platforms(["all"]))

    def test_refresh_only_like_and_comment(self):
        # collect/share 恒 0，--refresh 只刷点赞与评论，避免 0 覆盖既有值
        self.assertEqual(REFRESH_FIELDS_BY_PLATFORM["ks"], ("like_count", "comment_count"))


class MapKsTests(unittest.TestCase):
    def test_basic_mapping(self):
        payload = _map_ks(make_row())
        self.assertEqual(payload["platform"], "ks")
        self.assertEqual(payload["source_table"], "kuaishou_video")
        self.assertEqual(payload["external_id"], "3xabc")
        self.assertEqual(payload["like_count"], 1234)
        self.assertEqual(payload["comment_count"], 56)
        self.assertEqual(payload["collect_count"], 0)
        self.assertEqual(payload["share_count"], 0)
        self.assertEqual(payload["tags_json"], "[]")
        self.assertEqual(payload["url"], "https://www.kuaishou.com/short-video/3xabc")
        # create_time 毫秒 epoch 正确换算（2026-06-12 前后）
        self.assertIsNotNone(payload["publish_time"])
        self.assertEqual(payload["publish_time"].year, 2026)

    def test_publish_time_falls_back_to_add_ts(self):
        for bad in (None, 0):
            payload = _map_ks(make_row(create_time=bad))
            self.assertIsNotNone(payload["publish_time"])  # 回退 add_ts
            self.assertEqual(payload["publish_time"].year, 2026)

    def test_text_count_tolerance(self):
        # store 写入 str(realLikeCount)，缺失时可能是 "None"；映射侧容错为 0
        payload = _map_ks(make_row(liked_count="None", comment_count=None))
        self.assertEqual(payload["like_count"], 0)
        self.assertEqual(payload["comment_count"], 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
.\.venv\Scripts\python.exe -m unittest backend.tests.test_ks_sync_mapping -v
```
Expected: FAIL，`ImportError: cannot import name '_map_ks'`。

- [ ] **Step 3: 改 sync_media_to_raw_posts.py（六处）**

(1) `SUPPORTED_PLATFORMS = {"xhs", "weibo", "tieba", "zhihu"}` → `{"xhs", "weibo", "tieba", "zhihu", "ks"}`

(2) `TABLE_BY_PLATFORM` 加一行：`"ks": "kuaishou_video",`

(3) `_map_zhihu` 之后新增：

```python
def _map_ks(row: dict[str, Any]) -> dict[str, Any]:
    crawl_time = row.get("last_modify_ts") or row.get("add_ts")
    return _base_payload(
        platform="ks",
        source_table="kuaishou_video",
        source_raw_id=row.get("id"),
        external_id=row.get("video_id"),
        source_keyword=row.get("source_keyword"),
        title=row.get("title"),
        content=row.get("desc"),
        author=row.get("nickname"),
        # create_time 为毫秒 epoch（_parse_datetime 自动换算成秒）；0/空回退 add_ts
        publish_time=row.get("create_time") or row.get("add_ts"),
        url=row.get("video_url"),
        like_count=row.get("liked_count"),
        collect_count=0,
        comment_count=row.get("comment_count"),
        share_count=0,
        tags_json="[]",  # ks 标签未持久化，D 新话题信号不参与
        crawl_time=crawl_time,
        raw_row=row,
    )
```

(4) `MAPPER_BY_PLATFORM` 加一行：`"ks": _map_ks,`

(5) `_normalize_platforms` 内两处默认列表 `["xhs", "weibo", "tieba", "zhihu"]` 均改为 `["xhs", "weibo", "tieba", "zhihu", "ks"]`

(6) `REFRESH_FIELDS_BY_PLATFORM` 加一行（连同注释）：

```python
# 快手映射的 collect/share 恒 0（平台无此计数），--refresh 只刷点赞与评论，避免 0 覆盖既有值。
REFRESH_FIELDS_BY_PLATFORM = {
    "zhihu": ("like_count", "comment_count"),
    "ks": ("like_count", "comment_count"),
}
```

(7) CLI `--platform` choices：`choices=["all", "xhs", "weibo", "tieba", "zhihu", "json"]` → `choices=["all", "xhs", "weibo", "tieba", "zhihu", "ks", "json"]`

- [ ] **Step 4: 跑测试确认通过 + 全量**

```powershell
.\.venv\Scripts\python.exe -m unittest backend.tests.test_ks_sync_mapping -v
$env:PYTHONIOENCODING="utf-8"; .\.venv\Scripts\python.exe -m unittest discover -s backend/tests -t . -q
```
Expected: 新测试 PASS；全量 OK 且只增不减。注意：`backend/tests/test_platform_tags.py` 有对 `SUPPORTED_PLATFORMS`/`_normalize_platforms` 的既有断言，若它硬编码了四平台全集导致失败，属于**断言需要跟进的正当更新**（把期望集合加上 `"ks"`），修改时在该文件注明原因，不许删除断言。

- [ ] **Step 5: 提交**

```powershell
git add scripts/sync_media_to_raw_posts.py backend/tests/test_ks_sync_mapping.py
git commit -m "feat(ks): sync 入库链路接入（_map_ks + 注册面 + refresh 白名单）"
```
（若 Step 4 改了 test_platform_tags.py，把它也加进 `git add`。）

---

### Task 9: process choices + 评论路由 + 平台归一化

**Files:**
- Modify: `scripts/process_raw_posts.py:357`
- Modify: `backend/services/comment_loader.py:30-39`（SPEC）及模块 docstring 表格
- Modify: `backend/routers/api.py:52-63`
- Test: `backend/tests/test_ks_comment_loader.py`（新建）、`backend/tests/test_api_normalize_platform.py`（追加）

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_ks_comment_loader.py`：

```python
"""快手评论路由测试：SPEC 注册 + sqlite 内存库端到端取数（无点赞列用字面量 0）。"""

import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.services.comment_loader import PLATFORM_COMMENT_SPEC, fetch_top_comments


class KsCommentSpecTests(unittest.TestCase):
    def test_spec_registered(self):
        spec = PLATFORM_COMMENT_SPEC["ks"]
        self.assertEqual(spec["table"], "kuaishou_video_comment")
        self.assertEqual(spec["join_col"], "video_id")
        self.assertIsNone(spec["like_col"])  # ks 评论表无点赞列，同贴吧字面量 0


class KsFetchTopCommentsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE kuaishou_video_comment ("
                    "id INTEGER PRIMARY KEY, video_id VARCHAR(255), "
                    "content TEXT, add_ts BIGINT)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO kuaishou_video_comment (video_id, content, add_ts) VALUES "
                    "('3xabc', '早的评论', 1), ('3xabc', '晚的评论', 2), ('other', '别的视频', 3)"
                )
            )
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()

    def test_fetch_orders_by_add_ts_desc_with_zero_likes(self):
        result = fetch_top_comments(self.db, [("ks", "3xabc")], per_note=3)
        self.assertEqual(result[("ks", "3xabc")], ["晚的评论", "早的评论"])

    def test_unknown_ids_absent(self):
        result = fetch_top_comments(self.db, [("ks", "nope")])
        self.assertNotIn(("ks", "nope"), result)


if __name__ == "__main__":
    unittest.main()
```

在 `backend/tests/test_api_normalize_platform.py` 的测试类中追加方法（沿用该文件既有的 `_normalize_platform` 导入方式）：

```python
    def test_ks_variants(self):
        self.assertEqual(_normalize_platform("ks"), "ks")
        self.assertEqual(_normalize_platform("KS"), "ks")
        self.assertEqual(_normalize_platform("kuaishou"), "ks")
        self.assertEqual(_normalize_platform("快手"), "ks")
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
.\.venv\Scripts\python.exe -m unittest backend.tests.test_ks_comment_loader backend.tests.test_api_normalize_platform -v
```
Expected: FAIL——`KeyError: 'ks'`（SPEC 未注册）；`test_ks_variants` 断言失败（`"ks"` 走 passthrough 恰好返回 "ks" 会过，但 `"快手"`/`"kuaishou"` 会失败——确认至少这两个变体失败）。

- [ ] **Step 3: 三处实现**

(1) `scripts/process_raw_posts.py`：

```python
    parser.add_argument("--platform", action="append", choices=["xhs", "weibo", "tieba", "zhihu", "ks"])
```

(2) `backend/services/comment_loader.py` 的 `PLATFORM_COMMENT_SPEC` 加：

```python
    "ks": {"table": "kuaishou_video_comment", "join_col": "video_id", "like_col": None},
```

同时把模块 docstring 里的路由表格加一行：

```
| ks    | kuaishou_video_comment | video_id | 无（字面量 0）    |
```

（docstring 中"四个平台/四张表"的措辞改为"五个平台/五张表"。）

(3) `backend/routers/api.py` `_normalize_platform`，`zhihu` 分支之后、`return lower or text` 之前加：

```python
    if "kuaishou" in lower or lower == "ks" or "快手" in text:
        return "ks"
```

（用 `lower == "ks"` 全等而非子串，避免 "tasks" 这类字符串误命中。）

- [ ] **Step 4: 跑测试确认通过 + 全量**

```powershell
.\.venv\Scripts\python.exe -m unittest backend.tests.test_ks_comment_loader backend.tests.test_api_normalize_platform -v
$env:PYTHONIOENCODING="utf-8"; .\.venv\Scripts\python.exe -m unittest discover -s backend/tests -t . -q
```
Expected: 全部 PASS，总数只增不减。

- [ ] **Step 5: 提交**

```powershell
git add scripts/process_raw_posts.py backend/services/comment_loader.py backend/routers/api.py backend/tests/test_ks_comment_loader.py backend/tests/test_api_normalize_platform.py
git commit -m "feat(ks): process choices + 评论路由 + 平台归一化"
```

---

### Task 10: 前端四处平台枚举

**Files:**
- Modify: `frontend/src/views/AdminKeywordsView.vue:84-89`
- Modify: `frontend/src/views/AdminRawPostsView.vue:13-16, 132, 207-210`
- Modify: `frontend/src/utils/postLink.js:11-15`
- Modify: `frontend/src/views/SentimentView.vue:280`

前端无自动化测试，本任务纯编辑 + 语法自查（改完重读 diff 确认无破坏性改动）。

- [ ] **Step 1: AdminKeywordsView.vue** —— `PLATFORM_OPTIONS` 改为：

```javascript
const PLATFORM_OPTIONS = [
  { value: 'xhs', label: '小红书' },
  { value: 'wb', label: '微博' },
  { value: 'tieba', label: '贴吧' },
  { value: 'zhihu', label: '知乎' },
  { value: 'ks', label: '快手' },
]
```

- [ ] **Step 2: AdminRawPostsView.vue** —— 三处：

筛选选项（知乎行后）：

```html
        <el-option label="平台：快手" value="ks" />
```

标签映射：

```javascript
const PLATFORM_LABELS = { xhs: '小红书', weibo: '微博', tieba: '贴吧', zhihu: '知乎', ks: '快手' }
```

样式（`.source-zhihu` 行后，琥珀色系与现有四色区分）：

```css
.source-ks { background: #fefce8; color: #a16207; }
```

- [ ] **Step 3: postLink.js** —— `SEARCH_BUILDERS` 加：

```javascript
  ks: (kw) => `https://www.kuaishou.com/search/video?searchKey=${encodeURIComponent(kw)}`,
```

- [ ] **Step 4: SentimentView.vue** —— `platformTagType` 的 map 改为：

```javascript
  const map = { '微博': 'warning', '知乎': 'primary', '贴吧': 'success', '小红书': 'danger', '快手': 'info' }
```

- [ ] **Step 5: 提交**

```powershell
git add frontend/src/views/AdminKeywordsView.vue frontend/src/views/AdminRawPostsView.vue frontend/src/utils/postLink.js frontend/src/views/SentimentView.vue
git commit -m "feat(ks): 前端平台枚举四处加快手"
```

---

### Task 11: 全量回归 + 合并 main

- [ ] **Step 1: 双侧全量回归**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\MediaCrawler"
.\.venv\Scripts\python.exe -m pytest tests -q
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -t . -q
```
Expected: MediaCrawler `1 failed, 151 passed`（唯一失败=excel 既有）；主项目全绿、总数 ≥ 185。任何新失败先修再合并。

- [ ] **Step 2: stash 舞步合并**

```powershell
git stash push -- MediaCrawler/config/base_config.py
git checkout main
git merge --ff-only feature/ks-crawler-retrofit
git branch -d feature/ks-crawler-retrofit
git stash pop
git status --short   # 预期回到：仅 M MediaCrawler/config/base_config.py（冒烟调参）
git log --oneline -12  # 目视确认本计划各提交都在 main 上
```

---

### Task 12: 线上迁移（需用户确认，不可跳过确认环节）

前提：`.env` 指向共享阿里云 MySQL；网络代理已按 crawl-runbook §1.2 处理。

- [ ] **Step 1: dry-run 并把输出呈给用户**

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
.\.venv\Scripts\python.exe scripts\create_ks_tables.py --dry-run
```
两种预期输出之一：`would_create=2`（线上无 ks 表）或 `would_add_column`/`skipped` 组合（已有表）。**把输出给用户确认后**才执行下一步。

- [ ] **Step 2: 执行 + 幂等复跑**

```powershell
.\.venv\Scripts\python.exe scripts\create_ks_tables.py
.\.venv\Scripts\python.exe scripts\create_ks_tables.py   # 幂等复跑，预期全 skipped
```

- [ ] **Step 3: 唯一索引迁移（同样 dry-run → 用户确认 → 执行 → 复跑）**

```powershell
.\.venv\Scripts\python.exe scripts\add_crawler_unique_indexes.py --dry-run
.\.venv\Scripts\python.exe scripts\add_crawler_unique_indexes.py
.\.venv\Scripts\python.exe scripts\add_crawler_unique_indexes.py   # 幂等复跑
```
注意：若 ks 表是本次新建的，唯一索引随建表已在，脚本应显示 skip；若报"存在重复值拒绝"，把重复样本呈给用户人工定夺，**不得自行删数据**。

---

### Task 13: 冒烟指引与文档收尾

- [ ] **Step 1: 用户冒烟命令**（需扫码，无法代跑；把命令给用户）

```powershell
# 关代理（见 docs/crawl-runbook.md §1.2）后：
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\MediaCrawler"
.\.venv\Scripts\python.exe main.py --platform ks --keywords "宿舍" --get_comment yes --start_date <今天-14天> --end_date <今天>
# 之后：
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
.\.venv\Scripts\python.exe scripts\sync_media_to_raw_posts.py --platform ks
.\.venv\Scripts\python.exe scripts\process_raw_posts.py --platform ks
```

- [ ] **Step 2: 更新 docs/crawl-runbook.md**——平台对照表加 `快手 | ks | ks` 一行、新增 §3.4 快手小节（照 §3.3 知乎格式，注明：无服务端排序/时间筛选，`--fresh` 无操作可不带；时间窗口纯客户端过滤无提前停止）、末尾"贴吧暂不在本手册"段保持不变。提交：

```powershell
git add docs/crawl-runbook.md
git commit -m "docs: 爬取手册补快手小节"
```

---

## 完成定义（Definition of Done）

1. MediaCrawler pytest：既有 133 全过 + 新增 ≥18 个全过，唯一失败仍是 excel 既有用例。
2. 主项目 unittest：≥185 全绿。
3. main 分支含全部提交，feature 分支已删，工作区只剩 base_config 两处冒烟调参。
4. 线上：ks 两表在位（含 comment_count 列 + 唯一索引），迁移脚本幂等复跑全 skip。
5. 用户冒烟通过：爬取 → sync → process → 面板可见快手帖子（标签"快手"、琥珀色 pill）。
