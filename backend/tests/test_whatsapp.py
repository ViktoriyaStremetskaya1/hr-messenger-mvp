import pytest
from sqlalchemy import select

from app.channels.base import Button, ListRow, OutButtons, OutList, OutTemplate, OutText
from app.channels.whatsapp import WhatsAppCloudAdapter, build_payload
from app.core.config import get_settings
from app.models import Candidate, Message, WebhookEvent
from tests.wa_helpers import envelope, post_webhook, status, text_msg

WA = "77771234567"


# ---------- адаптер ----------

def test_payloads_respect_whatsapp_limits():
    p = build_payload("7777", OutButtons("Вопрос", [Button("a", "Очень длинное название кнопки")]))
    assert p["interactive"]["action"]["buttons"][0]["reply"]["title"] == "Очень длинное назва…"
    assert len(p["interactive"]["action"]["buttons"][0]["reply"]["title"]) == 20
    with pytest.raises(ValueError):
        build_payload("7777", OutButtons("x", [Button(str(i), str(i)) for i in range(4)]))
    with pytest.raises(ValueError):
        build_payload("7777", OutList("x", "Выбрать", [ListRow(str(i), str(i)) for i in range(11)]))
    t = build_payload("7777", OutTemplate("vacancy_offer", "kk", ["Айгүл", "Операционист", "Алматы"]))
    assert t["template"]["language"]["code"] == "kk"
    assert [x["text"] for x in t["template"]["components"][0]["parameters"]] == ["Айгүл", "Операционист", "Алматы"]
    assert build_payload("+77771234567", OutText("hi"))["to"] == "+77771234567"  # «+» снимает adapter.send


def test_signature_verification():
    a = WhatsAppCloudAdapter(get_settings())
    import hashlib
    import hmac
    body = b'{"x":1}'
    good = "sha256=" + hmac.new(b"test-app-secret", body, hashlib.sha256).hexdigest()
    assert a.verify_signature(body, {"x-hub-signature-256": good})
    assert not a.verify_signature(body + b" ", {"x-hub-signature-256": good})
    assert not a.verify_signature(body, {})


def test_parse_interactive_and_media():
    a = WhatsAppCloudAdapter(get_settings())
    msgs = [
        {"from": WA, "id": "w1", "timestamp": "1700000000", "type": "interactive",
         "interactive": {"type": "button_reply", "button_reply": {"id": "yes", "title": "Да"}}},
        {"from": WA, "id": "w2", "timestamp": "1700000000", "type": "interactive",
         "interactive": {"type": "list_reply", "list_reply": {"id": "slot:5", "title": "Пн 10:00"}}},
        {"from": WA, "id": "w3", "timestamp": "1700000000", "type": "button", "button": {"payload": "Да, интересно", "text": "Да, интересно"}},
        {"from": WA, "id": "w4", "timestamp": "1700000000", "type": "image", "image": {"id": "m1", "caption": "резюме"}},
        {"from": WA, "id": "w5", "timestamp": "1700000000", "type": "reaction", "reaction": {}},
    ]
    inbound, _ = a.parse_webhook(envelope({"contacts": [{"profile": {"name": "Асель"}, "wa_id": WA}], "messages": msgs}))
    assert [(m.type, m.reply_id, m.text) for m in inbound] == [
        ("button_reply", "yes", "Да"), ("list_reply", "slot:5", "Пн 10:00"), ("button_reply", "Да, интересно", "Да, интересно"),
        ("media", None, "резюме"), ("unsupported", None, "[reaction]"),
    ]
    assert inbound[0].contact_name == "Асель"


# ---------- webhook ----------

async def test_webhook_verify_challenge(anon):
    ok = await anon.get("/api/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    bad = await anon.get("/api/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "42"})
    assert bad.status_code == 403


async def test_webhook_rejects_bad_signature(anon, db):
    r = await post_webhook(anon, text_msg(WA, "Привет"), signature="sha256=deadbeef")
    assert r.status_code == 401
    assert (await db.execute(select(WebhookEvent))).first() is None


