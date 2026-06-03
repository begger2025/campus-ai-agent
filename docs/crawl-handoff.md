# 爬虫 JSON → 后端对接说明（任务 4）

## 交付文件

| 文件 | 说明 |
|------|------|
| **`data/samples/posts_week1_sample.json`** | 第一周正式交付样本（30 条，推荐后端用这个） |
| `data/samples/posts_YYYYMMDD_HHMMSS.json` | 每次运行 `crawl.bat` 自动生成的时间戳文件 |

## JSON 结构

```json
{
  "meta": {
    "crawl_time": "2026-05-16T12:00:00",
    "keyword": "校园",
    "total": 30,
    "sources": ["weibo", "tieba"],
    "mode": "demo"
  },
  "items": [ { "id", "platform", "title", "content", "author", "publish_time", "url", "crawl_time" } ]
}
```

- `meta.mode`：`live`（全真实）/ `live+demo_fallback`（部分真实）/ `demo`（结构化样本）
- 字段含义见 [field-spec.md](field-spec.md)

## 后端导入步骤

```cmd
cd C:\Users\pissy\Desktop\campus-ai-agent

REM 1. 导入 JSON 到 raw_posts 表
.\.venv\Scripts\python.exe scripts\import_posts.py data\samples\posts_week1_sample.json

REM 2. 启动 API
双击 run.bat

REM 3. 验证
浏览器打开 http://127.0.0.1:9000/posts
```

### 导入结果说明

| 输出 | 含义 |
|------|------|
| `imported N posts` | 新写入 N 条 |
| `imported 0 posts` | 条目不新增（`url` 已存在），数据已在库，可继续联调 |

## 与数据库字段映射

| JSON 字段 | `raw_posts` 列 |
|-----------|----------------|
| platform | platform |
| title | title |
| content | content |
| author | author |
| publish_time | publish_time |
| url | url |
| crawl_time | crawl_time |

`id`（字符串）当前不入库，以 `url` 去重；数据库 `id` 为自增整数。

## 前端联调

- 接口：`GET /posts?page=1&page_size=20`
- 文档：[api.md](api.md)
- 无需直接读 JSON 文件，统一走后端 API
