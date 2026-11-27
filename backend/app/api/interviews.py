from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.base import OutText
from app.core.db import get_session
from app.core.deps import client_ip, get_current_user
from app.models import Application, Candidate, Interview, InterviewSlot, Role, User, Vacancy
from app.services import interviews as svc
from app.services import messaging, policy
from app.services.audit import log_action

router = APIRouter(tags=["interviews"])


class SlotBulkIn(BaseModel):
    recruiter_id: int
    vacancy_id: int | None = None
    date: date
    start: str = Field(pattern=r"^\d{2}:\d{2}$")
    end: str = Field(pattern=r"^\d{2}:\d{2}$")
    duration_min: int = Field(ge=10, le=480)
    capacity: int = Field(default=1, ge=1, le=100)
    office_address: str | None = None


class SlotPatch(BaseModel):
    capacity: int | None = Field(default=None, ge=1, le=100)
    is_active: bool | None = None
    office_address: str | None = None


class Booking(BaseModel):
    interview_id: int
    candidate_id: int
    candidate_name: str
    status: str
    confirmed_at: datetime | None


class SlotOut(BaseModel):
    id: int
    recruiter_id: int
    recruiter_name: str
    vacancy_id: int | None
    vacancy_title: str | None
    starts_at: datetime
    ends_at: datetime
    capacity: int
    office_address: str | None
    is_active: bool
    booked: int
    bookings: list[Booking] = []


class InterviewIn(BaseModel):
    slot_id: int
    vacancy_id: int | None = None
    notify: bool = False


class InterviewPatch(BaseModel):
    status: Literal["attended", "no_show", "cancelled"]
    reason: str | None = Field(default=None, max_length=255)


class InterviewOut(BaseModel):
    id: int
    slot_id: int
    candidate_id: int
    candidate_name: str
    starts_at: datetime
    ends_at: datetime
    address: str
    recruiter_name: str
    vacancy_title: str | None
    status: str
    booked_via: str
    confirmed_at: datetime | None
    reminded_24h_at: datetime | None
    reminded_2h_at: datetime | None


def _hm(s: str) -> time:
    h, m = map(int, s.split(":"))
    if not (0 <= h < 24 and 0 <= m < 60):
        raise HTTPException(422, "Неверное время")
    return time(h, m)


async def _names(db: AsyncSession) -> dict[int, str]:
    return {u.id: u.full_name for u in (await db.execute(select(User))).scalars().all()}


async def _slot_out(db: AsyncSession, s: InterviewSlot, names: dict[int, str], vac_titles: dict[int, str]) -> SlotOut:
    rows = (await db.execute(select(Interview, Candidate.full_name).join(Candidate, Candidate.id == Interview.candidate_id)
                             .where(Interview.slot_id == s.id, Interview.status.in_(svc.ACTIVE)).order_by(Interview.id))).all()
    return SlotOut(id=s.id, recruiter_id=s.recruiter_id, recruiter_name=names.get(s.recruiter_id, "—"), vacancy_id=s.vacancy_id,
                   vacancy_title=vac_titles.get(s.vacancy_id or 0), starts_at=s.starts_at, ends_at=s.ends_at, capacity=s.capacity,
                   office_address=s.office_address, is_active=s.is_active, booked=len(rows),
                   bookings=[Booking(interview_id=iv.id, candidate_id=iv.candidate_id, candidate_name=n, status=iv.status,
                                     confirmed_at=iv.confirmed_at) for iv, n in rows])


async def _vac_titles(db: AsyncSession) -> dict[int, str]:
    return {v.id: f"{v.title} · {v.city}" for v in (await db.execute(select(Vacancy))).scalars().all()}


