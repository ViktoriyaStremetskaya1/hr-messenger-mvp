"""Импорт кандидатов из Excel/CSV.

Файл не хранится на сервере: предпросмотр и импорт — два независимых запроса с одним и тем же файлом.
"""
import csv
import io
from dataclasses import dataclass, field

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.models import Application, Candidate, ImportJob, Tag, Vacancy
from app.services.phone import PhoneError, normalize_phone

MAX_ROWS = 20000
FIELDS = ("full_name", "phone", "city", "vacancy", "source")

_SYNONYMS = {
    "full_name": ("фио", "ф.и.о", "ф.и.о.", "имя", "кандидат", "full name", "fullname", "name", "фамилия имя"),
    "phone": ("телефон", "тел", "тел.", "номер", "номер телефона", "мобильный", "phone", "whatsapp"),
    "city": ("город", "city", "населенный пункт", "населённый пункт"),
    "vacancy": ("вакансия", "должность", "позиция", "vacancy", "position"),
    "source": ("источник", "source", "канал", "откуда"),
}


class ImportFileError(ValueError):
    pass


def _cell(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def parse_file(file_name: str, content: bytes) -> tuple[list[str], list[list[str]]]:
    name = file_name.lower()
    if name.endswith((".xlsx", ".xlsm")):
        try:
            wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception as e:  # noqa: BLE001
            raise ImportFileError("Не удалось прочитать Excel-файл") from e
        ws = wb.worksheets[0]
        rows = [[_cell(c) for c in r] for r in ws.iter_rows(values_only=True)]
        wb.close()
    elif name.endswith((".csv", ".txt")):
        text = None
        for enc in ("utf-8-sig", "cp1251"):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise ImportFileError("Неизвестная кодировка CSV (ожидается UTF-8 или Windows-1251)")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t")
        except csv.Error:
            dialect = csv.excel
            dialect.delimiter = ";" if text.count(";") > text.count(",") else ","
        rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), dialect)]
    else:
        raise ImportFileError("Поддерживаются файлы .xlsx и .csv")

    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        raise ImportFileError("Файл пуст")
    headers = [h or f"Колонка {i + 1}" for i, h in enumerate(rows[0])]
    data = rows[1:]
    if len(data) > MAX_ROWS:
        raise ImportFileError(f"Слишком много строк: {len(data)} (максимум {MAX_ROWS})")
    width = len(headers)
    data = [(r + [""] * width)[:width] for r in data]
    return headers, data


def guess_mapping(headers: list[str]) -> dict[str, str | None]:
    mapping: dict[str, str | None] = {f: None for f in FIELDS}
    norm = {h: h.strip().lower() for h in headers}
    for f, syns in _SYNONYMS.items():
        for h, n in norm.items():
            if n in syns or any(n.startswith(s) for s in syns if len(s) > 3):
                if h not in mapping.values():
                    mapping[f] = h
                    break
    return mapping


def mask_phone(normalized: str) -> str:
    return f"+7 *** *** {normalized[-4:-2]} {normalized[-2:]}"


@dataclass
class _Row:
    line: int
    full_name: str
    phone: str
    city: str | None
    vacancy: str | None
    source: str | None


@dataclass
class ImportStats:
    total: int = 0
    created: int = 0
    updated: int = 0
    duplicates_in_file: int = 0
    errors: list[dict] = field(default_factory=list)
    unmatched_vacancies: set[str] = field(default_factory=set)


