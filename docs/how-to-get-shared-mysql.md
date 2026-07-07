# 如何拿到共享 MySQL，并执行 wp1_mysql_setup.sql

工作包 1 需要全组连**同一个** `campus_ai_agent` 库。下面分两部分：先「拿到服务器」，再「建库建账号」。

---

## 一、如何拿到共享 MySQL？（4 种常见方式）

### 方式 A：云数据库 RDS（最省事，推荐作业）

适合 4 人远程协作，不用自己装 MySQL。

| 平台 | 产品名 | 大致步骤 |
|------|--------|----------|
| 阿里云 | 云数据库 RDS MySQL | 控制台 → 创建实例 → 选 MySQL 8.0 → 设 root 密码 → 创建数据库 `campus_ai_agent` |
| 腾讯云 | 云数据库 MySQL | 同上 |
| 华为云 | RDS for MySQL | 同上 |

创建后记下：

```text
外网地址（或内网+公网映射）：例如 rm-xxxxx.mysql.rds.aliyuncs.com
端口：3306
root 或高权限账号密码
```

在 **安全组 / 白名单** 里添加组员 IP（或学校出口 IP），否则外网连不上。

#### 阿里云 RDS 怎么买（详细）

**买什么产品（二选一）**

| 推荐 | 产品 | 说明 |
|------|------|------|
| ⭐ 首选 | **云数据库 RDS → MySQL** | 不用自己装 MySQL，有外网地址、备份，适合工作包 1 |
| 备选 | **轻量应用服务器** + 自建 MySQL | 更便宜，但要 SSH 装库、开端口，运维多一步 |

作业 4 人协作：**直接买 RDS MySQL**，不要买 Redis、MongoDB、PolarDB（除非老师要求）。

**控制台路径**

