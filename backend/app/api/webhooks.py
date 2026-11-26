import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.registry import get_adapter
from app.core.config import get_settings
from app.core.db import get_session
from app.models import WebhookEvent
from app.tasks import enqueue

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
log = logging.getLogger(__name__)


@router.get("/whatsapp", response_class=PlainTextResponse)
async def verify(
    mode: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
):
    """Подтверждение webhook в кабинете Meta."""
    expected = get_settings().wa_verify_token
    if mode == "subscribe" and expected and token == expected:
        return challenge
    raise HTTPException(403, "verify token mismatch")


@router.post("/whatsapp")
async def receive(request: Request, db: AsyncSession = Depends(get_session)) -> dict[str, bool]:
    raw = await request.body()
    adapter = get_adapter("whatsapp")
    if not adapter.verify_signature(raw, {k.lower(): v for k, v in request.headers.items()}):
        log.warning("webhook: неверная подпись")
        raise HTTPException(401, "invalid signature")
    try:
        payload = json.loads(raw)
    except ValueError as e:
        raise HTTPException(400, "invalid json") from e
    ev = WebhookEvent(provider="whatsapp", raw=payload)
    db.add(ev)
    await db.commit()
    await enqueue("process_webhook_event", ev.id)
    return {"ok": True}
