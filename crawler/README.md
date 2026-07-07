# 爬虫模块

## 数据源

- 主：`weibo` — 微博公开搜索
- 备：`tieba` — 百度贴吧公开列表

详见 [docs/data-sources.md](../docs/data-sources.md)、[docs/field-spec.md](../docs/field-spec.md)。

## 真实采集（必读）

见 **[docs/crawl-real-data.md](../docs/crawl-real-data.md)**：

1. 双击 `save_weibo_login.bat` 登录微博一次  
2. 双击 `save_tieba_login.bat` 登录贴吧一次（否则贴吧常为 0 条）  
3. 再双击 `crawl.bat`

## 运行

```bash
# 真实采集（需登录态 + 联网）
.venv\Scripts\python.exe crawler\run_once.py

# 不要 demo 补充
.venv\Scripts\python.exe crawler\run_once.py --no-demo

# 指定关键词与条数
.venv\Scripts\python.exe crawler\run_once.py --keyword 校园 --limit 40

# 离线演示样本
.venv\Scripts\python.exe crawler\run_once.py --demo
```

输出目录：`data/samples/`

- 帖子 JSON：`posts_YYYYMMDD_HHMMSS.json`
- 异常摘要：`crawl_report_YYYYMMDD_HHMMSS.json`
- 第一周交付：`posts_week1_sample.json`

异常说明：[docs/crawl-issues.md](../docs/crawl-issues.md)  
后端对接：[docs/crawl-handoff.md](../docs/crawl-handoff.md)

## 导入后端

```bash
.venv\Scripts\python.exe scripts\import_posts.py data\samples\posts_xxx.json
```

然后访问 `GET /posts` 查看数据。
