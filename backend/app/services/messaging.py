"""Отправка и приём сообщений поверх абстракции канала.

Правила WhatsApp:
- первое сообщение и любое сообщение вне 24-часового окна — только шаблоном;
- свободный текст/кнопки/списки — только в течение 24 ч после последнего входящего сообщения кандидата.
"""
import logging
import re
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from arq import Retry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.base import (
    Button,
    InboundMessage,
    ListRow,
    OutButtons,
    Outbound,
    OutList,
    OutTemplate,
    OutText,
    StatusUpdate,
)
from app.channels.registry import get_adapter
from app.channels.whatsapp import WINDOW_EXPIRED_CODE
from app.core import crypto
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Application, Candidate, Conversation, Message, MessageTemplate, WebhookEvent
from app.models.enums import STATUS_RANK
from app.services import settings_store
from app.services.audit import log_action
from app.services.phone import PhoneError, normalize_phone
from app.tasks import enqueue, task

log = logging.getLogger(__name__)
WINDOW = timedelta(hours=24)
MAX_TRIES = 5

STOP_REPLY = {
    "ru": "Вы отписались от рассылки и больше не будете получать сообщения. Если передумаете, напишите СТАРТ.",
    "kk": "Сіз таратылымнан бас тарттыңыз, енді хабарлама келмейді. Ойыңыз өзгерсе, СТАРТ деп жазыңыз.",
}
START_REPLY = {
    "ru": "Вы снова подписаны на сообщения о вакансиях.",
    "kk": "Сіз бос орындар туралы хабарламаларға қайта жазылдыңыз.",
}
START_WORDS = {"старт", "start", "бастау"}


class MessagingError(Exception):
    pass


class WindowClosedError(MessagingError):
    def __init__(self) -> None:
        super().__init__("24-часовое окно закрыто: кандидату можно отправить только одобренный шаблон")


class UnsubscribedError(MessagingError):
    def __init__(self) -> None:
        super().__init__("Кандидат отписался от сообщений")


def now() -> datetime:
    return datetime.now(UTC)


def window_expires_at(conv: Conversation) -> datetime | None:
    return conv.last_inbound_at + WINDOW if conv.last_inbound_at else None


def window_open(conv: Conversation, at: datetime | None = None) -> bool:
    exp = window_expires_at(conv)
    return exp is not None and (at or now()) < exp


def render_template(body: str, params: list[str]) -> str:
    return re.sub(r"\{\{(\d+)\}\}", lambda m: params[int(m.group(1)) - 1] if int(m.group(1)) <= len(params) else m.group(0), body)


def outbound_to_dict(m: Outbound) -> dict[str, Any]:
    return asdict(m)


def outbound_from_dict(d: dict[str, Any]) -> Outbound:
    kind = d.get("kind")
    if kind == "text":
        return OutText(text=d["text"])
    if kind == "template":
        return OutTemplate(name=d["name"], language=d["language"], body_params=list(d.get("body_params") or []))
    if kind == "buttons":
        return OutButtons(text=d["text"], buttons=[Button(**b) for b in d["buttons"]], header=d.get("header"), footer=d.get("footer"))
    if kind == "list":
        return OutList(text=d["text"], button_label=d["button_label"], rows=[ListRow(**r) for r in d["rows"]],
                       section_title=d.get("section_title"))
    raise ValueError(f"unknown kind {kind}")


async def get_or_create_conversation(db: AsyncSession, candidate: Candidate, channel: str = "whatsapp") -> Conversation:
    conv = (
        await db.execute(select(Conversation).where(Conversation.candidate_id == candidate.id, Conversation.channel == channel))
    ).scalar_one_or_none()
    if conv is None:
        conv = Conversation(candidate_id=candidate.id, channel=channel, assignee_id=candidate.owner_id, context={})
        db.add(conv)
        await db.flush()
    return conv


async def queue_message(
    db: AsyncSession,
    conv: Conversation,
    out: Outbound,
    *,
    user_id: int | None = None,
    campaign_id: int | None = None,
    template: MessageTemplate | None = None,
    allow_unsubscribed: bool = False,
) -> Message:
    """Создаёт исходящее сообщение в статусе queued. Отправку запускает send_queued() после коммита."""
    candidate = await db.get(Candidate, conv.candidate_id)
    assert candidate is not None
    if candidate.unsubscribed_at and not allow_unsubscribed:
        raise UnsubscribedError()
    if not isinstance(out, OutTemplate) and not window_open(conv):
        raise WindowClosedError()
    if isinstance(out, OutTemplate):
        body = render_template(template.body, out.body_params) if template else f"[шаблон {out.name}]"
        extra: dict[str, Any] = {"buttons": template.buttons if template else []}
    else:
        body = out.text
        extra = {}
    msg = Message(
        conversation_id=conv.id, direction="out", type=out.kind, body=body,
        payload={"out": outbound_to_dict(out), **extra}, status="queued",
        sent_by_user_id=user_id, campaign_id=campaign_id, template_id=template.id if template else None,
    )
    db.add(msg)
    t = now()
    conv.last_outbound_at = t
    conv.last_message_at = t
    await db.flush()
    return msg


