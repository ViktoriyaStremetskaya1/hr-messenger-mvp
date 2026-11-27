import hashlib
import hmac
import json
import time
import uuid

SECRET = b"test-app-secret"


def envelope(value: dict) -> dict:
    return {"object": "whatsapp_business_account", "entry": [{"id": "waba-1", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"display_phone_number": "77769595468", "phone_number_id": "1234567890"}, **value}}]}]}


def text_msg(wa_id: str, text: str, name: str = "Кандидат", wamid: str | None = None) -> dict:
    return envelope({"contacts": [{"profile": {"name": name}, "wa_id": wa_id}], "messages": [
        {"from": wa_id, "id": wamid or f"wamid.T{uuid.uuid4().hex}", "timestamp": str(int(time.time())), "type": "text", "text": {"body": text}}]})


def status(wamid: str, st: str, wa_id: str = "77770000000", errors: list | None = None) -> dict:
    s = {"id": wamid, "status": st, "timestamp": str(int(time.time())), "recipient_id": wa_id}
    if errors:
        s["errors"] = errors
    return envelope({"statuses": [s]})


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()


async def post_webhook(client, payload: dict, signature: str | None = None):
    body = json.dumps(payload, ensure_ascii=False).encode()
    return await client.post("/api/webhooks/whatsapp", content=body,
                             headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature or sign(body)})


def button_reply(wa_id: str, reply_id: str, title: str) -> dict:
    return envelope({"contacts": [{"profile": {"name": "Кандидат"}, "wa_id": wa_id}], "messages": [
        {"from": wa_id, "id": f"wamid.B{uuid.uuid4().hex}", "timestamp": str(int(time.time())), "type": "interactive",
         "interactive": {"type": "button_reply", "button_reply": {"id": reply_id, "title": title}}}]})


def list_reply(wa_id: str, reply_id: str, title: str) -> dict:
    return envelope({"contacts": [{"profile": {"name": "Кандидат"}, "wa_id": wa_id}], "messages": [
        {"from": wa_id, "id": f"wamid.L{uuid.uuid4().hex}", "timestamp": str(int(time.time())), "type": "interactive",
         "interactive": {"type": "list_reply", "list_reply": {"id": reply_id, "title": title}}}]})


def quick_reply(wa_id: str, text: str) -> dict:
    """Нажатие кнопки быстрого ответа в шаблоне."""
    return envelope({"contacts": [{"profile": {"name": "Кандидат"}, "wa_id": wa_id}], "messages": [
        {"from": wa_id, "id": f"wamid.Q{uuid.uuid4().hex}", "timestamp": str(int(time.time())), "type": "button",
         "button": {"payload": text, "text": text}}]})
