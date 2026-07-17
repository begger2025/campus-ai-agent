# scripts — 运维/管线/评测脚本索引

44 个 Python 脚本按用途分类如下（物理上平铺在本目录，**被测试与文档按路径引用，请勿移动**）。
除特别说明外，均在项目根目录用 `.venv\Scripts\python.exe scripts\<name>.py` 运行。

所有触库脚本遵守项目纪律：**幂等可复跑**，写共享 MySQL 的一律支持 `--dry-run`/plan 模式先预览。

## 日常入口（最常用）

| 脚本 | 作用 |
|------|------|
| `run_pipeline.py` | 一键数据管线：同步 → 清洗 → 向量 → 事件，四步一条命令 |
| `init_db.py` | 初始化建表（共享 MySQL 只建表，不塞演示数据） |
| `verify_db_connection.py` | 验证 DATABASE_URL 连通性与表完整性 |
| `view_db.py` | 终端打印库统计与最近 20 条帖子 |
| `make_demo_snapshot.py` | 把共享 MySQL 导出为本地 SQLite 快照（`demo.bat` 的答辩降级预案） |
| `smoke_backend.py` / `smoke_backend.ps1` | 舆情链路冒烟测试 |
| `seed_demo.py` | 空的**本地**库灌演示数据（禁止对共享 MySQL 跑） |

## 数据管线（run_pipeline 的分步版）

| 脚本 | 作用 |
|------|------|
| `sync_media_to_raw_posts.py` | MediaCrawler 原生表/增强 JSON → `raw_posts` |
| `process_raw_posts.py` | 清洗 `raw_posts` → `processed_posts` |
| `build_post_vectors.py` | 离线构建帖子向量 → `data/post_vectors.npz` |
| `generate_public_events.py` | `processed_posts` → 舆情事件（聚类 + LLM 精修/风险/状态研判） |
| `import_posts.py` | 备用爬虫的 JSON 样本 → `raw_posts` |
| `backfill_tags.py` | 存量 tags 回填/归一化（平台差异修补） |
| `purge_offtopic_posts.py` | 全链路清理与中大无关的脏数据（含原生表与评论） |

## 采集协同（分布式爬取队列 + 登录态）

| 脚本 | 作用 |
|------|------|
| `seed_crawl_queue.py` | 向 `crawl_task_queue` 播种任务（智能选题推荐 / 手动双来源） |
| `crawl_queue_status.py` | 队列监控（按平台汇总 + 卡死提示） |
| `reset_crawl_queue.py` | 回收卡死/失败任务、清完成行 |
| `save_weibo_login.py` / `save_tieba_login.py` | 保存备用爬虫登录态（各只需一次，见 `bat/`） |
| `debug_tieba.py` | 贴吧 Playwright 响应诊断 |

## 建表与迁移（全部幂等）

`init_db.py` 建基础表；旧库增量变更按需运行：

- `add_*.py`：加列/加索引（`--dry-run` 预览）——crawler 唯一索引、模型索引、
  `processed_posts.excluded`/`heat_rank`、`public_events.curated`
- `create_*.py`：建独立表——爬取队列、爬取历史、快手/知乎原生表、事件评论、用户投稿
- `ensure_wp4_schema.py`：工作包 4 需要的小型增量迁移

## 评测与消融实验

| 脚本 | 作用 |
|------|------|
| `eval_chat_benchmark.py` | 单轮金标基准：路由 / 检索 / 引用合法 / 延迟四项判分 |
| `eval_chat_dialogue.py` | 多轮对话回归：话题连续性 + 话语行为 |
| `check_question_coverage.py` | 真实问题清单的检索命中率验收 |
| `seed_query_log.py` | 真实问题灌入 `chat_query_log`（激活智能选题信号） |
| `ablation_*.py`（6 个） | 消融实验：聚类精修 / 风险研判 / 时效衰减 / 生命周期 / LLM 裁决 / 智能选题，报告见 [docs/experiments/](../docs/experiments/) |

## 其他

| 脚本 | 作用 |
|------|------|
| `collect_evidence.py` | 联网证据采集命令行入口 |
| `sync_opinion_core.py`（+`.bat`） | 核心/服务层反向移植到舆情评测子仓 |
| `merge_compare.ps1` | 分支合并对比辅助 |

## 子目录

| 目录 | 内容 |
|------|------|
| [`bat/`](bat/) | 8 个双击即用的 Windows 批处理（采集/入库/建库/看库/登录态/演示数据） |
| [`sql/`](sql/) | 早期共享 MySQL 的手工 SQL（现由 Python 脚本接管，留作参考） |
| [`archive/`](archive/) | 历史工作包验收脚本（不再维护） |
