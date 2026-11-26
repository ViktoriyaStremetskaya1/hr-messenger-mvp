"""Настройки приложения, редактируемые из интерфейса (не секреты)."""
from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting

DEFAULTS: dict[str, Any] = {
    # Рабочие часы отправки, Asia/Almaty. days: 1=пн ... 7=вс
    "working_hours": {"start": "09:00", "end": "20:00", "days": [1, 2, 3, 4, 5, 6]},
    # Не чаще одного касания рассылкой в N дней на кандидата
    "touch_frequency_days": 3,
    # Лимиты отправки
    "rate_limit_per_minute": 60,
    "daily_send_limit": 2000,
    # Слово отписки (регистр не важен)
    "stop_words": ["стоп", "stop", "тоқта", "токта"],
    "feature_flags": {"ai": False},
}


async def get_all(db: AsyncSession) -> dict[str, Any]:
    result = deepcopy(DEFAULTS)
    rows = (await db.execute(select(AppSetting))).scalars().all()
    for r in rows:
        if r.key in result:
            result[r.key] = r.value
    return result


async def get_value(db: AsyncSession, key: str) -> Any:
    row = await db.get(AppSetting, key)
    return row.value if row else deepcopy(DEFAULTS[key])


async def set_values(db: AsyncSession, values: dict[str, Any]) -> dict[str, Any]:
    for k, v in values.items():
        if k not in DEFAULTS:
            raise KeyError(k)
        row = await db.get(AppSetting, k)
        if row:
            row.value = v
        else:
            db.add(AppSetting(key=k, value=v))
    await db.flush()
    return await get_all(db)
