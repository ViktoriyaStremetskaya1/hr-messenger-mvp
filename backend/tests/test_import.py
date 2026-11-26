import io
import json

from openpyxl import Workbook


def xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


ROWS = [
    ["ФИО", "Телефон", "Город", "Вакансия", "Источник"],
    ["Ахметова Айгуль", "+7 777 123 45 67", "Алматы", "Операционист", "hh.kz"],
    ["Сериков Арман", "8 (701) 555-11-22", "Астана", "операционист", ""],
    ["Дубль Айгуль", "87771234567", "Алматы", "Операционист", "hh.kz"],  # дубль по телефону
    ["Без телефона", "", "Алматы", "", ""],
    ["Городской", "+7 727 123 45 67", "Алматы", "", ""],
    ["Нет вакансии", 77051234567, "Шымкент", "Бариста", "Instagram"],
    ["", "87071234567", "", "", ""],
]
FILES = {"file": ("база.xlsx", xlsx(ROWS), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}


async def test_preview_guesses_mapping(recruiter):
    r = await recruiter.post("/api/candidates/import/preview", files=FILES)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["mapping"] == {"full_name": "ФИО", "phone": "Телефон", "city": "Город", "vacancy": "Вакансия", "source": "Источник"}
    assert p["total_rows"] == 7


async def test_import_full_flow(recruiter):
    v_alm = (await recruiter.post("/api/vacancies", json={"title": "Операционист", "city": "Алматы"})).json()
    v_ast = (await recruiter.post("/api/vacancies", json={"title": "Операционист", "city": "Астана"})).json()
    tag = (await recruiter.post("/api/tags", json={"name": "Импорт ноябрь"})).json()
    # кандидат уже есть в базе, без города
    await recruiter.post("/api/candidates", json={"full_name": "Сериков Арман", "phone": "87015551122"})

    preview = (await recruiter.post("/api/candidates/import/preview", files=FILES)).json()
    opts = {"mapping": preview["mapping"], "tag_ids": [tag["id"]], "default_source": "Excel"}
    r = await recruiter.post("/api/candidates/import", files=FILES, data={"options": json.dumps(opts)})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["created"] == 2  # Ахметова, «Нет вакансии»
    assert res["updated"] == 1  # Сериков
    assert res["duplicates_in_file"] == 1
    assert {e["line"] for e in res["errors"]} == {5, 6, 8}
    assert res["unmatched_vacancies"] == ["Бариста"]

    items = {c["full_name"]: c for c in (await recruiter.get("/api/candidates")).json()["items"]}
    assert items["Ахметова Айгуль"]["applications"][0]["vacancy"]["id"] == v_alm["id"]
    assert items["Сериков Арман"]["applications"][0]["vacancy"]["id"] == v_ast["id"]  # по городу
    assert items["Сериков Арман"]["city"] == "Астана"  # дозаполнено
    assert items["Нет вакансии"]["desired_position"] == "Бариста"
    assert items["Нет вакансии"]["source"] == "Instagram"
    assert items["Ахметова Айгуль"]["tags"][0]["name"] == "Импорт ноябрь"

    # повторный импорт того же файла ничего не дублирует
    r = await recruiter.post("/api/candidates/import", files=FILES, data={"options": json.dumps(opts)})
    assert r.json()["created"] == 0 and r.json()["updated"] == 3
    assert (await recruiter.get("/api/candidates")).json()["total"] == 3


async def test_import_csv_cp1251_semicolon(recruiter):
    csv_bytes = "ФИО;Телефон;Город\nКим Дана;+77751234567;Алматы\n".encode("cp1251")
    files = {"file": ("база.csv", csv_bytes, "text/csv")}
    p = (await recruiter.post("/api/candidates/import/preview", files=files)).json()
    assert p["headers"] == ["ФИО", "Телефон", "Город"]
    r = await recruiter.post("/api/candidates/import", files=files,
                             data={"options": json.dumps({"mapping": p["mapping"], "mark_reserve": True})})
    assert r.json()["created"] == 1
    c = (await recruiter.get("/api/candidates")).json()["items"][0]
    assert c["is_reserve"] is True and c["full_name"] == "Ким Дана"


async def test_import_rejects_bad_files(recruiter):
    r = await recruiter.post("/api/candidates/import/preview", files={"file": ("x.pdf", b"%PDF", "application/pdf")})
    assert r.status_code == 422
    r = await recruiter.post("/api/candidates/import", files=FILES,
                             data={"options": json.dumps({"mapping": {"full_name": "ФИО"}})})
    assert r.status_code == 422
