import pytest
from sqlalchemy import select

from app import create_admin
from app.core.security import verify_password
from app.models import AuditLog, User
from tests.conftest import client_for

GOOD = "Kz-Strong-Pass-2026"


def _prompt(*answers):
    it = iter(answers)
    return lambda _msg="": next(it)


async def _user(db, login):
    db.expire_all()
    return (await db.execute(select(User).where(User.login == login))).scalar_one_or_none()


async def test_creates_admin_from_env(db, capsys):
    code = await create_admin.main_async(["--login", "boss", "--name", "Иванова Анна"], env={"ADMIN_PASSWORD": GOOD})
    assert code == 0
    assert "создан" in capsys.readouterr().out

    u = await _user(db, "boss")
    assert u.role == "admin" and u.is_active and u.full_name == "Иванова Анна"
    assert verify_password(GOOD, u.password_hash)

    logs = (await db.execute(select(AuditLog).where(AuditLog.action == "user.create_admin_cli"))).scalars().all()
    assert len(logs) == 1
    assert logs[0].entity == "user" and logs[0].entity_id == str(u.id)
    assert logs[0].diff["mode"] == "created"
    assert GOOD not in str(logs[0].diff)

    async with client_for() as c:
        r = await c.post("/api/auth/login", json={"login": "boss", "password": GOOD})
        assert r.status_code == 200, r.text


async def test_interactive_prompt_twice(db):
    code = await create_admin.main_async(["--login", "boss", "--name", "Босс"], env={}, prompt=_prompt(GOOD, GOOD))
    assert code == 0
    assert verify_password(GOOD, (await _user(db, "boss")).password_hash)


async def test_mismatch_and_short_password_rejected(db, capsys):
    code = await create_admin.main_async(["--login", "boss", "--name", "Б"], env={}, prompt=_prompt(GOOD, GOOD + "x"))
    assert code == 1
    assert "не совпадают" in capsys.readouterr().err

    code = await create_admin.main_async(["--login", "boss", "--name", "Б"], env={"ADMIN_PASSWORD": "short123"})
    assert code == 1
    assert "не меньше 10" in capsys.readouterr().err
    assert await _user(db, "boss") is None


async def test_reset_existing_user(db, users):
    rec = users["recruiter"]
    rec.is_active = False
    await db.commit()

    code = await create_admin.main_async(["--login", "rec"], env={"ADMIN_PASSWORD": GOOD})
    assert code == 0

    u = await _user(db, "rec")
    assert u.id == rec.id
    assert u.is_active and u.role == "admin"
    assert verify_password(GOOD, u.password_hash)
    assert u.full_name == "Rec"  # без --name ФИО не меняется

    log = (await db.execute(select(AuditLog).where(AuditLog.action == "user.create_admin_cli"))).scalar_one()
    assert log.diff["mode"] == "reset"
    assert log.diff["is_active"] == [False, True]
    assert log.diff["role"] == ["recruiter", "admin"]


async def test_new_user_requires_name(db, capsys):
    code = await create_admin.main_async(["--login", "boss"], env={"ADMIN_PASSWORD": GOOD})
    assert code == 1
    assert "ФИО" in capsys.readouterr().err
    assert await _user(db, "boss") is None


async def test_bad_login_rejected(db):
    with pytest.raises(create_admin.AdminError):
        await create_admin.create_or_reset_admin("плохой логин", "Имя", GOOD)
