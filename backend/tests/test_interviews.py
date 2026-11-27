import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.models import Application, CampaignRecipient, Interview, InterviewSlot
from app.services import interviews
from app.services.interviews import due_reminders, send_due_reminders
from app.wamock.main import store as mock_store
from tests.wa_helpers import button_reply, list_reply, quick_reply
from tests.wa_helpers import post_webhook as _post

WA = "77771234567"


async def post(client, payload):
    for m in payload["entry"][0]["changes"][0]["value"].get("messages", []):
        mock_store.chat(m["from"])["last_inbound"] = time.time()
    return await _post(client, payload)


def phone():
    return mock_store.chats[WA]["messages"]


def last_rows():
    return [m for m in phone() if m.get("rows") or m.get("buttons")][-1]


async def tap(client, title):
    m = last_rows()
    if m.get("rows"):
        r = next(x for x in m["rows"] if x["title"] == title)
        return await post(client, list_reply(WA, r["id"], title))
    b = next(x for x in m["buttons"] if x["title"] == title)
    if b.get("quick"):
        return await post(client, quick_reply(WA, title))
    return await post(client, button_reply(WA, b["id"], title))


def at_local(days: int, hh: int, mm: int = 0) -> datetime:
    from app.services.policy import tz
    d = (datetime.now(UTC).astimezone(tz()) + timedelta(days=days)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    return d.astimezone(UTC)


@pytest.fixture
async def env(admin, users):
    await admin.patch("/api/settings", json={"working_hours": {"start": "00:00", "end": "23:59", "days": [1, 2, 3, 4, 5, 6, 7]}})
    await admin.post("/api/templates/sync")
    vac = (await admin.post("/api/vacancies", json={"title": "Операционист", "city": "Алматы", "schedule": "5/2",
                                                     "office_address": "пр. Абая, 10"})).json()
    cand = (await admin.post("/api/candidates", json={"full_name": "Ахметова Айгуль", "phone": "+77771234567", "city": "Алматы",
                                                       "vacancy_id": vac["id"]})).json()
    await admin.patch(f"/api/candidates/{cand['id']}", json={"language": "ru"})
    offer = (await admin.post("/api/scenarios/from-library", json={"key": "offer"})).json()
    return {"vac": vac, "cand": cand, "offer": offer, "rec": users["recruiter"]}


async def make_slots(admin, env, **kw):
    body = {"recruiter_id": env["rec"].id, "vacancy_id": env["vac"]["id"], "date": at_local(2, 0).astimezone().date().isoformat(),
            "start": "10:00", "end": "12:00", "duration_min": 30, "capacity": 1, **kw}
    from app.services.policy import tz
    body["date"] = (datetime.now(UTC).astimezone(tz()) + timedelta(days=kw.get("days", 2))).date().isoformat()
    body.pop("days", None)
    r = await admin.post("/api/slots/bulk", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def run_offer_to_booking(admin, env):
    await admin.post(f"/api/candidates/{env['cand']['id']}/scenario", json={"scenario_id": env["offer"]["id"], "vacancy_id": env["vac"]["id"]})
    await tap(admin, "Да, интересно")
    for t in ("Да", "Да", "До 1 года", "В течение недели"):
        await tap(admin, t)


# ---------- форматирование ----------

def test_date_format_ru_kk():
    dt = datetime(2026, 11, 30, 5, 0, tzinfo=UTC)  # пн 10:00 Алматы
    assert interviews.fmt_date(dt, "ru") == "30 ноября, пн" and interviews.fmt_time(dt) == "10:00"
    assert interviews.fmt_date(dt, "kk") == "30 қараша, дс"


# ---------- слоты ----------

async def test_bulk_slots_and_roles(admin, recruiter, env):
    slots = await make_slots(admin, env)
    assert len(slots) == 4  # 10:00–12:00 по 30 минут
    assert [interviews.fmt_time(datetime.fromisoformat(s["starts_at"])) for s in slots] == ["10:00", "10:30", "11:00", "11:30"]
    r = await recruiter.get("/api/slots")
    assert len(r.json()) == 4 and r.json()[0]["booked"] == 0
    # рекрутер может создавать слоты себе
    r = await recruiter.post("/api/slots/bulk", json={"recruiter_id": env["rec"].id, "date": slots[0]["starts_at"][:10],
                                                       "start": "15:00", "end": "16:00", "duration_min": 60, "capacity": 5})
    assert r.status_code == 201 and r.json()[0]["capacity"] == 5
    bad = await admin.post("/api/slots/bulk", json={"recruiter_id": env["rec"].id, "date": "2020-01-01", "start": "10:00", "end": "11:00", "duration_min": 30})
    assert bad.status_code == 422


async def test_full_booking_via_bot(admin, env, db):
    await make_slots(admin, env)
    await run_offer_to_booking(admin, env)
    m = last_rows()
    titles = [r["title"] for r in m["rows"]]
    assert len(titles) == 5 and titles[-1] == "Нет удобного времени" and titles[0].endswith("· 10:00")
    assert m["rows"][0]["description"] == "пр. Абая, 10"
    await tap(admin, titles[1])  # 10:30
    assert phone()[-1]["text"].startswith("Готово! Вы записаны на собеседование") and "в 10:30" in phone()[-1]["text"]
    iv = (await db.execute(select(Interview))).scalar_one()
    assert iv.status == "booked" and iv.booked_via == "bot"
    app = (await db.execute(select(Application))).scalar_one()
    assert app.status == "booked"
    st = (await admin.get(f"/api/candidates/{env['cand']['id']}/conversation")).json()
    assert st["scenario"]["outcome"] == "booked" and st["conversation"]["mode"] == "bot"
    # занятый слот больше не предлагается
    assert len(await interviews.available_slots(db, env["vac"]["id"])) == 3


async def test_slot_taken_race_and_other_time(admin, env, db, users):
    slots = await make_slots(admin, env, end="11:00")
    await run_offer_to_booking(admin, env)
    # пока кандидат думал, слот 10:00 занял другой
    other = (await admin.post("/api/candidates", json={"full_name": "Другой", "phone": "+77011112233"})).json()
    r = await admin.post(f"/api/candidates/{other['id']}/interviews", json={"slot_id": slots[0]["id"], "vacancy_id": env["vac"]["id"]})
    assert r.status_code == 201
    first = last_rows()["rows"][0]["title"]
    await tap(admin, first)
    texts = [m["text"] for m in phone() if m["dir"] == "out"]
    assert "только что заняли" in texts[-2]
    assert [r["title"] for r in last_rows()["rows"]][0].endswith("10:30")  # список обновлён
    await tap(admin, "Нет удобного времени")
    assert "подберёт другое время" in phone()[-1]["text"]
    st = (await admin.get(f"/api/candidates/{env['cand']['id']}/conversation")).json()
    assert st["scenario"]["reason"] == "кандидату не подошло время" and st["conversation"]["mode"] == "human"


async def test_group_slot_capacity(admin, env, db):
    slots = await make_slots(admin, env, end="10:30", capacity=2)
    ids = []
    for i in range(3):
        c = (await admin.post("/api/candidates", json={"full_name": f"Г{i}", "phone": f"+7701000000{i}"})).json()
        ids.append((await admin.post(f"/api/candidates/{c['id']}/interviews", json={"slot_id": slots[0]["id"]})).status_code)
    assert ids == [201, 201, 409]


async def test_reminders_24h_2h_and_confirm(admin, anon, env, db):
    slots = await make_slots(admin, env)
    r = await admin.post(f"/api/candidates/{env['cand']['id']}/interviews", json={"slot_id": slots[0]["id"], "vacancy_id": env["vac"]["id"]})
    iv_id = r.json()["id"]
    # запись сделана заранее
    await db.execute(update(Interview).values(created_at=datetime.now(UTC) - timedelta(days=5)))
    await db.commit()
    start = datetime.fromisoformat(slots[0]["starts_at"])
    assert await due_reminders(db, start - timedelta(hours=30)) == []
    due = await due_reminders(db, start - timedelta(hours=23))
    assert [k for _, k in due] == ["24h"]
    # сдвигаем «сейчас»: переносим слот так, чтобы до него было 23 часа
    await db.execute(update(InterviewSlot).where(InterviewSlot.id == slots[0]["id"]).values(starts_at=datetime.now(UTC) + timedelta(hours=23)))
    await db.commit()
    assert await send_due_reminders({}) == 1
    tpl = [m for m in phone() if m["dir"] == "out"][-1]
    assert tpl["kind"] == "template" and tpl["text"].startswith("Напоминаем: собеседование") and "пр. Абая, 10" in tpl["text"]
    assert await send_due_reminders({}) == 0  # повторно не шлём
    await tap(anon, "Приду")
    assert "ждём вас" in phone()[-1]["text"]
    db.expire_all()
    iv = await db.get(Interview, iv_id)
    assert iv.confirmed_at is not None and iv.reminded_24h_at is not None
    # за 2 часа
    await db.execute(update(InterviewSlot).where(InterviewSlot.id == slots[0]["id"]).values(starts_at=datetime.now(UTC) + timedelta(minutes=110)))
    await db.commit()
    assert await send_due_reminders({}) == 1
    db.expire_all()
    assert (await db.get(Interview, iv_id)).reminded_2h_at is not None


async def test_late_booking_skips_24h_reminder(admin, env, db):
    slots = await make_slots(admin, env)
    await db.execute(update(InterviewSlot).values(starts_at=datetime.now(UTC) + timedelta(hours=10)))
    await db.commit()
    await admin.post(f"/api/candidates/{env['cand']['id']}/interviews", json={"slot_id": slots[0]["id"]})
    assert await due_reminders(db) == []  # записался за 10 часов — напоминание «за сутки» не нужно


async def test_reschedule_and_cancel_from_reminder(admin, anon, env, db):
    slots = await make_slots(admin, env)
    r = await admin.post(f"/api/candidates/{env['cand']['id']}/interviews", json={"slot_id": slots[0]["id"], "vacancy_id": env["vac"]["id"]})
    old_id = r.json()["id"]
    iv = await db.get(Interview, old_id)
    ids = await interviews.remind(db, iv, "24h")
    await db.commit()
    from app.services.messaging import send_queued
    await send_queued(ids)
    await tap(anon, "Перенести")
    assert "Выберите новое время" in last_rows()["text"]
    await tap(anon, last_rows()["rows"][2]["title"])
    db.expire_all()
    rows = (await db.execute(select(Interview).order_by(Interview.id))).scalars().all()
    assert [x.status for x in rows] == ["rescheduled", "booked"]
    assert rows[1].slot_id == slots[3]["id"]  # свой текущий слот (10:00) в списке не предлагался
    # отмена через напоминание
    new_id = rows[1].id
    ids = await interviews.remind(db, rows[1], "2h")
    await db.commit()
    await send_queued(ids)
    await tap(anon, "Отменить")
    db.expire_all()
    assert (await db.get(Interview, new_id)).status == "cancelled"
    assert (await db.execute(select(Application.status))).scalar_one() == "replied"


async def test_attendance_marks_and_funnel(admin, env, db):
    slots = await make_slots(admin, env)
    camp = (await admin.post("/api/campaigns", json={"name": "т", "scenario_id": env["offer"]["id"], "vacancy_id": env["vac"]["id"],
                                                      "segment": {"vacancy_ids": [env["vac"]["id"]]}})).json()
    await admin.post(f"/api/campaigns/{camp['id']}/launch")
    await tap(admin, "Да, интересно")
    for t in ("Да", "Да", "До 1 года", "В течение недели"):
        await tap(admin, t)
    await tap(admin, last_rows()["rows"][0]["title"])
    iv = (await db.execute(select(Interview))).scalar_one()
    r = await admin.patch(f"/api/interviews/{iv.id}", json={"status": "attended"})
    assert r.status_code == 409  # собеседование ещё не началось
    await db.execute(update(InterviewSlot).where(InterviewSlot.id == iv.slot_id).values(starts_at=datetime.now(UTC) - timedelta(minutes=30)))
    await db.commit()
    r = await admin.patch(f"/api/interviews/{iv.id}", json={"status": "attended"})
    assert r.status_code == 200
    st = (await admin.get(f"/api/campaigns/{camp['id']}")).json()["stats"]
    assert st["booked"] == 1 and st["attended"] == 1
    assert (await db.execute(select(Application.status))).scalar_one() == "attended"
    lst = (await admin.get(f"/api/candidates/{env['cand']['id']}/interviews")).json()
    assert lst[0]["status"] == "attended" and lst[0]["recruiter_name"]
    # нельзя удалить слот с записью
    assert (await admin.delete(f"/api/slots/{slots[0]['id']}")).status_code == 409
    assert (await admin.delete(f"/api/slots/{slots[3]['id']}")).status_code == 204
