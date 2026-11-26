"""Песочница WhatsApp Cloud API.

- Принимает запросы приложения так же, как graph.facebook.com (POST /{ver}/{phone_id}/messages,
  GET /{ver}/{waba_id}/message_templates), соблюдает правило 24-часового окна (ошибка 131047).
- Отправляет в приложение подписанные webhooks: статусы sent/delivered/read и входящие сообщения.
- UI «телефон кандидата»: http://localhost:9000 — можно отвечать текстом и нажимать кнопки.

Состояние хранится в памяти процесса.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.wamock.templates import MOCK_TEMPLATES

log = logging.getLogger("wa-mock")
APP_SECRET = os.environ.get("WA_APP_SECRET", "")
ACCESS_TOKEN = os.environ.get("WA_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("WA_PHONE_NUMBER_ID", "")
WEBHOOK_URL = os.environ.get("MOCK_WEBHOOK_URL", "http://localhost:8000/api/webhooks/whatsapp")
STATUS_DELAY = float(os.environ.get("MOCK_STATUS_DELAY", "0.7"))
WINDOW = 24 * 3600

app = FastAPI(title="WhatsApp Cloud API mock")


class Store:
    def __init__(self) -> None:
        self.chats: dict[str, dict[str, Any]] = {}

    def chat(self, wa_id: str, name: str | None = None) -> dict[str, Any]:
        c = self.chats.setdefault(wa_id, {"wa_id": wa_id, "name": name or f"+{wa_id}", "messages": [], "last_inbound": 0.0})
        if name:
            c["name"] = name
        return c


store = Store()


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()


async def post_webhook(value: dict[str, Any]) -> None:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "MOCK_WABA", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "mock", "phone_number_id": PHONE_NUMBER_ID}, **value}}]}],
    }
    body = json.dumps(payload, ensure_ascii=False).encode()
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(WEBHOOK_URL, content=body, headers={"Content-Type": "application/json", "X-Hub-Signature-256": sign(body)})
            if r.status_code >= 300:
                log.warning("webhook -> %s: %s", r.status_code, r.text[:200])
    except httpx.HTTPError as e:
        log.warning("webhook недоступен: %s", e)


async def send_status(wa_id: str, wamid: str, status: str, delay: float = 0) -> None:
    if delay:
        await asyncio.sleep(delay)
    for m in store.chat(wa_id)["messages"]:
        if m["id"] == wamid:
            m["status"] = status
    await post_webhook({"statuses": [{"id": wamid, "status": status, "timestamp": str(int(time.time())), "recipient_id": wa_id}]})


def err(code: int, message: str, http: int = 400) -> HTTPException:
    return HTTPException(http, {"error": {"message": message, "type": "OAuthException", "code": code}})


@app.exception_handler(HTTPException)
async def _http_exc(request: Request, exc: HTTPException):
    from fastapi.responses import JSONResponse

    return JSONResponse(exc.detail if isinstance(exc.detail, dict) else {"error": {"message": exc.detail}}, status_code=exc.status_code)


def _render_template(name: str, lang: str, params: list[str]) -> tuple[str, list[str]]:
    for t in MOCK_TEMPLATES:
        if t["name"] == name and t["language"] == lang:
            body, buttons = "", []
            for comp in t["components"]:
                if comp["type"] == "BODY":
                    body = comp["text"]
                if comp["type"] == "BUTTONS":
                    buttons = [b["text"] for b in comp["buttons"]]
            for i, p in enumerate(params, 1):
                body = body.replace(f"{{{{{i}}}}}", p)
            return body, buttons
    raise err(132001, f"Template name does not exist in the translation ({name}, {lang})")


@app.post("/{version}/{phone_id}/messages")
async def send_message(version: str, phone_id: str, request: Request, bg: BackgroundTasks, authorization: str = Header("")):
    if ACCESS_TOKEN and authorization != f"Bearer {ACCESS_TOKEN}":
        raise err(190, "Invalid OAuth access token", 401)
    data = await request.json()
    wa_id = str(data.get("to", "")).lstrip("+")
    t = data.get("type")
    chat = store.chat(wa_id)
    if t != "template" and time.time() - chat["last_inbound"] > WINDOW:
        raise err(131047, "Re-engagement message: more than 24 hours have passed since the recipient last replied")
    msg: dict[str, Any] = {"id": f"wamid.MOCK{uuid.uuid4().hex[:20]}", "dir": "out", "status": "accepted", "ts": time.time()}
    if t == "text":
        msg.update(kind="text", text=data["text"]["body"])
    elif t == "template":
        tpl = data["template"]
        params = [p["text"] for c in tpl.get("components", []) if c["type"] == "body" for p in c.get("parameters", [])]
        text, buttons = _render_template(tpl["name"], tpl["language"]["code"], params)
        msg.update(kind="template", text=text, buttons=[{"id": b, "title": b, "quick": True} for b in buttons])
    elif t == "interactive":
        i = data["interactive"]
        msg.update(kind=i["type"], text=i["body"]["text"])
        if i["type"] == "button":
            msg["buttons"] = [{"id": b["reply"]["id"], "title": b["reply"]["title"]} for b in i["action"]["buttons"]]
        elif i["type"] == "list":
            msg["list_label"] = i["action"]["button"]
            msg["rows"] = [r for s in i["action"]["sections"] for r in s["rows"]]
    else:
        raise err(100, f"Unsupported message type {t}")
    chat["messages"].append(msg)
    bg.add_task(send_status, wa_id, msg["id"], "sent", STATUS_DELAY)
    bg.add_task(send_status, wa_id, msg["id"], "delivered", STATUS_DELAY)
    return {"messaging_product": "whatsapp", "contacts": [{"input": wa_id, "wa_id": wa_id}], "messages": [{"id": msg["id"]}]}


@app.get("/{version}/{waba_id}/message_templates")
async def templates(version: str, waba_id: str, authorization: str = Header("")):
    if ACCESS_TOKEN and authorization != f"Bearer {ACCESS_TOKEN}":
        raise err(190, "Invalid OAuth access token", 401)
    return {"data": MOCK_TEMPLATES, "paging": {}}


# ---------- UI «телефон кандидата» ----------

class InboundIn(BaseModel):
    wa_id: str
    name: str | None = None
    text: str | None = None
    reply_id: str | None = None
    reply_kind: str | None = None  # button | list | quick


@app.get("/", response_class=HTMLResponse)
async def ui():
    return (Path(__file__).parent / "phone.html").read_text(encoding="utf-8")


@app.get("/mock/chats")
async def chats():
    return sorted(store.chats.values(), key=lambda c: -(c["messages"][-1]["ts"] if c["messages"] else 0))


@app.post("/mock/inbound")
async def inbound(data: InboundIn):
    wa_id = "".join(ch for ch in data.wa_id if ch.isdigit())
    if len(wa_id) == 10:
        wa_id = "7" + wa_id
    if len(wa_id) == 11 and wa_id.startswith("8"):
        wa_id = "7" + wa_id[1:]
    chat = store.chat(wa_id, data.name)
    now = time.time()
    chat["last_inbound"] = now
    wamid = f"wamid.MOCKIN{uuid.uuid4().hex[:18]}"
    m: dict[str, Any] = {"from": wa_id, "id": wamid, "timestamp": str(int(now))}
    if data.reply_id and data.reply_kind == "quick":
        m.update(type="button", button={"payload": data.reply_id, "text": data.text})
    elif data.reply_id and data.reply_kind == "list":
        m.update(type="interactive", interactive={"type": "list_reply", "list_reply": {"id": data.reply_id, "title": data.text}})
    elif data.reply_id:
        m.update(type="interactive", interactive={"type": "button_reply", "button_reply": {"id": data.reply_id, "title": data.text}})
    else:
        m.update(type="text", text={"body": data.text or ""})
    chat["messages"].append({"id": wamid, "dir": "in", "kind": "text", "text": data.text, "ts": now})
    await post_webhook({"contacts": [{"profile": {"name": chat["name"]}, "wa_id": wa_id}], "messages": [m]})
    return {"ok": True, "wa_id": wa_id}


@app.post("/mock/read/{wa_id}")
async def mark_read(wa_id: str):
    for m in store.chat(wa_id)["messages"]:
        if m["dir"] == "out" and m.get("status") in ("sent", "delivered"):
            await send_status(wa_id, m["id"], "read")
    return {"ok": True}


@app.post("/mock/expire/{wa_id}")
async def expire_window(wa_id: str):
    """Для проверки: «состарить» последнее входящее на 25 часов (только в моке)."""
    store.chat(wa_id)["last_inbound"] -= 25 * 3600
    return {"ok": True, "note": "окно закрыто в моке; в приложении окно считается по времени входящего"}


@app.get("/mock/health")
async def health():
    return {"ok": True, "time": datetime.now(UTC).isoformat()}
