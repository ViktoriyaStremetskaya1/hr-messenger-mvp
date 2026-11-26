"""WhatsApp Business Cloud API (Meta). Только официальный API.

Ограничения WhatsApp, которые учитываются здесь:
- reply-кнопки: до 3 шт., заголовок до 20 символов;
- список: до 10 строк, заголовок строки до 24 символов, описание до 72;
- текст интерактивного сообщения до 1024 символов.
"""
import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any

import httpx

from app.channels.base import (
    InboundMessage,
    OutButtons,
    Outbound,
    OutList,
    OutTemplate,
    OutText,
    SendResult,
    StatusUpdate,
)
from app.core.config import Settings

# Ошибки Meta, после которых имеет смысл повторить попытку
RETRYABLE_CODES = {"4", "80007", "130429", "131016", "131048", "131056", "133004"}
# 131047 — истекло 24-часовое окно (нужен шаблон)
WINDOW_EXPIRED_CODE = "131047"


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def build_payload(to: str, m: Outbound) -> dict[str, Any]:
    base: dict[str, Any] = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to}
    if isinstance(m, OutText):
        return {**base, "type": "text", "text": {"body": _clip(m.text, 4096), "preview_url": False}}
    if isinstance(m, OutTemplate):
        tpl: dict[str, Any] = {"name": m.name, "language": {"code": m.language}}
        if m.body_params:
            tpl["components"] = [
                {"type": "body", "parameters": [{"type": "text", "text": p} for p in m.body_params]}
            ]
        return {**base, "type": "template", "template": tpl}
    if isinstance(m, OutButtons):
        if not 1 <= len(m.buttons) <= 3:
            raise ValueError("WhatsApp допускает от 1 до 3 кнопок")
        inter: dict[str, Any] = {
            "type": "button",
            "body": {"text": _clip(m.text, 1024)},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b.id[:256], "title": _clip(b.title, 20)}} for b in m.buttons
                ]
            },
        }
        if m.header:
            inter["header"] = {"type": "text", "text": _clip(m.header, 60)}
        if m.footer:
            inter["footer"] = {"text": _clip(m.footer, 60)}
        return {**base, "type": "interactive", "interactive": inter}
    if isinstance(m, OutList):
        if not 1 <= len(m.rows) <= 10:
            raise ValueError("В списке WhatsApp от 1 до 10 строк")
        rows = []
        for r in m.rows:
            row = {"id": r.id[:200], "title": _clip(r.title, 24)}
            if r.description:
                row["description"] = _clip(r.description, 72)
            rows.append(row)
        return {
            **base,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": _clip(m.text, 1024)},
                "action": {
                    "button": _clip(m.button_label, 20),
                    "sections": [{"title": _clip(m.section_title or "Варианты", 24), "rows": rows}],
                },
            },
        }
    raise TypeError(f"Неизвестный тип сообщения: {type(m)}")


def _ts(v: str | int | None) -> datetime:
    try:
        return datetime.fromtimestamp(int(v), UTC)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return datetime.now(UTC)


class WhatsAppCloudAdapter:
    channel = "whatsapp"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.s = settings
        self._client = client

    @property
    def _base(self) -> str:
        return f"{self.s.wa_api_base.rstrip('/')}/{self.s.wa_api_version}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.s.wa_access_token}"}

    async def _request(self, method: str, url: str, **kw: Any) -> httpx.Response:
        if self._client is not None:
            return await self._client.request(method, url, headers=self._headers(), **kw)
        async with httpx.AsyncClient(timeout=20) as c:
            return await c.request(method, url, headers=self._headers(), **kw)

    async def send(self, to: str, message: Outbound) -> SendResult:
        to = to.lstrip("+")
        payload = build_payload(to, message)
        try:
            r = await self._request("POST", f"{self._base}/{self.s.wa_phone_number_id}/messages", json=payload)
        except httpx.HTTPError as e:
            return SendResult(ok=False, error=f"сеть: {e.__class__.__name__}", retryable=True)
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code < 300 and data.get("messages"):
            return SendResult(ok=True, provider_message_id=data["messages"][0]["id"])
        err = data.get("error", {})
        code = str(err.get("code", r.status_code))
        return SendResult(
            ok=False,
            error_code=code,
            error=err.get("message") or f"HTTP {r.status_code}",
            retryable=code in RETRYABLE_CODES or r.status_code >= 500,
        )

    def verify_signature(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        sig = headers.get("x-hub-signature-256", "")
        if not self.s.wa_app_secret or not sig.startswith("sha256="):
            return False
        expected = hmac.new(self.s.wa_app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig[7:])

    def parse_webhook(self, payload: dict[str, Any]) -> tuple[list[InboundMessage], list[StatusUpdate]]:
        inbound: list[InboundMessage] = []
        statuses: list[StatusUpdate] = []
        if payload.get("object") != "whatsapp_business_account":
            return inbound, statuses
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") != "messages":
                    continue
                value = change.get("value", {})
                names = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts", [])}
                for m in value.get("messages", []):
                    inbound.append(self._parse_message(m, names))
                for st in value.get("statuses", []):
                    errors = st.get("errors") or []
                    err = None
                    if errors:
                        e = errors[0]
                        err = f"{e.get('code')}: {e.get('title') or e.get('message')}"
                    statuses.append(
                        StatusUpdate(provider_message_id=st["id"], status=st.get("status", ""), timestamp=_ts(st.get("timestamp")), error=err)
                    )
        return inbound, statuses

    @staticmethod
    def _parse_message(m: dict[str, Any], names: dict[str, str | None]) -> InboundMessage:
        t = m.get("type")
        base = dict(provider_message_id=m["id"], contact_id=m["from"], contact_name=names.get(m["from"]),
                    timestamp=_ts(m.get("timestamp")), raw=m)
        if t == "text":
            return InboundMessage(**base, type="text", text=(m.get("text") or {}).get("body", ""))
        if t == "interactive":
            i = m.get("interactive", {})
            if i.get("type") == "button_reply":
                r = i["button_reply"]
                return InboundMessage(**base, type="button_reply", text=r.get("title"), reply_id=r.get("id"))
            if i.get("type") == "list_reply":
                r = i["list_reply"]
                return InboundMessage(**base, type="list_reply", text=r.get("title"), reply_id=r.get("id"))
        if t == "button":  # quick reply кнопка шаблона
            b = m.get("button", {})
            return InboundMessage(**base, type="button_reply", text=b.get("text"), reply_id=b.get("payload") or b.get("text"))
        if t in ("image", "document", "audio", "video", "voice", "sticker", "location", "contacts"):
            caption = (m.get(t) or {}).get("caption") if isinstance(m.get(t), dict) else None
            return InboundMessage(**base, type="media", text=caption or f"[{t}]")
        return InboundMessage(**base, type="unsupported", text=f"[{t}]")

    async def list_templates(self) -> list[dict[str, Any]]:
        if not self.s.wa_business_account_id:
            return []
        out: list[dict[str, Any]] = []
        url: str | None = f"{self._base}/{self.s.wa_business_account_id}/message_templates?limit=100"
        while url:
            r = await self._request("GET", url)
            r.raise_for_status()
            data = r.json()
            out.extend(data.get("data", []))
            url = (data.get("paging") or {}).get("next")
        return out
