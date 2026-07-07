# data/ 目录说明

运行时数据目录，**不要提交** Cookie、数据库到 Git（已在 `.gitignore` 中忽略）。

## 结构

```text
data/
├── campus.db              # SQLite 主库（后端 /posts 读取 raw_posts）
├── cookies/
│   └── weibo_state.json   # 微博登录态（save_weibo_login.bat 生成）
└── samples/
    ├── posts_*.json       # 爬虫单次输出
    ├── crawl_report_*.json# 采集异常摘要
    └── posts_week1_sample.json  # 第一周交付样本
```

## 数据如何进入页面

| 步骤 | 命令 | 结果 |
|------|------|------|
| 爬取 | `crawl.bat` | 新增 `samples/posts_*.json` |
| 入库 | `import_latest.bat` | 写入 `campus.db` |
| 展示 | `run.bat` + 浏览器 | 前端通过 `/posts` 读取 |

## 样本 JSON 格式

```json
{
  "meta": { "mode": "live|demo|live+demo_fallback", "total": 30 },
  "items": [
    {
      "id": "weibo_xxx",
      "platform": "weibo",
      "title": "...",
      "content": "...",
      "author": "...",
      "publish_time": "...",
      "url": "...",
      "crawl_time": "..."
    }
  ]
}
```

## 如何查看数据库

`campus.db` 是 SQLite 二进制文件，在编辑器里直接打开会乱码。

**Cursor 内打开（推荐）**：已安装 **SQLite Viewer** 扩展，在资源管理器中 **双击** `data/campus.db` 即可。详细步骤见 [docs/open-campus-db.md](../docs/open-campus-db.md)。

| 方式 | 说明 |
|------|------|
| **双击 `campus.db`** | 需 SQLite Viewer 扩展（项目已配置推荐） |
| `view_db.bat` | 在终端打印表统计与最近 20 条帖子 |
| `data/campus_db_preview.md` | 运行 `view_db.bat` 后自动生成，可在 Cursor 中阅读 |
| [DB Browser for SQLite](https://sqlitebrowser.org/) | 图形化浏览、改表、执行 SQL |

## 与旧项目 `campus-ai-agent` 对齐

若从旧目录迁移，只需复制（择新者）：

- `data/campus.db`
- `data/cookies/weibo_state.json`
- `data/samples/posts_*.json`（可选，避免重复导入）

**以 `campus-ai-agent-main/data/` 为准**，旧目录可归档不再使用。
