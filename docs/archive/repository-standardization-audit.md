# Campus AI Agent 仓库规范性审查报告

> 审查对象：`D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main`  
> 审查日期：2026-07-18（Asia/Shanghai）  
> 审查维度：代码规范、文件层级规范、文件命名规范、文档规范、仓库卫生与可交付性  
> 审查方式：静态、只读盘点；未运行测试、未启动服务、未改动既有代码和目录  
> 报告性质：整改前审查基线，不代表已经执行下述整改

---

## 1. 执行摘要

项目的业务完成度、测试投入和课程交付材料明显高于普通课程作业，但仓库治理没有同步跟上功能增长速度。当前最突出的问题不是“代码不能运行”，而是：

1. **规范没有工具化**：主仓没有统一的 Python 格式化、Lint、类型检查、前端 ESLint/Prettier、pre-commit 和覆盖率门禁；规范主要存在于文字说明中，无法自动阻止回退。
2. **运行态数据与源代码边界不清**：`data/llm_cache.json`、`data/public_opinion_memory.json` 仍被 Git 跟踪且每次运行都会变化；`data/README.md` 又明确把 `data/` 定义为运行时目录，形成自相矛盾。
3. **模块和目录随功能自然生长**：后端 `services/`、`tests/` 过于扁平，前端多个页面接近或超过 1000 行，根目录有 13 个 `.bat` 入口，数据库变更依赖一组一次性脚本而非正式迁移体系。
4. **文档很多，但缺少生命周期治理**：当前 `docs/` 有 85 个跟踪文件，其中 50 个直接堆在根层；不少 Week2/Week6/Week7、工作包、交接、诊断、提示词和实现计划仍与当前参考文档混放，且存在明显过期路径和实现描述。
5. **交付包风险很高**：Git 已忽略 `.env`、虚拟环境、浏览器登录态等内容，但它们仍物理存在于项目目录中。若直接使用资源管理器压缩整个目录，可能同时提交约 2.4 GB 依赖/浏览器状态以及 `.env`、Cookie 等敏感内容。
6. **第三方代码边界不够清晰**：`MediaCrawler/` 占 282 个跟踪文件，并带有自己的依赖、配置、文档和工具链；主仓另有 `crawler/` 备用实现，但仓库层面没有清晰的第三方来源、版本、定制范围和维护策略说明。

值得肯定的是：

- Python 文件名整体遵循 `snake_case`，Vue 组件整体使用 `PascalCase`，前端工具模块多为 `camelCase`，源码命名基础较好。
- 后端静态识别到 109 个测试文件、约 1180 个 `test_*` 方法，测试数量和覆盖场景非常可观。
- 已存在 GitHub Actions，能执行后端测试、爬虫测试和前端构建。
- `.gitattributes` 已处理跨平台行尾，`.gitignore` 已覆盖常见环境、日志、数据库、上传和浏览器数据。
- 审查期间新增提交 `c9a1b49`，已将 358 个 AI Skill/IDE 状态文件移出版本库，并把相应目录加入忽略规则。这一方向正确，应保留。
- `docs/coursework/` 的编号、范围和交付逻辑相对清晰，是当前文档体系中最规范的一部分。

### 1.1 建议评分（按当前最新工作区状态）

| 评分项 | 建议分 | 评价 |
|---|---:|---|
| 代码是否规范 | 66/100 | 命名和测试基础较好，但缺少自动化规范门禁，存在大文件、配置分散、路径注入和手工迁移问题 |
| 文件层级是否规范 | 58/100 | 核心前后端分区清楚，但根目录、`services/`、`tests/`、`docs/` 和第三方目录边界不足 |
| 文件命名是否规范 | 72/100 | 源码命名总体合格；文档、工作包脚本、历史文件和目录例外没有统一规则 |
| 文档是否规范 | 57/100 | 文档数量丰富，但有效性、归档状态、引用路径和单一事实来源治理不足 |
| **综合建议分** | **63/100** | 功能质量强，工程呈现和仓库治理仍需一次系统整理 |

这不是功能评分，而是严格按“新成员能否快速理解、自动化工具能否守住规范、交付包能否安全复现”的工程规范口径评估。

---

## 2. 审查基线与仓库快照

### 2.1 审查期间的并行变化

审查开始时仓库仍跟踪 `.agents/`、`.claude/`、`.cursor/`、`.gemini/`、`.impeccable/`、`.superpowers/` 中的大量文件。审查过程中，当前分支新增提交：

```text
c9a1b49 chore(cleanup): 移除 358 个 AI 开发工具/IDE 配置文件出版本库（第一批规范化）
```

因此，本报告按**当前最新状态**评价：

- 上述 358 个文件已不再被 Git 跟踪，视为已经解决的版本库问题；
- 对应目录和 358 个物理文件仍存在于工作目录，但已被 `.gitignore` 忽略；
- 它们仍会进入“直接压缩整个文件夹”的交付包，因此物理残留属于打包流程问题，而不是 Git 跟踪问题；
- 当前还暂存了 `docs/README.md`、`docs/archive/README.md`，但索引中声称存在的 `docs/design/`、`docs/experiments/`、`docs/archive/process/`、`docs/archive/crawl/` 尚不存在，属于正在进行中的半完成迁移。

### 2.2 当前 Git 状态

审查时工作区不是干净状态：

```text
分支：feat/chat-latency-and-retrieval
相对远端：ahead 13

M  MediaCrawler/config/base_config.py
M  data/llm_cache.json
M  data/public_opinion_memory.json
A  docs/README.md
A  docs/archive/README.md
```

这意味着后续整改前必须先区分：

- 哪些是用户正在进行的功能修改；
- 哪些是运行时自动写入；
- 哪些是本轮规范化的独立提交。

不应在一次“大清理提交”中混入功能变更、缓存变化和文档迁移。

### 2.3 跟踪文件分布

当前共约 740 个跟踪文件：

