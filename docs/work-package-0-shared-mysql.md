# 工作包 0：统一共享数据库

> **第二周请以升级版为准**：[工作包 1：统一共享 MySQL 与历史数据处理](work-package-1-shared-mysql.md)

对应课件：`后端工作包0：统一共享数据库.pdf`

## 一、要解决什么问题？

| 现在（第一周） | 第二周目标 |
|----------------|------------|
| 每人电脑上的 `data/campus.db`（SQLite） | 全组共用一个 **MySQL** 库 `campus_ai_agent` |
| 你插入的数据别人看不到 | A 插入 → B/C/D 刷新也能看到 |
| 爬虫 JSON → 本地 import | MediaCrawler 写入共享 MySQL 平台表 |

**核心结论**：团队主库地址不能再写 `localhost` / `sqlite:///data/campus.db`，要写**云服务器或云 MySQL 的公网地址**。

## 二、目标架构

```text
组员 A 爬虫          组员 B 爬虫
组员 C 后端          组员 D Agent
        \           |           /
         \          |          /
          v         v         v
        同一个 MySQL：campus_ai_agent
                  |
            后端 API（FastAPI）
                  |
         浏览器 / 管理员后台（只调 API，不直连库）
```

### 数据写入分工（定好后不要乱改表）

| 谁写 | 写什么表 |
|------|----------|
| MediaCrawler | `xhs_note`、`weibo_note`、`tieba_note` 等平台原生表 |
| 主项目同步脚本 | 平台表 → `raw_posts` |
| 后端清洗 | `raw_posts` → `processed_posts` |
| 公共舆情 Agent | `public_events` |
| 管理员 | 审核 `public_events` |
| 个人 Agent | `personal_advices`（若已建） |
| **前端** | **禁止直连数据库**，只调 API |

你当前仓库第一周路径仍是：`crawl.bat` → JSON → `import_latest.bat` → `raw_posts`。接入共享 MySQL 后，**后端和 import 脚本改连同一 `DATABASE_URL`** 即可；MediaCrawler 由爬虫负责人单独初始化。

## 三、四人分工建议

| 角色 | 负责事项 |
|------|----------|
| **运维/组长** | 租云服务器或云 MySQL；开放 3306；把地址和密码发给组员 |
| **后端负责人（只做一次）** | 在共享库执行 `scripts/init_db.py` 建业务表 |
| **爬虫负责人（只做一次）** | 在 MediaCrawler 目录执行 `python main.py --init_db mysql` |
| **全体组员** | 改 `.env`、跑 `verify_db.bat`、确认不是 sqlite |

## 四、落地步骤（按 PDF 顺序）

### 第 1 步：确定数据库部署位置

选一个**全组都能访问**的地址，例如：

- 云服务器公网 IP + 自建 MySQL
- 阿里云 / 腾讯云 **云数据库 RDS MySQL**

记录：

```text
数据库主机：<公网 IP 或域名>
端口：3306
数据库名：campus_ai_agent
```

> 若 MySQL 和后端部署在**同一台**云服务器上，后端进程可以用 `127.0.0.1`，但**组员各自电脑**上的 `.env` 仍要写**公网 IP**，不能写 localhost。

### 第 2 步：创建数据库（在 MySQL 上执行一次）

```sql
CREATE DATABASE campus_ai_agent
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;
```

### 第 3 步：创建专用账号（不要用 root 给全组）

```sql
CREATE USER 'campus_app'@'%' IDENTIFIED BY '你的强密码';
CREATE USER 'campus_crawler'@'%' IDENTIFIED BY '你的强密码';

GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX
  ON campus_ai_agent.* TO 'campus_app'@'%';

GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX
  ON campus_ai_agent.* TO 'campus_crawler'@'%';

FLUSH PRIVILEGES;
```

- `campus_app` → 本仓库 FastAPI / `init_db` / `import_posts`
- `campus_crawler` → MediaCrawler 项目

云厂商安全组需放行 **3306**（建议只放行学校/组员 IP，不要对全网 0.0.0.0/0 长期开放）。

### 第 4 步：全组统一 `.env`

**本仓库** `campus-ai-agent-main/.env`（勿提交 Git）：