async def run_import(
    db: AsyncSession,
    *,
    file_name: str,
    headers: list[str],
    rows: list[list[str]],
    mapping: dict[str, str | None],
    user_id: int,
    default_vacancy_id: int | None = None,
    default_source: str | None = None,
    mark_reserve: bool = False,
    tag_ids: list[int] | None = None,
) -> tuple[ImportJob, ImportStats]:
    if not mapping.get("phone") or not mapping.get("full_name"):
        raise ImportFileError("Нужно указать колонки «ФИО» и «Телефон»")
    idx = {}
    for f in FIELDS:
        h = mapping.get(f)
        if h:
            if h not in headers:
                raise ImportFileError(f"Колонка «{h}» не найдена в файле")
            idx[f] = headers.index(h)

    def get(r: list[str], f: str) -> str | None:
        i = idx.get(f)
        v = r[i].strip() if i is not None else ""
        return v or None

    stats = ImportStats(total=len(rows))
    parsed: dict[str, _Row] = {}
    for n, r in enumerate(rows, start=2):  # строка 1 — заголовки
        name = get(r, "full_name")
        raw_phone = get(r, "phone")
        if not name:
            stats.errors.append({"line": n, "error": "нет ФИО"})
            continue
        try:
            phone = normalize_phone(raw_phone)
        except PhoneError as e:
            stats.errors.append({"line": n, "error": f"телефон: {e}"})
            continue
        h = crypto.phone_hash(phone)
        if h in parsed:
            stats.duplicates_in_file += 1
            continue
        parsed[h] = _Row(n, name, phone, get(r, "city"), get(r, "vacancy"), get(r, "source") or default_source)

    # Вакансии: сопоставление по названию (без регистра), предпочтительно в том же городе
    vacancies = (await db.execute(select(Vacancy))).scalars().all()
    by_title: dict[str, list[Vacancy]] = {}
    for v in vacancies:
        by_title.setdefault(v.title.strip().lower(), []).append(v)

    def match_vacancy(title: str | None, city: str | None) -> int | None:
        if not title:
            return default_vacancy_id
        options = by_title.get(title.strip().lower())
        if not options:
            stats.unmatched_vacancies.add(title)
            return None
        if city:
            for v in options:
                if v.city.strip().lower() == city.strip().lower():
                    return v.id
        return options[0].id

    tags = []
    if tag_ids:
        tags = list((await db.execute(select(Tag).where(Tag.id.in_(tag_ids)))).scalars().all())

    existing: dict[str, Candidate] = {}
    hashes = list(parsed.keys())
    for i in range(0, len(hashes), 1000):
        chunk = hashes[i : i + 1000]
        res = await db.execute(select(Candidate).where(Candidate.phone_hash.in_(chunk)))
        for c in res.scalars().all():
            existing[c.phone_hash] = c

    for h, row in parsed.items():
        vacancy_id = match_vacancy(row.vacancy, row.city)
        cand = existing.get(h)
        if cand is None:
            cand = Candidate(
                full_name=row.full_name,
                phone_enc=crypto.encrypt(row.phone),
                phone_hash=h,
                phone_last4=row.phone[-4:],
                city=row.city,
                source=row.source,
                desired_position=row.vacancy if vacancy_id is None else None,
                is_reserve=mark_reserve,
                owner_id=user_id,
                tags=list(tags),
                applications=[],
            )
            db.add(cand)
            stats.created += 1
        else:
            # Дозаполняем пустые поля, ничего не затираем
            if not cand.city and row.city:
                cand.city = row.city
            if not cand.source and row.source:
                cand.source = row.source
            if vacancy_id is None and row.vacancy and not cand.desired_position:
                cand.desired_position = row.vacancy
            if mark_reserve:
                cand.is_reserve = True
            for t in tags:
                if t not in cand.tags:
                    cand.tags.append(t)
            stats.updated += 1
        if vacancy_id and all(a.vacancy_id != vacancy_id for a in cand.applications):
            cand.applications.append(Application(vacancy_id=vacancy_id, recruiter_id=user_id))

    job = ImportJob(
        file_name=file_name,
        created_by=user_id,
        stats={
            "total": stats.total,
            "created": stats.created,
            "updated": stats.updated,
            "duplicates_in_file": stats.duplicates_in_file,
            "errors": len(stats.errors),
            "unmatched_vacancies": sorted(stats.unmatched_vacancies),
        },
    )
    db.add(job)
    await db.flush()
    return job, stats