| 一级路径 | 跟踪文件数 | 说明 |
|---|---:|---|
| `MediaCrawler/` | 282 | 第三方爬虫及本项目定制 |
| `backend/` | 198 | 后端、Agent 核心、服务和测试 |
| `docs/` | 85 | 当前文档、课程交付、历史记录、计划和实验结果 |
| `frontend/` | 58 | Vue 前端 |
| `scripts/` | 57 | 数据库、同步、评测、维护、实验和历史验收脚本 |
| `data/` | 28 | README、样本、缓存、记忆快照和 fixture |
| 仓库根目录 | 21 | README、配置及 13 个 `.bat` 等 |
| `crawler/` | 7 | 轻量备用爬虫 |
| `deploy/` | 3 | systemd、Nginx、部署脚本 |
| `.github/` | 1 | 单一 CI 工作流 |

### 2.4 本地物理体积

以下内容虽然大多已被 Git 忽略，但实际存在于项目目录：

| 路径 | 文件数 | 体积约 |
|---|---:|---:|
| `.venv/` | 42,066 | 1,183.8 MB |
| `frontend/node_modules/` | 11,912 | 106.3 MB |
| `MediaCrawler/.venv/` | 11,263 | 462.4 MB |
| `MediaCrawler/browser_data/` | 6,229 | 713.6 MB |
| `MediaCrawler/output/` | 63 | 6.7 MB |
| `data/` | 33 | 11.6 MB |

仅上述主要目录合计约 2.48 GB，尚未计入 `.git/` 和其他缓存。项目根目录还存在 5 KB 以上的真实 `.env`。

**结论：禁止直接压缩项目物理目录作为课程提交包。** 应使用 `git archive` 或专门的发布脚本从 Git 跟踪文件生成干净交付物。

---

## 3. 高优先级问题清单

### P0-01：运行时缓存仍被 Git 跟踪

**证据**

- `data/llm_cache.json`：约 813 KB、3887 行，当前为修改状态；
- `data/public_opinion_memory.json`：约 1.98 MB、65505 行，当前为修改状态；
- `backend/services/llm_config.py:72` 将前者作为默认缓存路径；
- `backend/services/public_opinion_adapter.py:56` 将后者作为记忆快照路径；
- `docs/agent-enhancement-progress.md:65` 已明确写出“Git 停止跟踪”是待办；
- `docs/audit-prompt.md:82` 和 `docs/audit-prompt-agent.md:231` 也已经识别该问题；
- `data/README.md:3` 把 `data/` 定义为运行时数据目录。

**影响**

- 每次运行后工作区自动变脏；
- 缓存内容会制造无意义的巨大 diff 和合并冲突；
- 可能提交提示词、模型响应、用户问题或阶段性运行状态；
- 评委会直观看到仓库卫生不合格。

**整改建议**

1. 在 `.gitignore` 增加：

   ```gitignore
   data/llm_cache.json
   data/public_opinion_memory.json
   ```

2. 使用 `git rm --cached` 停止跟踪，但保留本地文件；
3. 如果测试需要固定数据，提炼为最小化、脱敏、不可变的 `data/fixtures/` 文件；
4. 长期建议把运行时内容移到统一的 `var/`：

   ```text
   var/cache/llm.json
   var/state/public-opinion-memory.json
   var/db/chat-memory.sqlite3
   var/log/
   var/uploads/
   ```

### P0-02：交付包可能包含密钥、Cookie 和 2.4 GB 本地环境

**证据**

- 项目根目录存在真实 `.env`；
- `MediaCrawler/browser_data/` 约 713.6 MB，通常含浏览器配置和登录态；
- 两套虚拟环境合计约 1.65 GB；
- Git 忽略只能防止提交，不能防止资源管理器压缩。

**影响**

- 课程提交超大、打开慢、极不专业；
- 可能泄露数据库、LLM、Cookie 或 JWT 配置；
- 在其他机器上仍无法直接复用这些环境，体积没有交付价值。

**整改建议**

- 新增 `scripts/release/package_source.ps1`；
- 打包前要求 `git status --porcelain` 符合预期；
- 使用以下原则生成压缩包：只从 Git 跟踪内容导出，不从工作目录复制；
- 发布脚本输出文件清单、大小、Git commit 和 SHA-256；
- 交付前扫描压缩包中是否出现 `.env`、`browser_data`、`.venv`、`node_modules`、`*.db`、Cookie 文件。

推荐底层命令：

```powershell
git archive --format=zip --output campus-ai-agent-source.zip HEAD
```

### P0-03：暂存的文档索引先于真实目录结构

**证据**

当前暂存的 `docs/README.md` 声明：

- `docs/design/` 存放功能设计；
- `docs/experiments/` 存放消融实验；
- `docs/archive/` 已按历史记录分层。

当前暂存的 `docs/archive/README.md` 又声明：

- `archive/process/` 存在；
- `archive/crawl/` 存在。

但审查时上述 `design/`、`experiments/`、`archive/process/`、`archive/crawl/` 均不存在，绝大多数文档仍在 `docs/` 根层。

**影响**

- 文档索引与真实文件树不一致；
- 新成员按索引寻找文档会立即失败；
- 如果直接提交，等于新增一份错误的“单一事实来源”。

**整改建议**

- 要么先完成目录迁移再提交索引；
- 要么把索引标注为“目标结构/迁移中”，暂不声称目录已经存在；
- 文档移动和索引更新应在同一原子提交中完成；
- 移动后运行路径引用检查，并人工核对使用反引号书写的路径引用。

### P0-04：开发与部署文档公开使用可预测演示凭据

**证据**

- `.env.example` 预填了固定管理员/演示用户口令；
- `README.md:39` 直接公开演示账号；
- `docs/deploy-runbook.md:148-149` 在公网部署手册中继续使用同一组固定凭据；
- 多份当前和历史文档重复该凭据。

代码本身已经改进：`backend/services/auth_service.py:188-202` 在环境变量缺失时会生成随机初始密码，而不是退回固定密码。这与文档和 `.env.example` 的固定值形成新的不一致。

**影响**

- 如果公网环境照抄 `.env.example`，管理员账号可被直接猜中；
- 安全整改代码的效果被部署文档抵消；
- 文档规范和安全规范同时失分。

**整改建议**

- `.env.example` 中密码字段应为空或写成明显占位符；
- 本地演示凭据放入 `demo.bat` 的明确“仅本地演示模式”，不要作为公网部署默认值；
- 生产环境启动时若检测到弱口令或占位符，应直接失败；
- README 只说明“演示模式会创建本地账号”，不要把公网可用凭据写成永久事实。

