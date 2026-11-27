from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import Application, Candidate, Conversation
from app.scenario_library import library_list
from app.services import policy
from app.services.scenario_engine import _eval, scenario_timeout, starts_with_template, validate_graph
import time

from app.wamock.main import store as mock_store
from tests.wa_helpers import button_reply, list_reply, quick_reply, text_msg
from tests.wa_helpers import post_webhook as _post_webhook

WA = "77771234567"


async def post_webhook(client, payload):
    """Ответ кандидата: мок тоже должен знать, что окно 24 ч открылось."""
    for m in payload["entry"][0]["changes"][0]["value"].get("messages", []):
        mock_store.chat(m["from"])["last_inbound"] = time.time()
    return await _post_webhook(client, payload)


# ---------- юнит ----------

def test_library_graphs_are_valid():
    lib = library_list()
    assert {s["key"] for s in lib} == {"offer", "missed_call", "screening", "reminder", "reserve_revival"}
    for s in lib:
        assert validate_graph(s["graph"]) == [], s["key"]


def test_validation_errors():
    g = {"start": "a", "nodes": {
        "a": {"type": "buttons", "text": "Вопрос", "options": [{"id": "x", "label": {"ru": "Очень-очень длинная кнопка"}, "next": "zz"}]},
        "b": {"type": "weird"},
        "c": {"type": "template", "template": "nope", "options": [{"id": "y", "label": {"ru": "Да"}, "next": "a"}]},
        "d": {"type": "condition", "rules": [{"var": "v", "op": "like", "next": "a"}]},
    }}
    errors = validate_graph(g, template_names={("vacancy_offer", "ru")})
    text = " | ".join(errors)
    assert "несуществующий шаг «zz»" in text
    assert "длиннее 20 символов" in text
    assert "неизвестный тип «weird»" in text
    assert "шаблон «nope» не найден" in text
    assert "неизвестная операция «like»" in text
    assert "не указан переход «иначе»" in text
    assert validate_graph({"start": "x", "nodes": {}}) == ["В сценарии нет шагов"]


def test_condition_ops():
    v = {"a": {"value": "yes"}, "n": {"value": "3"}, "t": "Алматы, центр"}
    assert _eval({"var": "a", "op": "eq", "value": "YES"}, v)
    assert _eval({"var": "a", "op": "in", "value": ["no", "yes"]}, v)
    assert _eval({"var": "n", "op": "gte", "value": 2}, v) and not _eval({"var": "n", "op": "lte", "value": 2}, v)
    assert _eval({"var": "t", "op": "contains", "value": "алматы"}, v)
    assert _eval({"var": "missing", "op": "empty"}, v)
    assert not _eval({"var": "t", "op": "gte", "value": 1}, v)  # не число — не падаем


def test_starts_with_template_respects_known_language():
    g = library_list()[2]["graph"]  # скрининг: язык → текст
    assert starts_with_template(g, None) is True
    assert starts_with_template(g, "ru") is False
    offer = library_list()[0]["graph"]
    assert starts_with_template(offer, "kk") is True


def test_working_hours():
    wh = {"start": "09:00", "end": "20:00", "days": [1, 2, 3, 4, 5, 6]}
    # пт 27.11.2026 21:00 Алматы (16:00 UTC) → сб 09:00 Алматы (04:00 UTC)
    assert policy.next_working_moment(wh, datetime(2026, 11, 27, 16, 0, tzinfo=UTC)) == datetime(2026, 11, 28, 4, 0, tzinfo=UTC)
    # сб 21:00 → пн 09:00 (воскресенье не рабочее)
    assert policy.next_working_moment(wh, datetime(2026, 11, 28, 16, 0, tzinfo=UTC)) == datetime(2026, 11, 30, 4, 0, tzinfo=UTC)
    # вт 07:00 Алматы → вт 09:00
    assert policy.next_working_moment(wh, datetime(2026, 12, 1, 2, 0, tzinfo=UTC)) == datetime(2026, 12, 1, 4, 0, tzinfo=UTC)
    at = datetime(2026, 12, 1, 6, 0, tzinfo=UTC)  # вт 11:00
    assert policy.in_working_hours(wh, at) and policy.next_working_moment(wh, at) == at


# ---------- сквозные сценарии через мок ----------

