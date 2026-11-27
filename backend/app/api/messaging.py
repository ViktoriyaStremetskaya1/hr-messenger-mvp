import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.base import OutTemplate, OutText
from app.channels.registry import get_adapter
from app.core.db import get_session
from app.core.deps import client_ip, get_current_user, require_roles
from app.models import Candidate, Conversation, Message, MessageTemplate, Role, Scenario, User
from app.schemas.messaging import ConversationOut, ConversationView, MessageOut, ScenarioState, SendIn, TemplateIn, TemplateOut
from app.services import messaging
from app.services.audit import changes, log_action

router = APIRouter(tags=["messaging"])


def params_count(body: str) -> int:
    nums = [int(n) for n in re.findall(r"\{\{(\d+)\}\}", body)]
    return max(nums) if nums else 0


def tpl_out(t: MessageTemplate) -> TemplateOut:
    o = TemplateOut.model_validate(t)
    o.params_count = params_count(t.body)
    return o


async def _candidate(db: AsyncSession, cid: int) -> Candidate:
    c = await db.get(Candidate, cid)
    if not c or c.anonymized_at:
        raise HTTPException(404, "Кандидат не найден")
    return c


@router.get("/candidates/{candidate_id}/conversation", response_model=ConversationView)
async def get_conversation(candidate_id: int, db: AsyncSession = Depends(get_session), _: User = Depends(get_current_user)):
    c = await _candidate(db, candidate_id)
    conv = (await db.execute(select(Conversation).where(Conversation.candidate_id == c.id, Conversation.channel == "whatsapp"))).scalar_one_or_none()
    msgs: list[Message] = []
    if conv:
        msgs = list((await db.execute(select(Message).where(Message.conversation_id == conv.id)
                                      .order_by(Message.created_at, Message.id))).scalars().all())
        if conv.unread_count:
            conv.unread_count = 0
            await db.commit()
    state = None
    if conv and conv.scenario_id:
        sc = await db.get(Scenario, conv.scenario_id)
        if sc:
            ctx = conv.context or {}
            node = sc.graph.get("nodes", {}).get(conv.current_node or "", {})
            state = ScenarioState(
                scenario_id=sc.id, scenario_name=sc.name, current_node=conv.current_node, current_title=node.get("title"),
                waiting=bool(ctx.get("waiting")), outcome=ctx.get("outcome"), reason=ctx.get("reason"),
                vacancy_id=ctx.get("vacancy_id"),
                answers={k: (v.get("label") if isinstance(v, dict) else v) for k, v in (ctx.get("vars") or {}).items()},
            )
    return ConversationView(
        conversation=ConversationOut.model_validate(conv) if conv else None,
        scenario=state,
        messages=[MessageOut.model_validate(m) for m in msgs],
        window_open=bool(conv and messaging.window_open(conv)),
        window_expires_at=messaging.window_expires_at(conv) if conv else None,
        unsubscribed=c.unsubscribed_at is not None,
    )


@router.post("/candidates/{candidate_id}/messages", response_model=MessageOut, status_code=201)
async def send_message(
    candidate_id: int, data: SendIn, request: Request,
    db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user),
):
    c = await _candidate(db, candidate_id)
    conv = await messaging.get_or_create_conversation(db, c)
    template = None
    if data.kind == "text":
        if not (data.text or "").strip():
            raise HTTPException(422, "Пустое сообщение")
        out: Any = OutText(data.text.strip())  # type: ignore[union-attr]
    else:
        template = await db.get(MessageTemplate, data.template_id) if data.template_id else None
        if not template:
            raise HTTPException(422, "Шаблон не найден")
        if template.status != "APPROVED":
            raise HTTPException(422, "Шаблон не одобрен в Meta — отправлять можно только одобренные шаблоны")
        need = params_count(template.body)
        if len(data.params) != need or any(not p.strip() for p in data.params):
            raise HTTPException(422, f"Шаблону нужно параметров: {need}")
        out = OutTemplate(name=template.name, language=template.language, body_params=[p.strip() for p in data.params])
    try:
        msg = await messaging.queue_message(db, conv, out, user_id=user.id, template=template)
    except messaging.MessagingError as e:
        raise HTTPException(409, str(e)) from e
    # Рекрутер написал сам — диалог переходит к нему
    conv.mode = "human"
    if conv.assignee_id is None:
        conv.assignee_id = user.id
    await log_action(db, user_id=user.id, action="message.send", entity="candidate", entity_id=c.id,
                     diff={"kind": data.kind, "template": template.name if template else None}, ip=client_ip(request))
    await db.commit()
    await messaging.send_queued([msg.id])
    await db.refresh(msg)
    return msg


# ---------- Шаблоны ----------