### P0-05：主仓依赖不可复现，Python 版本口径冲突

**证据**

- 根 `requirements.txt` 中绝大多数依赖没有固定版本；
- 只有 `python-multipart>=0.0.9` 给出下界，没有锁文件；
- `README.md:96` 声称 Python 3.12；
- `.github/workflows/ci.yml` 使用 Python 3.11；
- 主仓不存在 `pyproject.toml`、`uv.lock`、`requirements.lock` 或 pip-tools 输出；
- `MediaCrawler/` 反而有自己的 `pyproject.toml` 和 `uv.lock`，主仓与子目录工具链不一致。

**影响**

- 今天可安装的依赖组合，未来可能不可安装或行为改变；
- 本地、CI、服务器三个环境可能运行不同版本；
- 评委无法确认“按 README 能否复现”。

**整改建议**

1. 明确唯一 Python 版本，建议与 CI 统一为 3.11，或把 CI/部署全部升级为 3.12；
2. 在根目录建立 `pyproject.toml`，统一项目元数据、工具配置和依赖；
3. 使用 `uv.lock` 或 pip-tools 生成锁定依赖；
4. CI 必须从锁文件安装；
5. `README`、CI、部署文档、`.python-version` 使用同一版本。

### P0-06：绝对本机路径破坏可移植性

**证据**

- `check.ps1:24` 硬编码 `D:\桌面文件\软件工程大作业\campus-opinion-agent\backend`；
- `scripts/sync_opinion_core.py:41` 硬编码同一台机器上的子项目路径；
- 多个脚本通过 `sys.path.insert(...)` 绕过正式包安装。

**影响**

- 换电脑、换盘符、换目录后脚本立即失效；
- CI 无法执行本地同口径检查；
- 规范评分中属于非常直观的扣分项。

**整改建议**

- 子仓路径改为命令行参数或环境变量，并允许缺省跳过；
- `check.ps1` 不应依赖仓库外的固定目录；
- 主项目安装为可导入包，脚本通过模块入口运行，逐步移除 `sys.path.insert` 和 `# noqa: E402`；
- 与独立子仓的同步改成明确的导入/导出工具，不让主仓回归依赖开发者私人目录。

---

## 4. 代码规范审查

### 4.1 做得好的部分

- Python 文件、函数和变量整体使用 `snake_case`；
- Vue 组件文件使用 `PascalCase.vue`；
- 前端 API、工具和常量模块基本遵循 `camelCase.js`；
- 后端已经形成 `routers/`、`services/`、`agent/`、`tests/` 基本分层；
- 复杂 Agent、证据采集、安全、并发、回退和引用校验都有较多测试；
- 统一日志、错误响应、JWT、防提示注入、SSRF 等工程意识较强；
- `.gitattributes` 对 shell、systemd、Nginx、Windows 脚本行尾做了明确约束。

### 4.2 缺少可执行的代码规范

主仓目前不存在：

```text
pyproject.toml
ruff.toml
.pre-commit-config.yaml
.editorconfig
pytest.ini
mypy.ini
frontend/eslint.config.js
frontend/.prettierrc
frontend/vitest.config.js
frontend/tsconfig.json
```

CI 只执行后端测试、爬虫测试和前端构建。`vite build` 不能替代 ESLint，也不会检查大部分代码风格、未使用变量、危险模式或格式一致性。

**建议的最低门禁**

```text
Python：ruff check + ruff format --check + unittest/pytest
Frontend：eslint + prettier --check + vite build
Docs：Markdown lint + 本地链接检查
Security：依赖审计 + secrets scan
Repository：禁止跟踪运行时文件、超大文件和本地绝对路径
```

### 4.3 大文件和职责过载

主项目代码（不含 `MediaCrawler` 第三方主体）约 312 个源码/脚本文件、69,000 行。以下生产文件过大：

| 文件 | 约行数 | 主要问题 |
|---|---:|---|
| `frontend/src/views/AdminEventsView.vue` | 1207 | 模板、业务状态、批量操作、表格和样式全部集中 |
| `frontend/src/views/AgentChatView.vue` | 1105 | 对话状态、流式响应、引用展示、进度和样式集中 |
| `frontend/src/views/HomeView.vue` | 1047 | 首页数据、图表、卡片和视觉逻辑集中 |
| `frontend/src/views/LoginView.vue` | 998 | 登录业务与大量视觉/动效实现耦合 |
| `frontend/src/views/AdminEvidenceView.vue` | 991 | 审核工作流、表格、请求与展示集中 |
| `backend/services/opinion_chat_service.py` | 948 | 记忆、检索、路由、流式回答、报告、ReAct 和响应组装集中 |
| `backend/services/llm_client.py` | 782 | 端点、缓存、用量、HTTP、重试、流式和报告生成集中 |
| `backend/services/public_opinion_adapter.py` | 721 | 适配、写回、记忆和流水线职责偏多 |
| `backend/services/evidence/providers.py` | 687 | 多供应商实现集中在单文件 |
| `backend/routers/api.py` | 639 | 路由层承担大量序列化、查询和领域逻辑 |
| `backend/routers/admin_events.py` | 605 | 管理接口控制器过重 |
| `scripts/sync_media_to_raw_posts.py` | 835 | 同步、映射、日志、事务和 CLI 集中 |

建议目标：

- 普通生产模块尽量控制在 300～500 行；
- Vue 页面只负责页面编排，复杂区块拆成组件，状态与请求拆为 composable；
- 路由层只做参数校验、鉴权、调用用例和响应转换；
- LLM 端点、缓存、HTTP transport、流式协议、用量统计分文件；
- 多供应商实现使用 `providers/` 子包；
- 不追求机械按行数拆分，而是按可独立测试的职责拆分。

### 4.4 后端层级过于扁平

当前：

- `backend/services/` 根层约 35 个模块；
- `backend/tests/` 根层有 109 个 `test_*.py`；
- `backend/routers/` 有 10 个模块；
- 模型分散为 `models.py`、`admin_models.py`、`models_evidence.py`；
- Schema 同时存在于 `backend/schemas.py`、Agent 核心和 evidence 子包。