async def test_inbound_from_unknown_number_creates_candidate(anon, recruiter, db):
    from app.models import Conversation
    r = await post_webhook(anon, text_msg(WA, "Здравствуйте, есть вакансии?", name="Асель"))
    assert r.status_code == 200
    assert (await db.execute(select(Conversation.unread_count))).scalar_one() == 1
    items = (await recruiter.get("/api/candidates")).json()["items"]
    assert len(items) == 1 and items[0]["full_name"] == "Асель" and items[0]["source"] == "WhatsApp (написал сам)"
    conv = (await recruiter.get(f"/api/candidates/{items[0]['id']}/conversation")).json()
    assert conv["window_open"] is True
    assert conv["messages"][0]["body"] == "Здравствуйте, есть вакансии?"
    assert conv["conversation"]["unread_count"] == 0  # просмотр сбрасывает счётчик


async def test_duplicate_webhook_is_idempotent(anon, db):
    payload = text_msg(WA, "Привет", wamid="wamid.SAME")
    await post_webhook(anon, payload)
    await post_webhook(anon, payload)
    assert len((await db.execute(select(Message))).scalars().all()) == 1


async def test_inbound_marks_application_replied(anon, recruiter):
    v = (await recruiter.post("/api/vacancies", json={"title": "Операционист", "city": "Алматы"})).json()
    c = (await recruiter.post("/api/candidates", json={"full_name": "Тест", "phone": "+77771234567", "vacancy_id": v["id"]})).json()
    await post_webhook(anon, text_msg(WA, "Да"))
    assert (await recruiter.get(f"/api/candidates/{c['id']}")).json()["status"] == "replied"


# ---------- отправка и 24-часовое окно ----------

async def _cand(client, phone="+77771234567"):
    return (await client.post("/api/candidates", json={"full_name": "Ахметова Айгуль", "phone": phone})).json()


async def _sync(admin):
    r = await admin.post("/api/templates/sync")
    assert r.status_code == 200, r.text
    return {(t["name"], t["language"]): t for t in (await admin.get("/api/templates")).json()}


async def test_free_text_requires_open_window(admin):
    c = await _cand(admin)
    r = await admin.post(f"/api/candidates/{c['id']}/messages", json={"kind": "text", "text": "Привет"})
    assert r.status_code == 409 and "24-часовое окно" in r.json()["detail"]


async def test_template_send_and_status_lifecycle(admin, anon, wa_mock):
    tpls = await _sync(admin)
    assert tpls[("vacancy_offer", "kk")]["status"] == "APPROVED"
    assert tpls[("vacancy_offer", "ru")]["params_count"] == 3
    c = await _cand(admin)
    tid = tpls[("vacancy_offer", "ru")]["id"]
    bad = await admin.post(f"/api/candidates/{c['id']}/messages", json={"kind": "template", "template_id": tid, "params": ["Айгуль"]})
    assert bad.status_code == 422
    r = await admin.post(f"/api/candidates/{c['id']}/messages",
                         json={"kind": "template", "template_id": tid, "params": ["Айгуль", "Операционист", "Алматы"]})
    assert r.status_code == 201, r.text
    view = (await admin.get(f"/api/candidates/{c['id']}/conversation")).json()
    m = view["messages"][0]
    assert m["status"] == "sent" and m["body"].startswith("Здравствуйте, Айгуль! Банк приглашает вас на вакансию «Операционист»")
    assert m["payload"]["buttons"][0]["text"] == "Да, интересно"
    # мок действительно получил сообщение
    assert wa_mock.chats[WA]["messages"][0]["kind"] == "template"
    wamid = wa_mock.chats[WA]["messages"][0]["id"]
    # статусы приходят не по порядку: read раньше delivered — статус не откатывается
    await post_webhook(anon, status(wamid, "read", WA))
    await post_webhook(anon, status(wamid, "delivered", WA))
    m = (await admin.get(f"/api/candidates/{c['id']}/conversation")).json()["messages"][0]
    assert m["status"] == "read" and m["read_at"] and m["delivered_at"]
    assert (await admin.get(f"/api/candidates/{c['id']}")).json()["last_touch_at"]