1. 登录 [阿里云控制台](https://www.aliyun.com/)
2. 顶部搜索 **「RDS」** 或 **「云数据库 RDS」**
3. 左侧 **实例列表** → **创建实例**

**创建实例时怎么选（学生作业够用）**

| 配置项 | 建议选择 | 不要选 |
|--------|----------|--------|
| 数据库类型 | **MySQL** | SQL Server、PostgreSQL |
| 版本 | **MySQL 8.0** | 5.6（太老，脚本可能不兼容） |
| 系列/规格 | **基础版** 或 **入门级**；1 核 1G / 1 核 2G | 高可用集群版（贵） |
| 存储 | **20GB** 高效云盘即可 | 几百 GB |
| 地域 | 选离你们最近的（如 **华东1 杭州**） | 随机选远的地域 |
| 可用区 | 默认即可 | — |
| 网络类型 | **专有网络 VPC**（默认） | — |
| **外网地址** | ✅ **开通外网地址**（组员在家必开） | 仅内网（组员连不上） |
| 计费 | **包年包月** 1 个月 或 **按量**（做完记得释放） | 长期包年除非一直用 |

**账号与库（创建向导里或创建后到控制台设）**

- 记下 **高权限账号**（或主账号）和密码（相当于 root 用途）
- 实例创建好后，在 RDS 控制台 → **数据库管理** → 可先建库 `campus_ai_agent`，  
  或交给 `wp1_mysql_setup.sql` 建库（用高权限账号执行 SQL 即可）

**白名单（必做，否则 100% 连不上）**

RDS 控制台 → 实例 → **数据安全性** → **白名单设置**：

- 测试阶段可临时加 `0.0.0.0/0`（允许所有 IP，**仅作业短期**，有安全风险）
- 更好：每个组员查自己公网 IP（百度搜索「IP」），逐个添加 `x.x.x.x/32`

**买完后要抄下来的信息**

```text
外网地址：rm-xxxx.mysql.rds.aliyuncs.com  （在「数据库连接」页）
端口：3306
数据库名：campus_ai_agent（SQL 脚本创建）
campus_app 密码：（wp1_mysql_setup.sql 里自设）
```

`.env` 示例：

```env
DATABASE_URL=mysql+pymysql://campus_app:密码@rm-xxxx.mysql.rds.aliyuncs.com:3306/campus_ai_agent?charset=utf8mb4
```

**费用与优惠**

- 新用户 / 学生：搜 **「云翼计划」**、**「学生机」**、RDS **免费试用**（常有 1 个月）
- 没有优惠时：基础版 RDS 约 **几十元/月**，4 人分摊
- 验收结束：**释放实例** 或 **关闭外网**，避免继续扣费

**不要买的（和本作业无关）**

- ECS 当网站服务器（除非你们顺便部署后端到同一台 ECS，那是另一件事）
- 对象存储 OSS、CDN、域名（数据库作业不需要）
- 云数据库 **只读实例**、**灾备实例**（小组作业用不到）

**若选轻量服务器而不是 RDS**

1. 产品：**轻量应用服务器**（不是 ECS 企业级，学生更便宜）
2. 镜像：**Ubuntu 22.04**
3. 套餐：2核2G 或最低配
4. 买好后：安全组入方向放行 **3306**，SSH 安装 `mysql-server`（见下文方式 B）

---

### 方式 B：租一台云服务器，自己装 MySQL（便宜、要会一点运维）

1. 买轻量应用服务器（阿里云/腾讯云/华为云，学生机更便宜）
2. 系统选 Ubuntu 22.04 或 CentOS
3. SSH 登录后安装 MySQL 8：

```bash
# Ubuntu 示例
sudo apt update
sudo apt install -y mysql-server
sudo mysql_secure_installation
```

4. 修改允许远程连接（仅作业期可放宽，做完要收紧）：

```bash
sudo nano /etc/mysql/mysql.conf.d/mysqld.cnf
# 注释 bind-address = 127.0.0.1  改为 bind-address = 0.0.0.0
sudo systemctl restart mysql
```

5. 云控制台 **安全组放行 3306**（建议只放行组员 IP，不要长期对 0.0.0.0/0 开放）

共享地址 = **服务器公网 IP**，端口 3306。

---

### 方式 C：实验室 / 学校提供的 MySQL

问老师或学长是否有：

- 固定 IP + 端口
- 是否允许 `%` 远程用户
- 是否允许你们建库 `campus_ai_agent`

有的话直接用学校地址，**组员 `.env` 写学校给的公网 IP**，不要写 localhost。

---

### 方式 D：一人电脑当临时库（不推荐作最终方案）

只有「其他组员能访问你电脑公网 IP + 你已开端口」时才勉强可用：

- 你家/宿舍需有公网 IP 或内网穿透（花生壳、frp）
- Windows 装 MySQL，防火墙放行 3306
- 稳定性差，作业演示容易翻车

**建议**：至少用方式 A 或 B。

---

## 二、组内谁来做？拿到后要发什么？

通常由 **组长 / 运维 / 后端负责人** 完成建库，然后在群里发（**不要发 Git**）：

```text
共享地址：<IP 或域名>
端口：3306
数据库名：campus_ai_agent

后端账号：campus_app
后端密码：xxxx

爬虫账号：campus_crawler
爬虫密码：xxxx
```

每人写入自己项目的 `.env`：

```env
DATABASE_URL=mysql+pymysql://campus_app:后端密码@共享地址:3306/campus_ai_agent?charset=utf8mb4
```

---

## 三、如何用 wp1_mysql_setup.sql 建库建账号

脚本路径：

`scripts/sql/wp1_mysql_setup.sql`

它只做 3 件事：**建库**、**建两个用户**、**授权**。  
**不会**建 `raw_posts` 等业务表（业务表由 `init_db.bat` 用 Python 创建）。

### 第 1 步：改密码（必做）

用记事本或 Cursor 打开 `wp1_mysql_setup.sql`，把：

```sql
'CHANGE_ME_app'
'CHANGE_ME_crawler'
```

改成你们组的强密码（字母+数字，各 16 位以上更好）。

### 第 2 步：用有权限的账号执行 SQL

需要 **root** 或能 `CREATE USER` / `GRANT` 的账号。

#### 方法 1：MySQL Workbench（你已有，推荐）

1. 打开 MySQL Workbench → **MySQL Connections** → `+` 新建连接  
2. **Hostname**：共享 IP 或 RDS 域名  
3. **Port**：3306  
4. **Username**：root（或云控制台给的账号）  
5. **Test Connection** → 成功 → OK  
6. 双击连接进入  
7. 菜单 **File → Open SQL Script** → 选 `wp1_mysql_setup.sql`  
8. 点击闪电图标 **Execute**（或 Ctrl+Shift+Enter）  
9. 下方 Output 无红色 Error 即成功  

#### 方法 2：命令行（服务器 SSH 上）

```bash
mysql -h 127.0.0.1 -u root -p < /path/to/wp1_mysql_setup.sql
```

Windows 本机若装了 mysql 客户端：

```bat
cd C:\Users\pissy\Desktop\campus-ai-agent-main
mysql -h 共享IP -P 3306 -u root -p < scripts\sql\wp1_mysql_setup.sql
```

提示输入 root 密码后执行。

#### 方法 3：云 RDS 控制台「SQL 窗口」

阿里云/腾讯云 RDS 常有 **DMS / SQL 编辑器**：粘贴整个 `.sql` 内容 → 执行。

---

### 第 3 步：验证账号是否建好

Workbench 里新建查询，执行：

```sql
SHOW DATABASES LIKE 'campus_ai_agent';
SELECT user, host FROM mysql.user WHERE user IN ('campus_app', 'campus_crawler');
```

应能看到库和两个用户。

---

### 第 4 步：本机测试组员能否连接

PowerShell：

```powershell
Test-NetConnection 共享IP -Port 3306
```

`TcpTestSucceeded : True` 表示端口通。

在项目根目录：

```bat
verify_db.bat
```

（需先把 `.env` 里 `DATABASE_URL` 改成 `campus_app` 和密码）

---

### 第 5 步：后端负责人初始化业务表（空表）

```bat
init_db.bat
check_wp1.bat
```

---

## 四、常见问题

**Q：执行 SQL 报错 `CREATE USER IF NOT EXISTS`？**  
MySQL 5.7 较老版本可能不支持 `IF NOT EXISTS` 建用户。可改成：

```sql
CREATE USER 'campus_app'@'%' IDENTIFIED BY '你的密码';
```

若提示用户已存在，跳过或先 `DROP USER`。

**Q：连不上，10060 超时？**  
查：云安全组是否放行 3306、MySQL 是否监听 0.0.0.0、密码是否正确、学校网络是否封 3306。

**Q：只有我一个人，还没有共享地址？**  
1. 和组长说需要云 MySQL（方式 A 最快）  
2. 或自己用学生优惠买一个月 RDS/轻量服务器  
3. 拿到地址前可继续用本地 `campus.db` 开发，**验收前必须切共享库**

**Q：SQL 脚本和 init_db.bat 有什么区别？**

| 步骤 | 做什么 |
|------|--------|
| `wp1_mysql_setup.sql` | 建**数据库** + **账号** |
| `init_db.bat` | 建**表**（raw_posts、users 等），且业务表为空 |

---

## 五、最小时间线（建议）

1. 今天：组长定方式 A 或 B，拿到 **公网地址 + root**  
2. 后端负责人：改密码 → 执行 `wp1_mysql_setup.sql` → 群发 `campus_app` 密码  
3. 全组：改 `.env` → `verify_db.bat`  
4. 后端：`init_db.bat` → `check_wp1.bat`  
5. 联系陈继橦：MediaCrawler 迁移（见 work-package-1-shared-mysql.md）
