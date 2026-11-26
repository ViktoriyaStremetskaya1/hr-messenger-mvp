from sqlalchemy import select

from app.models import Candidate


async def _vac(c, title="Операционист", city="Алматы"):
    return (await c.post("/api/vacancies", json={"title": title, "city": city})).json()


async def test_create_encrypts_and_dedups(recruiter, db):
    r = await recruiter.post("/api/candidates", json={"full_name": "Ахметова Айгуль", "phone": "+7 777 123 45 67", "city": "Алматы"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["phone_masked"] == "+7 *** *** 45 67"
    assert body["status"] == "new"
    assert "phone" not in body and "phone_enc" not in body
    row = (await db.execute(select(Candidate))).scalar_one()
    assert "7771234567" not in row.phone_enc
    # тот же номер в другом формате — дубль
    r = await recruiter.post("/api/candidates", json={"full_name": "Другая", "phone": "87771234567"})
    assert r.status_code == 409
    assert r.json()["detail"]["candidate_id"] == body["id"]


async def test_reveal_phone_is_audited(recruiter, admin):
    cid = (await recruiter.post("/api/candidates", json={"full_name": "А", "phone": "87011112233"})).json()["id"]
    assert (await recruiter.get(f"/api/candidates/{cid}/phone")).json()["phone"] == "+77011112233"
    log = (await admin.get("/api/audit", params={"action": "candidate.phone_reveal"})).json()
    assert log["total"] == 1 and log["items"][0]["entity_id"] == str(cid)


async def test_filters_and_search(recruiter):
    v1 = await _vac(recruiter)
    v2 = await _vac(recruiter, "Оператор колл-центра")
    tag = (await recruiter.post("/api/tags", json={"name": "Студент"})).json()
    a = (await recruiter.post("/api/candidates", json={"full_name": "Касымов Нурлан", "phone": "87770000001", "city": "Алматы", "vacancy_id": v1["id"], "tag_ids": [tag["id"]]})).json()
    b = (await recruiter.post("/api/candidates", json={"full_name": "Омарова Дина", "phone": "87770000002", "city": "Астана", "vacancy_id": v2["id"], "is_reserve": True})).json()
    await recruiter.post("/api/candidates", json={"full_name": "Без вакансии", "phone": "87770000003"})

    async def ids(**params):
        return {c["id"] for c in (await recruiter.get("/api/candidates", params=params)).json()["items"]}

    assert await ids(q="касымов") == {a["id"]}
    assert await ids(q="+7 777 000 00 02") == {b["id"]}
    assert await ids(q="0002") == {b["id"]}
    assert await ids(city="Астана") == {b["id"]}
    assert await ids(vacancy_id=v1["id"]) == {a["id"]}
    assert await ids(is_reserve=True) == {b["id"]}
    assert await ids(tag_id=tag["id"]) == {a["id"]}
    assert len(await ids(status="new")) == 3

    app_id = a["applications"][0]["id"]
    r = await recruiter.patch(f"/api/candidates/applications/{app_id}", json={"status": "booked", "screening_result": "fit"})
    assert r.status_code == 200 and r.json()["status"] == "booked"
    assert await ids(status="booked") == {a["id"]}
    assert await ids(screening_result="fit") == {a["id"]}
    assert a["id"] not in await ids(status="new")
    assert (await recruiter.get(f"/api/candidates/{a['id']}")).json()["status"] == "booked"


async def test_update_and_bulk(recruiter):
    v = await _vac(recruiter)
    tag = (await recruiter.post("/api/tags", json={"name": "Перезвонить"})).json()
    ids = [(await recruiter.post("/api/candidates", json={"full_name": f"К{i}", "phone": f"8777000001{i}"})).json()["id"] for i in range(3)]
    r = await recruiter.patch(f"/api/candidates/{ids[0]}", json={"city": "Шымкент", "tag_ids": [tag["id"]], "language": "kk"})
    assert r.json()["city"] == "Шымкент" and r.json()["tags"][0]["name"] == "Перезвонить"
    assert (await recruiter.post("/api/candidates/bulk", json={"candidate_ids": ids, "action": "add_tag", "tag_id": tag["id"]})).json()["affected"] == 2
    assert (await recruiter.post("/api/candidates/bulk", json={"candidate_ids": ids, "action": "set_reserve"})).json()["affected"] == 3
    assert (await recruiter.post("/api/candidates/bulk", json={"candidate_ids": ids, "action": "assign_vacancy", "vacancy_id": v["id"]})).json()["affected"] == 3
    assert (await recruiter.post("/api/candidates/bulk", json={"candidate_ids": ids, "action": "assign_vacancy", "vacancy_id": v["id"]})).json()["affected"] == 0
    r = await recruiter.post(f"/api/candidates/{ids[0]}/applications", json={"vacancy_id": v["id"]})
    assert r.status_code == 409


async def test_requires_auth(anon):
    assert (await anon.get("/api/candidates")).status_code == 401
