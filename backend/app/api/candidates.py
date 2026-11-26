import json
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.core.db import get_session
from app.core.deps import client_ip, get_current_user
from app.models import Application, ApplicationStatus, Candidate, Tag, User, Vacancy, candidate_tags
from app.schemas.candidates import (
    ApplicationIn,
    ApplicationOut,
    ApplicationUpdate,
    BulkAction,
    CandidateCreate,
    CandidateOut,
    CandidateUpdate,
    ImportCommit,
    ImportPreview,
    ImportResult,
)
from app.schemas.common import Page
from app.services import importer
from app.services.audit import changes, log_action
from app.services.phone import PhoneError, normalize_phone

router = APIRouter(prefix="/candidates", tags=["candidates"])

MAX_UPLOAD = 10 * 1024 * 1024


def to_out(c: Candidate) -> CandidateOut:
    apps = sorted(c.applications, key=lambda a: a.updated_at or a.created_at, reverse=True)
    return CandidateOut.model_validate(
        {
            **{k: getattr(c, k) for k in (
                "id", "full_name", "city", "source", "desired_position", "language", "notes", "is_reserve",
                "unsubscribed_at", "last_touch_at", "owner_id", "created_at", "tags",
            )},
            "phone_masked": f"+7 *** *** {c.phone_last4[:2]} {c.phone_last4[2:]}",
            "applications": apps,
            "status": apps[0].status if apps else ApplicationStatus.new,
        }
    )


async def _load(db: AsyncSession, candidate_id: int) -> Candidate:
    c = await db.get(Candidate, candidate_id, populate_existing=True)
    if not c or c.anonymized_at:
        raise HTTPException(404, "Кандидат не найден")
    return c


async def _tags(db: AsyncSession, ids: list[int]) -> list[Tag]:
    if not ids:
        return []
    return list((await db.execute(select(Tag).where(Tag.id.in_(ids)))).scalars().all())


