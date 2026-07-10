"""Database ownership and lifecycle helpers for evidence tables only."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Metadata boundary for the collector's independently managed tables."""


def create_database_engine(database_url: str) -> Engine:
    """Build an engine with database-specific safe connection settings."""

    options: dict[str, object] = {}
    normalized_url = database_url.lower()
    if normalized_url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
    elif normalized_url.startswith("mysql"):
        options["pool_pre_ping"] = True
        options["pool_recycle"] = 1800
    return create_engine(database_url, **options)


def create_session_factory(engine: Engine) -> Callable[[], Session]:
    """Return a session factory that can be supplied a test engine directly."""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_database(engine: Engine) -> None:
    """Create this package's evidence tables and no application-owned tables."""

    # Import models so their mappings are registered on this package's Base.
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
