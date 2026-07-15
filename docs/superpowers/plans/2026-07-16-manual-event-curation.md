# 人工事件修正（manual event curation）实施计划

> 状态：设计已定，分五阶段实施。2026-07-16 由用户提出：
> 重命名 / 创建 / 删除 / 合并 / 帖子加入 / 帖子移出——管理员修正 LLM 的聚类结果。

## 核心语义决策（先定死，全部实现围绕它）

**人工编辑 = 锁（curated=True）**，延续「机器绝不覆盖人的决定」的既有原则（同
actor 归档语义，见 admin_service 的 SYSTEM_REVIEWER 判据）：

1. 事件被人工编辑过（改名/合并/增删成员/人工创建）→ `public_events.curated = TRUE`；
2. **重新生成管线对 curated 行只读**：`persist_public_events` 遇 curated 的
   event_key 跳过 upsert（留 run 日志 warning）；
3. **curated 事件的成员帖退出聚类池**：生成取数时排除已链接到 curated 事件的
   processed_post（否则下轮同一批帖又聚出重复事件——等于人工合并白做）；
4. 人工创建的事件 event_key 前缀 `man:`（区别于 `sem:`/规则桶），天然不参与快照对齐。

**删除语义**：硬删除仅允许 draft / rejected / archived 状态（published 必须先归档——
对外结论不许静默蒸发）；删除前把事件快照写进 admin_operations 的 detail（审计可追）。
**合并语义**：source 事件的链接并入 target（去重），target 重算聚合并 curated=True；
source 不硬删而是归档 + 审核意见「已并入 #target_id」——保留审计轨迹。

## 聚合重算（算术，不走 LLM）

成员变化后重算：source_count=链接数、heat_score=成员帖 heat 之和、
member_times/event_time（中位数）/date_range 从成员帖 publish_time 现算。
风险/生命周期研判**保留原值**（那是 LLM 对内容的判断，成员微调不重跑；
管理员认为判断过时可用既有审核流程处理）。

## 阶段

### S1 迁移（共享库纪律：干跑 → 用户确认 → 执行 → 幂等复跑）
`scripts/add_public_events_curated.py`（仿 add_processed_posts_excluded.py）：
- `public_events.curated BOOLEAN DEFAULT FALSE` + 索引；只 ADD 不改删。
- models.py 加列。

### S2 服务层 + API（TDD，backend/services/event_curation.py + routers/admin_events.py）
- PATCH  /admin/events/{id}                {title}            重命名
- POST   /admin/events                     {title, post_ids}  创建（man: key）
- DELETE /admin/events/{id}                                   硬删（状态门槛+快照审计）
- POST   /admin/events/{id}/merge          {source_id}        合并
- POST   /admin/events/{id}/posts          {processed_post_id} 加入（role='manual'）
- DELETE /admin/events/{id}/posts/{pid}                        移出
全部：写 write_admin_operation 审计 + curated=True + 聚合重算。
测试关键用例：published 不许硬删；合并后 source 归档且 target 计数=并集；
移出最后一条成员的事件不许留空壳（拒绝或提示删除）；curated 行 persist 跳过。

### S3 再生成保护
- persist_public_events：curated event_key 跳过 upsert + warning；
- 生成取数排除 curated 事件的成员帖（adapter 的生成入口加反连接过滤）；
- 测试：人工合并后重跑生成，不再冒出重复事件；改名不被覆盖。

### S4 前端（AdminEventsView 详情抽屉扩展）
改名（行内编辑）、合并（选目标事件对话框）、成员管理（列表+移出按钮、
站内搜索添加帖子）、删除（状态门槛提示）、创建（从数据管理页勾选帖子发起）。
curated 事件加「人工修正」徽章（审核员要知道哪些是人改过的）。

### S5 验收
全量回归 + build + 共享库迁移（走纪律）+ 真库端到端冒烟（改名→重跑生成→
名字不回退；合并→重跑→无重复）+ 提交。

## 已知边界（如实写给答辩）
- 帖子加入/移出操作的对象是 event_post_links（代表帖表）：全量成员本就只以
  聚合数形式存在，人工调整的是"事件的证据链"而非完整成员集——口径与工作台
  展示一致。
- curated 事件永久退出机器再生成：管理员接管后 AI 不再更新它的聚合数——
  这是「人接管」的代价，界面上用徽章明示。