这在项目早期可接受，但当前规模已经形成“目录是分类，文件名承担全部导航”的状态。

建议采用按领域聚合的混合结构：

```text
backend/
├── app/
│   ├── core/                 # settings、database、logging、errors
│   ├── auth/
│   │   ├── router.py
│   │   ├── service.py
│   │   ├── schemas.py
│   │   └── models.py
│   ├── events/
│   ├── chat/
│   ├── evidence/
│   ├── submissions/
│   └── admin/
└── tests/
    ├── unit/
    ├── integration/
    ├── contract/
    ├── security/
    └── e2e/
```

若不希望大改导入路径，可先只把 `services/` 和 `tests/` 按领域建立子目录，不必立即改成 `backend/app/`。

### 4.5 配置读取分散

审查发现大量 `os.getenv`/`os.environ` 访问分散在后端、爬虫、脚本和测试中。实际 `.env` 有 35 个键，`.env.example` 有 59 个键，但实际环境中的以下 5 个键没有进入示例：

```text
EMBEDDING_ALIGN_THRESHOLD
EMBEDDING_CLUSTER_THRESHOLD
EMBEDDING_MERGE_THRESHOLD
EVIDENCE_GLM_MODEL
HEAT_PLATFORM_WEIGHTS
```

同时，`backend/database.py:13` 使用 `load_dotenv(..., override=True)`，意味着 `.env` 可能覆盖操作系统/容器注入的环境变量；这通常不符合生产环境配置优先级。

建议：

- 建立单一 `Settings` 对象，集中类型、默认值、必填校验和脱敏展示；
- 优先级使用“显式进程环境 > `.env` > 默认值”；
- 生产环境禁用自动加载本地 `.env` 或至少禁止 `override=True`；
- `.env.example` 由 Settings 字段自动核对；
- 配置分组：application、database、auth、LLM、evidence、crawler、feature flags；
- 启动时只打印非敏感配置摘要。

### 4.6 导入时副作用

示例：

- `backend/database.py:10` 导入时创建数据目录；
- `backend/database.py:13` 导入时加载并覆盖环境变量；
- `backend/main.py:14-17` 导入时加载环境并修改 `sys.path`；
- `backend/main.py:119` 导入时创建 uploads 目录。

这会让测试隔离、命令行工具、静态检查和应用工厂模式变得困难。建议把目录创建、配置加载和资源初始化放入明确的应用启动阶段。

### 4.7 异常处理和调试输出

静态扫描在主项目源码/脚本中发现约 72 个 `except Exception` 和约 387 个 `print(...)`。其中大量位于 CLI、迁移和实验脚本，并不等于都是缺陷，但当前没有 Lint 规则和例外规范，因此无法区分合理兜底与吞错。

建议：

- 业务代码优先捕获具体异常；
- 广义捕获必须记录上下文，并在边界层使用；
- 禁止空 `except` 或静默返回默认值；
- 生产代码用结构化日志，CLI 脚本可保留 `print`；
- Ruff 启用 BLE、B、SIM、UP、I 等规则，并对必要例外做最小化 `noqa`。

### 4.8 类型标注不完整

生产 Python 静态扫描约 959 个函数定义，其中约 685 个单行定义可识别到返回类型，约 274 个没有返回标注。项目已经广泛使用现代类型语法，说明具备统一类型治理的基础。

建议先对以下边界强制类型：

- 对外服务接口；
- Router 输入输出；
- 配置对象；
- 数据转换和 provider 接口；
- Agent 工具定义。

不必一次性对所有内部函数开启最严格模式，可按领域逐步提高。

### 4.9 前端直接依赖声明缺失

源码至少 10 处直接导入 `@element-plus/icons-vue`，`vite.config.js` 也把它放入独立 chunk，但 `frontend/package.json` 没有直接声明该依赖。它目前可能通过 `element-plus` 的依赖树被提升到顶层，因此“碰巧可用”。

建议把所有源码直接 import 的包写入直接 dependencies，避免上游依赖树变化后构建失败。

### 4.10 数据库迁移不规范

主仓没有 Alembic 或等价迁移框架，数据库演进主要依赖：

```text
scripts/add_*.py
scripts/create_*.py
scripts/ensure_wp4_schema.py
scripts/sql/wp1_*.sql
```

问题包括：

- 执行顺序不直观；
- 缺少统一版本号和升级/回滚链；
- `wp1`、`wp4` 是开发阶段术语，不是稳定领域命名；
- 很难确认新环境从零初始化和旧环境增量升级是否等价。

建议引入 Alembic，并把历史脚本归档为迁移来源；每个迁移使用时间/序号和语义名，例如：

```text
20260718_001_create_crawl_task_queue.py
20260718_002_add_processed_post_heat_rank.py
```

---

## 5. 文件层级审查

### 5.1 根目录过载

根目录现有 13 个 `.bat`：

```text
crawl.bat
demo.bat
dev.bat
import_latest.bat
init_db.bat
run.bat
save_tieba_login.bat
save_weibo_login.bat
seed_demo.bat
setup.bat
stop.bat
verify_db.bat
view_db.bat
```

这些脚本大多只有 5～48 行，属于不同领域和不同频率的入口，却全部展示在仓库首屏。

建议根目录只保留高频用户入口：

```text
setup.bat
run.bat
check.ps1
```

其他入口移入：

```text
scripts/windows/dev.bat
scripts/windows/demo.bat
scripts/crawler/crawl.bat
scripts/crawler/save_tieba_login.bat
scripts/crawler/save_weibo_login.bat
scripts/database/init_db.bat
scripts/database/verify_db.bat
scripts/database/view_db.bat
scripts/data/import_latest.bat
scripts/data/seed_demo.bat
```

README 提供统一命令索引即可。也可使用 `Taskfile.yml`、`justfile` 或一个参数化 PowerShell 入口替代多份薄包装脚本。

### 5.2 `MediaCrawler/` 第三方边界

正向点：该目录保留了 LICENSE、README、自己的 `pyproject.toml`、`uv.lock` 和测试。

不足：

