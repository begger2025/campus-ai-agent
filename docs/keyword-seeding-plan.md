# 语料扩充：关键词播种计划（96 词 · 8 轮）

> 本文档回答"**播什么词、按什么节奏播**"。爬取的操作细节（扫码登录、监控、断点续爬、
> 故障处理、入库四步的完整说明）见 [xhs-parallel-crawl-guide.md](xhs-parallel-crawl-guide.md)，
> 本文只在需要处引用，不重复。

---

## 一、目标与验收（为什么要爬、爬到多少算成）

当前基线（2026-07-15 实测）：`processed_posts` 未剔除 406 条，**近 30 天仅 30 条（7.4%）**。

系统里一大批机制是"当下"的函数，它们全部处于饥饿状态：`escalating`（持续发酵）
的增长判定、时效权重、趋势图、「最近有什么热点」。语料不补，这些已经建好的功能
等于不存在。

| 验收指标 | 现状 | 目标 | 解锁什么 |
|---|---|---|---|
| 近 30 天帖子数 | 19 | **≥ 500** | 增长信号、escalating、趋势图、"最近"类提问 |
| 单话题帖子数 | 多数 <10 | **主要话题 ≥ 30** | 事件簇有观点分化，简报写得出"主要观点" |
| 已发布事件数 | 8 | 25~40 | 聊天的事件层命中率（LLM 研判结论的覆盖面） |
| 总量 | 395 | 1500~3000 | 到 3000 后边际收益变平，**不必追更多** |

优先级：**新鲜度 > 话题密度 > 总量**。

---

## 二、关键词三条铁律（播错一条，整轮白跑或引来垃圾）

1. **只给话题词，不带校名。** `CRAWL_TOPIC_QUALIFIER` 会自动组合——你播「食堂」，
   爬虫实际搜「中山大学 食堂」。自己写「中山大学食堂」会组合成重复前缀。
2. **绝不播裸的「中山大学」。** `ALLOW_BROAD_KEYWORDS=False` 会直接拦掉；
   泛词捞回来的也全是与具体舆情无关的凑数帖。
3. **别播纯物品词。** 库里那条床垫集采广告就是「床垫」这类词招来的。
   物品要和诉求绑定：「宿舍空调」可以，「空调」勉强，「床垫」不行。

---

## 三、词库总表（96 词，按舆情价值分层）

### T1 · 进行中事件 + 强舆情信号词（最高优先）

| 组 | 关键词 | 说明 |
|---|---|---|
| 进行中事件 | 宿舍搬迁 · 搬宿舍 · 学术不端 · 实名举报 · 课间缩短 · 图书馆预约 | 库里已确认存在的事件，追增量 |
| 口碑信号词 | 吐槽 · 避雷 · 劝退 · 维权 · 投诉 · 后悔 | 高杠杆：搜出来几乎全是真实学生表达 |

> T1 建议**每两周复播一轮**（队列去重只挡 pending/claimed，done 过的词可以重新入队）——
> 进行中事件的增长信号就靠持续追踪。

### T2 · 常青主话题

| 话题域 | 关键词 |
|---|---|
| 住宿后勤 | 宿舍条件 · 宿舍空调 · 宿舍热水 · 宿舍卫生 · 宿舍维修 · 宿舍限电 · 宿舍分配 · 四人间 · 洗衣机 · 澡堂 · 门禁 · 快递 |
| 饮食 | 食堂 · 饭堂 · 食堂价格 · 食堂涨价 · 食堂卫生 · 外卖 · 校内超市 · 夜宵 |
| 学业教务 | 选课 · 抢课 · 转专业 · 绩点 · 保研 · 考研 · 挂科 · 补考 · 期末 · 早八 · 学分 · 延毕 · 毕业论文 · 查重 |
| 行政权益 | 辅导员 · 教务处 · 奖学金 · 助学金 · 评优 · 处分 · 校规 · 请假 · 报销 · 学生会 |
| 安全健康 | 校医院 · 心理咨询 · 诈骗 · 电诈 · 偷拍 · 骚扰 · 校车 · 电动车 · 消防 · 失物 |
| 就业 | 就业 · 实习 · 秋招 · 校招 · 考公 · offer |

### T3 · 设施校区 + 节点性话题（看时令补播）

