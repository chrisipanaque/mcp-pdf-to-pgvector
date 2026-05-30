from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db as _get_db


async def get_db():
    async for session in _get_db():
        yield session
