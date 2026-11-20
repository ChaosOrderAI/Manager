from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url, pool_size=10,
                             connect_args={"timeout": 30}
                             if "sqlite" in settings.database_url else {})


@event.listens_for(engine.sync_engine, "connect")
def _sqlite_pragma(dbapi_conn, _):
    """WAL + busy_timeout for SQLite so concurrent writers queue instead of
    erroring with 'database is locked'."""
    if engine.dialect.name == "sqlite":
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


SessionLocal = async_sessionmaker(engine, class_=AsyncSession,
                                  expire_on_commit=False)


async def get_db():
    async with SessionLocal() as s:
        yield s