- 位于仓库一级，视觉上与自研 `backend/`、`frontend/` 同权；
- 同时存在自研备用 `crawler/`，新成员不易判断主次；
- 没有根级 `THIRD_PARTY_NOTICES.md`；
- 没有明确记录上游仓库、基准版本、fork commit、本项目修改列表和更新流程；
- 目录内还有自己的 `.github/`、多语言 README、工具和历史内容，扩大主仓噪声。

推荐两种方案二选一：

1. **保守方案**：继续 vendoring，但移动到 `third_party/MediaCrawler/`，新增 `PATCHES.md` 和第三方声明；
2. **长期方案**：维护独立 fork，通过 Git submodule/subtree 固定版本，主仓只保留适配层。

课程项目更适合保守方案，风险较低，也更容易离线提交。

### 5.3 `crawler/` 与 `MediaCrawler/` 双实现

README 将 `MediaCrawler` 视为主链路，将 `crawler/` 视为微博/贴吧备用链路，这个解释是合理的，但目录名没有表达“主/备/legacy”。

建议：

- 将 `crawler/` 改为 `fallback_crawler/` 或 `integrations/legacy_crawler/`；
- 在目录 README 第一屏写清适用范围、支持平台、是否继续维护；
- 共享数据模型和配置，避免两套实现继续漂移。

### 5.4 `data/` 混合了四类内容

当前同时包含：

- 文档：`README.md`、`campus_db_preview.md`；
- 固定测试数据：`fixtures/`；
- 历史采集样本：`samples/`；
- 运行缓存/状态：`llm_cache.json`、`public_opinion_memory.json`。

建议拆分：

```text
data/
├── fixtures/            # 可跟踪、最小、脱敏、稳定
└── samples/             # 仅保留少量有说明的代表样本

var/                     # 整体忽略
├── cache/
├── db/
├── logs/
├── state/
└── uploads/
```

`campus_db_preview.md` 属于生成物，应由脚本生成到 `var/reports/` 或 CI artifact，不应长期手工维护。

### 5.5 `scripts/` 混合多种生命周期

当前 57 个文件混合了：

- 正式运维；
- 数据库建表/补字段；
- 数据同步；
- 登录态保存；
- 评测与消融实验；
- 调试；
- 历史工作包验收；
- SQL。

建议结构：

```text
scripts/
├── dev/
├── database/
│   ├── migrations/
│   └── maintenance/
├── ingestion/
├── evaluation/
├── release/
├── smoke/
├── windows/
└── archive/
```

每个脚本应有：用途、是否读写数据库、是否联网、参数、幂等性、示例、退出码说明。

---

## 6. 文件命名审查

### 6.1 建议正式写入仓库的命名规则

| 类型 | 规则 | 示例 |
|---|---|---|
| Python 模块/包 | `snake_case` | `event_read_model.py` |
| Python 类 | `PascalCase` | `OpinionChatService` |
| Python 函数/变量 | `snake_case` | `query_published_events` |
| Vue 组件/页面 | `PascalCase.vue` | `EventDetailView.vue` |
| JS 工具/API 模块 | 统一选择 `camelCase.js` 或 `kebab-case.js`，当前建议沿用 camelCase | `agentChat.js` |
| CSS | `kebab-case.css` 或语义单词 | `admin.css` |
| 普通文档 | 小写 `kebab-case.md` | `deployment-runbook.md` |
| ADR | `NNNN-kebab-case.md` | `0003-runtime-data-boundary.md` |
| 数据库迁移 | 时间/序号 + 语义名 | `20260718_002_add_heat_rank.py` |
| 脚本 | 动词开头 `verb_object.py` | `sync_media_posts.py` |
| 测试 | `test_<domain>_<behavior>.py` | `test_auth_password_bootstrap.py` |

### 6.2 当前命名问题

1. 活跃文档含 `week2`、`week6`、`week7`、`work-package-*`，阶段信息替代了稳定主题；
2. 同类文档混用 `week2`、`Week 7`、中文名、英文名；
3. `admin_models.py`、`models.py`、`models_evidence.py` 命名方式不对称；
4. `check_wp1.py` 等名称离开当时工作包语境后无法表达实际检查内容；
5. 根级 `DESIGN.md`、`PRODUCT.md` 与其他小写文档规则不一致；
6. `MediaCrawler` 是上游项目名，可作为第三方例外，但需在命名规范中声明；
7. `docs/coursework/01-需求分析报告.md` 等中文编号文件具有课程交付价值，可作为明确例外保留，不必为追求全英文而改名。

### 6.3 不建议做的事情

- 不要一次性把所有中文文档改成英文；
- 不要机械把 Vue 组件改成小写；
- 不要为了统一而修改第三方项目内部所有命名；
- 不要在同一提交中同时改文件名和大段业务逻辑；
- 不要仅改名而不修复 README、脚本、CI 和文档引用。

---

## 7. 文档规范审查

### 7.1 当前文档规模

当前 `docs/` 约 85 个跟踪文件：

| 位置 | 数量 | 判断 |
|---|---:|---|
| `docs/` 根层 | 50 | 严重过多，当前参考与历史过程混放 |
| `docs/superpowers/` | 16 | AI 工具生成/辅助的计划和规格，生命周期不清 |
| `docs/coursework/` | 9 | 结构最好，建议保留 |
| `docs/archive/` | 8 | 已有归档基础，但覆盖范围不足 |
| `docs/data/` | 2 | 评测 JSON，不属于普通文档 |

文档中约 28 份出现 `---`，但没有形成统一 front matter；未发现统一的 `status`、`owner`、`last_updated` 元数据。

### 7.2 明显过期或矛盾证据

1. `README.md:132` 仍写“会话记忆存于进程内存”，但当前已有 `backend/services/chat_memory_store.py` 和 `data/chat_memory.sqlite3` 持久化实现；
2. `README.md:96` 写 Python 3.12，CI 用 Python 3.11；
3. `docs/api.md` 标题仍是“Week2 后端接口”；代码中约有 59 个路由装饰器，而文档静态识别到约 19 个 `/api/` 方法条目；
4. 多份文档仍要求执行 `scripts/check_wp*.py`，这些脚本已经移动到 `scripts/archive/`；
5. 多份文档仍引用已删除的 `check_wp*.bat`；
6. `docs/前端后端依赖事项.md` 声称存在 `DataSourceBadge.vue`，实际文件不存在；
7. `data/README.md` 把 `data/` 说成运行时目录，却没有列出当前最大的两个缓存/状态文件；
8. `backend/README.md` 是零字节文件；
9. `docs/architecture.md` 只有约 52 行，而 `docs/coursework/03-架构设计文档.md` 有约 276 行，二者谁是当前事实来源没有明确关系；
10. `docs/superpowers/plans/` 中多份实现计划超过 1000 行，属于开发过程记录，不宜与最终参考文档同级。

