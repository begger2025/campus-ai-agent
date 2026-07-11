# Evidence Collector

This standalone package provides the foundational configuration, schemas, and
database models for collecting and reviewing externally sourced evidence. It
does not call providers and does not modify any main-project tables.

## Configuration

All configuration comes from environment variables. `EVIDENCE_DATABASE_URL`
takes precedence over `DATABASE_URL`; without either, the package uses a local
SQLite database at `evidence_collector/evidence_collector.db`.

Supported provider IDs are `deepseek`, `glm`, `kimi`, `doubao`, and `qwen`.
Each is enabled only when both `EVIDENCE_<PROVIDER>_API_KEY` is nonempty and
`EVIDENCE_<PROVIDER>_WEB_SEARCH_ENABLED=true`. Configuration objects retain no
API-key values. `EVIDENCE_COLLECTOR_TOKEN` is intentionally checked only by
`require_collector_token()` at future API startup.

Copy the local [`.env.example`](.env.example) as a reference; never commit real
credentials.

## Database

Use `create_database_engine()` and pass the returned engine to
`init_database()`. The package uses its own SQLAlchemy metadata and creates
only tables named `evidence_*`. It has no foreign keys to application tables.

## Tests

Run from the repository worktree:

```powershell
D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\.venv\Scripts\python.exe -m unittest discover -s evidence_collector\tests -v
```