@router.get("", response_model=Page[CandidateOut])
async def list_candidates(
    q: str | None = None,
    city: str | None = None,
    vacancy_id: int | None = None,
    status: ApplicationStatus | None = None,
    screening_result: str | None = None,
    is_reserve: bool | None = None,
    unsubscribed: bool | None = None,
    tag_id: list[int] | None = Query(default=None),
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    page_size = min(max(page_size, 1), 200)
    stmt = select(Candidate).where(Candidate.anonymized_at.is_(None))
    if q:
        q = q.strip()
        conds = [Candidate.full_name.ilike(f"%{q}%")]
        digits = re.sub(r"\D", "", q)
        if len(digits) >= 10:
            try:
                conds.append(Candidate.phone_hash == crypto.phone_hash(normalize_phone(q)))
            except PhoneError:
                pass
        elif len(digits) == 4:
            conds.append(Candidate.phone_last4 == digits)
        stmt = stmt.where(or_(*conds))
    if city:
        stmt = stmt.where(func.lower(Candidate.city) == city.lower())
    if is_reserve is not None:
        stmt = stmt.where(Candidate.is_reserve == is_reserve)
    if unsubscribed is not None:
        stmt = stmt.where(Candidate.unsubscribed_at.isnot(None) if unsubscribed else Candidate.unsubscribed_at.is_(None))
    app_conds = [Application.candidate_id == Candidate.id]
    if vacancy_id:
        app_conds.append(Application.vacancy_id == vacancy_id)
    if status:
        app_conds.append(Application.status == status)
    if screening_result:
        app_conds.append(Application.screening_result == screening_result)
    if len(app_conds) > 1:
        if status == ApplicationStatus.new and not vacancy_id and not screening_result:
            # «новый» — либо есть заявка в статусе new, либо заявок нет вовсе
            stmt = stmt.where(or_(exists().where(and_(*app_conds)),
                                  ~exists().where(Application.candidate_id == Candidate.id)))
        else:
            stmt = stmt.where(exists().where(and_(*app_conds)))
    for tid in tag_id or []:
        stmt = stmt.where(exists().where(and_(candidate_tags.c.candidate_id == Candidate.id, candidate_tags.c.tag_id == tid)))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await db.execute(stmt.order_by(Candidate.created_at.desc(), Candidate.id.desc())
                         .offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()
    return Page(items=[to_out(c) for c in rows], total=total, page=page, page_size=page_size)


@router.post("", response_model=CandidateOut, status_code=201)
async def create_candidate(
    data: CandidateCreate, request: Request, db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)
):
    try:
        phone = normalize_phone(data.phone)
    except PhoneError as e:
        raise HTTPException(422, f"Телефон: {e}") from e
    h = crypto.phone_hash(phone)
    dup = (await db.execute(select(Candidate.id).where(Candidate.phone_hash == h))).scalar_one_or_none()
    if dup:
        raise HTTPException(409, {"message": "Кандидат с таким телефоном уже есть", "candidate_id": dup})
    c = Candidate(
        full_name=data.full_name, phone_enc=crypto.encrypt(phone), phone_hash=h, phone_last4=phone[-4:],
        city=data.city, source=data.source, language=data.language, notes=data.notes,
        is_reserve=data.is_reserve, owner_id=user.id, tags=await _tags(db, data.tag_ids), applications=[],
    )
    if data.vacancy_id:
        if not await db.get(Vacancy, data.vacancy_id):
            raise HTTPException(422, "Вакансия не найдена")
        c.applications.append(Application(vacancy_id=data.vacancy_id, recruiter_id=user.id))
    db.add(c)
    await db.flush()
    await log_action(db, user_id=user.id, action="candidate.create", entity="candidate", entity_id=c.id, ip=client_ip(request))
    await db.commit()
    return to_out(await _load(db, c.id))


@router.get("/{candidate_id}", response_model=CandidateOut)
async def get_candidate(candidate_id: int, db: AsyncSession = Depends(get_session), _: User = Depends(get_current_user)):
    return to_out(await _load(db, candidate_id))


@router.get("/{candidate_id}/phone")
async def reveal_phone(
    candidate_id: int, request: Request, db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)
) -> dict[str, str]:
    """Показ полного номера — фиксируется в журнале действий."""
    c = await _load(db, candidate_id)
    await log_action(db, user_id=user.id, action="candidate.phone_reveal", entity="candidate", entity_id=c.id, ip=client_ip(request))
    await db.commit()
    return {"phone": crypto.decrypt(c.phone_enc)}


@router.patch("/{candidate_id}", response_model=CandidateOut)
async def update_candidate(
    candidate_id: int, data: CandidateUpdate, request: Request,
    db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user),
):
    c = await _load(db, candidate_id)
    payload = data.model_dump(exclude_unset=True)
    tag_ids = payload.pop("tag_ids", None)
    diff = changes(c, payload)
    if tag_ids is not None:
        old = sorted(t.id for t in c.tags)
        c.tags = await _tags(db, tag_ids)
        if old != sorted(tag_ids):
            diff["tags"] = [old, sorted(tag_ids)]
    await log_action(db, user_id=user.id, action="candidate.update", entity="candidate", entity_id=c.id, diff=diff, ip=client_ip(request))
    await db.commit()
    return to_out(await _load(db, c.id))


@router.post("/{candidate_id}/applications", response_model=CandidateOut, status_code=201)
async def add_application(
    candidate_id: int, data: ApplicationIn, request: Request,
    db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user),
):
    c = await _load(db, candidate_id)
    if not await db.get(Vacancy, data.vacancy_id):
        raise HTTPException(422, "Вакансия не найдена")
    if any(a.vacancy_id == data.vacancy_id for a in c.applications):
        raise HTTPException(409, "Кандидат уже привязан к этой вакансии")
    c.applications.append(Application(vacancy_id=data.vacancy_id, recruiter_id=user.id))
    await log_action(db, user_id=user.id, action="application.create", entity="candidate", entity_id=c.id,
                     diff={"vacancy_id": data.vacancy_id}, ip=client_ip(request))
    await db.commit()
    return to_out(await _load(db, c.id))


