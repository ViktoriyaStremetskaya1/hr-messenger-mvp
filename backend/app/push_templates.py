"""Подать шаблоны из app/whatsapp_templates.py на модерацию в Meta.

    python -m app.push_templates            # показать, что будет подано (ничего не отправляет)
    python -m app.push_templates --apply    # отправить

Нужны WA_API_BASE, WA_API_VERSION, WA_BUSINESS_ACCOUNT_ID, WA_ACCESS_TOKEN в окружении/.env.
Уже существующие в Meta шаблоны (то же имя и язык) пропускаются.
"""
import argparse
import asyncio
import sys

import httpx

from app.core.config import get_settings
from app.whatsapp_templates import TEMPLATES, to_meta_components


async def main(apply: bool, client: httpx.AsyncClient | None = None) -> int:
    s = get_settings()
    if not (s.wa_business_account_id and s.wa_access_token):
        print("Задайте WA_BUSINESS_ACCOUNT_ID и WA_ACCESS_TOKEN в .env")
        return 1
    base = f"{s.wa_api_base.rstrip('/')}/{s.wa_api_version}/{s.wa_business_account_id}/message_templates"
    headers = {"Authorization": f"Bearer {s.wa_access_token}"}
    async with (client or httpx.AsyncClient(timeout=30)) as c:
        c.headers.update(headers)
        existing: set[tuple[str, str]] = set()
        url: str | None = base + "?limit=100"
        while url:
            r = await c.get(url)
            if r.status_code >= 300:
                print(f"Не удалось получить список шаблонов: HTTP {r.status_code} {r.text[:300]}")
                return 1
            data = r.json()
            existing |= {(t["name"], t["language"].split("_")[0]) for t in data.get("data", [])}
            url = (data.get("paging") or {}).get("next")

        failed = 0
        for t in TEMPLATES:
            key = (t.name, t.language)
            if key in existing:
                print(f"= {t.name} [{t.language}] уже есть в Meta — пропускаю")
                continue
            payload = {"name": t.name, "language": t.language, "category": t.category, "components": to_meta_components(t)}
            if not apply:
                print(f"+ {t.name} [{t.language}] {t.category}: {t.body[:70]}…")
                continue
            r = await c.post(base, json=payload)
            if r.status_code < 300:
                print(f"✓ {t.name} [{t.language}] отправлен, статус: {r.json().get('status', '?')}")
            else:
                failed += 1
                err = r.json().get("error", {}) if r.headers.get("content-type", "").startswith("application/json") else {}
                print(f"✗ {t.name} [{t.language}]: {err.get('error_user_msg') or err.get('message') or r.text[:300]}")
        if not apply:
            print("\nЭто предпросмотр. Для отправки: python -m app.push_templates --apply")
        else:
            print("\nСтатус модерации — в WhatsApp Manager. После одобрения: «Шаблоны WhatsApp» → «Синхронизировать с Meta».")
        return 1 if failed else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true", help="действительно отправить в Meta")
    sys.exit(asyncio.run(main(p.parse_args().apply)))
