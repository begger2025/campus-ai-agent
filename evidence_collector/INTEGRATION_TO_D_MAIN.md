# evidence_collector 接入 D 盘主项目说明

本文档描述当前联网证据采集子项目的位置、提交状态，以及如何在不改动
`MediaCrawler`、后端、前端和其它既有目录的前提下接入 D 盘主项目。

## 1. 当前实际位置

| 项目 | 路径/状态 |
| --- | --- |
| 隔离工作区 | `C:\Users\31879\Documents\campus-ai-agent\evidence-collector-worktree` |
| 子项目目录 | `C:\Users\31879\Documents\campus-ai-agent\evidence-collector-worktree\evidence_collector` |
| Git 分支 | `codex/evidence-collector` |
| D 盘主项目 | `D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main` |
| D 盘目标目录 | `D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\evidence_collector` |

隔离工作区与 D 盘主项目使用 Git linked worktree 关联，但不是实时目录镜像。
当前实现只在隔离工作区提交；D 盘主项目不会因为这些提交自动出现
`evidence_collector/`。

当前实现的最后一个提交是 `7ea91b1`。完整功能提交链为：

```text
0c16d95  基础配置、数据库、模型和 schema
062fe15  URL 规范化与 SYSU 范围策略
72a24d5  五家供应商统一抽象
f65ac48  供应商配置与来源溯源加固
519edc3  检索、去重、范围判定和入库流水线
cfd776b  查询审计、质量分和 Session 生命周期修复
062103a  验证、人工审批和交付门禁
7ea91b1  可选 citation-only HTTP 传输桥
```

中间的测试提交也属于同一子项目提交链；如果使用 Git 迁移，建议按完整
提交链迁移，或直接复制最终的 `evidence_collector/` 目录。

## 2. 接入原则

接入 D 盘主项目时只允许新增或覆盖：

```text
D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\evidence_collector\
```

不要复制或修改以下内容：

- `MediaCrawler/`
- `backend/`、`frontend/`、`crawler/`、`scripts/`
- 主项目已有数据库模型、迁移脚本和配置
- `.git/`、`.venv/`、`__pycache__/`
- 任何真实 API key、数据库密码或登录凭据

`evidence_collector` 使用自己的 SQLAlchemy metadata，只创建名称以
`evidence_` 开头的表，不依赖主项目表的外键。

## 3. 推荐迁移方式：Git cherry-pick

这种方式不会把整个隔离工作区复制到 D 盘，只迁移已经提交的
`evidence_collector/` 变更。

### 3.1 迁移前检查

在 PowerShell 中执行：

```powershell
$main = 'D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main'
Set-Location $main
git status --short
git branch --show-current
```

先确认输出中没有本次迁移前才出现的其它改动。已有的
`MediaCrawler/config/base_config.py` 和其它用户文件不要重置、删除或覆盖。

### 3.2 创建接入分支并迁移

```powershell
Set-Location 'D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main'
git switch -c integrate/evidence-collector

git cherry-pick `
  0c16d95 `
  b5d4fd7 `
  3909fd0 `
  9d86ba9 `
  0e5926f `
  062fe15 `
  3298c80 `
  dc7b7a9 `
  72a24d5 `
  094d95a `
  f65ac48 `
  519edc3 `
  cfd776b `
  18899de `
  062103a `
  7ea91b1
```

如果 Git 报告冲突，只处理 `evidence_collector/` 内的冲突；不要使用
`git reset --hard`，也不要覆盖主项目其它文件。迁移完成后检查：

```powershell
git diff --name-only HEAD~16..HEAD
git status --short
```

预期新增文件都位于 `evidence_collector/`。

## 4. 无 Git 迁移方式：只复制子目录

如果不希望在 D 盘主项目中 cherry-pick，可以先备份已有目标目录，再只复制
子项目目录。以下命令不会删除目标目录中的其它内容：

```powershell
$source = 'C:\Users\31879\Documents\campus-ai-agent\evidence-collector-worktree\evidence_collector'
$target = 'D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\evidence_collector'

if (Test-Path -LiteralPath $target) {
    Copy-Item -LiteralPath $target -Destination ($target + '.backup') -Recurse -Force
}
New-Item -ItemType Directory -Path $target -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $source '*') -Destination $target -Recurse -Force
```

复制完成后应删除复制产生的 `__pycache__`，并确认没有复制真实的
`evidence_collector.db` 或 `.env`。推荐使用 Git 方式，因为它能保留提交记录
和审查边界。

## 5. D 盘主项目环境准备

子项目可以复用 D 盘主项目的 Python 虚拟环境：

```powershell
$main = 'D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main'
$python = Join-Path $main '.venv\Scripts\python.exe'
& $python -m pip install sqlalchemy pymysql pydantic httpx python-dotenv
```

`httpx` 是可选的 HTTP 客户端；也可以自行注入任何提供异步 `post()` 方法的
客户端。不要把依赖安装到 `MediaCrawler` 专用环境中，除非明确确认其依赖不会
发生冲突。

## 6. 环境变量配置

`.env.example` 只是模板，不会自动加载。可以使用 PowerShell 临时设置环境变量，
或在启动入口显式调用 `python-dotenv` 加载自己的 `.env` 文件。

以 DeepSeek 为例，至少需要四项：

