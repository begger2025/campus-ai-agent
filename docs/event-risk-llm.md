# 事件级 LLM 风险研判（把严重性从关键词表和互动量里解放出来）

> 消融实验结果（真实语料、可复现、不连数据库）：[event-risk-llm-ablation.md](./event-risk-llm-ablation.md)
> 由 `python scripts/ablation_event_risk.py` 生成。

## 1. 这是在修什么缺陷

线上共享库里 15 个**已发布**事件，风险排序是这样的：

| 事件 | risk_level | risk_score | 排名 |
| --- | --- | --- | --- |
| 本科课业压力争议（学生吐槽作业多） | medium | 64.0 | **第 1** |
| …… | | | |
| **东校区宿舍火灾**（宿舍着火、楼道浓烟、消防到场） | **low** | **4.0** | **垫底** |

一场宿舍火灾，是全库风险最低的事件；学生抱怨作业多，是全库风险最高的事件。

根因在 `backend/agent/public_opinion_core/sentiment_risk.py` 的一行：

```python
HIGH_RISK_WORDS = {"诈骗", "银行卡", "验证码", "陌生人", "尾随", "缴费链接"}
```

**系统对"高风险"的全部认识，就是这六个电信诈骗词。** 没有火灾、起火、消防、伤亡、坠楼、
食物中毒、打架、性骚扰、学术不端、抄袭、举报。于是火灾一个高风险词都不命中，只从
`RISK_TOPIC_WORDS` 里的「宿舍」拿到 +4 分——4.0 分的由来就是这个。

两个复合缺陷，各自都是**结构性**的：

### 缺陷①：闭集词表

往表里加一个「火灾」是治不了的。下一次是食物中毒、电梯困人、宿舍盗窃、导师霸凌、
论文代写、心理危机——**校园出事的方式穷举不完**。这正是必须上 LLM 的地方：它不需要
词表里有「火灾」这个词，它读得懂「楼道浓烟滚滚」。

### 缺陷②：风险被互动量污染

`analyze_note_sentiment_and_risk` 里：

```python
if note.comment_count >= 25: risk_score += 8    # 评论多 = 风险高？
if note.share_count >= 10:   risk_score += 10   # 转发多 = 风险高？
if _is_high_heat(note):      risk_score += 8    # 火 = 危险？
```

于是这个分数量的是**流行度**，不是**严重性**。火情播报是事实通报，没人点赞（语料里三条
火灾帖 heat_score 分别是 5 / 9 / 3），风险因此隐形；而一条 10 万赞的「中山大學宿舍日常」
生活 vlog（heat 108,420）反倒一路加分。

## 2. 设计

**在事件级研判，不在帖子级。** 37 个事件 vs 297 条帖子——便宜一个数量级，而且事件才是
UI 上展示、管理员要处置的那个东西。

**严重性与热度解耦**，这是本次改动的核心主张：

| 量 | 是什么 | 谁算 | 本次是否改动 |
| --- | --- | --- | --- |
| `heat_score` / `heat_rank` / `ranking_score` | **流行度**：可测量的互动量算术 | 算术（`scoring.py` / `platform_weights.py`） | **一个字节都不改** |
| `risk_level` / `risk_score` / `risk_reasons` / `concerns` | **严重性**：学校要不要现在就处置 | LLM 研判（规则兜底） | 改 |

LLM **不许发明热度**：`llm_risk._apply` 只写 risk_* 四个字段，模型即使在 JSON 里塞了
`heat_score` 也永远走不到那里（有回归测试盯着：`HeatIsUntouchedTest`）。

### 架构：沿用核心包既有的注入缝

`public_opinion_core/` 不 import 任何 `backend.*`，只吃**注入进来的 Callable**
（`Embedder` / `SentimentClassifier` / `ClusterRefiner`）。本次新增第四个：

```python
# public_opinion_core/llm_risk.py（纯 stdlib）
RiskAssessor = Callable[[str, list[str]], Mapping[str, Any] | None]
#              (事件标题, 成员帖文本) -> {"risk_level", "risk_score", "risk_reasons", "concerns"}
```

| 层 | 文件 | 职责 |
| --- | --- | --- |
| 核心（零依赖） | `backend/agent/public_opinion_core/llm_risk.py` | 协议、验证、逐事件降级；`assessor=None` ⇒ 保留规则风险 |
| 编排 | `public_opinion_core/service.py` | 事件建完 → 研判 → **按新风险重排**（`sort_events`）→ 记忆标注 |
| 部署（认识 HTTP/模型/key） | `backend/services/event_risk.py` | 提示词、`call_llm`（重试 + JSON 缓存 + 用量计费）、`temperature=0` |
| 注入 | `backend/services/public_opinion_adapter.py` | `risk_assessor=get_risk_assessor() if use_llm else None` |

返回的字段就是 `aggregate_risk_level` 本来那四个，**下游（落库、排序、前端）一行都不用改**。

### 提示词的三件事

