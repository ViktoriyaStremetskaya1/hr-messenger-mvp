"""Фоновые задачи. В проде выполняет воркер arq (Redis), в тестах — прямо в процессе (TASKS_INLINE=true)."""
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import get_settings

log = logging.getLogger(__name__)
_pool: ArqRedis | None = None
TASKS: dict[str, Callable[..., Awaitable[Any]]] = {}


def task(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    TASKS[fn.__name__] = fn
    return fn


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


async def get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings())
    return _pool


async def enqueue(name: str, *args: Any, defer_seconds: float | None = None, job_id: str | None = None) -> None:
    if get_settings().tasks_inline:
        if defer_seconds:  # отложенные задачи в inline-режиме не выполняем (их проверяют отдельно)
            log.info("inline: отложенная задача %s пропущена", name)
            return
        await TASKS[name]({"inline": True, "job_try": 1}, *args)
        return
    pool = await get_pool()
    await pool.enqueue_job(name, *args, _defer_by=defer_seconds, _job_id=job_id)
