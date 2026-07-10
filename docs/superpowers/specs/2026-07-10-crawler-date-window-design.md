# 设计：爬虫发布时间窗口筛选 + 防饥饿探索（三平台）

- 日期：2026-07-10
- 状态：已批准（用户选定完整范围：时间区间 + 三平台防饥饿）
- 范围：仅 MediaCrawler 子目录（主仓 git 管理）；主项目后端/前端/算法核心零改动

## 1. 背景（调查结论）

三平台搜索 API 均**不支持服务端时间参数**；现状无日期筛选、无防饥饿探索：

| | 排序现状 | 时间字段（搜索结果阶段） | 精度 |
|---|---|---|---|
| 小红书 | `SORT_TYPE` 可配置，默认"最热"；详情候选已有"最新优先"确定性排序 | 角标文本（"3天前"/"06-12"），已有解析模块 `store/xhs/xhs_publish_time.py` | 天级 |
| 微博 | `WEIBO_SEARCH_TYPE` 默认"综合"；`real_time`≈最新 | `mblog.created_at`（RFC2822，现成解析 `rfc2822_to_timestamp`） | 秒级 |
| 贴吧 | 硬编码时间倒序 | 原始字符串（"2026-6-12" / "YYYY-MM-DD HH:MM" / 相对文本），无解析代码 | 天级（弱） |

## 2. 时间窗口筛选（--start_date / --end_date）

- **统一策略**：客户端过滤 + 时间倒序下整页过旧即提前停止（省请求额度）。
- **配置**（base_config.py）+ **CLI**（cmd_arg/arg.py，覆盖 config 全局）：
  - `CRAWL_PUBLISH_TIME_START = ""` / `CRAWL_PUBLISH_TIME_END = ""`（"YYYY-MM-DD"，空=不启用；闭区间，END 含当天 23:59:59.999）
  - `PUBLISH_TIME_KEEP_UNKNOWN = True`（解析不出发布时间的帖子保留并打日志——贴吧相对文本解析弱，防误伤）
- **新纯函数模块** `tools/publish_time_window.py`（pytest 可测）：
  `parse_window(start,end) -> (lo_ms|None, hi_ms|None)`（非法格式抛 ValueError 尽早失败）、
  `is_within_window(ts_ms|None, lo, hi, keep_unknown) -> bool`、
  `parse_tieba_publish_time_ms(text) -> int|None`（支持 "YYYY-M-D" 与 "YYYY-MM-DD HH:MM"；相对文本返回 None）。
- **接入点**（来自代码调查，file:line 基于当前 main）：
  - xhs：`core.py _sort_new_note_items_by_publish_time`（候选的 publish_timestamp_ms 已在此解析）内做窗口过滤；整页已解析候选全部老于窗口起点时置标志，搜索循环在 `SORT_TYPE=="time_descending"` 时提前 break；
  - 微博：`core.py` 搜索循环逐条过滤 `mblog.created_at`；仅 `real_time` 模式下提前停止；
  - 贴吧：`core.py` `notes_list` 过滤后再入库；天然时间倒序，提前停止恒可用。
- **时区/精度说明**：窗口按本机（中国）时区解析为毫秒 epoch；xhs/贴吧本身只有天级精度，≤8h 的时区偏差可接受，答辩口径"天级窗口"。

## 3. 防饥饿探索

- **小红书（ε-greedy）**：详情候选排序后截断处（`selected = sorted[:quota]`）改为
  `select_with_exploration(sorted_items, quota, ε, rng)`：每个名额以 1-ε 取最新，
  ε 概率从剩余较旧候选随机抽一条；返回保持原相对顺序。`XHS_EXPLORE_OLDER_PROB = 0.2`。
  纯函数收进 `tools/publish_time_window.py`，注入 rng 可测。
- **微博/贴吧（起始页随机偏移）**：整页入库无截断结构，饥饿体现为"永远只翻前几页"。
  每个关键词开搜前以 `SEARCH_START_PAGE_JITTER_PROB = 0.2` 概率把 start_page 偏移
  `+randint(1, SEARCH_START_PAGE_JITTER_MAX=5)`，命中时打日志。

## 4. 测试与验收

- `MediaCrawler/tests/test_publish_time_window.py`（pytest，约 14 个）：窗口解析（含非法格式、
  END 闭区间边界）、窗口判定（含 unknown×keep 开关）、贴吧时间解析（两种绝对格式/相对文本/空）、
  ε-greedy（ε=0 取头、ε=1 从尾部抽、种子 rng 确定性、quota≥候选数、保序、空输入）。
- 基线：现有 pytest 24 通过 + 1 个**既有失败**（test_store_factory excel 用例，与本次无关）；
  验收 = 新测试全绿且不新增失败。三平台接入逻辑靠代码审查 + 用户日后真实爬取冒烟。

## 5. 用法示例

```
# 只爬 6.10–6.15 发布的帖子（小红书建议同时把 SORT_TYPE 设为 time_descending）
python main.py --platform xhs --keywords "宿舍空调" --start_date 2026-06-10 --end_date 2026-06-15
```
