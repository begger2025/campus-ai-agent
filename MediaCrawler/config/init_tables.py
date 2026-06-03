import asyncio
from dotenv import load_dotenv

load_dotenv(override=True)

from database.db_session import get_async_engine
from database.models import Base


async def main():
    engine = get_async_engine("db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("tables created")


asyncio.run(main())