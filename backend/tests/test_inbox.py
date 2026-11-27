import asyncio
import json
import time


from app.services import events
from app.wamock.main import store as mock_store
from tests.wa_helpers import post_webhook as _post
from tests.wa_helpers import quick_reply, text_msg


async def post(client, payload):
    for m in payload["entry"][0]["changes"][0]["value"].get("messages", []):
        mock_store.chat(m["from"])["last_inbound"] = time.time()
    return await _post(client, payload)


async def counts(c):
    return (await c.get("/api/inbox/counts")).json()


async def items(c, **params):
    return (await c.get("/api/inbox", params=params)).json()["items"]


async def test_new_inbound_needs_reply_and_unassigned(admin, recruiter):
    await post(admin, text_msg("77015550001", "Здравствуйте! Есть вакансии?", name="Асель"))
    lst = await items(recruiter)
    assert len(lst) == 1
    it = lst[0]
    assert it["candidate_name"] == "Асель" and it["last_preview"] == "Здравствуйте! Есть вакансии?" and it["last_direction"] == "in"
    assert it["needs_reply"] is True and it["unread_count"] == 1 and it["assignee_id"] is None and it["window_open"] is True
    c = await counts(recruiter)
    assert c["all"] == 1 and c["unassigned"] == 1 and c["needs_reply"] == 1 and c["mine"] == 0


async def test_takeover_reply_and_filters(admin, recruiter, users):
    await post(admin, text_msg("77015550002", "Добрый день", name="Дана"))
    conv = (await items(recruiter))[0]
    assert (await recruiter.post(f"/api/conversations/{conv['conversation_id']}/takeover")).status_code == 200
    mine = await items(recruiter, filter="mine")
    assert len(mine) == 1 and mine[0]["mode"] == "human" and mine[0]["assignee_name"] == "Rec"
    r = await recruiter.post(f"/api/candidates/{conv['candidate_id']}/messages", json={"kind": "text", "text": "Здравствуйте, Дана!"})
    assert r.status_code == 201
    it = (await items(recruiter))[0]
    assert it["needs_reply"] is False and it["last_direction"] == "out" and it["last_preview"] == "Здравствуйте, Дана!"
    await post(admin, text_msg("77015550002", "А какая зарплата?"))
    c = await counts(recruiter)
    assert c["mine_needs_reply"] == 1 and c["human"] == 1
    assert (await items(recruiter, filter="needs_reply"))[0]["last_preview"] == "А какая зарплата?"
    await recruiter.post(f"/api/conversations/{conv['conversation_id']}/done")
    assert (await counts(recruiter))["needs_reply"] == 0


async def test_assign_rules(admin, recruiter, lead, users):
    await post(admin, text_msg("77015550003", "Привет"))
    conv = (await items(admin))[0]["conversation_id"]
    r = await recruiter.post(f"/api/conversations/{conv}/assign", json={"user_id": users["lead"].id})
    assert r.status_code == 403
    assert (await recruiter.post(f"/api/conversations/{conv}/assign", json={"user_id": users["recruiter"].id})).status_code == 200
    assert (await lead.post(f"/api/conversations/{conv}/assign", json={"user_id": users["admin"].id})).status_code == 200
    assert (await recruiter.post(f"/api/conversations/{conv}/assign", json={"user_id": None})).status_code == 403
    assert (await items(admin, filter="mine"))[0]["conversation_id"] == conv
    audit = (await admin.get("/api/audit", params={"action": "conversation.assign"})).json()
    assert audit["total"] == 2


async def test_bot_conversation_not_needing_reply_until_handoff(admin):
    await admin.post("/api/templates/sync")
    vac = (await admin.post("/api/vacancies", json={"title": "Операционист", "city": "Алматы"})).json()
    cand = (await admin.post("/api/candidates", json={"full_name": "Ким Дана", "phone": "+77015550004", "vacancy_id": vac["id"]})).json()
    await admin.patch(f"/api/candidates/{cand['id']}", json={"language": "ru"})
    sc = (await admin.post("/api/scenarios/from-library", json={"key": "offer"})).json()
    await admin.post(f"/api/candidates/{cand['id']}/scenario", json={"scenario_id": sc["id"], "vacancy_id": vac["id"]})
    await post(admin, quick_reply("77015550004", "Да, интересно"))
    it = (await items(admin))[0]
    assert it["needs_reply"] is False and it["mode"] == "bot" and it["scenario_step"] == "Скрининг: город"
    assert (await counts(admin))["bot"] == 1
    for _ in range(3):  # непонятные ответы → бот передаёт рекрутеру
        await post(admin, text_msg("77015550004", "???"))
    it = (await items(admin))[0]
    assert it["needs_reply"] is True and it["mode"] == "human" and it["scenario_outcome"] == "handoff"


async def test_search_and_vacancy_filter(admin):
    vac = (await admin.post("/api/vacancies", json={"title": "Кассир", "city": "Астана"})).json()
    await post(admin, text_msg("77015550005", "Здравствуйте", name="Омарова Алия"))
    await post(admin, text_msg("77015550006", "Привет", name="Исаев Тимур"))
    assert [i["candidate_name"] for i in await items(admin, q="омарова")] == ["Омарова Алия"]
    assert [i["candidate_name"] for i in await items(admin, q="0006")] == ["Исаев Тимур"]
    tim = (await items(admin, q="Исаев"))[0]
    await admin.post(f"/api/candidates/{tim['candidate_id']}/applications", json={"vacancy_id": vac["id"]})
    assert [i["candidate_name"] for i in await items(admin, vacancy_id=vac["id"])] == ["Исаев Тимур"]


async def test_events_published_on_inbound(admin):
    pubsub = events.redis().pubsub()
    await pubsub.subscribe(events.CHANNEL)
    await pubsub.get_message(timeout=1)  # подтверждение подписки
    await post(admin, text_msg("77015550007", "Привет"))
    got = None
    for _ in range(20):
        m = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
        if m:
            got = json.loads(m["data"])
            break
        await asyncio.sleep(0.05)
    await pubsub.unsubscribe(events.CHANNEL)
    await pubsub.aclose()
    assert got and got["type"] == "message" and got["conversation_id"]


async def test_inbox_requires_auth(anon):
    assert (await anon.get("/api/inbox")).status_code == 401
    assert (await anon.get("/api/events/stream")).status_code == 401