@router.get("/slots", response_model=list[SlotOut])
async def list_slots(date_from: date | None = None, date_to: date | None = None, recruiter_id: int | None = None,
                     vacancy_id: int | None = None, db: AsyncSession = Depends(get_session), _: User = Depends(get_current_user)):
    tz = policy.tz()
    today = datetime.now(UTC).astimezone(tz).date()
    d0 = datetime.combine(date_from or today, time(0), tzinfo=tz)
    d1 = datetime.combine((date_to or today + timedelta(days=13)) + timedelta(days=1), time(0), tzinfo=tz)
    stmt = select(InterviewSlot).where(InterviewSlot.starts_at >= d0, InterviewSlot.starts_at < d1)
    if recruiter_id:
        stmt = stmt.where(InterviewSlot.recruiter_id == recruiter_id)
    if vacancy_id:
        stmt = stmt.where((InterviewSlot.vacancy_id == vacancy_id) | InterviewSlot.vacancy_id.is_(None))
    slots = (await db.execute(stmt.order_by(InterviewSlot.starts_at, InterviewSlot.id))).scalars().all()
    names, titles = await _names(db), await _vac_titles(db)
    return [await _slot_out(db, s, names, titles) for s in slots]


@router.get("/slots/available", response_model=list[SlotOut])
async def available(vacancy_id: int | None = None, db: AsyncSession = Depends(get_session), _: User = Depends(get_current_user)):
    slots = await svc.available_slots(db, vacancy_id, limit=50, min_lead=timedelta(0))
    names, titles = await _names(db), await _vac_titles(db)
    return [await _slot_out(db, s, names, titles) for s in slots]


