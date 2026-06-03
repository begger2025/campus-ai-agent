# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/database/db_session.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#
# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

from typing import Set

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from contextlib import asynccontextmanager
from .models import Base
import config
from config.db_config import mysql_db_config, sqlite_db_config, postgres_db_config
from tools import utils

# Keep a cache of engines
_engines = {}


async def create_database_if_not_exists(db_type: str):
    if db_type == "mysql" or db_type == "db":
        # Connect to the server without a database
        server_url = f"mysql+asyncmy://{mysql_db_config['user']}:{mysql_db_config['password']}@{mysql_db_config['host']}:{mysql_db_config['port']}"
        engine = create_async_engine(server_url, echo=False)
        async with engine.connect() as conn:
            await conn.execute(text(f"CREATE DATABASE IF NOT EXISTS {mysql_db_config['db_name']}"))
        await engine.dispose()
    elif db_type == "postgres":
        # Connect to the default 'postgres' database
        server_url = f"postgresql+asyncpg://{postgres_db_config['user']}:{postgres_db_config['password']}@{postgres_db_config['host']}:{postgres_db_config['port']}/postgres"
        print(f"[init_db] Connecting to Postgres: host={postgres_db_config['host']}, port={postgres_db_config['port']}, user={postgres_db_config['user']}, dbname=postgres")
        # Isolation level AUTOCOMMIT is required for CREATE DATABASE
        engine = create_async_engine(server_url, echo=False, isolation_level="AUTOCOMMIT")
        async with engine.connect() as conn:
            # Check if database exists
            result = await conn.execute(text(f"SELECT 1 FROM pg_database WHERE datname = '{postgres_db_config['db_name']}'"))
            if not result.scalar():
                await conn.execute(text(f"CREATE DATABASE {postgres_db_config['db_name']}"))
        await engine.dispose()


async def _table_exists(conn, table_name: str) -> bool:
    dialect_name = conn.dialect.name
    if dialect_name in {"mysql", "mariadb"}:
        result = await conn.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = :table_name"
            ),
            {"table_name": table_name},
        )
        return result.first() is not None
    if dialect_name == "sqlite":
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table' AND name = :table_name"),
            {"table_name": table_name},
        )
        return result.first() is not None
    if dialect_name == "postgresql":
        result = await conn.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = :table_name"
            ),
            {"table_name": table_name},
        )
        return result.first() is not None
    return False


async def _get_table_columns(conn, table_name: str) -> Set[str]:
    if not await _table_exists(conn, table_name):
        return set()

    dialect_name = conn.dialect.name
    if dialect_name in {"mysql", "mariadb"}:
        result = await conn.execute(text(f"SHOW COLUMNS FROM {table_name}"))
        return {str(row[0]) for row in result.fetchall()}
    if dialect_name == "sqlite":
        result = await conn.execute(text(f"PRAGMA table_info('{table_name}')"))
        return {str(row[1]) for row in result.fetchall()}
    if dialect_name == "postgresql":
        result = await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :table_name"
            ),
            {"table_name": table_name},
        )
        return {str(row[0]) for row in result.fetchall()}
    return set()


async def _get_table_indexes(conn, table_name: str) -> Set[str]:
    if not await _table_exists(conn, table_name):
        return set()

    dialect_name = conn.dialect.name
    if dialect_name in {"mysql", "mariadb"}:
        result = await conn.execute(text(f"SHOW INDEX FROM {table_name}"))
        return {str(row[2]) for row in result.fetchall()}
    if dialect_name == "sqlite":
        result = await conn.execute(text(f"PRAGMA index_list('{table_name}')"))
        return {str(row[1]) for row in result.fetchall()}
    if dialect_name == "postgresql":
        result = await conn.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename = :table_name"
            ),
            {"table_name": table_name},
        )
        return {str(row[0]) for row in result.fetchall()}
    return set()


async def _ensure_column(conn, table_name: str, column_name: str, definition_sql: str) -> None:
    columns = await _get_table_columns(conn, table_name)
    if column_name in columns:
        return

    utils.logger.info(
        f"[database.db_session] Adding missing column `{column_name}` to `{table_name}`"
    )
    await conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition_sql}"))