async def send_queued(message_ids: list[int]) -> None:
    """Отправляет сообщения строго по очереди (важно для цепочек «текст → кнопки»)."""
    if message_ids:
        await enqueue("deliver_sequence", list(message_ids), job_id=f"deliver:{message_ids[0]}")


@task
async def deliver_sequence(ctx: dict[str, Any], message_ids: list[int]) -> None:
    for i, mid in enumerate(message_ids):
        try:
            await deliver_message(ctx, mid)
        except Retry as r:
            rest = message_ids[i:]
            defer = (r.defer_score or 30000) / 1000
            await enqueue("deliver_sequence", rest, defer_seconds=defer, job_id=f"deliver:{rest[0]}:{int(now().timestamp())}")
            return


async def _rate_limit_ok(ctx: dict[str, Any]) -> bool:
    if ctx.get("inline") or "redis" not in ctx:
        return True
    async with SessionLocal() as db:
        limit = int(await settings_store.get_value(db, "rate_limit_per_minute"))
    key = f"wa:rl:{int(now().timestamp() // 60)}"
    n = await ctx["redis"].incr(key)
    if n == 1:
        await ctx["redis"].expire(key, 120)
    return n <= limit


@task
async def deliver_message(ctx: dict[str, Any], message_id: int) -> None:
    if not await _rate_limit_ok(ctx):
        raise Retry(defer=60 - now().second + 1)
    async with SessionLocal() as db:
        msg = await db.get(Message, message_id)
        if msg is None or msg.status != "queued":
            return
        conv = await db.get(Conversation, msg.conversation_id)
        candidate = await db.get(Candidate, conv.candidate_id)  # type: ignore[union-attr]
        phone = crypto.decrypt(candidate.phone_enc)  # type: ignore[union-attr]
        out = outbound_from_dict(msg.payload["out"])
        res = await get_adapter(conv.channel).send(phone, out)  # type: ignore[union-attr]
        if res.ok:
            msg.status = "sent"
            msg.provider_message_id = res.provider_message_id
            msg.sent_at = now()
            if msg.campaign_id or msg.type == "template":
                candidate.last_touch_at = now()  # type: ignore[union-attr]
        elif res.retryable and not ctx.get("inline") and int(msg.payload.get("attempts", 0)) + 1 < MAX_TRIES:
            attempts = int(msg.payload.get("attempts", 0)) + 1
            msg.payload = {**msg.payload, "attempts": attempts}
            msg.error = f"повтор: {res.error}"
            await db.commit()
            raise Retry(defer=30 * attempts)
        else:
            msg.status = "failed"
            msg.failed_at = now()
            msg.error = (
                "Истекло 24-часовое окно — нужен шаблон" if res.error_code == WINDOW_EXPIRED_CODE
                else f"{res.error_code or ''} {res.error or ''}".strip()
            )
            log.warning("Сообщение %s не отправлено: %s", msg.id, msg.error)
        await db.commit()


# ---------------- Входящие ----------------

def contact_to_phone(contact_id: str) -> str:
    try:
        return normalize_phone(contact_id)
    except PhoneError:
        return "+" + re.sub(r"\D", "", contact_id)


async def find_or_create_candidate(db: AsyncSession, contact_id: str, name: str | None) -> Candidate:
    phone = contact_to_phone(contact_id)
    h = crypto.phone_hash(phone)
    c = (await db.execute(select(Candidate).where(Candidate.phone_hash == h))).scalar_one_or_none()
    if c is None:
        c = Candidate(full_name=name or "Без имени", phone_enc=crypto.encrypt(phone), phone_hash=h,
                      phone_last4=phone[-4:], source="WhatsApp (написал сам)", tags=[], applications=[])
        db.add(c)
        await db.flush()
    return c


async def on_inbound_hook(db: AsyncSession, conv: Conversation, msg: Message, inbound: InboundMessage) -> list[int]:
    """Передаёт входящее движку сценариев. Возвращает id исходящих сообщений для отправки."""
    from app.services import scenario_engine

    return await scenario_engine.handle_inbound(db, conv, inbound)


