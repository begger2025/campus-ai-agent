# 设计：客观数据驱动的爬取关键词推荐（智能选题）

- 日期：2026-07-10
- 状态：已实现（2026-07-10，分支 feature/keyword-recommendation）
- 相关文档：docs/crawl-real-data.md（爬取流水线）、docs/architecture.md、子项目 docs/public-opinion-agent-design.md

## 1. 背景与目标

当前爬虫的搜索关键词完全靠人主观输入（"人想到什么就搜什么"），导致：

1. 爬取内容不基于客观数据，覆盖面取决于运营者的想象力；
2. 用户在对话页提问时，经常出现"爬虫从没搜过相关数据"、答不上来的情况。

**目标**：让程序基于库里的客观数据自动计算"下一轮优先爬什么"，以管理端推荐面板的形式呈现（人在环审核，管理员采纳后手动执行爬取），使网站内容供给逐渐贴合真实需求与真实热点。

### 已锁定的产品决策（用户确认）

| 决策点 | 选择 |
|---|---|
| 产品形态 | 管理端推荐面板（非自动爬取），管理员一键复制爬取命令 |
| 算法路线 | 方案 A：规则打分管线（零 LLM，公式可解释，可完整测试） |
| 信号组合 | 四信号融合：A 用户需求 + B 供给缺口 + C 小红书热度延续 + D 小红书新话题发现 |

## 2. 四路客观信号

| 信号 | 含义 | 热度产生地 | 数据来源 |
|---|---|---|---|
| **A 需求热度** | 用户最近在问什么 | 本网站（对话页） | 新表 `chat_query_log`（提问时间 + 意图路由提取的话题词） |
| **B 供给缺口** | 问了但站内没数据 | 本网站 | 同表 `hit_count` 字段（提问时检索命中的事件数） |
| **C 热度延续** | 已爬话题在小红书上是否仍在升温 | 小红书（点赞/评论/收藏） | `processed_posts` 近 14 天按 `source_keyword` 聚合互动量（点赞+评论+收藏+转发，见 §3 公式） |
| **D 新话题发现** | 小红书上正在热、但从没爬过的话题 | 小红书（笔记标签 + 互动量） | `processed_posts.tags_json` + 四个互动量字段，近 14 天 |

设计要点：

- C、D 完全不依赖用户数据——**冷启动时（没有任何用户提问）面板照样出推荐**。
- A、B 保证"用户问什么就补什么"——直接对应目标 2。
- D 解决"发现"问题：爬"食堂"回来的笔记常带 `#中大宿舍` `#期末周` 等作者标签，聚合这些标签就能发现相邻热点；配合定期用宽泛种子词（如"中山大学"）爬一轮作为发现输入源，形成"广撒网 → 挖标签 → 定向爬 → 再挖掘"的自驱闭环（种子轮询本身是运营动作，不在本期代码范围内）。

## 3. 打分公式（可现场手算）

```
score(kw) = (0.5·需求分 + 0.3·缺口分 + 0.2·热点分) × 已爬降权 × 10
            # 三个子分均归一化到 0–1、权重和为 1 → 总分严格落在 0–10

需求分   = norm( Σ 每次提问 0.5^(距今天数/3) )      # 3 天半衰期，除以本轮最大需求归一化
缺口分   = min(需求分 × 2, 1)（最近命中 < 3 时），否则 0   # 问了没答案的优先补，封顶 1
热点分   = norm( Σ 该词相关内容 互动权重 × 0.5^(距发布天数/7) )
           互动权重 = log10(1 + 点赞 + 评论 + 收藏 + 转发)   # 对数抑制爆款离群值
已爬降权 = 该词 14 天内爬过 ? 0.3 : 1.0             # 上次爬取时间 = processed_posts 该
                                                    #   source_keyword 最新 created_at
```

- "热点分"对 C（词 = `source_keyword`）和 D（词 = 标签）用同一公式，只是词的来源不同。
- 归一化 norm()：除以本轮所有候选词的最大热点分，压到 0–1，再与 A/B 同尺度加权。
- 每条推荐生成人话理由 + 信号来源徽章，例如：
  - `#1 宿舍空调 9.1 分 【需求】【缺口】` — 近 7 天被问 5 次，最近一次命中 0 条数据，从未爬取过
  - `#2 期末周 5.8 分 【新话题】` — 近 14 天 12 条已爬笔记带此标签、互动量高，从未作为关键词爬取
  - `#3 食堂涨价 4.2 分 【热点】` — 站内相关内容在小红书互动量持续上升，3 天前爬过（已降权）

### 候选词与归一化合并（不引入 jieba）

- A/B 的词直接复用 `route_intent` 已提取的话题词（记录进日志表），不重复造分词轮子；
- D 的词是笔记作者自己打的标签（`tags_json`），天然已是词；
- planner 内做轻量归一化合并：去首尾空白、剥离"中山大学/中大"前缀、包含关系合并（"宿舍空调"吸收"空调"的分数）、通用词黑名单过滤（"大学"、"校园"、"大学生活"、"中山大学"等约 20 个内置词）。

