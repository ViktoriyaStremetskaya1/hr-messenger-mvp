"""Тестовые данные для локальной разработки: python -m app.seed

Все ФИО и телефоны выдуманы.
"""
import asyncio
import os
import random

from sqlalchemy import select

from app.core import crypto
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import Application, Candidate, Tag, User, Vacancy

PASSWORD = os.environ.get("SEED_PASSWORD", "Passw0rd!")

USERS = [
    ("admin", "Администратор", "admin"),
    ("lead", "Руководитель подбора", "lead"),
    ("aigerim", "Айгерим Сапарова", "recruiter"),
    ("dana", "Дана Ким", "recruiter"),
    ("marat", "Марат Есенов", "recruiter"),
]

VACANCIES = [
    dict(title="Операционист", city="Алматы", schedule="5/2, 09:00–18:00", salary_from=250000, salary_to=320000,
         requirements="Среднее специальное или высшее образование, грамотная речь, ПК на уровне пользователя",
         office_address="г. Алматы, пр. Абая, 10, 3 этаж",
         faq=[{"q": "Есть ли обучение?", "a": "Да, оплачиваемое обучение 2 недели."}]),
    dict(title="Операционист", city="Астана", schedule="5/2, 09:00–18:00", salary_from=260000, salary_to=330000,
         requirements="Среднее специальное или высшее образование", office_address="г. Астана, ул. Кунаева, 12"),
    dict(title="Оператор колл-центра", city="Алматы", schedule="2/2, 08:00–20:00", salary_from=220000, salary_to=300000,
         requirements="Грамотная речь на русском, казахский — плюс", office_address="г. Алматы, ул. Сатпаева, 30"),
    dict(title="Оператор колл-центра", city="Шымкент", schedule="5/2 или 2/2", salary_from=200000, salary_to=260000,
         requirements="Грамотная речь", office_address="г. Шымкент, пр. Тауке хана, 5"),
    dict(title="Специалист Collection", city="Алматы", schedule="5/2, 09:00–18:00", salary_from=280000, salary_to=400000,
         requirements="Стрессоустойчивость, опыт продаж или взыскания — плюс", office_address="г. Алматы, пр. Абая, 10"),
]

FIRST = ["Айгуль", "Асель", "Нурлан", "Ерлан", "Дина", "Алия", "Бауыржан", "Мадина", "Арман", "Жанар", "Тимур",
         "Камила", "Данияр", "Сауле", "Ильяс", "Айдана", "Руслан", "Гульнара", "Санжар", "Индира"]
LAST = ["Ахметов", "Касымов", "Нурпеисов", "Жумабаев", "Сериков", "Омаров", "Абдрахманов", "Тулегенов", "Ким",
        "Иванов", "Бекова", "Мусина", "Исаев", "Садыков", "Алиева"]
CITIES = ["Алматы", "Астана", "Шымкент"]
SOURCES = ["hh.kz", "Instagram", "Рекомендация", "Ярмарка вакансий", "Сайт банка"]
PREFIXES = ["701", "702", "705", "707", "747", "771", "775", "777", "778"]


async def main() -> None:
    random.seed(42)
    async with SessionLocal() as db:
        if (await db.execute(select(User).limit(1))).scalar_one_or_none():
            print("Данные уже есть — пропускаю сиды")
            return
        users = [User(login=l, full_name=n, role=r, password_hash=hash_password(PASSWORD)) for l, n, r in USERS]
        db.add_all(users)
        await db.flush()
        recruiters = [u for u in users if u.role == "recruiter"]

        vacancies = [Vacancy(**v, owner_id=users[1].id) for v in VACANCIES]
        db.add_all(vacancies)
        tags = [Tag(name="Говорит на казахском", color="teal"), Tag(name="Студент", color="blue"),
                Tag(name="Был опыт в банке", color="green"), Tag(name="Перезвонить", color="orange")]
        db.add_all(tags)
        await db.flush()

        statuses = ["new"] * 6 + ["in_campaign"] * 4 + ["replied"] * 3 + ["booked"] * 2 + ["attended", "no_show", "offer", "hired"]
        for i in range(60):
            first, last = random.choice(FIRST), random.choice(LAST)
            if first.endswith(("а", "я", "ь")) and not last.endswith("а") and last not in ("Ким",):
                last += "а"
            phone = f"+7{random.choice(PREFIXES)}{random.randint(1000000, 9999999)}"
            city = random.choice(CITIES)
            rec = random.choice(recruiters)
            c = Candidate(
                full_name=f"{last} {first}", phone_enc=crypto.encrypt(phone), phone_hash=crypto.phone_hash(phone),
                phone_last4=phone[-4:], city=city, source=random.choice(SOURCES), is_reserve=i % 7 == 0,
                language=random.choice(["ru", "ru", "kk", None]), owner_id=rec.id,
                tags=random.sample(tags, k=random.choice([0, 0, 1, 2])), applications=[],
            )
            matching = [v for v in vacancies if v.city == city]
            if matching and i % 7 != 0:
                v = random.choice(matching)
                st = random.choice(statuses)
                c.applications.append(Application(
                    vacancy_id=v.id, status=st, recruiter_id=rec.id,
                    screening_result=random.choice(["fit", "fit", "review", "unfit"]) if st not in ("new", "in_campaign") else None,
                ))
            db.add(c)
        await db.commit()
        print(f"Создано: {len(users)} пользователей, {len(vacancies)} вакансий, 60 кандидатов. Пароль: {PASSWORD}")


if __name__ == "__main__":
    asyncio.run(main())
