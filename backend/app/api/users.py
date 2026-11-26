from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import client_ip, get_current_user, require_roles
from app.core.security import hash_password
from app.models import Role, User
from app.schemas.users import UserCreate, UserOut, UserUpdate
from app.services.audit import changes, log_action

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
async def list_users(db: AsyncSession = Depends(get_session), _: User = Depends(get_current_user)):
    return (await db.execute(select(User).order_by(User.full_name))).scalars().all()


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    data: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_session),
    actor: User = Depends(require_roles(Role.admin)),
):
    login = data.login.lower()
    if (await db.execute(select(User).where(User.login == login))).scalar_one_or_none():
        raise HTTPException(409, "Такой логин уже есть")
    user = User(login=login, full_name=data.full_name, role=data.role, password_hash=hash_password(data.password))
    db.add(user)
    await db.flush()
    await log_action(
        db, user_id=actor.id, action="user.create", entity="user", entity_id=user.id,
        diff={"login": login, "role": data.role}, ip=client_ip(request),
    )
    await db.commit()
    return user


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    data: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_session),
    actor: User = Depends(require_roles(Role.admin)),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    payload = data.model_dump(exclude_unset=True)
    password = payload.pop("password", None)
    if user.id == actor.id and (payload.get("is_active") is False or payload.get("role", Role.admin) != Role.admin):
        raise HTTPException(400, "Нельзя отключить себя или снять с себя роль администратора")
    diff = changes(user, payload)
    if password:
        user.password_hash = hash_password(password)
        diff["password"] = "changed"
    await log_action(db, user_id=actor.id, action="user.update", entity="user", entity_id=user.id, diff=diff, ip=client_ip(request))
    await db.commit()
    return user