## 4. 双仓分工与数据模型

### 子项目（campus-opinion-agent）——算法核心，TDD

新增 `backend/app/public_opinion_core/keyword_planner.py`，**纯函数、零 IO**：

```python
@dataclass
class QueryRecord:      # 一次用户提问
    keyword: str; asked_at: datetime; hit_count: int

@dataclass
class ContentStat:      # 一个词的站内内容统计（C 用 source_keyword，D 用标签）
    keyword: str; engagement: int; published_at: datetime

@dataclass
class KeywordSuggestion:
    keyword: str; score: float; signals: list[str]   # ["demand","gap","heat","discovery"]
    ask_count_7d: int; last_asked_at: datetime | None; last_hit_count: int | None
    last_crawled_at: datetime | None; reason: str

def plan_keywords(queries: list[QueryRecord],
                  content_stats: list[ContentStat],
                  crawled_at_by_keyword: dict[str, datetime],
                  now: datetime, top_n: int = 10) -> list[KeywordSuggestion]
```

同步机制：`scripts/sync_opinion_core.py` 对 core 目录整目录 glob，新文件跑一次脚本自动进主项目，无需改白名单。

### 主项目（campus-ai-agent-main）——落库 / 聚合 / API / 前端

**新表 `chat_query_log`**（加入 `backend/models.py` 的 Base metadata，兼容 SQLite 演示快照 create_all）：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | Integer PK | |
| user_id | String(64) | 提问用户 |
| message | String(500) | 原始提问（与请求体上限一致） |
| intent | String(32) | 路由意图 |
| keyword | String(64)，索引 | 路由提取的话题词（可为空） |
| hit_count | Integer | 本次回答检索命中的事件数（search 意图取 notes 数） |
| created_at | DateTime，索引 | |

**落库点**：`backend/routers/agent_public.py` 的 `/agent/public/chat` 成功路径——`service.chat()` 返回后，从返回值取 `intent`/`keyword`/`len(events)` 插一条；整体 try/except 包裹，**写日志失败绝不影响对话主流程**。

**新 adapter**（`backend/services/keyword_suggestion_adapter.py`）：

1. 读近 30 天 `chat_query_log` → `QueryRecord` 列表；
2. 读近 14 天 `processed_posts`：按 `source_keyword` 一组（C）、解析 `tags_json` 每标签一组（D）→ `ContentStat` 列表；
3. 按 `source_keyword` 取 `max(created_at)` → 上次爬取时间表；
4. 调 `plan_keywords()` 返回 Top10。

**新 API**：`GET /api/admin/keyword-suggestions?days=30&top=10`（`require_admin`），返回建议列表 + 各信号数据量元信息（供面板显示"基于 X 条提问 / Y 条内容计算"）。

**前端**：管理端新页面「智能选题」（对齐现有 Admin 页面风格，路由与导航同其余 Admin 页）：

- 推荐列表：排名、关键词、分数条、信号徽章（需求/缺口/热点/新话题）、人话理由、上次爬取时间；
- 每行"复制爬取命令"按钮：`.\.venv\Scripts\python.exe main.py --keywords "<kw>" --get_comment yes`（在 MediaCrawler 目录下执行）；
- 顶部说明卡片讲清打分逻辑；空数据时显示引导文案。

## 5. 测试策略（零网络纪律不变）

**子项目（纯函数，约 14 个）**：需求分时间衰减、缺口加权触发/不触发、热点分对数抑制与归一化、已爬降权、四信号融合排序、包含关系合并、前缀剥离、黑名单过滤、reason 文案、signals 徽章、空输入、top_n 截断。

**主项目（SQLite 内存库，约 8 个）**：chat 成功后日志落库字段正确、写日志抛异常不影响 chat 返回、API 权限（非 admin 403）、API 空数据返回空列表、adapter 端到端（造提问+内容数据 → 断言 Top1 及理由）、demo 快照 create_all 含新表、seed_query_log 导入条数与字段、check_question_coverage 命中率计算。

## 6. 答辩演示动线

> "爬什么不再靠人拍脑袋——系统看四件客观事实：用户在问什么、哪些问题答不上来、已爬话题在小红书还热不热、小红书上有什么新话题在冒头。"

1. 开场直接看「智能选题」面板：即使没有用户提问，C/D 信号已给出带理由的推荐（不怕冷启动）；
2. 登录普通用户，连问 3 个库里没有的问题（如"宿舍空调怎么样"）；
3. 切管理员刷新面板："宿舍空调"带着"被问 3 次、命中 0 条、从未爬取"的理由冲到榜首；
4. 点"复制爬取命令"，（口头讲）爬完跑完流水线后用户再问就有数据了——需求→供给闭环完成。

> ⚠️ 演示前提：第 2-3 步的"宿舍空调"精确提取依赖 LLM 意图路由（需配置 API key）。
> 无 key 时规则兜底只能从 KNOWN_KEYWORDS 提取粗粒度词（"宿舍空调怎么样"→"宿舍"），
> 若"宿舍"已有大量数据且近期爬过，它不会登顶。答辩演示务必配好 key，或改问一个
> 不含已知词、库里也没有的话题。

