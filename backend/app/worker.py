"""Воркер фоновых задач: arq app.worker.WorkerSettings"""
from app.core.logging import setup_logging
from arq import cron

from app.services import campaigns, messaging, scenario_engine  # noqa: F401  регистрирует задачи
from app.services.interviews import send_due_reminders
from app.tasks import TASKS, redis_settings

setup_logging()


class WorkerSettings:
    functions = list(TASKS.values())
    redis_settings = redis_settings()
    cron_jobs = [cron(send_due_reminders, minute=set(range(0, 60, 5)), run_at_startup=True)]
    max_tries = 5
    job_timeout = 60