| 话题域 | 关键词 |
|---|---|
| 设施 | 图书馆 · 体育馆 · 游泳池 · 教学楼 · 校园网 · 电梯 · 施工 · 修路 |
| 校区 | 东校区 · 南校区 · 珠海校区 · 深圳校区 |
| 节点性 | 毕业季 · 毕业照 · 录取 · 分数线 · 招生 · 转学 · 军训 · 迎新 · 开学 · 新生 · 校庆 · 放假安排 · 社团 · 校园卡 |

> 节点性词看日历播：**7 月正值毕业季 + 招生季**，毕业/录取组现在播正合适；
> 军训/迎新/开学留到 8 月下旬。

---

## 四、轮次计划（每轮 12 词，命令可直接复制）

节奏建议：**隔天一轮**。一轮小红书两机并行约 2~2.5 小时/机，快手/知乎附加约半小时。
8 轮 ≈ 两周半，配合快手走量，近 30 天 500 条的目标是现实的。

每轮固定两步：先 `--dry-run` 预览，确认"待插入"条数无误再去掉重跑。
平台策略：**同一批词播 xhs + ks 两平台**（小红书管新鲜度，快手管量）；
知乎观点密度高但吃词慢，每两轮补播一次当轮的词（`--platform zhihu`）。

```powershell
# ========== 第 1 轮 · T1 全部（进行中事件 + 口碑词） ==========
.\.venv\Scripts\python.exe scripts\seed_crawl_queue.py --platform xhs,ks `
  --keywords "宿舍搬迁,搬宿舍,学术不端,实名举报,课间缩短,图书馆预约,吐槽,避雷,劝退,维权,投诉,后悔" --dry-run

# ========== 第 2 轮 · 住宿后勤 ==========
.\.venv\Scripts\python.exe scripts\seed_crawl_queue.py --platform xhs,ks `
  --keywords "宿舍条件,宿舍空调,宿舍热水,宿舍卫生,宿舍维修,宿舍限电,宿舍分配,四人间,洗衣机,澡堂,门禁,快递" --dry-run

# ========== 第 3 轮 · 饮食 + 毕业/招生季（当令） ==========
.\.venv\Scripts\python.exe scripts\seed_crawl_queue.py --platform xhs,ks `
  --keywords "食堂,饭堂,食堂价格,食堂涨价,食堂卫生,外卖,夜宵,毕业季,毕业照,录取,分数线,招生" --dry-run

# ========== 第 4 轮 · 学业教务 A ==========
.\.venv\Scripts\python.exe scripts\seed_crawl_queue.py --platform xhs,ks `
  --keywords "选课,抢课,转专业,绩点,保研,考研,挂科,补考,期末,早八,学分,延毕" --dry-run

# ========== 第 5 轮 · 学业教务 B + 就业 ==========
.\.venv\Scripts\python.exe scripts\seed_crawl_queue.py --platform xhs,ks `
  --keywords "毕业论文,查重,就业,实习,秋招,校招,考公,offer,辅导员,教务处,奖学金,助学金" --dry-run

# ========== 第 6 轮 · 行政权益 + 安全 A ==========
.\.venv\Scripts\python.exe scripts\seed_crawl_queue.py --platform xhs,ks `
  --keywords "评优,处分,校规,请假,报销,学生会,校医院,心理咨询,诈骗,电诈,偷拍,骚扰" --dry-run

# ========== 第 7 轮 · 安全 B + 设施 ==========
.\.venv\Scripts\python.exe scripts\seed_crawl_queue.py --platform xhs,ks `
  --keywords "校车,电动车,消防,失物,图书馆,体育馆,游泳池,教学楼,校园网,电梯,施工,修路" --dry-run

# ========== 第 8 轮 · 校区 + 节点性补齐 ==========
.\.venv\Scripts\python.exe scripts\seed_crawl_queue.py --platform xhs,ks `
  --keywords "东校区,南校区,珠海校区,深圳校区,校庆,放假安排,社团,校园卡,转学,新生,迎新,开学" --dry-run
```

> 平台码对照：小红书 `xhs`、快手 `ks`、知乎 `zhihu`、微博 `wb`、贴吧 `tieba`
> （注意微博是 **wb** 不是 weibo）。
> 播种是笛卡尔积：`--platform xhs,ks` × 12 词 = 入队 24 条任务。

---

## 五、每轮标准作业流程（SOP）