## 7. 开发期数据自举策略（冷启动运营手册）

网站开发期没有真实用户，但上线时必须已覆盖近期热点、接得住第一批提问。三板斧：

### 7.1 种子词矩阵初爬（第 1–3 天）

- 关键词 = `学校限定词 × 校园生活领域词` 矩阵 + 裸词"中山大学"（借小红书搜索排序拿平台侧最热内容）：
  `{中山大学, 中大} × {宿舍, 食堂, 选课, 期末, 图书馆, 转专业, 军训, 奖学金, 保研, 实习, 校车, 校园卡, 搬迁}`
- 写进 `base_config.py` 的 `KEYWORDS`（逗号分隔），`run_xhs_batches.py --rounds 12 --interval-minutes 10` 分批跑。
- 吞吐量现实预期：反封号节流下一轮最多 5 条详情，一天 1–2 批次 ≈ 60–120 条笔记，
  **连跑 10–14 天 ≈ 800–1500 条**；`XHS_SKIP_EXISTING_NOTE_DETAILS` 保证重复轮次不浪费额度。
- 注意：种子矩阵只是初爬清单（运营动作），**不进打分算法**——算法信号仍是第 2 节的四路。

### 7.2 C/D 信号滚动选题（第 4 天起，吃自己的狗粮）

初爬起量后，「智能选题」面板的 C/D 信号即可工作。开发期每日循环：
跑流水线 → 看面板 → 次日 KEYWORDS 采纳 D 信号冒头的新话题。
上线前的数据积累本身就由本算法选题，答辩可作为算法有效性的实证。

### 7.3 真实问题预收集与覆盖率验收（贯穿全程）

- 问卷/内测收集 30–50 个真实问题（"你会问舆情助手什么？"）；
- `scripts/seed_query_log.py`（本期实现）：问题清单导入 `chat_query_log`，提前激活 A/B 信号，
  缺口信号直接指出哪些真实需求库里接不住；内测同学在对话页直接提问亦可自然产生日志；
- `scripts/check_question_coverage.py`（本期实现）：问题清单逐条跑检索、统计命中率
  （hit_count > 0 占比），**开发期验收目标 ≥ 80%**——"满足相当数量的用户"由此变为可测量指标。

节奏：矩阵初爬起量 → 算法滚动选题 → 问题清单验收缺口，循环至覆盖率达标。

## 8. 范围外（明确不做）

- 自动触发爬虫（小红书需扫码/验证码，人在环是硬约束，也是产品决策）；
- 站外热榜（微博热搜等）接入；
- 网站端浏览量/点击量埋点；
- 种子词轮询的自动调度代码（7.1 是手动运营动作，写入运营手册）；
- jieba 或任何新分词依赖。

## 9. 增量：微博/贴吧完整参与 + 标签格式修复（2026-07-10 追加，已批准推进）

**背景**：初版 D 信号实际上只有小红书供给；且核实发现小红书 `tag_list` 入库是
**字典数组** `[{"name":"宿舍","type":"topic"}]`，adapter 的 `str(tag)` 会把字典
字符串当关键词——真实数据下面板会出乱码推荐（合成测试未暴露的潜伏 bug）。

1. **标签格式修复（双层防御）**：
   - 入库层：`_map_xhs` 把 tag_list 解析为纯名字数组 `["宿舍",...]` 再写 tags_json；
   - 读取层：adapter `_parse_tags` 对字典项取 `item["name"]`（容错旧数据）。
2. **微博**：`weibo_note` 无独立话题字段，话题嵌在正文（`#话题#`）。`_map_weibo`
   用正则提取（剥 `[超话]` 后缀、长度 2–20、去重）写入 tags_json。
3. **贴吧**：无标签机制，`tieba_name`（吧名）是唯一原生话题信号，作为单标签写入；
   校名吧被 planner 黑名单自动过滤。
4. **存量回填**：`scripts/backfill_tags.py --dry-run`——对已入库的三平台行幂等补写/
   归一化 tags_json（raw_posts + processed_posts 双表；贴吧吧名从 raw_json 取）。
5. **前端**：面板顶部平台单选（小红书/微博/贴吧），复制命令带 `--platform`。
6. **算法核心零改动**（子项目不参与本次增量）。

## 10. 风险与对策

| 风险 | 对策 |
|---|---|
| 意图路由偶尔提取不出话题词（keyword 为空） | 照常落日志但 planner 忽略空词；不影响 C/D 信号 |
| tags_json 有脏数据/非 JSON | adapter 解析失败按空标签处理，单测覆盖 |
| 演示模式 SQLite 无历史数据 | 面板显示引导文案；演示动线第 2 步现场制造数据 |
| 权重 0.5/0.3/0.2 是拍的 | 常量集中定义并在文档说明"可调超参"，答辩如实说明设计取舍 |