@pytest.fixture
async def setup(admin):
    await admin.post("/api/templates/sync")
    v = (await admin.post("/api/vacancies", json={
        "title": "Операционист", "city": "Алматы", "schedule": "5/2, 09:00–18:00", "salary_from": 250000, "salary_to": 320000,
        "office_address": "пр. Абая, 10"})).json()
    c = (await admin.post("/api/candidates", json={"full_name": "Ахметова Айгуль", "phone": "+77771234567", "city": "Алматы"})).json()
    scenarios = {}
    for key in ("offer", "screening", "reserve_revival", "reminder"):
        scenarios[key] = (await admin.post("/api/scenarios/from-library", json={"key": key})).json()
    return {"v": v, "c": c, "s": scenarios}


def phone(wa_mock):
    return wa_mock.chats[WA]["messages"]


def last_buttons(wa_mock):
    m = [x for x in phone(wa_mock) if x["dir"] == "out" and (x.get("buttons") or x.get("rows"))][-1]
    return m.get("buttons") or m.get("rows")


async def tap(client, wa_mock, title):
    b = next(x for x in last_buttons(wa_mock) if x["title"] == title)
    if b.get("quick"):
        return await post_webhook(client, quick_reply(WA, title))
    if "description" in b or ":vac:" in b["id"]:
        return await post_webhook(client, list_reply(WA, b["id"], title))
    return await post_webhook(client, button_reply(WA, b["id"], title))


async def state(client, cid):
    return (await client.get(f"/api/candidates/{cid}/conversation")).json()


async def test_offer_happy_path_kazakh(admin, wa_mock, setup, db):
    c, v, s = setup["c"], setup["v"], setup["s"]
    r = await admin.post(f"/api/candidates/{c['id']}/scenario", json={"scenario_id": s["offer"]["id"], "vacancy_id": v["id"]})
    assert r.status_code == 200, r.text
    assert phone(wa_mock)[-1]["text"].startswith("Здравствуйте! Сәлеметсіз бе!")  # шаблон выбора языка
    await tap(admin, wa_mock, "Қазақша")
    assert phone(wa_mock)[-1]["text"].startswith("Сәлеметсіз бе, Айгуль! Сізді «Операционист» бос орнына шақырамыз, қала: Алматы")
    await tap(admin, wa_mock, "Иә, қызық")
    out = [m for m in phone(wa_mock) if m["dir"] == "out"]
    assert "«Операционист» бос орны туралы қысқаша" in out[-2]["text"] and "250 000–320 000 ₸" in out[-2]["text"]
    assert out[-1]["text"].startswith("Кеңсе мекенжайы: пр. Абая, 10")  # порядок сохранён: детали → вопрос
    for title in ("Иә", "Иә", "1 жылдан көп", "Бір апта ішінде"):
        await tap(admin, wa_mock, title)
    assert "сіз бізге сәйкессіз" in phone(wa_mock)[-1]["text"]
    st = await state(admin, c["id"])
    assert st["scenario"]["outcome"] == "handoff" and st["scenario"]["reason"] == "запись на собеседование"
    assert st["conversation"]["mode"] == "human"
    assert st["scenario"]["answers"] == {"interested": "Иә, қызық", "city_ok": "Иә", "schedule_ok": "Иә",
                                         "experience": "1 жылдан көп", "start": "Бір апта ішінде"}
    app = (await db.execute(select(Application))).scalar_one()
    assert app.screening_result == "fit" and app.status == "replied"
    assert app.screening_answers["experience"]["answer"] == "1 жылдан көп"
    assert (await db.execute(select(Candidate.language))).scalar_one() == "kk"


async def test_offer_unfit_goes_to_reserve(admin, wa_mock, setup, db):
    c, v, s = setup["c"], setup["v"], setup["s"]
    await admin.patch(f"/api/candidates/{c['id']}", json={"language": "ru"})
    await admin.post(f"/api/candidates/{c['id']}/scenario", json={"scenario_id": s["offer"]["id"], "vacancy_id": v["id"]})
    assert phone(wa_mock)[-1]["text"].startswith("Здравствуйте, Айгуль! Приглашаем")  # язык известен — сразу оффер
    await tap(admin, wa_mock, "Да, интересно")
    for title in ("Нет", "Да", "Нет опыта", "В течение недели"):
        await tap(admin, wa_mock, title)
    assert "сейчас эта вакансия вам не подходит" in phone(wa_mock)[-1]["text"]
    await tap(admin, wa_mock, "Да, сообщайте")
    assert phone(wa_mock)[-1]["text"].startswith("Спасибо! Хорошего дня")
    st = await state(admin, c["id"])
    assert st["scenario"]["outcome"] == "completed"
    assert (await db.execute(select(Application.screening_result))).scalar_one() == "unfit"
    assert (await db.execute(select(Candidate.is_reserve))).scalar_one() is True


