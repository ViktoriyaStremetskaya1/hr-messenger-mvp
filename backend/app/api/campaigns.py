from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import client_ip, get_current_user
from app.models import Campaign, CampaignRecipient, Candidate, Scenario, User, Vacancy
from app.schemas.common import ORM, Page
from app.services import campaigns as svc
from app.services import scenario_engine
from app.services.audit import log_action

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


class Segment(BaseModel):
    candidate_ids: list[int] = Field(default=[], max_length=20000)
    cities: list[str] = []
    vacancy_ids: list[int] = []
    statuses: list[str] = []
    screening: list[str] = []
    is_reserve: bool | None = None
    tag_ids: list[int] = []
    languages: list[Literal["ru", "kk", "none"]] = []
    sources: list[str] = []


class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    scenario_id: int
    vacancy_id: int | None = None
    segment: Segment
    scheduled_at: datetime | None = None


class CampaignOut(ORM):
    id: int
    name: str
    scenario_id: int
    vacancy_id: int | None
    segment: dict[str, Any]
    status: str
    scheduled_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    created_by: int | None
    created_at: datetime
    stats: dict[str, Any] = {}


class RecipientOut(ORM):
    id: int
    candidate_id: int
    candidate_name: str = ""
    status: str
    skip_reason: str | None
    error: str | None
    message_status: str | None = None
    processed_at: datetime | None


async def _get(db: AsyncSession, cid: int) -> Campaign:
    c = await db.get(Campaign, cid)
    if not c:
        raise HTTPException(404, "Рассылка не найдена")
    return c


async def _validate(db: AsyncSession, data: CampaignIn) -> None:
    sc = await db.get(Scenario, data.scenario_id)
    if not sc or not sc.is_active:
        raise HTTPException(422, "Сценарий не найден или выключен")
    if sc.kind == "reminder":
        raise HTTPException(422, "Напоминания не рассылаются вручную")
    # после выбора языка (если он есть) первым должен идти шаблон: кандидатам пишем первыми
    if not scenario_engine.starts_with_template(sc.graph, "ru"):
        raise HTTPException(422, "Сценарий рассылки должен начинаться с шаблона WhatsApp или выбора языка: кандидатам пишем первыми")
    needs_vacancy = sc.kind in ("offer", "missed_call") or any(
        any("{vacancy}" in p for p in n.get("params") or []) for n in sc.graph.get("nodes", {}).values())
    if needs_vacancy and not data.vacancy_id:
        raise HTTPException(422, "Для этого сценария выберите вакансию")
    if data.vacancy_id and not await db.get(Vacancy, data.vacancy_id):
        raise HTTPException(422, "Вакансия не найдена")


async def _out(db: AsyncSession, c: Campaign, with_stats: bool = True) -> CampaignOut:
    o = CampaignOut.model_validate(c)
    if with_stats:
        o.stats = await svc.stats(db, c.id) if c.status != "draft" else {}
    return o


@router.get("", response_model=list[CampaignOut])
async def list_campaigns(db: AsyncSession = Depends(get_session), _: User = Depends(get_current_user)):
    rows = (await db.execute(select(Campaign).order_by(Campaign.created_at.desc()).limit(200))).scalars().all()
    return [await _out(db, c) for c in rows]


