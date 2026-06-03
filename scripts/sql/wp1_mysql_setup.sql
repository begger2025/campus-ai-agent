-- Work package 1: run on shared MySQL server (DBA / team lead)
-- Replace passwords before executing.

CREATE DATABASE IF NOT EXISTS campus_ai_agent
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'campus_app'@'%' IDENTIFIED BY 'CHANGE_ME_app';
CREATE USER IF NOT EXISTS 'campus_crawler'@'%' IDENTIFIED BY 'CHANGE_ME_crawler';

GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES
  ON campus_ai_agent.* TO 'campus_app'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES
  ON campus_ai_agent.* TO 'campus_crawler'@'%';

FLUSH PRIVILEGES;

-- Main project tables: created by init_db.bat (Python ORM), not this file.
-- MediaCrawler tables: imported via mysqldump from media_crawler (crawler lead).