async def test_offer_declined_and_review(admin, wa_mock, setup, db):
    c, v, s = setup["c"], setup["v"], setup["s"]
    await admin.patch(f"/api/candidates/{c['id']}", json={"language": "ru"})
    await admin.post(f"/api/candidates/{c['id']}/scenario", json={"scenario_id": s["offer"]["id"], "vacancy_id": v["id"]})
    await tap(admin, wa_mock, "Нет, спасибо")
    assert phone(wa_mock)[-1]["text"].startswith("Понимаем! Можно сообщать")
    await tap(admin, wa_mock, "Нет")
    assert (await state(admin, c["id"]))["scenario"]["outcome"] == "completed"
    assert (await db.execute(select(Candidate.is_reserve))).scalar_one() is False
    # второй запуск: ответ «Позже» → на ревью
    await admin.post(f"/api/candidates/{c['id']}/scenario", json={"scenario_id": s["screening"]["id"], "vacancy_id": v["id"]})
    for title in ("Да", "Да", "До 1 года", "Позже"):
        await tap(admin, wa_mock, title)
    assert "Рекрутер изучит" in phone(wa_mock)[-1]["text"]
    assert (await db.execute(select(Application.screening_result))).scalar_one() == "review"


async def test_text_answers_and_reprompt_then_handoff(admin, wa_mock, setup):
    c, v, s = setup["c"], setup["v"], setup["s"]
    await admin.patch(f"/api/candidates/{c['id']}", json={"language": "ru"})
    await admin.post(f"/api/candidates/{c['id']}/scenario", json={"scenario_id": s["offer"]["id"], "vacancy_id": v["id"]})
    await post_webhook(admin, text_msg(WA, "да, интересно"))  # текст вместо кнопки, совпадает с подписью
    assert phone(wa_mock)[-1]["text"].startswith("Офис находится")
    await post_webhook(admin, text_msg(WA, "а сколько платят?"))
    assert phone(wa_mock)[-1]["text"] == "Пожалуйста, выберите один из вариантов 👇"
    assert [b["title"] for b in last_buttons(wa_mock)] == ["Да", "Нет"]
    await post_webhook(admin, text_msg(WA, "не понимаю"))
    await post_webhook(admin, text_msg(WA, "???"))
    assert "Рекрутер свяжется" in phone(wa_mock)[-1]["text"]
    st = await state(admin, c["id"])
    assert st["scenario"]["outcome"] == "handoff" and st["conversation"]["mode"] == "human"


async def test_screening_needs_open_window(admin, setup):
    c, v, s = setup["c"], setup["v"], setup["s"]
    await admin.patch(f"/api/candidates/{c['id']}", json={"language": "ru"})
    r = await admin.post(f"/api/candidates/{c['id']}/scenario", json={"scenario_id": s["screening"]["id"], "vacancy_id": v["id"]})
    assert r.status_code == 409 and "24-часовое окно" in r.json()["detail"]
    r = await admin.post(f"/api/candidates/{c['id']}/scenario", json={"scenario_id": s["offer"]["id"]})
    assert r.status_code == 422  # нужна вакансия
    r = await admin.post(f"/api/candidates/{c['id']}/scenario", json={"scenario_id": s["reminder"]["id"]})
    assert r.status_code == 422


async def test_reserve_revival_vacancy_choice(admin, wa_mock, setup, db):
    c, v, s = setup["c"], setup["v"], setup["s"]
    await admin.post("/api/vacancies", json={"title": "Оператор колл-центра", "city": "Алматы"})
    await admin.post("/api/vacancies", json={"title": "Кассир", "city": "Астана"})  # другой город — не показываем
    await admin.patch(f"/api/candidates/{c['id']}", json={"language": "ru", "is_reserve": True})
    await admin.post(f"/api/candidates/{c['id']}/scenario", json={"scenario_id": s["reserve_revival"]["id"]})
    await tap(admin, wa_mock, "Да")
    assert [r["title"] for r in last_buttons(wa_mock)] == ["Оператор колл-центра", "Операционист"]  # по алфавиту
    await tap(admin, wa_mock, "Оператор колл-центра")
    assert "Коротко о вакансии «Оператор колл-центра»" in [m for m in phone(wa_mock) if m["dir"] == "out"][-2]["text"]
    apps = (await db.execute(select(Application))).scalars().all()
    assert len(apps) == 1 and apps[0].status == "in_campaign"


