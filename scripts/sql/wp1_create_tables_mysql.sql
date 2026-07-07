-- Week2 shared MySQL schema for campus_ai_agent.
-- This file mirrors backend SQLAlchemy models and the current shared MySQL tables.

CREATE TABLE IF NOT EXISTS raw_posts (
  id INT NOT NULL AUTO_INCREMENT,
  platform VARCHAR(50) NOT NULL,
  external_id VARCHAR(255),
  source_table VARCHAR(64) NOT NULL DEFAULT '',
  source_raw_id VARCHAR(255) NOT NULL DEFAULT '',
  source_keyword VARCHAR(255) NOT NULL DEFAULT '',
  title VARCHAR(500) NOT NULL,
  content TEXT NOT NULL,
  author VARCHAR(100) NOT NULL DEFAULT '',
  publish_time DATETIME,
  url VARCHAR(500) NOT NULL DEFAULT '',
  raw_url VARCHAR(500) NOT NULL DEFAULT '',
  like_count INT NOT NULL DEFAULT 0,
  collect_count INT NOT NULL DEFAULT 0,
  comment_count INT NOT NULL DEFAULT 0,
  share_count INT NOT NULL DEFAULT 0,
  tags_json TEXT NOT NULL,
  images_json TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  crawl_time DATETIME,
  status VARCHAR(20) NOT NULL DEFAULT 'active',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY ux_raw_posts_platform_external_id (platform, external_id)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS processed_posts (
  id INT NOT NULL AUTO_INCREMENT,
  raw_post_id INT NOT NULL,
  platform VARCHAR(50) NOT NULL,
  note_id VARCHAR(255) NOT NULL DEFAULT '',
  title VARCHAR(500) NOT NULL,
  content TEXT NOT NULL,
  source_keyword VARCHAR(255) NOT NULL DEFAULT '',
  publish_date VARCHAR(20) NOT NULL DEFAULT '',
  publish_time_raw TEXT NOT NULL,
  author_name VARCHAR(128) NOT NULL DEFAULT '',
  tags_json TEXT NOT NULL,
  note_url VARCHAR(500) NOT NULL DEFAULT '',
  raw_note_url VARCHAR(500) NOT NULL DEFAULT '',
  images_json TEXT NOT NULL,
  like_count INT NOT NULL DEFAULT 0,
  collect_count INT NOT NULL DEFAULT 0,
  comment_count INT NOT NULL DEFAULT 0,
  share_count INT NOT NULL DEFAULT 0,
  heat_score FLOAT NOT NULL DEFAULT 0,
  sentiment VARCHAR(20) NOT NULL DEFAULT 'neutral',
  sentiment_score FLOAT NOT NULL DEFAULT 0,
  risk_level VARCHAR(20) NOT NULL DEFAULT 'low',
  risk_score FLOAT NOT NULL DEFAULT 0,
  risk_reasons_json TEXT NOT NULL,
  concerns_json TEXT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  author VARCHAR(100) NOT NULL DEFAULT '',
  publish_time DATETIME,
  PRIMARY KEY (id),
  UNIQUE KEY raw_post_id (raw_post_id),
  CONSTRAINT fk_processed_posts_raw_post FOREIGN KEY (raw_post_id) REFERENCES raw_posts (id)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS public_events (
  id INT NOT NULL AUTO_INCREMENT,
  event_key VARCHAR(255),
  title VARCHAR(200) NOT NULL,
  summary TEXT NOT NULL,
  topic VARCHAR(100) NOT NULL DEFAULT '',
  event_type VARCHAR(64) NOT NULL DEFAULT '',
  sentiment VARCHAR(20) NOT NULL DEFAULT 'neutral',
  risk_level VARCHAR(20) NOT NULL DEFAULT 'low',
  risk_score FLOAT NOT NULL DEFAULT 0,
  heat_score FLOAT NOT NULL DEFAULT 0,
  confidence FLOAT NOT NULL DEFAULT 0,
  source_count INT NOT NULL DEFAULT 0,
  date_range_json TEXT NOT NULL,
  source_keywords_json TEXT NOT NULL,
  top_tags_json TEXT NOT NULL,
  concerns_json TEXT NOT NULL,
  risk_reasons_json TEXT NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'draft',
  reviewed_by VARCHAR(64) NOT NULL DEFAULT '',
  reviewed_at DATETIME,
  review_comment TEXT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  source_post_id INT,
  PRIMARY KEY (id),
  UNIQUE KEY ux_public_events_event_key (event_key),
  KEY source_post_id (source_post_id),
  CONSTRAINT fk_public_events_source_post FOREIGN KEY (source_post_id) REFERENCES processed_posts (id)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS event_post_links (
  id INT NOT NULL AUTO_INCREMENT,
  event_id INT NOT NULL,
  processed_post_id INT,
  raw_post_id INT,
  `rank` INT NOT NULL DEFAULT 0,
  `role` VARCHAR(32) NOT NULL DEFAULT 'source',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_event_post_links_event_id (event_id),
  KEY idx_event_post_links_processed_post_id (processed_post_id),
  KEY idx_event_post_links_raw_post_id (raw_post_id),
  CONSTRAINT fk_event_post_links_event FOREIGN KEY (event_id) REFERENCES public_events (id),
  CONSTRAINT fk_event_post_links_processed_post FOREIGN KEY (processed_post_id) REFERENCES processed_posts (id),
  CONSTRAINT fk_event_post_links_raw_post FOREIGN KEY (raw_post_id) REFERENCES raw_posts (id)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS users (
  id INT NOT NULL AUTO_INCREMENT,
  username VARCHAR(64) NOT NULL,
  password_hash VARCHAR(255) NOT NULL DEFAULT '',
  display_name VARCHAR(128) NOT NULL DEFAULT '',
  `role` VARCHAR(32) NOT NULL DEFAULT 'user',
  email VARCHAR(128) NOT NULL DEFAULT '',
  phone VARCHAR(32) NOT NULL DEFAULT '',
  status VARCHAR(20) NOT NULL DEFAULT 'active',
  last_login_at DATETIME,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  is_active BOOL NOT NULL DEFAULT TRUE,
  PRIMARY KEY (id),
  UNIQUE KEY username (username)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS crawl_tasks (
  id INT NOT NULL AUTO_INCREMENT,
  task_name VARCHAR(128) NOT NULL DEFAULT '',
  task_type VARCHAR(32) NOT NULL DEFAULT 'crawl',
  platform VARCHAR(50) NOT NULL,
  keyword VARCHAR(200) NOT NULL DEFAULT '',
  status VARCHAR(20) NOT NULL DEFAULT 'pending',
  started_by VARCHAR(64) NOT NULL DEFAULT '',
  started_at DATETIME,
  finished_at DATETIME,
  total_count INT NOT NULL DEFAULT 0,
  success_count INT NOT NULL DEFAULT 0,
  failed_count INT NOT NULL DEFAULT 0,
  error_message TEXT NOT NULL,
  report_path VARCHAR(500) NOT NULL DEFAULT '',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  created_by VARCHAR(64) NOT NULL DEFAULT '',
  PRIMARY KEY (id)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS agent_run_logs (
  id INT NOT NULL AUTO_INCREMENT,
  agent_type VARCHAR(50) NOT NULL,
  keyword VARCHAR(255) NOT NULL DEFAULT '',
  input_count INT NOT NULL DEFAULT 0,
  output_count INT NOT NULL DEFAULT 0,
  input_summary TEXT NOT NULL,
  output_summary TEXT NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'running',
  error_message TEXT NOT NULL,
  duration_ms INT NOT NULL DEFAULT 0,
  created_by VARCHAR(64) NOT NULL DEFAULT '',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at DATETIME,
  PRIMARY KEY (id)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS event_review_logs (
  id INT NOT NULL AUTO_INCREMENT,
  event_id INT NOT NULL,
  reviewer_id VARCHAR(64) NOT NULL DEFAULT '',
  old_status VARCHAR(20) NOT NULL DEFAULT '',
  new_status VARCHAR(20) NOT NULL DEFAULT '',
  review_comment TEXT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  comment TEXT NOT NULL,
  PRIMARY KEY (id),
  KEY event_id (event_id),
  CONSTRAINT fk_event_review_logs_event FOREIGN KEY (event_id) REFERENCES public_events (id)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS admin_operation_logs (
  id INT NOT NULL AUTO_INCREMENT,
  admin_user_id VARCHAR(64) NOT NULL DEFAULT '',
  action VARCHAR(64) NOT NULL,
  target_type VARCHAR(64) NOT NULL DEFAULT '',
  target_id VARCHAR(64) NOT NULL DEFAULT '',
  detail TEXT NOT NULL,
  ip_address VARCHAR(64) NOT NULL DEFAULT '',
  user_agent VARCHAR(500) NOT NULL DEFAULT '',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  user_id VARCHAR(64) NOT NULL DEFAULT '',
  ip VARCHAR(64) NOT NULL DEFAULT '',
  PRIMARY KEY (id)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS system_logs (
  id INT NOT NULL AUTO_INCREMENT,
  level VARCHAR(16) NOT NULL DEFAULT 'INFO',
  module VARCHAR(64) NOT NULL DEFAULT '',
  message TEXT NOT NULL,
  detail TEXT NOT NULL,
  request_id VARCHAR(128) NOT NULL DEFAULT '',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_feedback (
  id INT NOT NULL AUTO_INCREMENT,
  user_id VARCHAR(64) NOT NULL DEFAULT 'anonymous',
  target_type VARCHAR(32) NOT NULL DEFAULT 'system',
  target_id VARCHAR(64) NOT NULL DEFAULT '',
  feedback_type VARCHAR(32) NOT NULL DEFAULT 'suggestion',
  content TEXT NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'pending',
  handled_by VARCHAR(64) NOT NULL DEFAULT '',
  handled_at DATETIME,
  handle_note TEXT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  contact VARCHAR(128) NOT NULL DEFAULT '',
  PRIMARY KEY (id)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS system_configs (
  id INT NOT NULL AUTO_INCREMENT,
  config_key VARCHAR(128) NOT NULL,
  config_value TEXT NOT NULL,
  description TEXT NOT NULL,
  updated_by VARCHAR(64) NOT NULL DEFAULT '',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY ux_system_configs_config_key (config_key)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_tasks (
  id INT NOT NULL AUTO_INCREMENT,
  user_id VARCHAR(50) NOT NULL DEFAULT 'default',
  title VARCHAR(200) NOT NULL,
  description TEXT NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'pending',
  due_at DATETIME,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_schedules (
  id INT NOT NULL AUTO_INCREMENT,
  user_id VARCHAR(50) NOT NULL DEFAULT 'default',
  title VARCHAR(200) NOT NULL,
  start_at DATETIME NOT NULL,
  end_at DATETIME NOT NULL,
  location VARCHAR(200) NOT NULL DEFAULT '',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