@router.patch("/applications/{application_id}", response_model=ApplicationOut)
async def update_application(
    application_id: int, data: ApplicationUpdate, request: Request,
    db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user),
):
    a = await db.get(Application, application_id)
    if not a:
        raise HTTPException(404, "Заявка не найдена")
    diff = changes(a, data.model_dump(exclude_unset=True, mode="json"))
    await log_action(db, user_id=user.id, action="application.update", entity="application", entity_id=a.id, diff=diff, ip=client_ip(request))
    await db.commit()
    await db.refresh(a)
    return a


@router.post("/bulk")
async def bulk_action(
    data: BulkAction, request: Request, db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)
) -> dict[str, int]:
    cands = (await db.execute(select(Candidate).where(Candidate.id.in_(data.candidate_ids)))).scalars().all()
    tag = None
    if data.action in ("add_tag", "remove_tag"):
        tag = await db.get(Tag, data.tag_id) if data.tag_id else None
        if not tag:
            raise HTTPException(422, "Тег не найден")
    if data.action == "assign_vacancy" and not (data.vacancy_id and await db.get(Vacancy, data.vacancy_id)):
        raise HTTPException(422, "Вакансия не найдена")
    affected = 0
    for c in cands:
        if data.action == "add_tag" and tag not in c.tags:
            c.tags.append(tag)
            affected += 1
        elif data.action == "remove_tag" and tag in c.tags:
            c.tags.remove(tag)
            affected += 1
        elif data.action in ("set_reserve", "unset_reserve"):
            val = data.action == "set_reserve"
            if c.is_reserve != val:
                c.is_reserve = val
                affected += 1
        elif data.action == "assign_vacancy" and all(a.vacancy_id != data.vacancy_id for a in c.applications):
            c.applications.append(Application(vacancy_id=data.vacancy_id, recruiter_id=user.id))
            affected += 1
    await log_action(db, user_id=user.id, action=f"candidate.bulk.{data.action}", entity="candidate",
                     diff={"ids": data.candidate_ids[:100], "count": len(cands), "tag_id": data.tag_id,
                           "vacancy_id": data.vacancy_id}, ip=client_ip(request))
    await db.commit()
    return {"affected": affected}


# ---------- Импорт ----------

async def _read_upload(file: UploadFile) -> tuple[list[str], list[list[str]]]:
    content = await file.read(MAX_UPLOAD + 1)
    if len(content) > MAX_UPLOAD:
        raise HTTPException(413, "Файл больше 10 МБ")
    try:
        return importer.parse_file(file.filename or "", content)
    except importer.ImportFileError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/import/preview", response_model=ImportPreview)
async def import_preview(file: UploadFile = File(...), _: User = Depends(get_current_user)):
    headers, rows = await _read_upload(file)
    return ImportPreview(
        file_name=file.filename or "", headers=headers, mapping=importer.guess_mapping(headers),
        sample=rows[:10], total_rows=len(rows),
    )


@router.post("/import", response_model=ImportResult)
async def import_commit(
    request: Request,
    file: UploadFile = File(...),
    options: str = Form(..., description="JSON: mapping, default_vacancy_id, default_source, mark_reserve, tag_ids"),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    try:
        opts = ImportCommit.model_validate(json.loads(options))
    except (ValueError, TypeError) as e:
        raise HTTPException(422, "Неверные параметры импорта") from e
    headers, rows = await _read_upload(file)
    try:
        job, stats = await importer.run_import(
            db, file_name=file.filename or "", headers=headers, rows=rows, mapping=opts.mapping, user_id=user.id,
            default_vacancy_id=opts.default_vacancy_id, default_source=opts.default_source,
            mark_reserve=opts.mark_reserve, tag_ids=opts.tag_ids,
        )
    except importer.ImportFileError as e:
        raise HTTPException(422, str(e)) from e
    await log_action(db, user_id=user.id, action="candidate.import", entity="import_job", entity_id=job.id,
                     diff=job.stats, ip=client_ip(request))
    await db.commit()
    return ImportResult(
        job_id=job.id, total=stats.total, created=stats.created, updated=stats.updated,
        duplicates_in_file=stats.duplicates_in_file, errors=stats.errors[:500],
        unmatched_vacancies=sorted(stats.unmatched_vacancies),
    )
