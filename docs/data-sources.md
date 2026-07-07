# 第一批数据源说明

## 选定方案（第一周）

| 角色 | 平台 | 标识 `platform` | 说明 |
|------|------|-----------------|------|
| **主数据源** | 微博 | `weibo` | 公开关键词搜索，适合校园热点、舆情 |
| **备用数据源** | 百度贴吧 | `tieba` | 公开版块帖子列表，主源不足时补充 |

## 选择理由

- **微博**：用户量大，校园相关讨论多，适合舆情 Agent 分析。
- **贴吧**：无需登录即可浏览部分列表，结构稳定，作为备用可提高样本数量。

## 采集范围与限制

**做：**

- 仅采集公开可见的搜索/列表页
- 关键词默认：`校园`（微博）、版块 `大学生活`（贴吧）
- 单次 20~50 条，用于开发与联调

**不做（第一周）：**

- 登录墙后的私信、好友圈
- 高频爬取、对平台造成压力
- 个人隐私数据（学号、手机号等）

## 已知异常（需记录）

详细记录见 **[crawl-issues.md](crawl-issues.md)**（任务 5）。

| 现象 | 处理 |
|------|------|
| 微博接口返回空或 432 | 改用贴吧；仍不足则用 `run_once.py --demo` |
| 贴吧反爬验证页 | 减少频率，换 UA，或仅用微博 |
| 只能抓到标题无正文 | 贴吧以标题+回复数入库，正文标为摘要 |
| 时间字段缺失 | `publish_time` 允许为 `null` |

## 运行采集

```bash
.venv\Scripts\python.exe crawler\run_once.py
```

输出：`data/samples/posts_YYYYMMDD_HHMMSS.json`

导入后端（任务 4 对接说明见 **[crawl-handoff.md](crawl-handoff.md)**）：

```bash
.venv\Scripts\python.exe scripts\import_posts.py data\samples\posts_week1_sample.json
```
