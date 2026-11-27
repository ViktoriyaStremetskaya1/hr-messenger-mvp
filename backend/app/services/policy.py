"""Правила отправки: рабочие часы (Asia/Almaty), частота касаний."""
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def _hm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def in_working_hours(wh: dict[str, Any], at: datetime | None = None) -> bool:
    local = (at or datetime.now(UTC)).astimezone(tz())
    return local.isoweekday() in wh["days"] and _hm(wh["start"]) <= local.time() < _hm(wh["end"])


def next_working_moment(wh: dict[str, Any], at: datetime | None = None) -> datetime:
    """Ближайший момент внутри рабочих часов (сам `at`, если он уже рабочий)."""
    at = at or datetime.now(UTC)
    if in_working_hours(wh, at):
        return at
    local = at.astimezone(tz())
    start, end = _hm(wh["start"]), _hm(wh["end"])
    for add in range(0, 8):
        day = (local + timedelta(days=add)).date()
        if datetime(day.year, day.month, day.day, tzinfo=tz()).isoweekday() not in wh["days"]:
            continue
        candidate = datetime.combine(day, start, tzinfo=tz())
        if add == 0 and local.time() >= end:
            continue
        if candidate >= local or add == 0:
            return max(candidate, local).astimezone(UTC)
    return at  # дни не заданы — не блокируем


def touch_allowed(last_touch_at: datetime | None, frequency_days: int, at: datetime | None = None) -> bool:
    if not last_touch_at or frequency_days <= 0:
        return True
    return (at or datetime.now(UTC)) - last_touch_at >= timedelta(days=frequency_days)
