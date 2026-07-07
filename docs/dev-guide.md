# 开发规范（第一周 · 任务 4 · 团队规范文档）

本文档约定 campus-ai-agent 项目的协作方式，全体成员遵守。如有疑问在组内讨论后更新本文档。

| 任务 4 要求 | 本文档章节 |
|-------------|------------|
| 分支怎么建 | §1 分支规范 |
| 提交信息怎么写 | §2 提交信息规范 |
| 文件命名规范 | §3 文件命名规范 |
| 接口返回格式规范 | §4 接口返回格式规范 |

---

## 1. 分支规范

### 1.1 主分支

| 分支 | 用途 |
|------|------|
| `main` | 稳定可运行代码，**禁止直接 push** |
| `dev`（可选） | 日常集成联调，由各功能分支合并 |

### 1.2 功能分支命名

从 `main`（或 `dev`）拉取新分支，命名格式：

```text
<type>/<简短描述>
```

| type | 含义 | 示例 |
|------|------|------|
| `feat` | 新功能 | `feat/posts-import` |
| `fix` | 修复 bug | `fix/posts-pagination` |
| `docs` | 仅文档 | `docs/api-update` |
| `refactor` | 重构 | `refactor/database-layer` |
| `chore` | 构建/依赖/配置 | `chore/add-sqlalchemy` |

规则：

- 全小写，单词用 `-` 连接
- 描述简短明确，建议 2~4 个英文单词
- 每人开发自己的模块，**不要多人共用一个分支长期开发**

### 1.3 推荐工作流

```bash
# 1. 同步最新 main
git checkout main
git pull origin main

# 2. 新建功能分支
git checkout -b feat/your-feature

# 3. 开发、提交（见下文 commit 规范）
git add .
git commit -m "feat: 添加帖子导入接口"

# 4. 推送并在 GitHub 提 Pull Request
git push -u origin feat/your-feature
```

### 1.4 合并要求

- 通过 **Pull Request** 合并到 `main`
- PR 需至少 **1 名组员 review**（第一周可由组长或后端同学代审）
- 合并前确认本地能启动、`/ping` 正常
- 合并后删除已合并的远程功能分支（可选）

---

## 2. 提交信息规范

采用 **Conventional Commits** 简化版：

```text
<type>: <简短说明>
```

### 2.1 type 类型

| type | 说明 |
|------|------|
| `feat` | 新功能 |
| `fix` | 修复 |
| `docs` | 文档 |
| `style` | 格式（不影响逻辑） |
| `refactor` | 重构 |
| `test` | 测试 |
| `chore` | 构建/工具/依赖 |

### 2.2 示例

```text
feat: 添加 GET /posts 分页接口
fix: 修复数据库路径在 Windows 下错误
docs: 补充 api.md 导入接口说明
chore: 更新 requirements.txt 添加 sqlalchemy
```

### 2.3 要求

- 使用中文或英文均可，组内统一即可（建议中文说明 + 英文 type）
- 一行说清「做了什么」，不超过 50 字
- 一次 commit 只做一件事，避免 `update`、`fix bug` 等模糊描述
- **不要提交**：`.env`、`.venv/`、`__pycache__/`、`data/*.db`、密钥文件

---

## 3. 文件命名规范

### 3.1 通用规则

| 规则 | 说明 |
|------|------|
| 小写 | 目录、文件一律小写 |
| 分隔 | 多个单词用 `_`（Python）或 `-`（文档、前端资源） |
| 语言 | 代码用英文命名；文档可用中文文件名如 `meeting-notes.md` |

### 3.2 各模块约定

| 模块 | 路径 | 命名示例 |
|------|------|----------|
| 后端 Python | `backend/` | `database.py`、`models.py`、`import_posts.py` |
| 后端路由 | `backend/routers/` | `api.py`、`posts.py`（按资源拆分） |
| 爬虫脚本 | `crawler/` | `weibo_spider.py`、`export_json.py` |
| Agent 脚本 | `agent/` | `public_opinion_agent.py`、`test_agent.py` |
| 前端（Vue） | `frontend/src/` | `PostList.vue`、`api/posts.ts` |
| 文档 | `docs/` | `api.md`、`database.md`、`dev-guide.md` |
| 脚本 | `scripts/` | `init_db.py`、`import_posts.py` |
| 数据样本 | `data/` | `samples/weibo_2026-05-16.json` |

### 3.3 禁止事项

- 不要使用中文文件名（代码目录内）
- 不要空格、`Copy of xxx.py` 这类临时命名
- 不要把业务逻辑全堆在 `main.py`，按职责拆分文件

---

## 4. 接口返回格式规范

### 4.1 统一结构

除特殊说明外，**所有业务 API** 使用统一 JSON 包装：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | int | `0` 表示成功；非 `0` 表示错误（见错误码表） |
| `message` | string | 提示信息，成功一般为 `"ok"` |
| `data` | object / array / null | 实际业务数据 |

后端使用 `backend/schemas.py` 中的 `ok()` 辅助函数：

```python
from backend.schemas import ok

return ok({"items": [], "total": 0})
```

### 4.2 成功示例

**GET /ping**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "pong": true,
    "timestamp": "2026-05-16T12:00:00",
    "database": "data/campus.db"
  }
}
```

**GET /posts**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "items": [
      {
        "id": 1,
        "platform": "weibo",
        "title": "标题",
        "content": "正文",
        "author": "作者",
        "publish_time": "2026-05-16T08:00:00",
        "url": "https://example.com/1",
        "crawl_time": "2026-05-16T12:00:00"
      }
    ],
    "total": 1
  }
}
```

### 4.3 错误响应

```json
{
  "code": 4001,
  "message": "参数 page 必须大于 0",
  "data": null
}
```

建议错误码分段（可随项目扩展）：

| code 范围 | 含义 |
|-----------|------|
| `0` | 成功 |
| `4000~4099` | 请求参数错误 |
| `4040~4049` | 资源不存在 |
| `5000~5099` | 服务端内部错误 |

### 4.4 例外接口

以下接口可不使用统一包装（保持简单）：

| 接口 | 返回示例 | 说明 |
|------|----------|------|
| `GET /health` | `{"status": "ok"}` | 存活探针 |
| 静态页面 `GET /` | HTML | 前端首页 |

新增接口请在 `docs/api.md` 中同步文档。

### 4.5 其他约定

- 时间字段：ISO 8601 字符串，如 `2026-05-16T12:00:00`
- 分页列表：`data` 内包含 `items` + `total`
- 字段命名：`snake_case`（与 Python / JSON 一致）
- HTTP 状态码：成功用 `200`；参数错误用 `400`；未找到用 `404`；服务器错误用 `500`（同时 `code` 非 0）

---

## 5. 文档同步

- 新增/修改接口 → 更新 `docs/api.md`
- 修改表结构 → 更新 `docs/database.md`
- 变更协作流程 → 更新本文档 `docs/dev-guide.md`

---

## 6. 代码 Review 检查清单（PR 时）

- [ ] 分支命名符合规范
- [ ] commit 信息清晰
- [ ] 无 `.env`、数据库文件等敏感/临时文件
- [ ] 新接口有文档且返回格式符合第 4 节
- [ ] 本地 `run.bat` 能启动，`/ping` 正常