@router.post("/slots/bulk", response_model=list[SlotOut], status_code=201)
async def bulk_create(data: SlotBulkIn, request: Request, db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    if user.role == Role.recruiter and data.recruiter_id != user.id:
        raise HTTPException(403, "Рекрутер создаёт слоты только себе")
    rec = await db.get(User, data.recruiter_id)
    if not rec or not rec.is_active:
        raise HTTPException(422, "Рекрутер не найден")
    if data.vacancy_id and not await db.get(Vacancy, data.vacancy_id):
        raise HTTPException(422, "Вакансия не найдена")
    tz = policy.tz()
    start = datetime.combine(data.date, _hm(data.start), tzinfo=tz)
    end = datetime.combine(data.date, _hm(data.end), tzinfo=tz)
    if end <= start:
        raise HTTPException(422, "Окончание должно быть позже начала")
    if end <= datetime.now(UTC):
        raise HTTPException(422, "Нельзя создать слоты в прошлом")
    step = timedelta(minutes=data.duration_min)
    created: list[InterviewSlot] = []
    t = start
    while t + step <= end and len(created) < 100:
        if t > datetime.now(UTC):
            s = InterviewSlot(recruiter_id=data.recruiter_id, vacancy_id=data.vacancy_id, starts_at=t.astimezone(UTC),
                              ends_at=(t + step).astimezone(UTC), capacity=data.capacity, office_address=data.office_address or None)
            db.add(s)
            created.append(s)
        t += step
    if not created:
        raise HTTPException(422, "Ни одного слота не помещается в указанный интервал")
    await db.flush()
    await log_action(db, user_id=user.id, action="slot.create", entity="user", entity_id=data.recruiter_id,
                     diff={"count": len(created), "date": data.date.isoformat(), "from": data.start, "to": data.end}, ip=client_ip(request))
    await db.commit()
    names, titles = await _names(db), await _vac_titles(db)
    return [await _slot_out(db, s, names, titles) for s in created]


@router.patch("/slots/{slot_id}", response_model=SlotOut)
async def patch_slot(slot_id: int, data: SlotPatch, request: Request, db: AsyncSession = Depends(get_session),
                     user: User = Depends(get_current_user)):
    s = await db.get(InterviewSlot, slot_id)
    if not s:
        raise HTTPException(404, "Слот не найден")
    if user.role == Role.recruiter and s.recruiter_id != user.id:
        raise HTTPException(403, "Это слот другого рекрутера")
    payload = data.model_dump(exclude_unset=True)
    if "capacity" in payload and payload["capacity"] < await svc.booked_count(db, s.id):
        raise HTTPException(409, "Мест меньше, чем уже записано")
    for k, v in payload.items():
        setattr(s, k, v)
    await log_action(db, user_id=user.id, action="slot.update", entity="slot", entity_id=s.id, diff=payload, ip=client_ip(request))
    await db.commit()
    return await _slot_out(db, s, await _names(db), await _vac_titles(db))


@router.delete("/slots/{slot_id}", status_code=204)
async def delete_slot(slot_id: int, request: Request, db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    s = await db.get(InterviewSlot, slot_id)
    if not s:
        raise HTTPException(404, "Слот не найден")
    if user.role == Role.recruiter and s.recruiter_id != user.id:
        raise HTTPException(403, "Это слот другого рекрутера")
    if await svc.booked_count(db, s.id):
        raise HTTPException(409, "На слот уже записаны — сначала отмените записи или выключите слот")
    await db.delete(s)
    await log_action(db, user_id=user.id, action="slot.delete", entity="slot", entity_id=slot_id, ip=client_ip(request))
    await db.commit()


async def _iv_out(db: AsyncSession, iv: Interview) -> InterviewOut:
    s = iv.slot
    cand = await db.get(Candidate, iv.candidate_id)
    app = await db.get(Application, iv.application_id) if iv.application_id else None
    vac = await db.get(Vacancy, app.vacancy_id) if app else (await db.get(Vacancy, s.vacancy_id) if s.vacancy_id else None)
    rec = await db.get(User, s.recruiter_id)
    return InterviewOut(id=iv.id, slot_id=s.id, candidate_id=iv.candidate_id, candidate_name=cand.full_name if cand else "—",
                        starts_at=s.starts_at, ends_at=s.ends_at, address=await svc.slot_address(db, s, vac.id if vac else None),
                        recruiter_name=rec.full_name if rec else "—", vacancy_title=f"{vac.title} · {vac.city}" if vac else None,
                        status=iv.status, booked_via=iv.booked_via, confirmed_at=iv.confirmed_at,
                        reminded_24h_at=iv.reminded_24h_at, reminded_2h_at=iv.reminded_2h_at)


@router.get("/candidates/{candidate_id}/interviews", response_model=list[InterviewOut])
async def candidate_interviews(candidate_id: int, db: AsyncSession = Depends(get_session), _: User = Depends(get_current_user)):
    rows = (await db.execute(select(Interview).where(Interview.candidate_id == candidate_id).order_by(Interview.id.desc()))).scalars().all()
    return [await _iv_out(db, iv) for iv in rows]


@router.post("/candidates/{candidate_id}/interviews", response_model=InterviewOut, status_code=201)
async def book_manually(candidate_id: int, data: InterviewIn, db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    cand = await db.get(Candidate, candidate_id)
    if not cand or cand.anonymized_at:
        raise HTTPException(404, "Кандидат не найден")
    try:
        iv = await svc.book(db, candidate_id=candidate_id, slot_id=data.slot_id, vacancy_id=data.vacancy_id, via="recruiter", user_id=user.id)
    except svc.SlotUnavailable as e:
        raise HTTPException(409, str(e)) from e
    ids: list[int] = []
    if data.notify:
        conv = await messaging.get_or_create_conversation(db, cand)
        if messaging.window_open(conv) and not cand.unsubscribed_at:
            lang = cand.language or "ru"
            addr = await svc.slot_address(db, iv.slot, data.vacancy_id)
            from app.services.scenario_engine import BOOKING_CONFIRM, render, tr

            text = render(tr(BOOKING_CONFIRM, lang), {"interview_date": svc.fmt_date(iv.slot.starts_at, lang),
                                                       "interview_time": svc.fmt_time(iv.slot.starts_at), "address": addr})
            ids.append((await messaging.queue_message(db, conv, OutText(text), user_id=user.id)).id)
    await db.commit()
    await messaging.send_queued(ids)
    return await _iv_out(db, iv)


@router.patch("/interviews/{interview_id}", response_model=InterviewOut)
async def update_interview(interview_id: int, data: InterviewPatch, db: AsyncSession = Depends(get_session),
                           user: User = Depends(get_current_user)):
    iv = await db.get(Interview, interview_id)
    if not iv:
        raise HTTPException(404, "Запись не найдена")
    if iv.status in ("cancelled", "rescheduled"):
        raise HTTPException(409, "Запись уже отменена или перенесена")
    if data.status in ("attended", "no_show") and iv.slot.starts_at > datetime.now(UTC) + timedelta(hours=1):
        raise HTTPException(409, "Отметить явку можно только после начала собеседования")
    await svc.set_status(db, iv, data.status, user_id=user.id, reason=data.reason)
    await db.commit()
    return await _iv_out(db, iv)
