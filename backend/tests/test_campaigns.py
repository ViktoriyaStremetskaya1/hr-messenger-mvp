import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.models import Campaign, Candidate
from app.services.campaigns import campaign_tick
from app.services.segments import segment_query
from app.wamock.main import store as mock_store
from tests.wa_helpers import post_webhook, quick_reply, status

ALL_DAY = {"start": "00:00", "end": "23:59", "days": [1, 2, 3, 4, 5, 6, 7]}


@pytest.fixture
async def env(admin, db):
    await admin.patch("/api/settings", json={"working_hours": ALL_DAY})
    await admin.post("/api/templates/sync")
    vac = (await admin.post("/api/vacancies", json={"title": "Операционист", "city": "Алматы", "office_address": "пр. Абая, 10"})).json()
    other = (await admin.post("/api/vacancies", json={"title": "Кассир", "city": "Астана"})).json()
    offer = (await admin.post("/api/scenarios/from-library", json={"key": "offer"})).json()
    screening = (await admin.post("/api/scenarios/from-library", json={"key": "screening"})).json()
    cands = []
    for i in range(5):
        c = (await admin.post("/api/candidates", json={"full_name": f"Кандидатова Асель{i}", "phone": f"+7701555000{i}",
                                                        "city": "Алматы", "vacancy_id": vac["id"]})).json()
        await admin.patch(f"/api/candidates/{c['id']}", json={"language": "ru"})
        cands.append(c)
    astana = (await admin.post("/api/candidates", json={"full_name": "Астанова", "phone": "+77015550099", "city": "Астана",
                                                         "vacancy_id": other["id"], "is_reserve": True})).json()
    return {"vac": vac, "offer": offer, "screening": screening, "cands": cands, "astana": astana}


def body(env, **kw):
    return {"name": "Операционисты ноябрь", "scenario_id": env["offer"]["id"], "vacancy_id": env["vac"]["id"],
            "segment": {"vacancy_ids": [env["vac"]["id"]]}, **kw}


async def test_segment_filters(env, db):
    async def ids(seg):
        return set((await db.execute(segment_query(seg))).scalars().all())
    alm = {c["id"] for c in env["cands"]}
    assert await ids({"cities": ["алматы"]}) == alm
    assert await ids({"is_reserve": True}) == {env["astana"]["id"]}
    assert await ids({"vacancy_ids": [env["vac"]["id"]], "statuses": ["new"]}) == alm
    assert await ids({"languages": ["none"]}) == {env["astana"]["id"]}
    assert await ids({"candidate_ids": [env["cands"][0]["id"]], "cities": ["Алматы"]}) == {env["cands"][0]["id"]}


async def test_preview_counts_exclusions(admin, env, db):
    c0, c1 = env["cands"][0]["id"], env["cands"][1]["id"]
    await db.execute(update(Candidate).where(Candidate.id == c0).values(unsubscribed_at=datetime.now(UTC)))
    await db.execute(update(Candidate).where(Candidate.id == c1).values(last_touch_at=datetime.now(UTC) - timedelta(days=1)))
    await db.commit()
    p = (await admin.post("/api/campaigns/preview", json={"vacancy_ids": [env["vac"]["id"]]})).json()
    assert p["total"] == 5 and p["eligible"] == 3
    assert p["excluded"] == {"unsubscribed": 1, "frequency": 1, "active_scenario": 0}
    assert len(p["sample"]) == 3


async def test_campaign_end_to_end(admin, anon, env, db, wa_mock):
    c0, c1 = env["cands"][0]["id"], env["cands"][1]["id"]
    await db.execute(update(Candidate).where(Candidate.id == c0).values(unsubscribed_at=datetime.now(UTC)))
    await db.execute(update(Candidate).where(Candidate.id == c1).values(last_touch_at=datetime.now(UTC) - timedelta(days=1)))
    await db.commit()
    camp = (await admin.post("/api/campaigns", json=body(env))).json()
    assert camp["status"] == "draft"
    r = await admin.post(f"/api/campaigns/{camp['id']}/launch")
    assert r.status_code == 200, r.text
    camp = (await admin.get(f"/api/campaigns/{camp['id']}")).json()
    assert camp["status"] == "done"
    st = camp["stats"]
    assert st["total"] == 5 and st["sent"] == 3 and st["skipped"] == 2
    assert st["skipped_by_reason"] == {"unsubscribed": 1, "frequency": 1}
    sent_to = [k for k, ch in wa_mock.chats.items() if ch["messages"]]
    assert len(sent_to) == 3
    first = wa_mock.chats[sent_to[0]]["messages"][0]
    assert first["kind"] == "template" and "Приглашаем вас на вакансию «Операционист»" in first["text"]
    # статусы доставки и ответ одного кандидата
    for wa in sent_to:
        await post_webhook(anon, status(wa_mock.chats[wa]["messages"][0]["id"], "read", wa))
    mock_store.chat(sent_to[0])["last_inbound"] = time.time()
    await post_webhook(anon, quick_reply(sent_to[0], "Да, интересно"))
    st = (await admin.get(f"/api/campaigns/{camp['id']}")).json()["stats"]
    assert st["delivered"] == 3 and st["read"] == 3 and st["replied"] == 1
    # кандидаты помечены касанием — повторная рассылка сразу всех пропустит по частоте
    camp2 = (await admin.post("/api/campaigns", json=body(env, name="Повтор"))).json()
    await admin.post(f"/api/campaigns/{camp2['id']}/launch")
    st2 = (await admin.get(f"/api/campaigns/{camp2['id']}")).json()["stats"]
    assert st2["sent"] == 0
    assert st2["skipped_by_reason"] == {"unsubscribed": 1, "frequency": 4}  # 3 только что + 1 касались вчера
    recips = (await admin.get(f"/api/campaigns/{camp['id']}/recipients", params={"status": "sent"})).json()
    assert recips["total"] == 3 and recips["items"][0]["message_status"] == "read"


