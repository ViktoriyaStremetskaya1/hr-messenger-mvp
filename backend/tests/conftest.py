import base64
import os

os.environ.setdefault("APP_ENV", "test")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://hr:hr@localhost:5432/hr_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-0123456789")
os.environ.setdefault("PHONE_ENC_KEYS", "v1:" + base64.b64encode(b"k" * 32).decode())
os.environ.setdefault("PHONE_HASH_KEY", "test-hash-key")
os.environ["TASKS_INLINE"] = "true"
os.environ["WA_API_BASE"] = "http://wamock"
os.environ["WA_APP_SECRET"] = "test-app-secret"
os.environ["WA_VERIFY_TOKEN"] = "verify-me"
os.environ["WA_ACCESS_TOKEN"] = "test-token"
os.environ["WA_PHONE_NUMBER_ID"] = "1234567890"
os.environ["WA_BUSINESS_ACCOUNT_ID"] = "waba-1"
os.environ["MOCK_STATUS_DELAY"] = "0"
os.environ["MOCK_WEBHOOK_URL"] = "http://127.0.0.1:9/unreachable"

from contextlib import asynccontextmanager  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.channels.registry import set_adapter_override  # noqa: E402
from app.channels.whatsapp import WhatsAppCloudAdapter  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.wamock import main as wamock  # noqa: E402

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


@pytest.fixture(autouse=True)
async def wa_mock():
    """Реальный адаптер Cloud API, но запросы уходят в мок по ASGI (без сети)."""
    wamock.store.chats.clear()
    client = AsyncClient(transport=ASGITransport(app=wamock.app), base_url="http://wamock")
    set_adapter_override("whatsapp", WhatsAppCloudAdapter(get_settings(), client=client))
    yield wamock.store
    set_adapter_override("whatsapp", None)
    await client.aclose()
