import base64
import os

os.environ.setdefault("APP_ENV", "test")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://hr:hr@localhost:5432/hr_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-0123456789")
os.environ.setdefault("PHONE_ENC_KEYS", "v1:" + base64.b64encode(b"k" * 32).decode())
os.environ.setdefault("PHONE_HASH_KEY", "test-hash-key")

from contextlib import asynccontextmanager  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402

PASSWORD = "Passw0rd!"


@pytest.fixture(scope="session", autouse=True)
async def _schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
async def _clean():
    yield
    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def db():
    async with SessionLocal() as s:
        yield s


@pytest.fixture
async def users(db):
    created = {}
    for login, role in (("admin", "admin"), ("lead", "lead"), ("rec", "recruiter")):
        u = User(login=login, full_name=login.title(), role=role, password_hash=hash_password(PASSWORD))
        db.add(u)
        created[role] = u
    await db.commit()
    return created


@asynccontextmanager
async def client_for(login: str | None = None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        if login:
            r = await c.post("/api/auth/login", json={"login": login, "password": PASSWORD})
            assert r.status_code == 200, r.text
        yield c


@pytest.fixture
async def anon():
    async with client_for() as c:
        yield c


@pytest.fixture
async def admin(users):
    async with client_for("admin") as c:
        yield c


@pytest.fixture
async def recruiter(users):
    async with client_for("rec") as c:
        yield c


@pytest.fixture
async def lead(users):
    async with client_for("lead") as c:
        yield c
