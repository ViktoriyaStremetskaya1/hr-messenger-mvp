VAC = {
    "title": "Операционист", "city": "Алматы", "schedule": "5/2", "salary_from": 250000, "salary_to": 320000,
    "requirements": "Грамотная речь", "office_address": "пр. Абая, 10",
    "faq": [{"q": "Есть обучение?", "a": "Да, 2 недели"}],
}


async def test_vacancy_crud(recruiter, lead):
    r = await recruiter.post("/api/vacancies", json=VAC)
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["faq"][0]["a"] == "Да, 2 недели"
    r = await recruiter.put(f"/api/vacancies/{v['id']}", json={**VAC, "salary_to": 350000, "is_active": False})
    assert r.json()["salary_to"] == 350000 and r.json()["is_active"] is False
    assert len((await recruiter.get("/api/vacancies", params={"active": True})).json()) == 0
    assert len((await recruiter.get("/api/vacancies", params={"city": "алматы"})).json()) == 1
    assert (await recruiter.delete(f"/api/vacancies/{v['id']}")).status_code == 403
    assert (await lead.delete(f"/api/vacancies/{v['id']}")).status_code == 204


async def test_vacancy_salary_validation(recruiter):
    r = await recruiter.post("/api/vacancies", json={**VAC, "salary_from": 500000, "salary_to": 100000})
    assert r.status_code == 422


async def test_cannot_delete_vacancy_with_candidates(recruiter, lead):
    v = (await recruiter.post("/api/vacancies", json=VAC)).json()
    await recruiter.post("/api/candidates", json={"full_name": "Тест", "phone": "87771234567", "vacancy_id": v["id"]})
    assert (await lead.delete(f"/api/vacancies/{v['id']}")).status_code == 409
    assert (await recruiter.get(f"/api/vacancies/{v['id']}")).json()["candidates_count"] == 1
