"""Воркер фоновых задач: arq app.worker.WorkerSettings"""
from app.core.logging import setup_logging
from app.services import messaging  # noqa: F401  регистрирует задачи
from app.tasks import TASKS, redis_settings

setup_logging()


class WorkerSettings:
    functions = list(TASKS.values())
    redis_settings = redis_settings()
    max_tries = 5
    job_timeout = 60
