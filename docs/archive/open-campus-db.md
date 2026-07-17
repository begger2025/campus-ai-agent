# 在 Cursor 中打开 campus.db

本项目数据库为 **SQLite** 单文件：`data/campus.db`。

## 已为你安装

| 扩展 | 扩展 ID | 用途 |
|------|---------|------|
| **SQLite Viewer** | `qwtel.sqlite-viewer` | 双击 `.db` 表格浏览（已安装） |

另两个扩展写在 `.vscode/extensions.json` 里，需要时可自行安装：

- `alexcvzz.vscode-sqlite` — 执行 SQL、导出
- `cweijan.dbclient-jdbc` — 多数据库客户端（含 SQLite）

## 打开步骤（推荐）

1. 用 **Cursor** 打开本项目文件夹  
   `C:\Users\pissy\Desktop\campus-ai-agent-main`

2. 若提示 **「是否安装推荐的扩展」**，点 **安装**（或已自动装好 SQLite Viewer）。

3. 左侧 **资源管理器** 展开 `data` 文件夹。

4. **双击** `campus.db`。  
   - 首次可能问「用哪个扩展打开」，选 **SQLite Viewer**。  
   - 可勾选 **始终用此应用打开 .db 文件**。

5. 在打开的面板中：
   - 左侧选表，例如 **`raw_posts`**
   - 右侧查看帖子数据（platform、title、url 等）

6. 看完直接关标签页即可；**不要**用普通文本模式编辑 `.db`。

## 若双击仍是乱码

1. 在 `campus.db` 上 **右键** → **打开方式** → **SQLite Viewer**。  
2. 或 `Ctrl+Shift+P` → 输入 `SQLite Viewer` → 选 **Open with SQLite Viewer**，再选 `data/campus.db`。

## 可选：执行 SQL

若已安装 `alexcvzz.vscode-sqlite`：

1. `Ctrl+Shift+P` → **SQLite: Open Database**
2. 选择 `data/campus.db`
3. 新建 `.sql` 文件，写查询后右键 **Run Query**，例如：

```sql
SELECT platform, COUNT(*) AS cnt FROM raw_posts GROUP BY platform;
SELECT id, platform, title, url FROM raw_posts ORDER BY id DESC LIMIT 20;
```

## 不用扩展时的备选

| 方式 | 命令 / 文件 |
|------|-------------|
| 终端预览 | 双击 `view_db.bat` |
| Markdown 导出 | `data/campus_db_preview.md`（运行 view_db 后更新） |
| 桌面软件 | [DB Browser for SQLite](https://sqlitebrowser.org/) |

## 注意

- 正在运行 `run.bat` 时，尽量避免多个程序同时**写入**数据库。  
- 只读浏览是安全的。