```
播种（机器 A，两分钟）
  └─ dry-run 预览 → 确认条数 → 去掉 --dry-run 正式播种
爬取（两机并行，各 ~2.5h）
  ├─ 机器 A：cd MediaCrawler
  │   .\.venv\Scripts\python.exe main.py --platform xhs --from-queue yes --worker cjt `
  │     --get_comment yes --fresh yes --start_date <今天往前30天，如 2026-06-15>
  ├─ 机器 B（组员，只有 --worker 不同）：
  │   .\.venv\Scripts\python.exe main.py --platform xhs --from-queue yes --worker pissy `
  │     --get_comment yes --fresh yes --start_date <同上>
  └─ 快手（任一台，xhs 跑完后）：--platform ks，其余参数同上
入库（机器 A，参见 xhs-parallel-crawl-guide.md §入库四步）
  ├─ scripts\sync_media_to_raw_posts.py --limit 0     ← --limit 0 必须写！默认 100 会静默丢
  ├─ scripts\process_raw_posts.py --limit 0
  └─ scripts\generate_public_events.py --preview → 确认 → 正式生成
质量管控（管理员，5 分钟）
  └─ 数据管理页过一遍新帖：台湾国立中山大学 / 蹭校名广告 → 剔除（理由必填，可恢复）
事件审核（管理员）
  └─ 事件审核页处理新 draft：通过并发布 / 驳回
复测指标（机器 A，一条命令）
  └─ 见下节
```

队列状态随时可查：
```powershell
.\.venv\Scripts\python.exe scripts\crawl_queue_status.py
```
中断重来：`reset_crawl_queue.py --requeue-claimed`（收回租约）/ `--requeue-failed`（重排失败）。

---

## 六、进度复测（每轮爬完跑一次，留数据）

```powershell
# 新鲜度 KPI（只读）
.\.venv\Scripts\python.exe -c "import datetime as dt; from backend.database import SessionLocal; from backend.models import ProcessedPost; db=SessionLocal(); q=db.query(ProcessedPost).filter(ProcessedPost.excluded.is_(False)); total=q.count(); recent=q.filter(ProcessedPost.publish_time>=dt.datetime.now()-dt.timedelta(days=30)).count(); print(f'总量 {total}，近30天 {recent}（{recent/max(total,1):.1%}）'); db.close()"
```

建议每轮记一行（答辩时这张表就是"数据工程"的过程证据）：

| 轮次 | 日期 | 播种词组 | 新增帖 | 剔除 | 总量 | 近30天占比 | 新发布事件 |
|---|---|---|---|---|---|---|---|
| 基线 | 07-15 | — | — | — | 406 | 7.4% | 8 |
| 1 | | T1 | | | | | |

---

## 七、坑清单（每一条都真实踩过或差点踩）

| 坑 | 后果 | 规避 |
|---|---|---|
| 不带 `--fresh yes` | 捞回历史爆款老帖，新鲜度目标作废 | 所有平台都带（知乎也生效，切时间倒序） |
| `sync/process` 忘写 `--limit 0` | 默认 100，超出部分**静默丢弃** | 两条命令都显式 `--limit 0` |
| 播裸「中山大学」 | 被 `ALLOW_BROAD_KEYWORDS` 拦截 | 只播话题词 |
| 自己加「中山大学」前缀 | 组合成重复前缀，搜索质量下降 | 话题限定符自动加 |
| 播纯物品词（床垫…） | 招来集采广告类噪声 | 物品必须绑诉求（宿舍空调 ✓） |
| 小红书跑到一半"卡住" | 其实在 sleep（保守模式 3~5 分钟/条详情） | 看日志 `Sleeping ... before detail fetch`，别动 |
| 为提速调小 sleep | 触发验证码 → fail-fast 整轮白跑 | 时间预算按 2~2.5h/机排 |
| 爬完不做剔除 | 无关帖污染统计、聚类、聊天三条下游 | 每轮入库后过一遍数据管理页 |
| 微博平台码写 weibo | 播种脚本直接报错 | 是 `wb` |

---

## 八、和智能选题的配合

跑完 3~4 轮后，`--from-recommendations` 开始有价值（推荐基于近 30 天数据，
现在数据太稀它推不出东西）：

```powershell
# 让系统根据已采集数据推荐下一批词（与手动词并用，不互斥）
.\.venv\Scripts\python.exe scripts\seed_crawl_queue.py --platform xhs,ks --from-recommendations --top 10 --dry-run
```

手动词库管**广度**（本文档），智能推荐管**深挖**（哪些话题正在起量）——
后者正是答辩里"AI 参与数据工程"的展示位。