### 7.3 Markdown 链接检查的局限

静态检查了 24 个标准 Markdown 本地链接，未发现断链；但这不能证明引用正确，因为项目大量使用反引号写路径，例如：

```markdown
`scripts/check_wp4.py`
```

这种写法不会被链接检查器识别，实际已经存在大量路径过期。

建议：

- 可跳转的文档引用统一使用 Markdown 链接；
- 命令中的路径仍可使用代码格式，但 CI 另做路径存在性检查；
- 引入 `markdownlint` 和 `lychee`/`markdown-link-check`；
- 对反引号路径做自定义检查，至少覆盖 `docs/` 中的仓库相对路径。

### 7.4 文档生命周期模型

建议每份非归档文档包含：

```yaml
---
title: API Reference
status: active          # draft | active | deprecated | archived
owner: backend
last_updated: 2026-07-18
source_of_truth: code   # code | document | generated
review_cycle: release
---
```

规则：

- `active`：代表当前实现，必须随代码更新；
- `draft`：尚未完成，不得从主 README 当成正式依据；
- `deprecated`：仍可见，但必须指向替代文档；
- `archived`：历史快照，不再持续修正；
- 归档文档一旦归档，原则上只修断链和敏感信息，不重写历史结论；
- API 参考优先从 OpenAPI 生成，手写文档只解释约定、鉴权、错误码和示例。

### 7.5 文档去留矩阵

#### A. 保留在当前参考层，但必须更新

```text
docs/README.md
docs/architecture.md
docs/api.md
docs/database.md
docs/data-sources.md
docs/field-spec.md
docs/page-responsibilities.md
docs/dev-guide.md
docs/deploy-runbook.md
docs/crawl-runbook.md
docs/demo-guide.md
```

处理要求：

- 修复当前实现矛盾；
- 标注 owner/status/last_updated；
- `api.md` 改为 API 使用指南并链接自动生成 OpenAPI；
- `architecture.md` 做短版总览，链接课程版详细架构；
- `dev-guide.md` 从“第一周任务文档”升级为长期团队规范。

#### B. 移入 `docs/design/`

```text
docs/event-clustering-llm-refine.md
docs/event-lifecycle.md
docs/event-recency.md
docs/event-risk-llm.md
docs/keyword-event-design.md
docs/evidence-collector.md
```

处理要求：去除实现进度口吻，保留问题、约束、方案、接口、权衡和验证。

#### C. 移入 `docs/experiments/`

```text
docs/event-clustering-llm-refine-ablation.md
docs/event-lifecycle-ablation.md
docs/event-recency-ablation.md
docs/event-risk-llm-ablation.md
docs/keyword-event-ablation.md
docs/data/*.json
```

处理要求：每个实验记录数据集版本、commit、参数、指标、结论和复现命令。

#### D. 移入 `docs/archive/process/`

```text
docs/agent-enhancement-progress.md
docs/agent-subproject-to-main-integration-guide.md
docs/audit-prompt.md
docs/audit-prompt-agent.md
docs/backend-smoke-test.md
docs/week2-backend-to-frontend-handoff-guide.md
docs/week2-backend-wp5-agent-status-guide.md
docs/week2-frontend-progress-audit.md
docs/week6-public-opinion-agent-chat.md
docs/week6-public-opinion-agent-integration.md
docs/week7-p0-auth-hardening.md
docs/week7-p1-admin-pages-and-user-loop.md
docs/week7-p2-engineering-quality.md
docs/前端后端依赖事项.md
docs/组员冒烟部署指南.md
```

其中 `audit-prompt*.md` 更像 AI 会话输入，可考虑删除；若要保留，只应作为开发历史，不应出现在当前文档导航。

#### E. 移入 `docs/archive/crawl/`

```text
docs/crawl-handoff.md
docs/crawl-issues.md
docs/keyword-seeding-plan.md
docs/ks-empty-page-diagnostic-guide.md
docs/machine-c-crawl-guide.md
docs/xhs-parallel-crawl-guide.md
docs/xhs-parallel-crawl-expansion-guide.md
```

`docs/crawl-real-data.md` 如果仍有效，可合并进当前 `crawl-runbook.md`；合并后归档原文。

#### F. 移入 `docs/archive/setup-and-collaboration/`

```text
docs/how-to-get-shared-mysql.md
docs/open-campus-db.md
docs/merge-with-team-github.md
docs/work-package-0-shared-mysql.md
docs/work-package-1-shared-mysql.md
```

当前仍需要的数据库接入步骤应提炼到 `docs/guides/local-development.md`，不要继续维护多份工作包文档。

#### G. 处理 `docs/superpowers/`

- `plans/`：整体移入 `docs/archive/implementation-plans/`；
- `specs/`：逐份判断；仍代表当前设计的内容提炼进 `docs/design/`，其余归档；
- 不建议继续使用工具名 `superpowers` 作为正式文档信息架构的一部分；
- 超过 1000 行的逐步实现计划不应被评委误认为当前操作手册。

#### H. 根级文档

- `PRODUCT.md` → `docs/product/product-overview.md`；
- `DESIGN.md` → `docs/design/design-system.md`；
- `backend/README.md`：要么补成后端开发入口，要么删除空文件；
- `frontend/README.md`、`crawler/README.md`：保留为各子系统入口，但与根 README 避免重复；
- `data/README.md`：改成“测试数据与本地运行数据边界”说明。

### 7.6 `docs/coursework/` 的处理原则

该目录是正式课程交付物，应保持编号和中文命名：

