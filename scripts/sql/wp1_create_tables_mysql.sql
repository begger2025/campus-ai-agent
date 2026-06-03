-- admin_operation_logs
CREATE TABLE IF NOT EXISTS admin_operation_logs (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	user_id VARCHAR(64) NOT NULL, 
	action VARCHAR(64) NOT NULL, 
	target_type VARCHAR(64) NOT NULL, 
	target_id VARCHAR(64) NOT NULL, 
	detail TEXT NOT NULL, 
	ip VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

-- agent_run_logs
CREATE TABLE IF NOT EXISTS agent_run_logs (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	agent_type VARCHAR(50) NOT NULL, 
	input_summary TEXT NOT NULL, 
	output_summary TEXT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	started_at DATETIME NOT NULL, 
	finished_at DATETIME, 
	PRIMARY KEY (id)
);

-- crawl_tasks
CREATE TABLE IF NOT EXISTS crawl_tasks (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	platform VARCHAR(50) NOT NULL, 
	keyword VARCHAR(200) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_by VARCHAR(64) NOT NULL, 
	error_message TEXT NOT NULL, 
	started_at DATETIME, 
	finished_at DATETIME, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

-- event_review_logs
CREATE TABLE IF NOT EXISTS event_review_logs (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	event_id INTEGER NOT NULL, 
	reviewer_id VARCHAR(64) NOT NULL, 
	old_status VARCHAR(20) NOT NULL, 
	new_status VARCHAR(20) NOT NULL, 
	comment TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(event_id) REFERENCES public_events (id)
);

-- processed_posts
CREATE TABLE IF NOT EXISTS processed_posts (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	raw_post_id INTEGER NOT NULL, 
	platform VARCHAR(50) NOT NULL, 
	title VARCHAR(500) NOT NULL, 
	content TEXT NOT NULL, 
	author VARCHAR(100) NOT NULL, 
	publish_time DATETIME, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (raw_post_id), 
	FOREIGN KEY(raw_post_id) REFERENCES raw_posts (id)
);

-- public_events
CREATE TABLE IF NOT EXISTS public_events (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	title VARCHAR(200) NOT NULL, 
	summary TEXT NOT NULL, 
	sentiment VARCHAR(20) NOT NULL, 
	topic VARCHAR(100) NOT NULL, 
	heat_score FLOAT NOT NULL, 
	source_post_id INTEGER, 
	status VARCHAR(20) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(source_post_id) REFERENCES processed_posts (id)
);

-- raw_posts
CREATE TABLE IF NOT EXISTS raw_posts (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	platform VARCHAR(50) NOT NULL, 
	title VARCHAR(500) NOT NULL, 
	content TEXT NOT NULL, 
	author VARCHAR(100) NOT NULL, 
	publish_time DATETIME, 
	url VARCHAR(500) NOT NULL, 
	crawl_time DATETIME, 
	PRIMARY KEY (id)
);

-- system_logs
CREATE TABLE IF NOT EXISTS system_logs (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	level VARCHAR(16) NOT NULL, 
	module VARCHAR(64) NOT NULL, 
	message TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

-- user_feedback
CREATE TABLE IF NOT EXISTS user_feedback (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	user_id VARCHAR(64) NOT NULL, 
	content TEXT NOT NULL, 
	contact VARCHAR(128) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

-- user_schedules
CREATE TABLE IF NOT EXISTS user_schedules (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	user_id VARCHAR(50) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	start_at DATETIME NOT NULL, 
	end_at DATETIME NOT NULL, 
	location VARCHAR(200) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

-- user_tasks
CREATE TABLE IF NOT EXISTS user_tasks (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	user_id VARCHAR(50) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	description TEXT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	due_at DATETIME, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

-- users
CREATE TABLE IF NOT EXISTS users (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	username VARCHAR(64) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	`role` VARCHAR(32) NOT NULL, 
	email VARCHAR(128) NOT NULL, 
	is_active BOOL NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (username)
);

