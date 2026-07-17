# scripts/sql — 共享 MySQL 手工 SQL（早期，留作参考）

早期在共享 RDS 上手工执行过的 SQL。**现在建表/迁移一律走 `scripts/` 下的幂等 Python 脚本**
（`init_db.py` + `add_*.py`/`create_*.py`），这里仅保留历史参考与账号授权语句。

| 文件 | 作用 | 现状 |
|------|------|------|
| `wp1_mysql_setup.sql` | 建库、建 `campus_app`/`campus_crawler` 账号与授权 | 授权语句仍有参考价值；业务表建表已由 `scripts/bat/init_db.bat`（Python ORM）接管 |
| `wp1_create_tables_mysql.sql` | 早期手工建表 DDL | 已被 ORM `create_all` 取代，仅作字段对照 |
| `fix_campus_app_grants.sql` | 修补 `campus_app` 账号权限 | 一次性修补，已执行 |

如需在新 MySQL 实例上从零初始化：建库与账号参考 `wp1_mysql_setup.sql`，
然后运行 `scripts/init_db.py` 建业务表——不要直接执行这里的旧 DDL。
