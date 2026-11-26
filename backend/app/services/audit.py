from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def log_action(
    db: AsyncSession,
    *,
    user_id: int | None,
    action: str,
    entity: str | None = None,
    entity_id: Any = None,
    diff: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """Запись в журнал действий. Коммит — на вызывающей стороне (в той же транзакции)."""
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id is not None else None,
            diff=diff or {},
            ip=ip,
        )
    )


def changes(obj: Any, data: dict[str, Any]) -> dict[str, Any]:
    """Применяет data к объекту и возвращает diff {поле: [было, стало]}."""
    diff: dict[str, Any] = {}
    for k, v in data.items():
        old = getattr(obj, k)
        if old != v:
            diff[k] = [old, v]
            setattr(obj, k, v)
    return diff
