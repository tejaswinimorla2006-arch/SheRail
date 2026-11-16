import os
import secrets
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "postgresql+asyncpg://localhost/sherail_test"
os.environ["JWT_SECRET_KEY"] = secrets.token_urlsafe(48)
os.environ["CORS_ORIGINS"] = "[]"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import get_db
from app.main import app
from app.models import Base


@pytest_asyncio.fixture
async def test_sessions():
    test_engine = create_async_engine("sqlite+aiosqlite://")
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    sessions = async_sessionmaker(test_engine, expire_on_commit=False)
    yield sessions
    await test_engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_sessions):
    async with test_sessions() as session:
        yield session


@pytest_asyncio.fixture
async def client(test_sessions):

    async def override_get_db():
        async with test_sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as test_client:
        yield test_client

    app.dependency_overrides.clear()
