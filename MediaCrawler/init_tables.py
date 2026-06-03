import asyncio
from dotenv import load_dotenv

load_dotenv(override=True)

from database.db_session import create_tables


async def main():
    await create_tables("db")
    print("tables created and schema ensured")


asyncio.run(main())
