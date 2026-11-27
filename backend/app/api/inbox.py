import asyncio
import re
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.core.db import get_session
from app.core.deps import client_ip, get_current_user
from app.models import Application, Candidate, Conversation, Role, Scenario, User
from app.schemas.common import Page
from app.services import messaging, scenario_engine
from app.services.audit import log_action
from app.services.events import CHANNEL, publish, redis
from app.services.phone import PhoneError, normalize_phone

router = APIRouter(tags=["inbox"])

Filter = Literal["all", "mine", "unassigned", "needs_reply", "unread", "bot", "human"]


class InboxItem(BaseModel):
    conversation_id: int
    candidate_id: int
    candidate_name: str
    phone_masked: str
    city: str | None
    last_preview: str | None
    last_direction: str | None
    last_message_at: datetime | None
    unread_count: int
    needs_reply: bool
    mode: str
    assignee_id: int | None
    assignee_name: str | None
    scenario_name: str | None
    scenario_step: str | None
    scenario_outcome: str | None
    window_open: bool
    unsubscribed: bool
    vacancy: str | None


def _filter(stmt, f: Filter, user: User):
    if f == "mine":
        return stmt.where(Conversation.assignee_id == user.id)
    if f == "unassigned":
        return stmt.where(Conversation.assignee_id.is_(None))
    if f == "needs_reply":
        return stmt.where(Conversation.needs_reply.is_(True))
    if f == "unread":
        return stmt.where(Conversation.unread_count > 0)
    if f == "bot":
        return stmt.where(Conversation.mode == "bot", Conversation.current_node.isnot(None))
    if f == "human":
        return stmt.where(Conversation.mode == "human")
    return stmt


@router.get("/inbox", response_model=Page[InboxItem])
async def inbox(filter: Filter = "all", q: str | None = None, vacancy_id: int | None = None, assignee_id: int | None = None,
                page: int = 1, page_size: int = 50, db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    page_size = min(max(page_size, 1), 100)
    stmt = (select(Conversation, Candidate).join(Candidate, Candidate.id == Conversation.candidate_id)
            .where(Candidate.anonymized_at.is_(None), Conversation.last_message_at.isnot(None)))
    stmt = _filter(stmt, filter, user)
    if assignee_id:
        stmt = stmt.where(Conversation.assignee_id == assignee_id)
    if vacancy_id:
        stmt = stmt.where(exists().where(and_(Application.candidate_id == Candidate.id, Application.vacancy_id == vacancy_id)))
    if q:
        conds = [Candidate.full_name.ilike(f"%{q.strip()}%")]
        digits = re.sub(r"\D", "", q)
        if len(digits) >= 10:
            try:
                conds.append(Candidate.phone_hash == crypto.phone_hash(normalize_phone(q)))
            except PhoneError:
                pass
        elif len(digits) == 4:
            conds.append(Candidate.phone_last4 == digits)
        stmt = stmt.where(or_(*conds))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(Conversation.needs_reply.desc() if filter == "needs_reply" else Conversation.last_message_at.desc(),
                                           Conversation.last_message_at.desc())
                             .offset((page - 1) * page_size).limit(page_size))).all()
    names = {u.id: u.full_name for u in (await db.execute(select(User))).scalars().all()}
    scen = {s.id: s for s in (await db.execute(select(Scenario))).scalars().all()}
    items = []
    for conv, cand in rows:
        sc = scen.get(conv.scenario_id or 0)
        ctx = conv.context or {}
        apps = sorted(cand.applications, key=lambda a: a.updated_at, reverse=True)
        items.append(InboxItem(
            conversation_id=conv.id, candidate_id=cand.id, candidate_name=cand.full_name,
            phone_masked=f"+7 *** *** {cand.phone_last4[:2]} {cand.phone_last4[2:]}", city=cand.city,
            last_preview=conv.last_preview, last_direction=conv.last_direction, last_message_at=conv.last_message_at,
            unread_count=conv.unread_count, needs_reply=conv.needs_reply, mode=conv.mode, assignee_id=conv.assignee_id,
            assignee_name=names.get(conv.assignee_id or 0), scenario_name=sc.name if sc else None,
            scenario_step=(sc.graph.get("nodes", {}).get(conv.current_node or "", {}).get("title") if sc and conv.current_node else None),
            scenario_outcome=ctx.get("outcome"), window_open=messaging.window_open(conv), unsubscribed=cand.unsubscribed_at is not None,
            vacancy=f"{apps[0].vacancy.title} · {apps[0].vacancy.city}" if apps else None,
        ))
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/inbox/counts")
async def counts(db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)) -> dict[str, int]:
    base = select(func.count()).select_from(Conversation).join(Candidate, Candidate.id == Conversation.candidate_id) \
        .where(Candidate.anonymized_at.is_(None), Conversation.last_message_at.isnot(None))
    out = {}
    for f in ("all", "mine", "unassigned", "needs_reply", "unread", "bot", "human"):
        out[f] = (await db.execute(_filter(base, f, user))).scalar_one()  # type: ignore[arg-type]
    out["mine_needs_reply"] = (await db.execute(base.where(Conversation.assignee_id == user.id, Conversation.needs_reply.is_(True)))).scalar_one()
    return out


