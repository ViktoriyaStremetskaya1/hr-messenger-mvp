"""Слоты, запись на собеседование, напоминания за 24 ч и за 2 ч."""
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.models import Application, CampaignRecipient, Candidate, Interview, InterviewSlot, Scenario, Vacancy
from app.services import policy
from app.services.audit import log_action

log = logging.getLogger(__name__)

ACTIVE = ("booked", "attended", "no_show")  # занимают место в слоте
MIN_LEAD = timedelta(hours=2)  # бот не предлагает слоты ближе, чем через 2 часа
HORIZON_DAYS = 14

MONTHS = {
    "ru": ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"],
    "kk": ["қаңтар", "ақпан", "наурыз", "сәуір", "мамыр", "маусым", "шілде", "тамыз", "қыркүйек", "қазан", "қараша", "желтоқсан"],
}
WEEKDAYS = {"ru": ["пн", "вт", "ср", "чт", "пт", "сб", "вс"], "kk": ["дс", "сс", "ср", "бс", "жм", "сб", "жс"]}


class SlotUnavailable(Exception):
    pass


def local(dt: datetime) -> datetime:
    return dt.astimezone(policy.tz())


def fmt_date(dt: datetime, lang: str = "ru") -> str:
    d = local(dt)
    lang = lang if lang in MONTHS else "ru"
    return f"{d.day} {MONTHS[lang][d.month - 1]}, {WEEKDAYS[lang][d.weekday()]}"


def fmt_time(dt: datetime) -> str:
    return local(dt).strftime("%H:%M")


async def booked_count(db: AsyncSession, slot_id: int) -> int:
    return (await db.execute(select(func.count()).select_from(Interview).where(
        Interview.slot_id == slot_id, Interview.status.in_(ACTIVE)))).scalar_one()


async def available_slots(db: AsyncSession, vacancy_id: int | None, *, limit: int = 9,
                          min_lead: timedelta = MIN_LEAD) -> list[InterviewSlot]:
    now = datetime.now(UTC)
    taken = select(Interview.slot_id, func.count().label("n")).where(Interview.status.in_(ACTIVE)).group_by(Interview.slot_id).subquery()
    stmt = (select(InterviewSlot).outerjoin(taken, taken.c.slot_id == InterviewSlot.id)
            .where(InterviewSlot.is_active.is_(True), InterviewSlot.starts_at >= now + min_lead,
                   InterviewSlot.starts_at <= now + timedelta(days=HORIZON_DAYS),
                   func.coalesce(taken.c.n, 0) < InterviewSlot.capacity))
    if vacancy_id:
        stmt = stmt.where((InterviewSlot.vacancy_id == vacancy_id) | InterviewSlot.vacancy_id.is_(None))
    return list((await db.execute(stmt.order_by(InterviewSlot.starts_at).limit(limit))).scalars().all())


async def slot_address(db: AsyncSession, slot: InterviewSlot, vacancy_id: int | None) -> str:
    if slot.office_address:
        return slot.office_address
    vid = slot.vacancy_id or vacancy_id
    vac = await db.get(Vacancy, vid) if vid else None
    return (vac.office_address if vac else None) or "адрес уточнит рекрутер"


async def _application(db: AsyncSession, candidate_id: int, vacancy_id: int | None) -> Application | None:
    if not vacancy_id:
        return None
    return (await db.execute(select(Application).where(Application.candidate_id == candidate_id,
                                                         Application.vacancy_id == vacancy_id))).scalar_one_or_none()


async def _recipients_for(db: AsyncSession, app: Application | None) -> list[CampaignRecipient]:
    if not app or not app.campaign_id:
        return []
    return list((await db.execute(select(CampaignRecipient).where(CampaignRecipient.campaign_id == app.campaign_id,
                                                                    CampaignRecipient.candidate_id == app.candidate_id))).scalars().all())


async def book(db: AsyncSession, *, candidate_id: int, slot_id: int, vacancy_id: int | None, via: str,
               user_id: int | None = None, replaces: int | None = None) -> Interview:
    """Запись с блокировкой слота (два кандидата не займут последнее место одновременно)."""
    slot = (await db.execute(select(InterviewSlot).where(InterviewSlot.id == slot_id).with_for_update())).scalar_one_or_none()
    if slot is None or not slot.is_active:
        raise SlotUnavailable("Слот недоступен")
    if slot.starts_at <= datetime.now(UTC):
        raise SlotUnavailable("Это время уже прошло")
    if await booked_count(db, slot.id) >= slot.capacity:
        raise SlotUnavailable("Это время уже заняли")
    vacancy_id = vacancy_id or slot.vacancy_id
    app = await _application(db, candidate_id, vacancy_id)
    if app is None and vacancy_id:
        app = Application(candidate_id=candidate_id, vacancy_id=vacancy_id, status="booked", recruiter_id=slot.recruiter_id,
                          screening_answers={})
        db.add(app)
        await db.flush()
    # у кандидата одна активная запись по вакансии: прежняя — перенесена
    prev_q = select(Interview).where(Interview.candidate_id == candidate_id, Interview.status == "booked")
    if app is not None:
        prev_q = prev_q.where(Interview.application_id == app.id)
    elif replaces:
        prev_q = prev_q.where(Interview.id == replaces)
    else:
        prev_q = prev_q.where(Interview.id == -1)
    for prev in (await db.execute(prev_q)).scalars().all():
        prev.status = "rescheduled"
        prev.cancelled_at = datetime.now(UTC)
    iv = Interview(slot=slot, candidate_id=candidate_id, application_id=app.id if app else None,
                   status="booked", booked_via=via, booked_by=user_id)
    db.add(iv)
    if app is not None:
        app.status = "booked"
    for r in await _recipients_for(db, app):
        r.booked_at = r.booked_at or datetime.now(UTC)
    await db.flush()
    await log_action(db, user_id=user_id, action="interview.book", entity="candidate", entity_id=candidate_id,
                     diff={"slot_id": slot.id, "via": via, "starts_at": slot.starts_at.isoformat()})
    return iv


