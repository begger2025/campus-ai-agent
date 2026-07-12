# 消融实验：事件聚类的 LLM 精修

语料：`data/fixtures/event_clustering_297.json`（297 条 processed_posts 只读快照，不连数据库）
参数：cluster=0.7 merge=0.88 align=0.78 min_cluster_size=2 refine_min_size=8 model=gpt-5.4 temperature=0

## 总览

| 指标 | 纯 embedding | embedding + LLM 精修 |
| --- | --- | --- |
| 事件数 | 14 | 37 |
| 最大事件（帖数 / 占比） | 91（31%） | 21（7%） |
| 巨簇（>20% 语料） | 1 | 0 |
| 「…相关讨论」套话标题数 | 14 | 7 |
| 「作息调整」独立成事件 | 是：中山大学·中山大学作息调整相关讨论（11 帖） | 是：中大作息调整争议（14 帖） |
| 　└ 捞回的作息帖 / 全语料作息帖 | 10 / 17 | 13 / 17 |
| 　└ 仍埋在巨簇里的作息帖 | 3 | 0 |
| 被压制的小簇（< min_cluster_size） | 44 | 49 |
| 被 LLM 精修的簇数 | 0 | 7 |
| 聚类模式（run_log） | semantic | semantic+llm |

## 事件列表：纯 embedding

簇大小分布：`[91, 59, 24, 15, 13, 11, 10, 7, 7, 6, 3, 3, 2, 2]`（覆盖 253/297 帖）

| 帖数 | 事件标题 | 来源 |
| ---: | --- | --- |
| 91 | 中山大学相关讨论 | embedding |
| 59 | 课程相关讨论 | embedding |
| 24 | 食堂相关讨论 | embedding |
| 15 | 宿舍相关讨论 | embedding |
| 13 | 中山大学·广州拍照相关讨论 | embedding |
| 11 | 中山大学·中山大学作息调整相关讨论 | embedding |
| 10 | 考试相关讨论 | embedding |
| 7 | 通知相关讨论 | embedding |
| 7 | 宿舍·中山大学相关讨论 | embedding |
| 6 | 中山大学·计算机专业相关讨论 | embedding |
| 3 | 中国红相关讨论 | embedding |
| 3 | 学术相关讨论 | embedding |
| 2 | 中山大学学生恶意侮辱诽谤他人，被开除！ …相关讨论 | embedding |
| 2 | 国内首枚!相关讨论 | embedding |

降级/告警：
- suppressed 44 clusters (44 notes) smaller than min_cluster_size=2: they are not public events

## 事件列表：embedding + LLM 精修

簇大小分布：`[21, 16, 14, 14, 14, 13, 13, 13, 9, 8, 8, 7, 7, 7, 7, 6, 6, 6, 5, 5, 5, 4, 4, 4, 4, 3, 3, 3, 3, 2, 2, 2, 2, 2, 2, 2, 2]`（覆盖 248/297 帖）

| 帖数 | 事件标题 | 来源 |
| ---: | --- | --- |
| 21 | 零散杂项帖 | LLM 精修 |
| 16 | 中大学生与宿舍生活 | LLM 精修 |
| 14 | 中大报考与招生宣传 | LLM 精修 |
| 14 | 中大校园日常Vlog | LLM 精修 |
| 14 | 中大作息调整争议 | LLM 精修 |
| 13 | 中大校园体验与印象 | LLM 精修 |
| 13 | 各专业考研咨询 | LLM 精修 |
| 13 | 中大考研泛咨询 | LLM 精修 |
| 9 | 计算机考研经验 | LLM 精修 |
| 8 | 中大食堂探店推荐 | LLM 精修 |
| 8 | 选课与学分规则 | LLM 精修 |
| 7 | 中大南校园游览推荐 | LLM 精修 |
| 7 | 中大校区与宿舍环境 | LLM 精修 |
| 7 | 通知相关讨论 | embedding |
| 7 | 宿舍相关讨论 | embedding |
| 6 | 中山大学相关讨论 | embedding |
| 6 | 中大校庆与毕业内容 | LLM 精修 |
| 6 | 中大图情考研难度 | LLM 精修 |
| 5 | 中大食堂试吃会 | LLM 精修 |
| 5 | 宿舍大规模搬迁争议 | LLM 精修 |
| 5 | 中大学习空间与图书馆 | LLM 精修 |
| 4 | 本科课业压力争议 | LLM 精修 |
| 4 | 食堂价格分量争议 | LLM 精修 |
| 4 | 绩点与辅修保研 | LLM 精修 |
| 4 | 东校区宿舍火灾 | LLM 精修 |
| 3 | 中国红相关讨论 | embedding |
| 3 | 学术相关讨论 | embedding |
| 3 | 广州雨天公园推荐 | LLM 精修 |
| 3 | 拟录取与分数线 | LLM 精修 |
| 2 | 中山大学学生恶意侮辱诽谤他人，被开除！ …相关讨论 | embedding |
| 2 | 专业课程设置咨询 | LLM 精修 |
| 2 | 项飙中大对谈活动 | LLM 精修 |
| 2 | 中大图情硕士体验 | LLM 精修 |
| 2 | 国内首枚!相关讨论 | embedding |
| 2 | 中大参观预约咨询 | LLM 精修 |
| 2 | 校外校区食堂体验 | LLM 精修 |
| 2 | 食堂对外开放询问 | LLM 精修 |

降级/告警：
- suppressed 49 clusters (49 notes) smaller than min_cluster_size=2: they are not public events

## LLM 用量

- 调用 7 次（缓存命中 7，失败 0）、token 0、耗时 0 ms
- 精修簇数：7（只精修 ≥ 8 帖的簇）

> 由 `python scripts/ablation_event_refine.py` 生成。
