# Week 7 P0：安全整改 + 真实登录接入

产品化差距评估（P0~P3）中的第一批工作。目标：消除两处硬编码凭据风险，
把前端假登录替换为真实后端认证。

## 1. 安全整改（后端）

`backend/services/auth_service.py`：

- **JWT 密钥**：删除硬编码的 `DEFAULT_JWT_SECRET`。`JWT_SECRET_KEY` env 优先；
  未配置时启动生成进程级随机密钥并打印警告（重启后所有登录态失效——这是
  提醒配置的信号，不是 bug）。公开仓库里的固定密钥等于任何人可伪造管理员 token。
- **默认管理员密码**：删除硬编码的 `admin123456` 兜底。`ADMIN_PASSWORD` env 优先；
  账号已存在且有密码则不动；**新建**且未配置时生成随机密码、控制台打印一次。
- **演示普通用户**：新增 `ensure_default_demo_user()`（lifespan 调用），保证本地
  新库有可登录的 user 角色账号（`DEMO_USER_USERNAME`/`DEMO_USER_PASSWORD`，
  `ENSURE_DEMO_USER=false` 关闭）。已有账号（如共享库的 `user`/测试用户）不改密、
  不改昵称。
- `.env` 已补 `JWT_SECRET_KEY`（随机生成）、`ADMIN_PASSWORD`、`DEMO_USER_PASSWORD`；
  `.env.example` 同步补演示用户模板。`.gitignore` 本就排除 `.env`（确认过）。

## 2. 真实登录接入（前端）

- 新增 `src/api/auth.js`：`login()` → `POST /api/auth/login`，`fetchMe()` → `GET /api/auth/me`。
- `src/auth/session.js`：删除 `mockLogin`/`DEMO_ACCOUNTS`，新增 `setSession()`。
  管理员默认落地页临时改为 `/`（`/admin` 尚未实现，P1 完成后改回）。
- `LoginView.vue`：`handleLogin` 走真实接口（带 loading 态）；角色切换按钮降级为
  **演示账号快速填充**（认证一律走后端，角色以后端返回为准）；401/403/网络错误
  分别给中文提示。
- `src/api/http.js`：401/403 全局跳转豁免登录请求本身（否则登录失败的错误提示
  会被强制刷新吞掉）；提取后端 `detail`/`message` 作为错误文案；无响应时提示
  "无法连接服务器"。

## 3. 验证记录（2026-07-08）

- 后端测试 27/27（新增 `backend/tests/test_auth.py` 13 个：登录成功/错误密码 401/
  禁用账号 403/token 取 me/JWT 随机化/管理员密码治理/演示用户），TDD 先红后绿。
- `npm run build` 通过。
- live 验证（uvicorn + 共享 MySQL）：`user/user123456` 登录 → 真实 JWT →
  `/auth/me` 返回"测试用户"；错误密码 401；SPA 托管 200。
- 共享库现有账号实测：`admin/admin123456`、`user/user123456` 可登录（登录页
  快速填充与之对齐）。

## 4. 注意事项

- 共享 MySQL 的 `users` 表已有 9 个账号（含各工作包验收的 wp8/wp9/wp10/smoke
  系列测试号），P1 做用户管理时建议清理。
- 合并到团队 GitHub 前 double-check `.env` 不入库（.gitignore 已覆盖，但审慎起见
  用 `git status` 确认）。
- `JWT_EXPIRE_MINUTES` 默认 1440（24h），可在 .env 调整。