async def test_rate_limit_batches_and_daily_limit(admin, env, db, wa_mock):
    await admin.patch("/api/settings", json={"rate_limit_per_minute": 2})
    camp = (await admin.post("/api/campaigns", json=body(env))).json()
    await admin.post(f"/api/campaigns/{camp['id']}/launch")
    s = (await admin.get(f"/api/campaigns/{camp['id']}")).json()
    assert s["status"] == "running" and s["stats"]["sent"] == 2 and s["stats"]["queued"] == 3
    await campaign_tick({"inline": True}, camp["id"])  # следующая минута
    assert (await admin.get(f"/api/campaigns/{camp['id']}")).json()["stats"]["sent"] == 4
    await admin.patch("/api/settings", json={"daily_send_limit": 4})  # суточный лимит исчерпан
    await campaign_tick({"inline": True}, camp["id"])
    s = (await admin.get(f"/api/campaigns/{camp['id']}")).json()
    assert s["stats"]["sent"] == 4 and s["status"] == "running"
    await admin.patch("/api/settings", json={"daily_send_limit": 2000})
    await campaign_tick({"inline": True}, camp["id"])
    s = (await admin.get(f"/api/campaigns/{camp['id']}")).json()
    assert s["stats"]["sent"] == 5 and s["status"] == "done"


async def test_respects_working_hours(admin, env, wa_mock):
    from app.services.policy import tz
    today = datetime.now(UTC).astimezone(tz()).isoweekday()
    await admin.patch("/api/settings", json={"working_hours": {"start": "09:00", "end": "20:00", "days": [d for d in range(1, 8) if d != today]}})
    camp = (await admin.post("/api/campaigns", json=body(env))).json()
    await admin.post(f"/api/campaigns/{camp['id']}/launch")
    s = (await admin.get(f"/api/campaigns/{camp['id']}")).json()
    assert s["status"] == "running" and s["stats"]["sent"] == 0 and s["stats"]["queued"] == 5
    assert not any(ch["messages"] for ch in wa_mock.chats.values())


async def test_scheduled_in_future(admin, env, db):
    later = (datetime.now(UTC) + timedelta(hours=3)).isoformat()
    camp = (await admin.post("/api/campaigns", json=body(env))).json()
    s = (await admin.post(f"/api/campaigns/{camp['id']}/launch", json={"scheduled_at": later})).json()
    assert s["status"] == "scheduled" and s["stats"]["queued"] == 5
    await campaign_tick({"inline": True}, camp["id"])  # рано — ничего не отправляет
    assert (await admin.get(f"/api/campaigns/{camp['id']}")).json()["stats"]["sent"] == 0


async def test_pause_resume_cancel(admin, env, db):
    await admin.patch("/api/settings", json={"rate_limit_per_minute": 1})
    camp = (await admin.post("/api/campaigns", json=body(env))).json()
    await admin.post(f"/api/campaigns/{camp['id']}/launch")
    assert (await admin.post(f"/api/campaigns/{camp['id']}/pause")).json()["status"] == "paused"
    await campaign_tick({"inline": True}, camp["id"])
    assert (await admin.get(f"/api/campaigns/{camp['id']}")).json()["stats"]["sent"] == 1
    s = (await admin.post(f"/api/campaigns/{camp['id']}/resume")).json()  # resume сразу делает тик
    assert s["status"] == "running" and s["stats"]["sent"] == 2
    s = (await admin.post(f"/api/campaigns/{camp['id']}/cancel")).json()
    assert s["status"] == "cancelled" and s["stats"]["skipped_by_reason"] == {"cancelled": 3}
    await campaign_tick({"inline": True}, camp["id"])
    assert (await admin.get(f"/api/campaigns/{camp['id']}")).json()["stats"]["sent"] == 2
    assert (await admin.post(f"/api/campaigns/{camp['id']}/resume")).status_code == 409
    assert (await admin.delete(f"/api/campaigns/{camp['id']}")).status_code == 409


async def test_validation(admin, recruiter, env):
    r = await admin.post("/api/campaigns", json=body(env, scenario_id=env["screening"]["id"]))
    assert r.status_code == 422 and "начинаться с шаблона" in r.json()["detail"]
    r = await admin.post("/api/campaigns", json=body(env, vacancy_id=None))
    assert r.status_code == 422
    camp = (await recruiter.post("/api/campaigns", json=body(env, segment={"cities": ["Караганда"]}))).json()
    r = await recruiter.post(f"/api/campaigns/{camp['id']}/launch")
    assert r.status_code == 422 and "нет кандидатов" in r.json()["detail"]
    assert (await recruiter.delete(f"/api/campaigns/{camp['id']}")).status_code == 204


async def test_campaign_for_selected_candidates(admin, env, wa_mock, db):
    ids = [env["cands"][0]["id"], env["cands"][2]["id"]]
    camp = (await admin.post("/api/campaigns", json=body(env, segment={"candidate_ids": ids}))).json()
    await admin.post(f"/api/campaigns/{camp['id']}/launch")
    s = (await admin.get(f"/api/campaigns/{camp['id']}")).json()
    assert s["stats"]["sent"] == 2
    c = (await db.execute(select(Campaign))).scalar_one()
    assert c.status == "done"
