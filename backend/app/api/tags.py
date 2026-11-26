from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import client_ip, get_current_user, require_roles
from app.models import Role, Tag, User
from app.schemas.candidates import TagIn, TagOut
from app.services.audit import log_action

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("", response_model=list[TagOut])
async def list_tags(db: AsyncSession = Depends(get_session), _: User = Depends(get_current_user)):
    return (await db.execute(select(Tag).order_by(Tag.name))).scalars().all()


@router.post("", response_model=TagOut, status_code=201)
async def create_tag(data: TagIn, request: Request, db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    name = data.name.strip()
    if (await db.execute(select(Tag).where(Tag.name == name))).scalar_one_or_none():
        raise HTTPException(409, "Такой тег уже есть")
    tag = Tag(name=name, color=data.color)
    db.add(tag)
    await db.flush()
    await log_action(db, user_id=user.id, action="tag.create", entity="tag", entity_id=tag.id, diff={"name": name}, ip=client_ip(request))
    await db.commit()
    return tag


@router.delete("/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: int, request: Request, db: AsyncSession = Depends(get_session),
    user: User = Depends(require_roles(Role.admin, Role.lead)),
):
    tag = await db.get(Tag, tag_id)
    if not tag:
        raise HTTPException(404, "Тег не найден")
    await db.delete(tag)
    await log_action(db, user_id=user.id, action="tag.delete", entity="tag", entity_id=tag_id, diff={"name": tag.name}, ip=client_ip(request))
    await db.commit()
