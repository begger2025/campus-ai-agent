# Week 7 P2：工程质量 + 演示降级 + 个人事务页真实化

P0（安全/登录）、P1（后台/用户/闭环）之后的第三批产品化工作。

## P2a 日志与全局异常处理

- **Python logging 落地**（此前后端零 logging）：`backend/logging_setup.py`，
  控制台 + `data/logs/app.log` 轮转文件（5MB×3），`LOG_LEVEL` env 可调，幂等初始化。
  业务代码用 `logging.getLogger("campus.<module>")`。
- **全局异常兜底**（`backend/main.py`）：未捕获异常统一返回
  `{"code":500,"message":"服务器内部错误，请稍后重试","data":null}`——不向前端泄露
  堆栈；同时写 Python 日志 + 落 `system_logs` 表（管理后台"系统日志"页签可见，
  线上错误形成可视闭环）。业务 `HTTPException`（401/404 等）不受影响。
- 测试：`backend/tests/test_error_handling.py`（4 个，TDD 先红后绿）。

## P2b 演示降级预案（答辩保险）

共享 Aliyun RDS 本周多次连接超时。现在有两步保险：

1. **生成快照**（MySQL 可用时提前跑一次，之后定期刷新）：
   `.venv\Scripts\python.exe scripts\make_demo_snapshot.py`
   → 把 backend 模型的全部表导出到 `data/campus_demo.db`（本次实测 575 行，
   含 182 帖、36 事件、9 账号——密码哈希一并复制，登录照常）。
2. **降级演示**：MySQL 挂掉时直接运行 **`demo.bat`**——通过 `CAMPUS_DEMO_MODE=1`
   让后端切到本地 SQLite 快照，前端零改动，全功能演示（含登录、后台、Agent）。

已实测：demo 模式下事件列表、admin 登录、后台概览全部正常。

## P2c 路由层测试补全

`backend/tests/test_public_api.py`（8 个）：公开事件列表只返回 published、
详情含代表帖、draft/未知 ID 404、公开端点无 token 可访问（游客浏览契约）、
反馈入库为 pending、空内容 422、admin 端点无 token 一律 401。
后端测试总数 **54**（P0 前是 11）。

## P2d 个人事务页轻量真实化（用户选定方案）

重写 `PersonalView.vue`，删除全部写死数据（假课表/假活动/假日程/假 AI 建议）：

- **待办与提醒**：真实可用的本地待办（新建/勾选完成/删除，截止日期 + 优先级 +
  逾期/临期徽章），按用户名隔离存 localStorage（`campus_personal_tasks_<username>`），
  不加后端表——课程项目里"个人数据不出本机"也是一种诚实的设计取舍。
- **与你相关的舆情动态**：真实已发布事件中的中高风险项，可跳详情/影响评估。
- **事件影响评估**：展示所选事件的真实 summary/关注点/风险依据（不再是编造的
  影响话术）；"问舆情助手：对我有什么影响"按钮带预填问题跳转真实 Agent。
- 统计卡全部由真实数据驱动。

## 决策记录：不引入 Alembic

表结构已稳定、`create_all` 只增不删、四人共享线上库上做迁移操作风险大于收益。
若后续需要破坏性变更（删列/改类型），再引入 Alembic 并以当时库状态为 baseline。

## 验证记录（2026-07-08）

- 后端 54/54；`npm run build` 通过。
- demo 模式 live 验证：快照生成 575 行 → `CAMPUS_DEMO_MODE=1` 起服 →
  游客拉事件 200、admin 登录 + 概览 200。

## 建议的答辩前动作

1. 演示前一天重新跑一次 `make_demo_snapshot.py`（让快照数据最新）。
2. 浏览器过一遍 P1 文档里的 8 步验收清单 + 本页个人事项（新建待办、影响评估）。
3. 把整个项目合并进团队 GitHub（`.env` 已被 .gitignore 排除，合并后用
   `git status` 确认一次）。
