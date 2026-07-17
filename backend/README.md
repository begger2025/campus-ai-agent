# backend — 后端服务

FastAPI 应用,提供全部业务 REST 接口、鉴权、舆情 Agent 对话与证据核验。

## 目录结构

| 目录/文件 | 职责 |
|-----------|------|
| `main.py` | 应用入口(`app = FastAPI(...)`),挂载路由与静态资源,启动 `uvicorn backend.main:app` |
| `routers/` | 9 组路由(接口层,薄控制器):`auth` `api` `agent_public` `admin` `admin_events` `admin_evidence` `comments` `submissions` `feedback` |
| `services/` | 业务层(编排与规则):对话编排、事件修正、证据采集、LLM 客户端、embedding 等 30+ 服务 |
| `agent/public_opinion_core/` | 舆情核心算法包(聚类/研判/排序/记忆),**仅依赖 Python 标准库**,可独立测试与移植 |
| `models.py` / `admin_models.py` / `models_evidence.py` | SQLAlchemy 数据模型(业务主线 / 运营审计 / 证据核验三域) |
| `schemas.py` | Pydantic 响应模型与统一返回封装 `ok()` |
| `database.py` | 引擎与会话(MySQL 主用,SQLite 兜底) |
| `tests/` | 约 1180 个单元/接口测试,零网络依赖 |

## 分层原则

`routers`(接口)→ `services`(业务编排)→ `public_opinion_core`(纯标准库算法),依赖单向向下。
核心算法层不 import 框架,LLM 调用与向量以函数注入方式进入(依赖倒置),因此可独立测试、整包移植。

## 运行与测试

```bash
# 启动(项目根)
run.bat                # 或 uvicorn backend.main:app --host 127.0.0.1 --port 9000

# 测试(项目根,零网络依赖)
.venv\Scripts\python.exe -m unittest discover -s backend/tests -t .
```

接口契约见 [`../docs/api.md`](../docs/api.md),数据库设计见 [`../docs/database.md`](../docs/database.md)。
