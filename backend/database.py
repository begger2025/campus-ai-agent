import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / os.getenv("DATA_DIR", "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# interpolate=False: Windows 下 %26 不会被 dotenv 误解析，避免密码中的 & 破坏 URL
load_dotenv(ROOT / ".env", override=True, interpolate=False)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'campus.db'}")

# 演示降级预案：CAMPUS_DEMO_MODE=1（demo.bat）时改用本地 SQLite 快照，
# 共享 MySQL 不可用也能照常演示。快照由 scripts/make_demo_snapshot.py 生成。
# 注意放在 load_dotenv 之后：.env 会覆盖环境变量，但 .env 里没有这个开关。
if (os.getenv("CAMPUS_DEMO_MODE") or "").lower() in ("1", "true", "yes"):
    DATABASE_URL = f"sqlite:///{DATA_DIR / 'campus_demo.db'}"

if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    engine = create_engine(DATABASE_URL, connect_args=connect_args)
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=3600,
    )
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def uses_mysql() -> bool:
    return DATABASE_URL.startswith("mysql")


def init_db():
    from backend import admin_models, models  # noqa: F401

    Base.metadata.create_all(bind=engine)
