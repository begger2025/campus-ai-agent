# 工作包 1：统一共享 MySQL 与历史数据处理

对应课件：`新后端工作包1.pdf`（在工作包 0 基础上的升级版）

## 与工作包 0 的关键区别

| 项目 | 工作包 0 | 工作包 1 |
|------|----------|----------|
| 主项目旧 SQLite `campus.db` | 可迁移数据 | **只建空表，不迁移旧数据** |
| 共享 MySQL 初始化 | 可能带 demo | **禁止插入 demo** |
| MediaCrawler 旧库 `media_crawler` | 新建表 | **完整 mysqldump 迁移** |
| 后台管理表 | 未要求 | **必须创建**（users、crawl_tasks 等） |
| `public_events` | 无审核状态 | 增加 `status` 字段 |

## 一、目标库结构

```text
campus_ai_agent
├── MediaCrawler 原生表（爬虫负责人迁移）
│   ├── xhs_note, xhs_note_comment, xhs_creator, ...
│   ├── weibo_note, weibo_note_comment, ...
│   └── tieba_note, tieba_comment, ...
├── 主项目业务表（后端负责人 init，必须为空）
│   ├── raw_posts = 0
│   ├── processed_posts = 0
│   ├── public_events = 0
│   ├── user_tasks = 0
│   └── user_schedules = 0
└── 后台管理表（后端负责人 init，可为空）
    ├── users, crawl_tasks, agent_run_logs
    ├── event_review_logs, admin_operation_logs
    ├── system_logs, user_feedback
```

本周**不要求** `personal_advices` 表。

## 二、后端负责人清单（你）

### 1. 共享库与账号（同工作包 0）

```sql
CREATE DATABASE campus_ai_agent
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

CREATE USER 'campus_app'@'%' IDENTIFIED BY '强密码';
CREATE USER 'campus_crawler'@'%' IDENTIFIED BY '强密码';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX
  ON campus_ai_agent.* TO 'campus_app'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX
  ON campus_ai_agent.* TO 'campus_crawler'@'%';
FLUSH PRIVILEGES;
```

### 2. 配置 `.env`（全组统一）

```env
DATABASE_URL=mysql+pymysql://campus_app:密码@共享IP:3306/campus_ai_agent?charset=utf8mb4
```

**禁止**：

```env
DATABASE_URL=sqlite:///data/campus.db
# 组员 .env 里不能写 localhost / 127.0.0.1 作为团队主库
```

参考：`.env.example`

### 3. 初始化主项目表（只执行一次，空表）

```bat
init_db.bat
```

等价于：

```bat
.\.venv\Scripts\python.exe scripts\init_db.py
```

- **不要**加 `--seed-demo`
- **不要**把 `data/campus.db` 里的 120 条导入新库

本地第一周调试如需 demo：

```bat
seed_demo.bat
```

仅当 `DATABASE_URL` 为 SQLite 时可用。

### 4. 验收脚本

```bat
verify_db.bat
check_wp1.bat
```

`check_wp1.bat` 会检查：

- 使用 MySQL
- 业务表 + 管理表存在
- `raw_posts` 等 5 张业务表行数为 **0**

### 5. 启动后端

```bat
run.bat
```

工作包 1 下 `run.bat` **不会**自动写入 demo（`SEED_DEMO_ON_START` 默认 false，且 MySQL 强制不 seed）。

## 三、爬虫负责人（陈继橦 — 后端联系他完成）

**不由后端负责人配置 MediaCrawler `.env` 和迁移**，但需知晓验收标准：

### MediaCrawler `.env`

```env
MYSQL_DB_HOST=共享IP
MYSQL_DB_PORT=3306
MYSQL_DB_USER=campus_crawler
MYSQL_DB_PWD=密码
MYSQL_DB_NAME=campus_ai_agent
```

不能再写 `media_crawler` 或 `localhost`。

### 完整迁移旧库

```bat
mysqldump -h 旧库地址 -P 3306 -u root -p media_crawler > media_crawler_backup.sql
mysql -h 共享IP -P 3306 -u campus_crawler -p campus_ai_agent < media_crawler_backup.sql
```

导入前检查 SQL **没有**：

```sql
DROP TABLE raw_posts;
DROP TABLE processed_posts;
```

正常 dump 只含平台表，不会覆盖主项目空表。

### 初始化（若需）

```bat
cd MediaCrawler-main
python main.py --init_db mysql
```

## 四、数据写入链路（第二周起）

```text
MediaCrawler → xhs_note / weibo_note / tieba_note
     ↓ 同步脚本
raw_posts
     ↓ 清洗
processed_posts
     ↓ 公共舆情 Agent
public_events (status: draft → published / rejected / archived)
     ↓ 管理员审核
前端 → 后端 API → MySQL
```

**禁止**：

- 前端直连数据库
- 主项目继续写 SQLite
- MediaCrawler 写旧 `media_crawler`
- 爬虫直接写 `public_events`

## 五、验收标准（对照 PDF）

- [ ] 库名 `campus_ai_agent`，4 人 `.env` 同一地址
- [ ] `DATABASE_URL` 为 `mysql+pymysql://...`，不是 sqlite
- [ ] 主项目 5 张业务表存在且 **= 0 行**
- [ ] 旧 `campus.db` 数据**未**导入新库
- [ ] 7 张管理表存在
- [ ] MediaCrawler 平台表已迁移，条数与旧 `media_crawler` 一致
- [ ] 新采集写入 `campus_ai_agent.xhs_note`
- [ ] `init_db` / `run.bat` 不插入第一周 demo
- [ ] 任意组员写入，他人可见

## 六、本项目命令速查

| 命令 | 谁用 | 说明 |
|------|------|------|
| `init_db.bat` | 后端负责人一次 | 建空表 |
| `check_wp1.bat` | 全组 | 验收 |
| `verify_db.bat` | 全组 | 连通性 |
| `seed_demo.bat` | 仅本地 SQLite | 勿用于共享 MySQL |
| `import_latest.bat` | 第二周后 | 写入共享库 `raw_posts` 前需已切 MySQL |

## 七、从当前仓库切换步骤（你个人）

1. 向组长要共享 IP、账号密码  
2. 修改 `.env` 中 `DATABASE_URL`  
3. `pip install pymysql`（`setup.bat` 已含）  
4. 后端负责人执行 `init_db.bat`  
5. 联系陈继橦完成 MediaCrawler 迁移  
6. `check_wp1.bat` 通过  
7. `data/campus.db` 保留作历史备份，不再 `import` 到团队主库除非组长要求  

SQL 参考脚本：`scripts/sql/wp1_mysql_setup.sql`  
**如何租库、如何用 Workbench 执行 SQL**：见 [how-to-get-shared-mysql.md](how-to-get-shared-mysql.md)
