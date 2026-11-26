from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.deps import client_ip, get_current_user
from app.core.security import SESSION_COOKIE, create_session_token, verify_password
from app.models import User
from app.schemas.users import LoginIn, UserOut
from app.services.audit import log_action

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
async def login(data: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_session)):
    user = (await db.execute(select(User).where(User.login == data.login.strip().lower()))).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(data.password, user.password_hash):
        await log_action(db, user_id=None, action="auth.login_failed", diff={"login": data.login}, ip=client_ip(request))
        await db.commit()
        raise HTTPException(401, "Неверный логин или пароль")
    user.last_login_at = datetime.now(UTC)
    await log_action(db, user_id=user.id, action="auth.login", ip=client_ip(request))
    await db.commit()
    s = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(user.id),
        httponly=True,
        secure=s.cookie_secure,
        samesite="strict",
        max_age=s.session_ttl_hours * 3600,
        path="/",
    )
    return user


@router.post("/logout", status_code=204)
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user
