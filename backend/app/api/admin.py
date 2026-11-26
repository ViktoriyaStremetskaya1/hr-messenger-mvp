from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import client_ip, get_current_user, require_roles
from app.models import AuditLog, Role, User
from app.schemas.common import ORM, Page
from app.services import settings_store
from app.services.audit import log_action

router = APIRouter(tags=["admin"])


@router.get("/settings")
async def get_settings_api(db: AsyncSession = Depends(get_session), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return await settings_store.get_all(db)


@router.patch("/settings")
async def patch_settings(
    values: dict[str, Any], request: Request, db: AsyncSession = Depends(get_session),
    user: User = Depends(require_roles(Role.admin, Role.lead)),
) -> dict[str, Any]:
    try:
        result = await settings_store.set_values(db, values)
    except KeyError as e:
        raise HTTPException(400, f"Неизвестная настройка: {e.args[0]}") from e
    await log_action(db, user_id=user.id, action="settings.update", diff=values, ip=client_ip(request))
    await db.commit()
    return result


class AuditOut(ORM):
    id: int
    user_id: int | None
    action: str
    entity: str | None
    entity_id: str | None
    diff: dict[str, Any]
    ip: str | None
    created_at: datetime




@router.get("/audit", response_model=Page[AuditOut])
async def audit_log(
    user_id: int | None = None,
    action: str | None = None,
    entity: str | None = None,
    entity_id: str | None = None,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_session),
    _: User = Depends(require_roles(Role.admin, Role.lead)),
):
    page_size = min(max(page_size, 1), 200)
    stmt = select(AuditLog)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action:
        stmt = stmt.where(AuditLog.action.startswith(action))
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    items = (
        await db.execute(stmt.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()
    return Page(items=items, total=total, page=page, page_size=page_size)