```text
01-需求分析报告.md
02-系统建模报告.md
03-架构设计文档.md
04-软件工程化说明文档.md
05-软件测试与质量保证报告.md
05a-缺陷跟踪台账.md
06-软件配置与运维文档.md
07-团队报告.md
08-演示视频脚本与拍摄清单.md
```

建议新增 `docs/coursework/README.md`，说明：

- 交付物版本和冻结日期；
- 与当前代码 commit 的对应关系；
- 哪些数字由脚本生成；
- 正式评审阅读顺序；
- 课程文档与日常技术文档的关系。

---

## 8. 推荐目标目录结构

以下结构以“降低迁移风险”为前提，不强制一次性改成大型 monorepo：

```text
campus-ai-agent-main/
├── README.md
├── LICENSE
├── CONTRIBUTING.md
├── CHANGELOG.md
├── .editorconfig
├── .gitattributes
├── .gitignore
├── .env.example
├── pyproject.toml
├── uv.lock
├── check.ps1
├── setup.bat
├── run.bat
│
├── backend/
│   ├── README.md
│   ├── app/                         # 可分阶段迁移，不要求首批完成
│   │   ├── core/
│   │   ├── auth/
│   │   ├── events/
│   │   ├── chat/
│   │   ├── evidence/
│   │   ├── ingestion/
│   │   └── admin/
│   └── tests/
│       ├── unit/
│       ├── integration/
│       ├── contract/
│       ├── security/
│       └── e2e/
│
├── frontend/
│   ├── README.md
│   ├── package.json
│   ├── package-lock.json
│   ├── eslint.config.js
│   ├── .prettierrc
│   └── src/
│       ├── api/
│       ├── components/
│       ├── composables/
│       ├── layouts/
│       ├── router/
│       ├── stores/
│       ├── utils/
│       └── views/
│
├── integrations/
│   └── fallback_crawler/            # 当前 crawler/
│
├── third_party/
│   └── MediaCrawler/
│       ├── UPSTREAM.md
│       ├── PATCHES.md
│       └── LICENSE
│
├── scripts/
│   ├── database/
│   ├── ingestion/
│   ├── evaluation/
│   ├── smoke/
│   ├── release/
│   ├── windows/
│   └── archive/
│
├── deploy/
│   ├── README.md
│   ├── systemd/
│   └── nginx/
│
├── data/
│   ├── README.md
│   ├── fixtures/
│   └── samples/
│
├── var/                              # 整体 Git ignore
│   ├── cache/
│   ├── db/
│   ├── logs/
│   ├── state/
│   └── uploads/
│
└── docs/
    ├── README.md
    ├── product/
    ├── architecture/
    ├── reference/
    ├── guides/
    ├── design/
    ├── decisions/
    ├── experiments/
    ├── coursework/
    └── archive/
```

### 8.1 根目录允许清单

建议将根目录治理成“允许清单”，而不是发现一个文件再决定放哪里：

```text
README.md
LICENSE
CONTRIBUTING.md
CHANGELOG.md
.editorconfig
.gitattributes
.gitignore
.env.example
pyproject.toml
uv.lock
check.ps1
setup.bat
run.bat
核心一级目录
```

其他文件默认进入对应子目录。

---

## 9. 工具链与 CI 目标

### 9.1 Python

建议在根 `pyproject.toml` 统一：

- 项目 Python 版本；
- Ruff lint/format；
- import 排序；
- 测试配置；
- 覆盖率配置；
- 可选 mypy/pyright；
- 主项目依赖和开发依赖。

推荐门禁：

```powershell
ruff format --check backend crawler scripts
ruff check backend crawler scripts
python -m unittest discover -s backend/tests -t . -q
```

### 9.2 Frontend

`package.json` 至少增加：

```json
{
  "scripts": {
    "lint": "eslint .",
    "format:check": "prettier --check .",
    "test": "vitest run",
    "build": "vite build"
  }
}
```

并直接声明 `@element-plus/icons-vue`。

### 9.3 文档

建议增加：

```text
markdownlint
lychee 或 markdown-link-check
自定义仓库路径存在性检查
文档 front matter 检查
```

### 9.4 CI 工作流

建议拆为以下 jobs：

```text
repository-hygiene
python-lint
python-tests
frontend-lint
frontend-tests
frontend-build
docs-check
dependency-audit
```

并补充：

- `permissions: contents: read`；
- job timeout；
- concurrency cancel；
- Python/Node 缓存；
- 锁文件安装；
- 测试报告和覆盖率 artifact；
- 禁止提交 `.env`、运行态数据和超限文件。

---

## 10. 分阶段整改方案

### 阶段 0：冻结基线与保护现有改动

目标：避免规范化误伤正在开发的功能。

1. 记录当前 commit、分支和 Git 状态；
2. 将 `c9a1b49` 的 AI 工具清理视为独立已完成提交；
3. 确认 `MediaCrawler/config/base_config.py` 的修改归属；
4. 不把两个运行态 JSON 的变化并入功能提交；
5. 暂存的文档索引与实际移动一起完成，不单独提交错误索引。

### 阶段 1：仓库卫生与交付安全

这是收益最高、功能风险最低的一批：

1. 停止跟踪两个运行态 JSON；
2. 完善 `.gitignore`；
3. 修正 `.env.example`，去除可直接使用的弱口令/真实风格连接串；
4. 新增干净打包脚本；
5. 新增根 LICENSE、CONTRIBUTING、第三方声明；
6. 补齐或删除空 `backend/README.md`；
7. 校验 Git 工作区在正常运行后不会自动变脏。

### 阶段 2：文档信息架构

1. 先创建真实目录；
2. 按本报告“文档去留矩阵”移动；
3. 更新 `docs/README.md` 和 `docs/archive/README.md`；
4. 修复所有过期 `check_wp*`、`DataSourceBadge`、Python 版本和会话记忆描述；
5. 当前文档添加 metadata；
6. 历史文档统一标记 archived；
7. 将 `superpowers/plans` 移出当前参考层；
8. 运行 Markdown 和路径检查。

### 阶段 3：规范工具化

1. 统一 Python 版本；
2. 引入根 `pyproject.toml` 和锁文件；
3. 引入 Ruff；
4. 前端引入 ESLint、Prettier、Vitest；
5. 引入 `.editorconfig` 和 pre-commit；
6. CI 增加 lint、docs、security、repository hygiene；
7. 先按现状格式建立基线，再小批量修复，不要一次产生不可审查的全仓 diff。

