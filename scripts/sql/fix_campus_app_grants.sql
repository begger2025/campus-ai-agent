-- Run in DMS as high-privilege user (campus_ai_agent).
-- Fixes: 1142 REFERENCES command denied when init_db / run.bat creates FK tables.

GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES
  ON campus_ai_agent.* TO 'campus_app'@'%';

GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES
  ON campus_ai_agent.* TO 'campus_crawler'@'%';

FLUSH PRIVILEGES;