@router.get("/templates", response_model=list[TemplateOut])
async def list_templates(db: AsyncSession = Depends(get_session), _: User = Depends(get_current_user)):
    rows = (await db.execute(select(MessageTemplate).order_by(MessageTemplate.name, MessageTemplate.language))).scalars().all()
    return [tpl_out(t) for t in rows]


@router.post("/templates", response_model=TemplateOut, status_code=201)
async def create_template(data: TemplateIn, request: Request, db: AsyncSession = Depends(get_session),
                          user: User = Depends(require_roles(Role.admin, Role.lead))):
    if (await db.execute(select(MessageTemplate).where(MessageTemplate.name == data.name, MessageTemplate.language == data.language))).scalar_one_or_none():
        raise HTTPException(409, "Шаблон с таким именем и языком уже есть")
    t = MessageTemplate(**data.model_dump(), status="LOCAL")
    db.add(t)
    await db.flush()
    await log_action(db, user_id=user.id, action="template.create", entity="template", entity_id=t.id, diff={"name": t.name}, ip=client_ip(request))
    await db.commit()
    await db.refresh(t)
    return tpl_out(t)


@router.put("/templates/{template_id}", response_model=TemplateOut)
async def update_template(template_id: int, data: TemplateIn, request: Request, db: AsyncSession = Depends(get_session),
                          user: User = Depends(require_roles(Role.admin, Role.lead))):
    t = await db.get(MessageTemplate, template_id)
    if not t:
        raise HTTPException(404, "Шаблон не найден")
    if t.status != "LOCAL":
        raise HTTPException(409, "Шаблон из Meta редактируется в кабинете Meta, затем «Синхронизировать»")
    diff = changes(t, data.model_dump())
    await log_action(db, user_id=user.id, action="template.update", entity="template", entity_id=t.id, diff=diff, ip=client_ip(request))
    await db.commit()
    await db.refresh(t)
    return tpl_out(t)


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(template_id: int, request: Request, db: AsyncSession = Depends(get_session),
                          user: User = Depends(require_roles(Role.admin, Role.lead))):
    t = await db.get(MessageTemplate, template_id)
    if not t:
        raise HTTPException(404, "Шаблон не найден")
    await db.delete(t)
    await log_action(db, user_id=user.id, action="template.delete", entity="template", entity_id=template_id, diff={"name": t.name}, ip=client_ip(request))
    await db.commit()


def _from_meta(t: dict[str, Any]) -> dict[str, Any]:
    header = body = footer = None
    buttons: list[dict[str, Any]] = []
    for comp in t.get("components", []):
        ct = comp.get("type", "").upper()
        if ct == "HEADER" and comp.get("format", "TEXT") == "TEXT":
            header = comp.get("text")
        elif ct == "BODY":
            body = comp.get("text")
        elif ct == "FOOTER":
            footer = comp.get("text")
        elif ct == "BUTTONS":
            buttons = [{"type": b.get("type"), "text": b.get("text")} for b in comp.get("buttons", [])]
    return {"header": header, "body": body or "", "footer": footer, "buttons": buttons,
            "category": t.get("category", "MARKETING"), "status": t.get("status", "PENDING"), "provider_id": t.get("id")}


@router.post("/templates/sync")
async def sync_templates(request: Request, db: AsyncSession = Depends(get_session),
                         user: User = Depends(require_roles(Role.admin, Role.lead))) -> dict[str, int]:
    """Загружает шаблоны и их статусы из WhatsApp Business Account."""
    try:
        remote = await get_adapter("whatsapp").list_templates()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Не удалось получить шаблоны из Meta: {e.__class__.__name__}") from e
    created = updated = 0
    for r in remote:
        lang = (r.get("language") or "").split("_")[0]
        if lang not in ("ru", "kk"):
            continue
        fields = _from_meta(r)
        t = (await db.execute(select(MessageTemplate).where(MessageTemplate.name == r["name"], MessageTemplate.language == lang))).scalar_one_or_none()
        if t is None:
            db.add(MessageTemplate(name=r["name"], language=lang, **fields))
            created += 1
        else:
            changes(t, fields)
            updated += 1
    await log_action(db, user_id=user.id, action="template.sync", diff={"created": created, "updated": updated}, ip=client_ip(request))
    await db.commit()
    return {"created": created, "updated": updated, "total": len(remote)}


@router.get("/channel/status")
async def channel_status(_: User = Depends(get_current_user)) -> dict[str, Any]:
    from app.core.config import get_settings

    s = get_settings()
    return {
        "mode": "mock" if messaging.is_mock() else "live",
        "configured": bool(s.wa_phone_number_id and s.wa_access_token and s.wa_app_secret),
        "display_phone": s.wa_display_phone,
        "api_version": s.wa_api_version,
    }