async def set_status(db: AsyncSession, iv: Interview, status: str, *, user_id: int | None = None, reason: str | None = None) -> None:
    iv.status = status
    app = await db.get(Application, iv.application_id) if iv.application_id else None
    if status == "cancelled":
        iv.cancelled_at = datetime.now(UTC)
        iv.cancel_reason = reason
        if app and app.status == "booked":
            app.status = "replied"
    elif status in ("attended", "no_show") and app:
        app.status = status
        if status == "attended":
            for r in await _recipients_for(db, app):
                r.attended_at = r.attended_at or datetime.now(UTC)
    await log_action(db, user_id=user_id, action=f"interview.{status}", entity="candidate", entity_id=iv.candidate_id,
                     diff={"interview_id": iv.id, "reason": reason})


async def reminder_scenario(db: AsyncSession) -> Scenario:
    sc = (await db.execute(select(Scenario).where(Scenario.kind == "reminder", Scenario.is_active.is_(True))
                           .order_by(Scenario.id))).scalars().first()
    if sc is None:
        from app.scenario_library import LIBRARY, build

        sc = Scenario(name=LIBRARY["reminder"]["name"], kind="reminder", description=LIBRARY["reminder"]["description"],
                      graph=build("reminder"))
        db.add(sc)
        await db.flush()
    return sc


async def remind(db: AsyncSession, iv: Interview, kind: str) -> list[int]:
    """Запускает сценарий-напоминание (шаблон interview_reminder с кнопками)."""
    from app.services import messaging, scenario_engine

    cand = await db.get(Candidate, iv.candidate_id)
    if cand is None or cand.unsubscribed_at:
        return []
    slot = iv.slot
    app = await db.get(Application, iv.application_id) if iv.application_id else None
    lang = cand.language or "ru"
    extra = {"interview_id": iv.id, "interview_date": fmt_date(slot.starts_at, lang), "interview_time": fmt_time(slot.starts_at),
             "address": await slot_address(db, slot, app.vacancy_id if app else None), "reminder": kind}
    conv = await messaging.get_or_create_conversation(db, cand)
    if scenario_engine.is_active(conv):
        await scenario_engine.stop(db, conv, None, reason="напоминание о собеседовании")
    sc = await reminder_scenario(db)
    return await scenario_engine.start(db, conv, sc, vacancy_id=app.vacancy_id if app else None, extra=extra)


async def due_reminders(db: AsyncSession, now: datetime | None = None) -> list[tuple[Interview, str]]:
    now = now or datetime.now(UTC)
    rows = (await db.execute(select(Interview).join(InterviewSlot).where(
        Interview.status == "booked", InterviewSlot.starts_at > now,
        InterviewSlot.starts_at <= now + timedelta(hours=24)))).scalars().all()
    due: list[tuple[Interview, str]] = []
    for iv in rows:
        left = iv.slot.starts_at - now
        if left <= timedelta(hours=2):
            # за 2 часа — если запись сделана раньше, чем за 2 часа до начала
            if iv.reminded_2h_at is None and iv.created_at < iv.slot.starts_at - timedelta(hours=2):
                due.append((iv, "2h"))
        elif iv.reminded_24h_at is None and iv.created_at < iv.slot.starts_at - timedelta(hours=24):
            due.append((iv, "24h"))
    return due


async def send_due_reminders(ctx: dict[str, Any]) -> int:
    """Cron раз в 5 минут. Напоминания не зависят от рабочих часов: кандидат ждёт их."""
    from app.services import messaging

    sent = 0
    async with SessionLocal() as db:
        for iv, kind in await due_reminders(db):
            try:
                async with db.begin_nested():
                    ids = await remind(db, iv, kind)
                    setattr(iv, "reminded_24h_at" if kind == "24h" else "reminded_2h_at", datetime.now(UTC))
            except Exception:  # noqa: BLE001
                log.exception("Напоминание для интервью %s не отправлено", iv.id)
                continue
            await db.commit()
            await messaging.send_queued(ids)
            sent += 1
    return sent