async def test_reply_opens_window_then_free_text_goes_through(admin, wa_mock):
    c = await _cand(admin)
    # кандидат пишет через «телефон» мока → мок шлёт webhook; здесь эмулируем доставку вручную
    await wa_mock_inbound(admin, "Да, интересно")
    r = await admin.post(f"/api/candidates/{c['id']}/messages", json={"kind": "text", "text": "Отлично! Расскажу подробнее."})
    assert r.status_code == 201
    view = (await admin.get(f"/api/candidates/{c['id']}/conversation")).json()
    assert view["window_open"] is True
    assert view["messages"][-1]["status"] == "sent"
    assert view["conversation"]["mode"] == "human"  # рекрутер перехватил диалог


async def wa_mock_inbound(client, text, wa_id=WA):
    from app.wamock.main import store
    import time
    store.chat(wa_id)["last_inbound"] = time.time()
    return await post_webhook(client, text_msg(wa_id, text))


async def test_provider_window_error_marks_failed(admin, wa_mock):
    c = await _cand(admin)
    await wa_mock_inbound(admin, "Привет")
    wa_mock.chats[WA]["last_inbound"] -= 25 * 3600  # в Meta окно уже закрыто
    await admin.post(f"/api/candidates/{c['id']}/messages", json={"kind": "text", "text": "Ответ"})
    m = (await admin.get(f"/api/candidates/{c['id']}/conversation")).json()["messages"][-1]
    assert m["status"] == "failed" and "24-часовое окно" in m["error"]


async def test_local_template_cannot_be_sent(admin):
    c = await _cand(admin)
    t = (await admin.post("/api/templates", json={"name": "draft_tpl", "language": "ru", "body": "Текст {{1}}"})).json()
    assert t["status"] == "LOCAL" and t["params_count"] == 1
    r = await admin.post(f"/api/candidates/{c['id']}/messages", json={"kind": "template", "template_id": t["id"], "params": ["x"]})
    assert r.status_code == 422


async def test_recruiter_cannot_manage_templates(recruiter):
    assert (await recruiter.post("/api/templates/sync")).status_code == 403
    assert (await recruiter.get("/api/templates")).status_code == 200


# ---------- СТОП ----------

async def test_stop_unsubscribes_immediately(admin, anon, wa_mock, db):
    tpls = await _sync(admin)
    c = await _cand(admin)
    await wa_mock_inbound(admin, "СТОП!")
    cand = (await admin.get(f"/api/candidates/{c['id']}")).json()
    assert cand["unsubscribed_at"] is not None
    view = (await admin.get(f"/api/candidates/{c['id']}/conversation")).json()
    assert view["unsubscribed"] is True
    assert view["messages"][-1]["direction"] == "out" and "отписались" in view["messages"][-1]["body"]
    assert view["messages"][-1]["status"] == "sent"
    # ни шаблон, ни текст больше не отправить
    tid = tpls[("reserve_revival", "ru")]["id"]
    r = await admin.post(f"/api/candidates/{c['id']}/messages", json={"kind": "template", "template_id": tid, "params": ["Айгуль"]})
    assert r.status_code == 409
    # повторный СТОП не шлёт второе подтверждение
    await wa_mock_inbound(admin, "стоп")
    assert len((await admin.get(f"/api/candidates/{c['id']}/conversation")).json()["messages"]) == 3
    audit = (await admin.get("/api/audit", params={"action": "candidate.unsubscribe"})).json()
    assert audit["total"] == 1
    # СТАРТ — снова подписан
    await wa_mock_inbound(admin, "Старт")
    assert (await admin.get(f"/api/candidates/{c['id']}")).json()["unsubscribed_at"] is None


async def test_stop_reply_in_kazakh(admin, wa_mock):
    c = await _cand(admin)
    await admin.patch(f"/api/candidates/{c['id']}", json={"language": "kk"})
    await wa_mock_inbound(admin, "тоқта")
    msgs = (await admin.get(f"/api/candidates/{c['id']}/conversation")).json()["messages"]
    assert "бас тарттыңыз" in msgs[-1]["body"]


async def test_phone_not_logged_in_webhook_errors(anon, db, caplog):
    await post_webhook(anon, text_msg(WA, "Привет"))
    assert "7771234567" not in caplog.text
    row = (await db.execute(select(Candidate))).scalar_one()
    assert "7771234567" not in row.phone_enc