async def test_recruiter_takeover_pauses_bot(admin, wa_mock, setup):
    c, v, s = setup["c"], setup["v"], setup["s"]
    await admin.patch(f"/api/candidates/{c['id']}", json={"language": "ru"})
    await admin.post(f"/api/candidates/{c['id']}/scenario", json={"scenario_id": s["offer"]["id"], "vacancy_id": v["id"]})
    await tap(admin, wa_mock, "Да, интересно")
    await admin.post(f"/api/candidates/{c['id']}/messages", json={"kind": "text", "text": "Добрый день! Я рекрутер Айгерим."})
    n = len(phone(wa_mock))
    await tap(admin, wa_mock, "Да")  # бот на паузе — не отвечает
    assert len(phone(wa_mock)) == n  # бот ничего не отправил
    await admin.post(f"/api/candidates/{c['id']}/bot")
    await post_webhook(admin, text_msg(WA, "да"))  # следующий ответ — бот продолжает с текущего шага
    assert phone(wa_mock)[-1]["text"].startswith("График работы")  # ответ во время паузы не засчитан


async def test_stop_and_restart_rules(admin, wa_mock, setup):
    c, v, s = setup["c"], setup["v"], setup["s"]
    await admin.patch(f"/api/candidates/{c['id']}", json={"language": "ru"})
    body = {"scenario_id": s["offer"]["id"], "vacancy_id": v["id"]}
    await admin.post(f"/api/candidates/{c['id']}/scenario", json=body)
    assert (await admin.post(f"/api/candidates/{c['id']}/scenario", json=body)).status_code == 409  # уже идёт
    assert (await admin.delete(f"/api/candidates/{c['id']}/scenario")).status_code == 200
    assert (await state(admin, c["id"]))["scenario"]["outcome"] == "stopped"
    await admin.post(f"/api/candidates/{c['id']}/scenario", json=body)
    await post_webhook(admin, text_msg(WA, "СТОП"))
    st = await state(admin, c["id"])
    assert st["scenario"]["outcome"] == "unsubscribed" and st["unsubscribed"] is True


async def test_timeout_no_reply(admin, wa_mock, setup, db):
    c, v, s = setup["c"], setup["v"], setup["s"]
    await admin.patch("/api/settings", json={"working_hours": {"start": "00:00", "end": "23:59", "days": [1, 2, 3, 4, 5, 6, 7]}})
    await admin.patch(f"/api/candidates/{c['id']}", json={"language": "ru"})
    await admin.post(f"/api/candidates/{c['id']}/scenario", json={"scenario_id": s["offer"]["id"], "vacancy_id": v["id"]})
    conv = (await db.execute(select(Conversation))).scalar_one()
    step = conv.context["step"]
    await scenario_timeout({"inline": True}, conv.id, step + 99)  # устаревший шаг — ничего не делает
    assert (await state(admin, c["id"]))["scenario"]["outcome"] is None
    await scenario_timeout({"inline": True}, conv.id, step)
    st = await state(admin, c["id"])
    assert st["scenario"]["outcome"] == "no_reply" and st["scenario"]["current_node"] is None


async def test_scenario_crud_and_roles(admin, recruiter):
    lib = (await admin.get("/api/scenarios/library")).json()
    graph = lib[0]["graph"]
    assert (await recruiter.post("/api/scenarios", json={"name": "x", "graph": graph})).status_code == 403
    r = await admin.post("/api/scenarios", json={"name": "Мой", "graph": graph})
    assert r.status_code == 201 and r.json()["version"] == 1
    sid = r.json()["id"]
    bad = {**graph, "start": "nope"}
    r = await admin.put(f"/api/scenarios/{sid}", json={"name": "Мой", "graph": bad})
    assert r.status_code == 422 and r.json()["detail"]["errors"]
    graph["nodes"]["bye"]["text"]["ru"] = "Пока!"
    r = await admin.put(f"/api/scenarios/{sid}", json={"name": "Мой", "graph": graph})
    assert r.json()["version"] == 2
    v = (await recruiter.post("/api/scenarios/validate", json=graph)).json()
    assert v["ok"] is False and any("не найден среди одобренных" in e for e in v["errors"])  # шаблоны не синхронизированы
    assert (await admin.delete(f"/api/scenarios/{sid}")).status_code == 204
