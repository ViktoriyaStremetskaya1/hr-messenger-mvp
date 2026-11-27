"""Создание администратора или сброс его пароля из командной строки.

    python -m app.create_admin --login admin --name "Иванов Иван"

Пароль спрашивается дважды (ввод не отображается). Для неинтерактивного запуска
пароль можно передать в переменной окружения ADMIN_PASSWORD.

Если пользователь с таким логином уже есть, ему задаётся новый пароль,
роль «admin» и он снова становится активным. Каждое действие пишется в журнал.
"""
import argparse
import asyncio
import getpass
import os
import re
import sys
from collections.abc import Sequence

from sqlalchemy import select

from app.core.db import SessionLocal, engine
from app.core.security import hash_password
from app.models import User
from app.services.audit import log_action

MIN_PASSWORD_LEN = 10
MAX_PASSWORD_LEN = 128
LOGIN_RE = re.compile(r"^[a-zA-Z0-9._-]{3,64}$")
AUDIT_ACTION = "user.create_admin_cli"


class AdminError(Exception):
    """Ошибка ввода: сообщение показывается пользователю как есть."""


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LEN:
        raise AdminError(f"Пароль слишком короткий: нужно не меньше {MIN_PASSWORD_LEN} символов.")
    if len(password) > MAX_PASSWORD_LEN:
        raise AdminError(f"Пароль слишком длинный: не больше {MAX_PASSWORD_LEN} символов.")
    if password.strip() != password:
        raise AdminError("Пароль не должен начинаться или заканчиваться пробелом.")


def read_password(env: dict[str, str] | None = None, prompt=getpass.getpass) -> str:
    """Пароль из ADMIN_PASSWORD или с клавиатуры (дважды, с проверкой совпадения)."""
    env = os.environ if env is None else env
    password = env.get("ADMIN_PASSWORD")
    if password:
        validate_password(password)
        return password
    password = prompt(f"Пароль (не меньше {MIN_PASSWORD_LEN} символов): ")
    validate_password(password)
    if prompt("Повторите пароль: ") != password:
        raise AdminError("Пароли не совпадают.")
    return password


async def create_or_reset_admin(login: str, full_name: str | None, password: str) -> str:
    """Возвращает "created" или "reset"."""
    login = login.strip()
    if not LOGIN_RE.match(login):
        raise AdminError("Логин: 3–64 символа, латинские буквы, цифры, точка, дефис, подчёркивание.")
    validate_password(password)
    full_name = (full_name or "").strip() or None
    if full_name and len(full_name) > 255:
        raise AdminError("ФИО слишком длинное (не больше 255 символов).")

    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.login == login))).scalar_one_or_none()
        if user is None:
            if not full_name:
                raise AdminError("Для нового пользователя укажите ФИО: --name \"Фамилия Имя\".")
            user = User(login=login, full_name=full_name, role="admin", is_active=True,
                        password_hash=hash_password(password))
            db.add(user)
            await db.flush()
            result = "created"
            diff = {"login": login, "full_name": full_name, "role": "admin"}
        else:
            diff = {"password": "сброшен"}
            if user.role != "admin":
                diff["role"] = [user.role, "admin"]
                user.role = "admin"
            if not user.is_active:
                diff["is_active"] = [False, True]
                user.is_active = True
            if full_name and full_name != user.full_name:
                diff["full_name"] = [user.full_name, full_name]
                user.full_name = full_name
            user.password_hash = hash_password(password)
            result = "reset"
        diff["mode"] = result
        await log_action(db, user_id=None, action=AUDIT_ACTION, entity="user", entity_id=user.id, diff=diff,
                         ip="cli")
        await db.commit()
    return result


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m app.create_admin",
        description="Создать администратора или сбросить пароль существующему пользователю.",
    )
    p.add_argument("--login", required=True, help="логин для входа (латиница, цифры, . _ -)")
    p.add_argument("--name", default=None, help="ФИО (обязательно для нового пользователя)")
    return p.parse_args(argv)


async def main_async(argv: Sequence[str] | None = None, env: dict[str, str] | None = None,
                     prompt=getpass.getpass) -> int:
    args = parse_args(argv)
    try:
        password = read_password(env, prompt)
        result = await create_or_reset_admin(args.login, args.name, password)
    except AdminError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1
    if result == "created":
        print(f"Готово: администратор «{args.login}» создан. Войдите с этим логином и паролем.")
    else:
        print(f"Готово: пароль пользователя «{args.login}» изменён, учётная запись активна, роль — администратор.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    async def _run() -> int:
        try:
            return await main_async(argv)
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except (KeyboardInterrupt, EOFError):
        print("\nОтменено.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
