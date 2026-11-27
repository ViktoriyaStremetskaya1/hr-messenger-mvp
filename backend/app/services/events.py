"""События для обновления интерфейса в реальном времени (Redis pub/sub → SSE)."""
import json
import logging
from typing import Any

from redis.asyncio import Redis

from app.core.config import get_settings

CHANNEL = "hr:events"
log = logging.getLogger(__name__)
_redis: Redis | None = None


def redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


async def publish(event: dict[str, Any]) -> None:
    """Не роняет основную логику, если Redis недоступен."""
    try:
        await redis().publish(CHANNEL, json.dumps(event, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        log.debug("events: %s", e)
