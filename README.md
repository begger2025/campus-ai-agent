# campus-ai-agent

一个面向校园场景的 AI Agent 项目，主要包括：

- 公共校园舆情分析 Agent
- 个人事项安排 Agent
- 数据采集、后端服务、前端展示等模块

## 相关文档

- [开发规范](docs/dev-guide.md) — 分支、提交、命名、接口格式
- [接口文档](docs/api.md)
- [数据库设计](docs/database.md)
- [数据源说明](docs/data-sources.md) · [字段说明](docs/field-spec.md)
- [爬虫交付/对接](docs/crawl-handoff.md) · [爬虫异常记录](docs/crawl-issues.md)
- [**真实爬取配置**](docs/crawl-real-data.md)

## 爬虫采集

```bash
双击 crawl.bat                    # 或: python crawler/run_once.py
python scripts/import_posts.py data/samples/posts_week1_sample.json
```

## 项目结构

```text
campus-ai-agent/
├─ README.md
├─ docs/
├─ backend/
├─ frontend/
├─ crawler/
├─ agent/
├─ data/
├─ scripts/
├─ .gitignore
└─ requirements.txt
```