@router.post("/preview")
async def preview(segment: Segment, db: AsyncSession = Depends(get_session), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return await svc.preview(db, segment.model_dump())


@router.post("", response_model=CampaignOut, status_code=201)
async def create(data: CampaignIn, request: Request, db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    await _validate(db, data)
    c = Campaign(name=data.name, scenario_id=data.scenario_id, vacancy_id=data.vacancy_id,
                 segment=data.segment.model_dump(), scheduled_at=data.scheduled_at, created_by=user.id)
    db.add(c)
    await db.flush()
    await log_action(db, user_id=user.id, action="campaign.create", entity="campaign", entity_id=c.id, diff={"name": c.name}, ip=client_ip(request))
    await db.commit()
    await db.refresh(c)
    return await _out(db, c)


@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign(campaign_id: int, db: AsyncSession = Depends(get_session), _: User = Depends(get_current_user)):
    return await _out(db, await _get(db, campaign_id))


@router.put("/{campaign_id}", response_model=CampaignOut)
async def update(campaign_id: int, data: CampaignIn, request: Request, db: AsyncSession = Depends(get_session),
                 user: User = Depends(get_current_user)):
    c = await _get(db, campaign_id)
    if c.status != "draft":
        raise HTTPException(409, "Изменять можно только черновик")
    await _validate(db, data)
    c.name, c.scenario_id, c.vacancy_id = data.name, data.scenario_id, data.vacancy_id
    c.segment, c.scheduled_at = data.segment.model_dump(), data.scheduled_at
    await log_action(db, user_id=user.id, action="campaign.update", entity="campaign", entity_id=c.id, ip=client_ip(request))
    await db.commit()
    await db.refresh(c)
    return await _out(db, c)


@router.delete("/{campaign_id}", status_code=204)
async def delete(campaign_id: int, request: Request, db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    c = await _get(db, campaign_id)
    if c.status != "draft":
        raise HTTPException(409, "Удалить можно только черновик — запущенную рассылку отмените")
    await db.delete(c)
    await log_action(db, user_id=user.id, action="campaign.delete", entity="campaign", entity_id=campaign_id, ip=client_ip(request))
    await db.commit()


class LaunchIn(BaseModel):
    scheduled_at: datetime | None = None


@router.post("/{campaign_id}/launch", response_model=CampaignOut)
async def launch(campaign_id: int, request: Request, data: LaunchIn | None = None, db: AsyncSession = Depends(get_session),
                 user: User = Depends(get_current_user)):
    c = await _get(db, campaign_id)
    if c.status != "draft":
        raise HTTPException(409, "Рассылка уже запущена")
    if data and data.scheduled_at:
        c.scheduled_at = data.scheduled_at
    if c.scheduled_at and c.scheduled_at.tzinfo is None:
        c.scheduled_at = c.scheduled_at.replace(tzinfo=UTC)
    n = await svc.snapshot_recipients(db, c)
    if n == 0:
        raise HTTPException(422, "В сегменте нет кандидатов")
    c.status = "scheduled"
    await log_action(db, user_id=user.id, action="campaign.launch", entity="campaign", entity_id=c.id,
                     diff={"recipients": n, "scheduled_at": c.scheduled_at.isoformat() if c.scheduled_at else None}, ip=client_ip(request))
    await db.commit()
    await svc.schedule_tick(c.id, c.scheduled_at)
    await db.refresh(c)
    return await _out(db, c)


@router.post("/{campaign_id}/{action}", response_model=CampaignOut)
async def control(campaign_id: int, action: Literal["pause", "resume", "cancel"], request: Request,
                  db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    c = await _get(db, campaign_id)
    allowed = {"pause": ("scheduled", "running"), "resume": ("paused",), "cancel": ("scheduled", "running", "paused")}
    if c.status not in allowed[action]:
        raise HTTPException(409, f"Нельзя выполнить «{action}» для рассылки в статусе «{c.status}»")
    if action == "pause":
        c.status = "paused"
    elif action == "resume":
        c.status = "running"
    else:
        c.status = "cancelled"
        c.finished_at = datetime.now(UTC)
        await db.execute(CampaignRecipient.__table__.update()
                         .where(CampaignRecipient.campaign_id == c.id, CampaignRecipient.status == "queued")
                         .values(status="skipped", skip_reason="cancelled"))
    await log_action(db, user_id=user.id, action=f"campaign.{action}", entity="campaign", entity_id=c.id, ip=client_ip(request))
    await db.commit()
    if action == "resume":
        await svc.schedule_tick(c.id)
    await db.refresh(c)
    return await _out(db, c)


@router.get("/{campaign_id}/recipients", response_model=Page[RecipientOut])
async def recipients(campaign_id: int, status: str | None = None, page: int = 1, page_size: int = 50,
                     db: AsyncSession = Depends(get_session), _: User = Depends(get_current_user)):
    from app.models import Message

    page_size = min(max(page_size, 1), 200)
    stmt = select(CampaignRecipient, Candidate.full_name, Message.status).join(Candidate, Candidate.id == CampaignRecipient.candidate_id) \
        .outerjoin(Message, Message.id == CampaignRecipient.message_id).where(CampaignRecipient.campaign_id == campaign_id)
    if status:
        stmt = stmt.where(CampaignRecipient.status == status)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(CampaignRecipient.id).offset((page - 1) * page_size).limit(page_size))).all()
    items = []
    for r, name, mstatus in rows:
        o = RecipientOut.model_validate(r)
        o.candidate_name, o.message_status = name, mstatus
        items.append(o)
    return Page(items=items, total=total, page=page, page_size=page_size)