async def _get_duplicate_xhs_note_ids(conn) -> list[str]:
    result = await conn.execute(
        text(
            "SELECT note_id FROM xhs_note "
            "WHERE note_id IS NOT NULL AND note_id != '' "
            "GROUP BY note_id HAVING COUNT(*) > 1 LIMIT 5"
        )
    )
    return [str(row[0]) for row in result.fetchall() if row and row[0]]


async def _ensure_unique_index(conn, table_name: str, index_name: str, column_name: str) -> None:
    indexes = await _get_table_indexes(conn, table_name)
    if index_name in indexes:
        return

    duplicate_note_ids = await _get_duplicate_xhs_note_ids(conn)
    if duplicate_note_ids:
        utils.logger.error(
            f"[database.db_session] Skip creating unique index `{index_name}` on `{table_name}.{column_name}` "
            f"because duplicate note_ids already exist: {duplicate_note_ids}"
        )
        return

    utils.logger.info(
        f"[database.db_session] Creating unique index `{index_name}` on `{table_name}.{column_name}`"
    )
    await conn.execute(text(f"CREATE UNIQUE INDEX {index_name} ON {table_name} ({column_name})"))


async def _ensure_xhs_schema(conn) -> None:
    if not await _table_exists(conn, "xhs_note"):
        return

    await _ensure_column(conn, "xhs_note", "first_crawled_at", "BIGINT")
    await _ensure_column(conn, "xhs_note", "last_crawled_at", "BIGINT")
    await _ensure_column(conn, "xhs_note", "crawl_count", "INT DEFAULT 1")
    await _ensure_column(conn, "xhs_note", "publish_time_raw", "TEXT")
    await _ensure_column(conn, "xhs_note", "publish_timestamp_ms", "BIGINT")
    await _ensure_column(conn, "xhs_note", "publish_date", "VARCHAR(20)")
    await _ensure_column(conn, "xhs_note", "publish_year", "INT")
    await _ensure_column(conn, "xhs_note", "publish_month", "INT")
    await _ensure_column(conn, "xhs_note", "publish_day", "INT")
    utils.logger.info(
        "[database.db_session] Skip full backfill for xhs_note crawl fields to avoid heavy table rewrite"
    )
    utils.logger.info(
        "[database.db_session] Existing rows with NULL crawl fields will be backfilled lazily during future updates"
    )
    await _ensure_unique_index(conn, "xhs_note", "ux_xhs_note_note_id", "note_id")


def get_async_engine(db_type: str = None):
    if db_type is None:
        db_type = config.SAVE_DATA_OPTION

    if db_type in _engines:
        return _engines[db_type]

    if db_type in ["json", "jsonl", "csv"]:
        return None

    if db_type == "sqlite":
        db_url = f"sqlite+aiosqlite:///{sqlite_db_config['db_path']}"
    elif db_type == "mysql" or db_type == "db":
        db_url = f"mysql+asyncmy://{mysql_db_config['user']}:{mysql_db_config['password']}@{mysql_db_config['host']}:{mysql_db_config['port']}/{mysql_db_config['db_name']}"
    elif db_type == "postgres":
        db_url = f"postgresql+asyncpg://{postgres_db_config['user']}:{postgres_db_config['password']}@{postgres_db_config['host']}:{postgres_db_config['port']}/{postgres_db_config['db_name']}"
    else:
        raise ValueError(f"Unsupported database type: {db_type}")

    engine = create_async_engine(db_url, echo=False)
    _engines[db_type] = engine
    return engine


async def create_tables(db_type: str = None):
    if db_type is None:
        db_type = config.SAVE_DATA_OPTION
    await create_database_if_not_exists(db_type)
    engine = get_async_engine(db_type)
    if engine:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await _ensure_xhs_schema(conn)


@asynccontextmanager
async def get_session() -> AsyncSession:
    engine = get_async_engine(config.SAVE_DATA_OPTION)
    if not engine:
        yield None
        return
    AsyncSessionFactory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    session = AsyncSessionFactory()
    try:
        yield session
        await session.commit()
    except Exception as e:
        await session.rollback()
        raise e
    finally:
        await session.close()
