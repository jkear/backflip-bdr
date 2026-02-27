"""Database connection module for Backflip SDR pipeline.

Provides:
- engine: AsyncEngine connected to PostgreSQL
- AsyncSessionLocal: Session factory
- get_db(): async context manager for use in agent code
"""
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.engine import make_url as _make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. "
        "Copy .env.example to .env and set your database credentials."
    )

_url = _make_url(DATABASE_URL)
if _url.drivername != "postgresql+asyncpg":
    raise RuntimeError(
        f"DATABASE_URL must use the 'postgresql+asyncpg' driver. "
        f"Got: '{_url.drivername}'. "
        f"Example: postgresql+asyncpg://user:password@localhost:5432/dbname"
    )

engine = create_async_engine(
    _url,
    echo=False,
    pool_pre_ping=True,
    pool_size=int(os.environ.get("DB_POOL_SIZE", "5")),
    max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", "10")),
    pool_timeout=int(os.environ.get("DB_POOL_TIMEOUT", "30")),
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_db() -> AsyncIterator[AsyncSession]:
    """Async context manager that yields a database session.

    Usage:
        async with get_db() as db:
            result = await db.execute(...)
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Database session rolled back due to exception")
            raise


async def dispose_engine() -> None:
    """Dispose the engine connection pool. Call once on application shutdown."""
    await engine.dispose()
