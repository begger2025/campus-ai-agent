# 设计：知乎平台接入后的主项目补齐（A+B+C）

- 日期：2026-07-11
- 状态：已批准（用户："A + B + C 一起修，按老流程推进"）
- 来源：三份只读审计（后端/前端/脚本）。范围仅主项目 backend/、scripts/、frontend/；MediaCrawler/ 与 .env 零触碰。

## 背景

知乎已接入爬虫、sync、唯一索引、面板复制命令。`raw_posts.platform`/`processed_posts.platform`
现有 `"zhihu"` 值；`processed_posts.note_id` 形如 `"zhihu:2056070606362302108"`（前缀严格等于
平台码，已实测四平台一致）。知乎无标签（tags_json=[]）、无收藏/转发（collect/share=0）。
本批修复把知乎补进各处平台处理，不改算法核心、不改爬虫。

## A. 评论加载按平台路由（唯一真阻断，顺带修好微博/贴吧）

**问题**：`backend/services/comment_loader.py` 硬编码只查 `xhs_note_comment`、写死 `note_id`
关联、`like_count` 列、`create_time` 排序。四个平台的原生评论表列名不同（线上实测）：

| 平台 | 关联列 | 点赞列 | 内容列 |
|---|---|---|---|
| xhs | note_id | like_count | content |
| weibo | note_id | **comment_like_count** | content |
| tieba | note_id | **无点赞列**（用字面量 0） | content |
| zhihu | **content_id** | like_count | content |

四张表都有 `add_ts`（BigInteger 毫秒）与 `content`。故知乎评论区永远空、微博用错点赞列、
贴吧无点赞列——当前实现对非 xhs 平台全部失效。

**方案**：
- 在 comment_loader 定义 `PLATFORM_COMMENT_SPEC: dict[str, dict]`，每平台给
  `{"table":..., "join_col":..., "like_expr":...}`：
  - xhs → `xhs_note_comment` / `note_id` / `CAST(like_count AS <int>)`
  - weibo → `weibo_note_comment` / `note_id` / `CAST(comment_like_count AS <int>)`
  - tieba → `tieba_comment` / `note_id` / `0`（无点赞列，字面量）
  - zhihu → `zhihu_comment` / `content_id` / `CAST(like_count AS <int>)`
  - `<int>` 按方言：mysql=`UNSIGNED`、其它=`INTEGER`（沿用现有二分支）。
- 排序统一 `ORDER BY likes DESC, add_ts DESC`（add_ts 四表皆有，替代 create_time——
  create_time 仅 xhs/weibo 有；这是一处刻意的统一化，对"高赞前 N"结果无实质影响）。
- **函数签名改为**：`fetch_top_comments(db, refs, *, per_note=3)`，`refs: list[tuple[str, str]]`
  = `(platform, bare_id)`。内部按 platform 分组，未知/不在 SPEC 的平台跳过；每平台先
  `inspect(bind).get_table_names()` 判表存在（不存在跳过，保留演示快照优雅降级）；返回
  `dict[tuple[str, str], list[str]]`，键为 `(platform, bare_id)`（避免跨平台裸 id 撞车）。
- **调用方** `public_opinion_adapter.py:query_agent_rows`（~142-149）：
  `refs = [(row["platform"], bare_note_id(row["note_id"])) for row in agent_rows if row.get("note_id")]`；
  `row["top_comments"] = comments.get((row["platform"], bare_note_id(row["note_id"])), [])`。
  `bare_note_id` 拆 `":"` 取后段的逻辑保留。

**测试**（backend/tests/test_comment_loader.py 已存在，扩充）：
- SQLite 建四张评论表最小结构 + processed 场景，断言：知乎按 content_id 命中评论；微博按
  comment_like_count 排序；贴吧无点赞列不报错（likes=0 仍返回按 add_ts）；跨平台裸 id 相同
  不串（键含 platform）；表不存在优雅返回空；per_note 截断；空输入空返回。
- 保持既有 xhs 用例行为不回归（可能需把旧用例的 fetch_top_comments 调用改成新签名）。

## B. 平台枚举补齐（功能断裂）

1. `scripts/process_raw_posts.py:357`：`--platform` 的 `choices` 加 `"zhihu"`
   （→ `["xhs","weibo","tieba","zhihu"]`）。不加参数本就全量处理，此为解锁显式过滤。
   测试：既有该脚本测试模块加一条"--platform zhihu 被接受"断言。
2. `frontend/src/mock/events.js` 的 `sourceOptions`（被 EventListView/OpinionView import 作真实
   下拉+label 源）：加 `{ value: 'zhihu', label: '知乎' }`。
3. `frontend/src/views/AdminRawPostsView.vue` 平台筛选下拉：加 `<el-option label="平台：知乎" value="zhihu" />`。

## C. 展示补齐（降级项）

后端：
4. `backend/routers/api.py:52 _normalize_platform`：加 `if "zhihu" in lower or "知乎" in text: return "zhihu"`
   （与其它平台一致的中文别名收敛；一行健壮性）。

前端 label 字典加 `zhihu: '知乎'`：
5. `AdminRawPostsView.vue:131` `PLATFORM_LABELS`
6. `EventDetailView.vue:258` `sourceLabel` 的 `map`

前端样式/图标（知乎蓝 `color:#0369a1; background:#f0f9ff; border:1px solid #bae6fd`）：
7. `EventDetailView.vue`：加 `.source-zhihu`
8. `EventListView.vue`：加 `.source-zhihu` 与 `.source-icon-zhihu { background:#0284c7; }`
9. `EventListView.vue:461 sourceShort`：加 `if (value === 'zhihu') return '知'`

前端改动完成后 `cd frontend && npm run build` 验证编译通过（dist 在 .gitignore，不提交）。

## 范围外（审计判定可接受，本次不改）

- `postLink.js` 站内搜索备用入口缺 zhihu（原帖直链用 post.url 正常，不受影响）。
- SentimentView/HomeView "全平台都显示英文码"的既有老问题（非知乎专属回归）。
- make_demo_snapshot.py（知乎无专属缺口：原生表本就不进快照，知乎数据经 sync+process 进
  raw_posts 即入快照）。
- backfill_tags.py（已正确跳过知乎）。
- 演示态所有平台 top_comments 为空（原生评论表不进快照，A 修复后线上库正常、快照仍空——
  既有限制，非本次目标）。

## 测试基线
- 主项目 unittest：当前 164 → 只增不改全绿。
- 前端 `npm run build` 通过。