async def _conv(db: AsyncSession, cid: int) -> Conversation:
    c = await db.get(Conversation, cid)
    if not c:
        raise HTTPException(404, "Диалог не найден")
    return c


class AssignIn(BaseModel):
    user_id: int | None


@router.post("/conversations/{conversation_id}/assign")
async def assign(conversation_id: int, data: AssignIn, request: Request, db: AsyncSession = Depends(get_session),
                 user: User = Depends(get_current_user)) -> dict[str, bool]:
    conv = await _conv(db, conversation_id)
    if user.role == Role.recruiter and data.user_id not in (user.id, None):
        raise HTTPException(403, "Рекрутер может назначить диалог только на себя")
    if user.role == Role.recruiter and data.user_id is None and conv.assignee_id not in (user.id, None):
        raise HTTPException(403, "Снять чужое назначение может только руководитель")
    if data.user_id is not None:
        target = await db.get(User, data.user_id)
        if not target or not target.is_active:
            raise HTTPException(422, "Пользователь не найден")
    old = conv.assignee_id
    conv.assignee_id = data.user_id
    await log_action(db, user_id=user.id, action="conversation.assign", entity="candidate", entity_id=conv.candidate_id,
                     diff={"from": old, "to": data.user_id}, ip=client_ip(request))
    await db.commit()
    await publish({"type": "conversation", "conversation_id": conv.id})
    return {"ok": True}


@router.post("/conversations/{conversation_id}/takeover")
async def takeover(conversation_id: int, request: Request, db: AsyncSession = Depends(get_session),
                   user: User = Depends(get_current_user)) -> dict[str, bool]:
    """Перехватить диалог у бота: бот замолкает, диалог закрепляется за мной."""
    conv = await _conv(db, conversation_id)
    conv.mode = "human"
    conv.assignee_id = user.id
    await log_action(db, user_id=user.id, action="conversation.takeover", entity="candidate", entity_id=conv.candidate_id,
                     diff={"scenario_active": scenario_engine.is_active(conv)}, ip=client_ip(request))
    await db.commit()
    await publish({"type": "conversation", "conversation_id": conv.id})
    return {"ok": True}


@router.post("/conversations/{conversation_id}/done")
async def mark_done(conversation_id: int, db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)) -> dict[str, bool]:
    """Снять отметку «ждёт ответа» (например, ответили по телефону)."""
    conv = await _conv(db, conversation_id)
    conv.needs_reply = False
    conv.unread_count = 0
    await db.commit()
    await publish({"type": "conversation", "conversation_id": conv.id})
    return {"ok": True}


@router.get("/events/stream")
async def stream(request: Request, _: User = Depends(get_current_user)):
    """Server-Sent Events: интерфейс обновляет чаты без перезагрузки."""
    async def gen():
        pubsub = redis().pubsub()
        await pubsub.subscribe(CHANNEL)
        try:
            yield "retry: 3000\n\n"
            while not await request.is_disconnected():
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15)
                if msg and msg.get("type") == "message":
                    yield f"data: {msg['data']}\n\n"
                else:
                    yield ": ping\n\n"
                await asyncio.sleep(0)
        finally:
            await pubsub.unsubscribe(CHANNEL)
            await pubsub.aclose()

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