### 阶段 4：目录与代码拆分

1. 拆 `opinion_chat_service.py`、`llm_client.py`、`providers.py`；
2. 拆 5 个接近/超过 1000 行的 Vue 页面；
3. Router 下沉业务逻辑到用例/服务；
4. `services/`、`tests/` 按领域分组；
5. 配置统一到 Settings；
6. 引入数据库迁移框架；
7. 移除绝对路径、`sys.path.insert` 和不必要的 `E402`；
8. 每次结构调整必须先有回归测试保护。

### 阶段 5：第三方与发布治理

1. 确认 `MediaCrawler` 上游版本和本地 patch；
2. 移入 `third_party/` 或固定 fork/subtree；
3. 明确 `crawler/` 的备用/legacy 身份；
4. 生成 release manifest；
5. 在干净临时目录验证“从零安装、构建、测试、运行、打包”。

---

## 11. 建议的提交拆分

不要做一个“规范化全部”的巨型提交。建议：

```text
chore(repo): stop tracking runtime cache and state files
docs(repo): establish documentation index and lifecycle metadata
docs(archive): move historical week and work-package records
docs(reference): refresh API architecture and runtime-state descriptions
build(python): add pyproject ruff and dependency lock
build(frontend): add eslint prettier vitest and direct icon dependency
ci: enforce lint tests docs and repository hygiene
refactor(config): centralize application settings
refactor(chat): split chat orchestration memory retrieval and rendering
refactor(frontend): extract large view components and composables
build(db): introduce versioned database migrations
chore(vendor): document MediaCrawler upstream and local patches
chore(release): add clean source packaging workflow
```

每个提交都应可独立解释、可回滚、可通过测试。

---

## 12. 验收标准

### 12.1 代码规范

- [ ] Python 格式化、Lint 在本地和 CI 一致；
- [ ] 前端 ESLint、Prettier、测试和 build 全绿；
- [ ] 依赖从锁文件安装；
- [ ] README、CI、部署 Python 版本一致；
- [ ] 不再依赖本机绝对路径；
- [ ] 核心模块职责清晰，大文件有拆分计划或合理说明；
- [ ] 配置集中、有类型、有启动校验；
- [ ] 数据库变更有版本化迁移。

### 12.2 文件层级

- [ ] 根目录只保留允许清单文件；
- [ ] 运行态数据统一进入忽略目录；
- [ ] `scripts/` 按用途和生命周期分组；
- [ ] `tests/` 按测试层级/领域分组；
- [ ] 第三方代码有清晰边界和来源说明；
- [ ] 主爬虫与备用爬虫关系一眼可见；
- [ ] 文档索引描述与真实目录完全一致。

### 12.3 文件命名

- [ ] Python/Vue/JS/文档/迁移分别有书面命名规则；
- [ ] 当前文档不再使用 Week/工作包作为主要命名；
- [ ] 历史阶段名只出现在 archive；
- [ ] 脚本名称表达动作和对象；
- [ ] 中文课程交付文件作为明确例外；
- [ ] 重命名后所有引用通过自动检查。

### 12.4 文档规范

- [ ] `docs/README.md` 是可靠导航；
- [ ] 当前文档有 status、owner、last_updated；
- [ ] 历史文档均在 archive 并有醒目标记；
- [ ] API 文档与 OpenAPI/代码一致；
- [ ] README 不再包含过期会话记忆和版本描述；
- [ ] 不再引用缺失的 `check_wp*`、`DataSourceBadge` 等路径；
- [ ] 标准 Markdown 链接无断链；
- [ ] 课程交付物固定到明确 commit。

### 12.5 仓库与交付

- [ ] 正常运行一次后 `git status` 不因缓存自动变脏；
- [ ] 提交包不含 `.env`、Cookie、数据库、虚拟环境、node_modules、browser_data；
- [ ] 源码压缩包大小合理；
- [ ] 干净机器可按 README 从零安装；
- [ ] `check.ps1` 不依赖开发者私人目录；
- [ ] CI 与本地一键检查口径一致。

---

## 13. 最终结论

该项目不是“缺少工程化”，而是**工程化成果散落、没有被仓库治理体系收束**。测试、CI、安全修复、部署、设计规范、课程交付物都已经存在；真正拉低“规范性”观感的是：

- 运行态内容仍进入版本控制；
- 文档没有清晰的当前/历史边界；
- 规范没有通过工具强制执行；
- 根目录和大目录缺少允许清单与职责上限；
- 第三方、备用实现、实验脚本和正式产品代码边界不够明显；
- 打包方式可能把本地环境和敏感状态一起交付。

优先完成“仓库卫生 → 文档分层 → 规范工具化”三步，就能在不触碰业务逻辑的前提下显著提升四个评分项。大文件拆分、领域重组和数据库迁移应放在后续独立阶段，避免为了目录漂亮而引入功能回归。

本报告建议作为整改基线保留。每完成一个阶段，在报告末尾追加“完成记录、commit、验证结果”，而不是直接改写原始审查结论，这样既能向评委展示问题识别能力，也能展示规范化整改的可追溯过程。

---

## 附录 A：本次审查未执行的操作

为遵守“先审查、不修改”的要求，本次没有：

- 运行后端或爬虫测试；
- 执行前端构建；
- 启动服务或访问数据库；
- 移动、删除或重命名现有文件；
- 修改 `.env`；
- 修改缓存或运行时状态；
- 执行自动格式化；
- 调用任何会写数据库的验收脚本。

测试数量、路由数量、代码行数和文件规模均来自静态扫描，可能与测试框架最终收集数量存在小幅差异，应在正式整改阶段通过 CI 再确认。

## 附录 B：推荐整改记录模板

```markdown
## 整改记录

### 2026-07-XX — 阶段 1：仓库卫生

- Commit：`<sha>`
- 完成：停止跟踪运行态缓存、完善 ignore、增加打包脚本
- 验证：
  - `git status` after normal run：clean
  - source archive size：xx MB
  - secret scan：pass
- 未完成/风险：...
```
