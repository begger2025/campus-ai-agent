# 与组员 GitHub 代码合并指南

你的 `campus-ai-agent-main` **不是 git 仓库**（ZIP 下载），需要先把组仓库 clone 下来，再合并你的改动。

---

## 你需要提供给后端负责人 / AI 的信息

1. **GitHub 仓库地址**（例如 `https://github.com/xxx/campus-ai-agent.git`）
2. **分支名**（一般是 `main` 或 `master`）
3. 你有 **GitHub 推送权限**（组员已加你为 collaborator）

---

## 一键对比（PowerShell）

在项目根目录执行（把 URL 换成真实地址）：

```powershell
cd C:\Users\pissy\Desktop\campus-ai-agent-main
powershell -ExecutionPolicy Bypass -File scripts\merge_compare.ps1 -RepoUrl "https://github.com/xxx/yyy.git"
```

会：

- 克隆远程到 `Desktop\campus-ai-agent-upstream`
- 列出「仅远程有 / 仅本地有 / 两边都有但内容不同」的文件
- **不会**自动覆盖你的文件

---

## 推荐合并步骤

### 1. 运行对比脚本（见上）

### 2. 手动合并策略

| 类型 | 做法 |
|------|------|
| **仅组员新增** | 从 `campus-ai-agent-upstream` 复制到你的项目 |
| **仅你新增**（如 `scripts/verify_db.bat`、MySQL 文档） | 保留，提交时 add |
| **两边都改了同一文件** | 用 Cursor 打开对比，**两段代码都保留有用部分** |
| **`.env`** | **永远不要**从 Git 复制或提交 |

### 3. 在合并后的目录初始化 Git 并推送

```powershell
cd C:\Users\pissy\Desktop\campus-ai-agent-main
git init
git remote add origin https://github.com/xxx/yyy.git
git fetch origin
git checkout -b main
git reset origin/main
# 此时工作区是你的合并结果，再：
git add .
git reset HEAD .env
git status
git commit -m "merge: 合并组员代码与共享 MySQL 工作包1改动"
git push -u origin main
```

若 `git push` 被拒，先：

```powershell
git pull origin main --rebase
git push origin main
```

**禁止** `git push --force`。

---

## 你这边常见「仅本地有」的文件（一般直接保留）

- `scripts/verify_db_connection.py`、`diagnose_db_network.py`、`check_wp1.py`
- `scripts/sql/`、`init_db.bat`、`verify_db.bat`、`check_wp1.bat`、`diagnose_db.bat`
- `backend/admin_models.py`、`docs/work-package-1*.md`、`docs/how-to-get-shared-mysql.md`
- `.env.ecs.example`、`requirements-ecs.txt`（若有）

## 不要提交

- `.env`、`.venv/`、`data/campus.db`、`data/cookies/`、`frontend/node_modules/`