```powershell
$env:EVIDENCE_DEEPSEEK_API_KEY = '<your-api-key>'
$env:EVIDENCE_DEEPSEEK_MODEL = '<actual-model-id>'
$env:EVIDENCE_DEEPSEEK_BASE_URL = 'https://<provider-host>/<chat-completions-path>'
$env:EVIDENCE_DEEPSEEK_WEB_SEARCH_ENABLED = 'true'
```

其它供应商使用同样的前缀：

```text
EVIDENCE_GLM_API_KEY / EVIDENCE_GLM_MODEL / EVIDENCE_GLM_BASE_URL / EVIDENCE_GLM_WEB_SEARCH_ENABLED
EVIDENCE_KIMI_API_KEY / EVIDENCE_KIMI_MODEL / EVIDENCE_KIMI_BASE_URL / EVIDENCE_KIMI_WEB_SEARCH_ENABLED
EVIDENCE_DOUBAO_API_KEY / EVIDENCE_DOUBAO_MODEL / EVIDENCE_DOUBAO_BASE_URL / EVIDENCE_DOUBAO_WEB_SEARCH_ENABLED
EVIDENCE_QWEN_API_KEY / EVIDENCE_QWEN_MODEL / EVIDENCE_QWEN_BASE_URL / EVIDENCE_QWEN_WEB_SEARCH_ENABLED
```

当前 HTTP 桥把 `BASE_URL` 当作实际 POST endpoint 使用，不会自动拼接路径。
请以供应商官方文档给出的 OpenAI-compatible chat-completions 地址为准。

数据库可以先用本地 SQLite 验证：

```powershell
$env:EVIDENCE_DATABASE_URL = 'sqlite:///evidence_collector.db'
```

接入公共 MySQL 时改为类似下面的形式，不要把真实密码写入文档或 Git：

```text
EVIDENCE_DATABASE_URL=mysql+pymysql://<user>:<password>@<host>:3306/<database>?charset=utf8mb4
```

## 7. 最小真实 API 测试代码

下面代码只使用 `evidence_collector/` 的公开接口，不会调用
`MediaCrawler`，也不会写主项目原有表：

```python
import asyncio
import httpx

from evidence_collector.config import load_settings
from evidence_collector.database import (
    create_database_engine,
    create_session_factory,
    init_database,
)
from evidence_collector.services.collector import EvidenceCollector
from evidence_collector.services.http_transport import build_http_transports
from evidence_collector.services.providers import ProviderRegistry


async def main():
    settings = load_settings()
    engine = create_database_engine(settings.database_url)
    init_database(engine)

    async with httpx.AsyncClient(timeout=60) as client:
        transports = build_http_transports(client=client)
        registry = ProviderRegistry.from_environment(transports=transports)
        print('enabled providers:', registry.enabled_provider_ids)

        collector = EvidenceCollector(
            create_session_factory(engine),
            registry,
        )
        run = await collector.collect(
            topic='中山大学校园公共信息测试',
            queries=['中山大学近期校园通知'],
            provider_ids=['deepseek'],
            creator='manual-smoke-test',
        )
        print('run:', run.id, run.status)


asyncio.run(main())
```

运行方式：

```powershell
Set-Location 'D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main'
& .\.venv\Scripts\python.exe .\smoke_test.py
```

建议先只启用一个供应商，确认一条证据完整落库后，再逐个开启其它供应商。

## 8. 数据处理流程

一次 `EvidenceCollector.collect()` 的处理顺序如下：

1. 生成包含“中山大学 / Sun Yat-sen University / SYSU”背景约束的查询。
2. 调用启用的供应商，并只接受带 HTTP(S) URL 与非空摘录的 citation。
3. 规范化 URL，计算 64 位 SHA-256 `canonical_url_hash`。
4. 依据 SYSU 官方域名、新闻域名、标题和摘录判定 `in_scope`、
   `out_of_scope` 或 `needs_review`。
5. 写入 `evidence_runs`、`evidence_queries`、`evidence_documents`、
   `evidence_items`；同一 canonical URL 全局去重。
6. 通过 `verify_item()` 记录验证，通过 `review_item()` 进行人工审批。
7. 只有 `in_scope + verified + approved` 的项目才能生成交付批次。

初始化数据库只创建本子项目的 `evidence_*` 表，不会迁移或修改主项目已有表。

## 9. 迁移后的验证清单

```powershell
Set-Location 'D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main'
$python = '.\.venv\Scripts\python.exe'

& $python -m unittest discover -s evidence_collector\tests -v
& $python -m compileall -q evidence_collector
git status --short
```

当前基线为 **56 项测试全部通过**。迁移后如果测试失败，先检查：

- 是否使用了 D 盘项目自己的 `.venv`；
- `pydantic`、`sqlalchemy`、`pymysql` 是否安装；
- 是否错误地把 `BASE_URL` 写成控制台网页地址；
- 是否忘记设置 `WEB_SEARCH_ENABLED=true`；
- API 返回是否包含 citation URL 和 quote；
- MySQL 用户是否有创建/写入 `evidence_*` 表的权限。

## 10. 当前能力边界

当前实现提供的是安全的统一接入层，不硬编码五家厂商的真实 endpoint 和
联网工具协议。不同厂商可能需要不同的请求体、搜索工具参数或响应解析器；
如果某个模型的 API 不是 OpenAI-compatible，应该在
`evidence_collector/services/` 内新增该厂商的 transport 适配器，而不是修改
`MediaCrawler` 或主项目已有抓取逻辑。

默认没有注入 HTTP 客户端时，系统明确不联网；因此仅填写 API key 不能让系统
自动开始抓取，这是有意设计的安全门槛。