1. **领域框架**：这是高校校园舆情，服务对象是宣传部/保卫处/学工部；判的是「学校需要为
   这件事**立即采取行动**吗」。high 的范围明确列举（人身安全事故、治安刑事、学术不端、
   违纪处分、师德失范、群体性事件、心理危机、法律与声誉风险），并写明**词表是举例不是清单**。
2. **流行度不是严重性**（写死在提示词里）：「一条帖子有几万点赞不能因此提高风险等级；
   一条帖子没人点赞也不能因此降低风险等级。事故就是事故，哪怕只有 3 个赞。」
   并明令**点赞/评论/转发/热度不得作为 `risk_reasons` 出现**。
3. **日常抱怨不是 high**：食堂饭菜贵、作业多、选课难、宿舍热水不稳——不管多少人点赞。

## 3. 模型会失败，失败不许拖垮流水线

`llm_risk._validate` 是安全边界。风险等级是要**落库、排序、给管理员照着处置**的值——
编造的等级、越界的分数、没有依据的判决，一个都不许进真实数据：

| 模型返回 | 处理 |
| --- | --- |
| 抛异常（超时/网络/SDK） | 该事件退回规则风险 + warning `llm risk unavailable for event 「X」` |
| `None` / 非 JSON 对象 / 解析失败 | 同上（warning `llm risk returned unusable output`） |
| `risk_level` 不在 `{low, medium, high}`（如自创的 `critical`） | 同上 |
| `risk_score` 越界（140 / -5）、非数字（`"很高"`）、`True` | 同上（`bool` 是 `int` 的子类，单独挡） |
| `risk_reasons` 为空 | 同上——**无依据的判决不算判决**：管理员看到 high 必须能看到"凭什么" |
| `risk_level` 写成 `" HIGH "` | 容错：strip + lower |
| `risk_reasons` / `concerns` 有空串、重复、超长 | 清洗：去空白、去重、限长限条数 |

**降级是逐事件的**：一个事件判砸，其余照判（`test_one_bad_event_does_not_poison_the_others`）。
一个都没判成时 `run_log.extra.risk_mode` 如实记成 `rules`——**降级必须在日志里看得见，
不能假装 AI 上过**。所有 warning 进 `agent_run_logs`。

## 4. 消融实验结果（真实语料 297 条，两臂共用同一批事件）

完整表格见 [event-risk-llm-ablation.md](./event-risk-llm-ablation.md)。要点：

| 事件 | 规则：排名 / 等级 / 分 | LLM：排名 / 等级 / 分 |
| --- | --- | --- |
| **东校区宿舍火灾** | 第 36 / 37 · **low** · 4.0 | **第 3 / 37** · **high** · 94.0 |
| **本科课业压力争议** | 第 6 / 37 · **medium** · 64.0 | 第 27 / 37 · **low** · 28.0 |

- 等级分布：规则 **high 0 个** / medium 8 / low 29 → LLM **high 3** / medium 4 / low 30。
  规则臂在这批语料上**一个高风险事件都判不出来**（85 分的门槛只有靠电诈词才够得着）。
- 37 个事件里 **13 个等级发生变化**，37/37 成功研判（0 降级）。
- LLM 另外捞出两个规则完全看不见的高风险事件：
  「中大副院长被实名举报」（规则第 26 → LLM **第 1**，low → high）、
  「中大学生诽谤被开除」（规则第 28 → LLM **第 2**，low → high）——师德失范与违纪处分，
  六个电诈词里当然没有这两个概念。
- 反向也成立：靠互动量刷上来的生活内容被降下去——「中大校园体验与印象」（heat 93,928，
  规则第 1，medium）→ LLM low，「中大食堂试吃会」（heat 32,163，medium/72）→ low。
- **热度不变**：`heat_score` / `heat_rank` / `ranking_score` 两臂逐事件比对**全部一致**。

## 5. 配置与开关

```bash
EVENT_RISK_ENABLED=true    # 0 = 回到规则风险
EVENT_RISK_MAX_TEXTS=20    # 一个事件最多送几条帖子给模型
EVENT_LLM_MODEL=gpt-5.4    # 与聚类精修复用同一组 EVENT_LLM_*（缺省回落 OPENAI_*）
```

答辩现场断网/欠费：`EVENT_RISK_ENABLED=0` 即回到规则风险，事件照出。不关也会自动降级。
`temperature=0` + `call_llm` 的 JSON 缓存 ⇒ 同一批事件重复跑不再花钱，消融实验可复现。

## 6. 已知边界

- 规则风险仍然**逐帖**跑（`processed_posts.risk_level` 回写不变），LLM 只重判**事件级**。
  帖子级风险目前只用于可视化的风险分布图，事件级才是管理员看的东西。
- 一个事件最多送 20 条帖子（代表帖优先，再补其余成员帖）。>20 帖的事件里，排在 20 名
  之后的帖子不进研判——`representative_notes` 是按 ranking_score（流行度）挑的，所以
  这里**先放代表帖再补成员帖**，正是为了不让"没人点赞的严重帖子"被截断掉。
