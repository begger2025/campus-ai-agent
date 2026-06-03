# 数据库设计初稿（第一周）

数据库文件：`data/campus.db`（SQLite，可通过 `.env` 的 `DATABASE_URL` 切换 PostgreSQL/MySQL）

## 表结构

### raw_posts（爬虫原始数据）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| platform | VARCHAR(50) | 平台，如 weibo |
| title | VARCHAR(500) | 标题 |
| content | TEXT | 正文 |
| author | VARCHAR(100) | 作者 |
| publish_time | DATETIME | 发布时间 |
| url | VARCHAR(500) | 原文链接 |
| crawl_time | DATETIME | 抓取时间 |

### processed_posts（清洗后帖子）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| raw_post_id | INTEGER FK | 关联 raw_posts |
| platform / title / content / author / publish_time | | 清洗后字段 |
| created_at | DATETIME | 入库时间 |

### public_events（公共舆情事件）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | |
| title | VARCHAR(200) | 事件标题 |
| summary | TEXT | 摘要 |
| sentiment | VARCHAR(20) | 情绪：positive/negative/neutral |
| topic | VARCHAR(100) | 主题 |
| heat_score | FLOAT | 热度 0~1 |
| source_post_id | INTEGER FK | 来源帖子（可空） |
| created_at | DATETIME | |

### user_tasks（用户待办）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | |
| user_id | VARCHAR(50) | 用户标识 |
| title | VARCHAR(200) | 标题 |
| description | TEXT | 描述 |
| status | VARCHAR(20) | pending / done |
| due_at | DATETIME | 截止时间 |
| created_at | DATETIME | |

### user_schedules（用户日程）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | |
| user_id | VARCHAR(50) | 用户标识 |
| title | VARCHAR(200) | 标题 |
| start_at / end_at | DATETIME | 起止时间 |
| location | VARCHAR(200) | 地点 |
| created_at | DATETIME | |

## 初始化

```bash
.\.venv\Scripts\python.exe scripts\init_db.py
```

启动 `run.bat` 时也会自动建表；若表为空会写入 3 条示例帖子。