```env
DATABASE_URL=mysql+pymysql://campus_app:你的密码@共享数据库地址:3306/campus_ai_agent?charset=utf8mb4
```

**MediaCrawler** 项目 `.env`（路径以你们作业目录为准）：

```env
MYSQL_DB_HOST=共享数据库地址
MYSQL_DB_PORT=3306
MYSQL_DB_USER=campus_crawler
MYSQL_DB_PWD=你的密码
MYSQL_DB_NAME=campus_ai_agent
```

仓库内只提交 `.env.example` 占位，见本项目已更新的示例。

### 第 5 步：验证本机能否连接

PowerShell：

```powershell
Test-NetConnection 共享数据库地址 -Port 3306
```

`TcpTestSucceeded : True` 表示端口通。

在本项目根目录：

```bat
verify_db.bat
```

或：

```bat
.\.venv\Scripts\python.exe scripts\verify_db_connection.py
```

成功时应看到：

- `driver: mysql`
- `host` 为共享 IP/域名（**不是** localhost）
- `SELECT 1` 成功

### 第 6 步：只由后端负责人初始化表（一次）

```bat
cd C:\Users\pissy\Desktop\campus-ai-agent-main
init_db.bat
```

会创建：`raw_posts`、`processed_posts`、`public_events`、`user_tasks`、`user_schedules` 等。

**不要 4 个人同时建表或改表结构。**

### 第 7 步：爬虫负责人初始化 MediaCrawler 表（一次）

```bat
cd <MediaCrawler-main 路径>
python main.py --init_db mysql
```

### 第 8 步：验收（全组）

- [ ] 4 台电脑 `.env` 的 `DATABASE_URL` 指向同一主机和库名
- [ ] `verify_db.bat` 全员通过
- [ ] 后端负责人已执行 `init_db.bat` 一次
- [ ] 爬虫负责人已执行 MediaCrawler `--init_db mysql` 一次
- [ ] 任意一人 `import_latest.bat` 或 API 写入后，他人用 MySQL 客户端或 `/posts` 能看到新数据
- [ ] `run.bat` 后访问 http://127.0.0.1:9000/posts 返回的是**共享库**数据
- [ ] `data/campus.db` 仅作历史备份，不再作为团队主库

## 五、与本仓库的对应关系

| PDF 要求 | 本项目文件/命令 |
|----------|-----------------|
| 主项目 DATABASE_URL | `.env`、`.env.example` |
| 初始化业务表 | `scripts/init_db.py`、`init_db.bat` |
| 验证连接 | `scripts/verify_db_connection.py`、`verify_db.bat` |
| 读帖子 API | `GET /posts`（`backend/routers/api.py`） |
| 第一周本地库 | `data/campus.db` → 迁移后可弃用为主库 |
| 安装 MySQL 驱动 | `requirements.txt` 中的 `pymysql` |

切换 MySQL 后需要：

```bat
setup.bat
```

或至少：

```bat
.\.venv\Scripts\pip.exe install pymysql
```

## 六、从 SQLite 迁到 MySQL（可选）

若要把现有 `campus.db` 里数据拷到共享库（后端负责人做一次）：

1. 共享库已 `init_db.bat`
2. 临时在 `.env` 保留一份 SQLite 备份配置，或用脚本导出 CSV
3. 使用 `import_latest.bat` 对最新 `posts_*.json` 再导入一次（推荐，简单）
4. 或在 MySQL 客户端中手动 INSERT

## 七、常见问题

**Q：我还能用 campus.db 吗？**  
个人调试可以；团队交付和验收必须用共享 MySQL。

**Q：MySQL Workbench 能打开 campus.db 吗？**  
不能；Workbench 连 MySQL。共享库建好后用 Workbench 连 `campus_ai_agent`。

**Q：连接失败？**  
查：密码、安全组 3306、MySQL `bind-address`、用户是否 `'%'` 主机、本机防火墙。

**Q：我是组员，没有服务器怎么办？**  
推动组长租云库；你先把 `.env.example` 填好占位，服务器就绪后只改一行 `DATABASE_URL` 再跑 `verify_db.bat`。
