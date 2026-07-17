# crawler — 备用轻量采集链路

本目录是**降级备用**的采集实现（微博公开搜索 + 百度贴吧公开列表，requests/Playwright 轻量方案）。
主采集系统是根目录的 [MediaCrawler/](../MediaCrawler/)（5 平台：小红书/知乎/微博/贴吧/快手），
日常采集请优先走 MediaCrawler，流程见 [docs/crawl-runbook.md](../docs/crawl-runbook.md)。

保留本链路的理由：

- MediaCrawler 依赖浏览器登录态与站点反爬博弈，失效时本链路可快速补采；
- `--demo` 模式可离线生成演示样本，不依赖任何外网。

## 使用（项目根目录）

```text
1. scripts\bat\save_weibo_login.bat   # 登录微博一次，保存登录态
2. scripts\bat\save_tieba_login.bat   # 登录贴吧一次（否则贴吧常为 0 条）
3. scripts\bat\crawl.bat              # 采集，输出到 data/samples/
4. scripts\bat\import_latest.bat      # 把最新样本导入数据库
```

等价的命令行用法：

```bash
# 真实采集（需登录态 + 联网）
.venv\Scripts\python.exe crawler\run_once.py

# 不要 demo 补充
.venv\Scripts\python.exe crawler\run_once.py --no-demo

# 指定关键词与条数
.venv\Scripts\python.exe crawler\run_once.py --keyword 校园 --limit 40

# 离线演示样本（零网络）
.venv\Scripts\python.exe crawler\run_once.py --demo
```

## 输出

`data/samples/` 下：

- 帖子 JSON：`posts_YYYYMMDD_HHMMSS.json`
- 异常摘要：`crawl_report_YYYYMMDD_HHMMSS.json`

字段规范见 [docs/field-spec.md](../docs/field-spec.md)，数据源说明见 [docs/data-sources.md](../docs/data-sources.md)。

## 历史文档

早期的真实采集指南、异常记录与后端对接文档已归档（内容对应当时阶段，不代表现状）：

- [docs/archive/crawl/crawl-real-data.md](../docs/archive/crawl/crawl-real-data.md)
- [docs/archive/crawl/crawl-issues.md](../docs/archive/crawl/crawl-issues.md)
- [docs/archive/crawl/crawl-handoff.md](../docs/archive/crawl/crawl-handoff.md)