async def handle_inbound(db: AsyncSession, m: InboundMessage) -> list[int]:
    exists = (await db.execute(select(Message.id).where(Message.provider_message_id == m.provider_message_id))).scalar_one_or_none()
    if exists:
        return []  # повторная доставка webhook
    candidate = await find_or_create_candidate(db, m.contact_id, m.contact_name)
    conv = await get_or_create_conversation(db, candidate)
    msg = Message(conversation_id=conv.id, direction="in", type=m.type, body=m.text,
                  payload={"reply_id": m.reply_id, "raw": m.raw}, provider_message_id=m.provider_message_id,
                  status="received", created_at=m.timestamp)
    db.add(msg)
    if not conv.last_inbound_at or m.timestamp > conv.last_inbound_at:
        conv.last_inbound_at = m.timestamp
    conv.last_message_at = max(filter(None, [conv.last_message_at, m.timestamp]))
    conv.unread_count += 1
    for a in candidate.applications:
        if a.status in ("new", "in_campaign"):
            a.status = "replied"
    from app.services.scenario_engine import campaign_recipient

    if (rcp := await campaign_recipient(db, conv)) and not rcp.replied_at:
        rcp.replied_at = m.timestamp  # для воронки рассылки
    await db.flush()

    to_send: list[int] = []
    word = (m.text or "").strip().lower().strip(".!")
    lang = candidate.language or "ru"
    stop_words = {w.lower() for w in await settings_store.get_value(db, "stop_words")}
    if m.type == "text" and word in stop_words:
        if conv.current_node:  # остановить сценарий
            conv.current_node = None
            conv.context = {**(conv.context or {}), "outcome": "unsubscribed", "waiting": False}
        if not candidate.unsubscribed_at:
            candidate.unsubscribed_at = now()
            await log_action(db, user_id=None, action="candidate.unsubscribe", entity="candidate", entity_id=candidate.id,
                             diff={"word": word, "channel": conv.channel})
            reply = await queue_message(db, conv, OutText(STOP_REPLY.get(lang, STOP_REPLY["ru"])), allow_unsubscribed=True)
            to_send.append(reply.id)
        return to_send
    if m.type == "text" and word in START_WORDS and candidate.unsubscribed_at:
        candidate.unsubscribed_at = None
        await log_action(db, user_id=None, action="candidate.resubscribe", entity="candidate", entity_id=candidate.id)
        reply = await queue_message(db, conv, OutText(START_REPLY.get(lang, START_REPLY["ru"])))
        return [reply.id]
    if candidate.unsubscribed_at:
        return to_send
    if conv.mode == "bot":
        to_send += await on_inbound_hook(db, conv, msg, m)
    return to_send


async def handle_status(db: AsyncSession, st: StatusUpdate) -> None:
    msg = (await db.execute(select(Message).where(Message.provider_message_id == st.provider_message_id))).scalar_one_or_none()
    if msg is None:
        return
    if st.status == "failed":
        msg.status = "failed"
        msg.failed_at = st.timestamp
        msg.error = st.error
        return
    if st.status not in STATUS_RANK:
        return
    if STATUS_RANK.get(msg.status, -1) < STATUS_RANK[st.status] and msg.status != "failed":
        msg.status = st.status
    setattr(msg, f"{st.status}_at", getattr(msg, f"{st.status}_at", None) or st.timestamp)
    if st.status == "read" and not msg.delivered_at:
        msg.delivered_at = st.timestamp


@task
async def process_webhook_event(ctx: dict[str, Any], event_id: int) -> None:
    async with SessionLocal() as db:
        ev = await db.get(WebhookEvent, event_id)
        if ev is None or ev.processed_at:
            return
        to_send: list[int] = []
        try:
            inbound, statuses = get_adapter(ev.provider).parse_webhook(ev.raw)
            for m in inbound:
                to_send += await handle_inbound(db, m)
            for st in statuses:
                await handle_status(db, st)
            ev.processed_at = now()
            await db.commit()
        except Exception as e:  # noqa: BLE001
            await db.rollback()
            ev = await db.get(WebhookEvent, event_id)
            ev.error = f"{e.__class__.__name__}: {e}"[:2000]  # type: ignore[union-attr]
            await db.commit()
            log.exception("Ошибка обработки webhook %s", event_id)
            if not ctx.get("inline"):
                raise
            return
    await send_queued(to_send)


def is_mock() -> bool:
    return "graph.facebook.com" not in get_settings().wa_api_base
