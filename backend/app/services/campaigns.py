"""Исполнение рассылок.

Каждую минуту (тик) берётся порция получателей размером rate_limit_per_minute.
Для каждого проверяется: отписка → частота касаний → нет ли уже идущего сценария.
Затем запускается сценарий рассылки (первое сообщение — шаблон). Вне рабочих часов и при
исчерпании суточного лимита тик переносится на ближайшее разрешённое время.
"""
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.models import Campaign, CampaignRecipient, Candidate, Conversation, Message, Scenario
from app.services import messaging, policy, scenario_engine, settings_store
from app.services.segments import segment_query
from app.tasks import enqueue, task

log = logging.getLogger(__name__)
TICK_SECONDS = 60


def now() -> datetime:
    return datetime.now(UTC)


async def sent_today(db: AsyncSession) -> int:
    local_midnight = now().astimezone(policy.tz()).replace(hour=0, minute=0, second=0, microsecond=0)
    q = select(func.count()).select_from(Message).where(
        Message.campaign_id.isnot(None), Message.type == "template", Message.created_at >= local_midnight)
    return (await db.execute(q)).scalar_one()


async def eligibility(db: AsyncSession, candidate: Candidate, frequency_days: int) -> str | None:
    """Причина пропуска или None, если писать можно."""
    if candidate.unsubscribed_at:
        return "unsubscribed"
    if not policy.touch_allowed(candidate.last_touch_at, frequency_days):
        return "frequency"
    conv = (await db.execute(select(Conversation).where(Conversation.candidate_id == candidate.id))).scalar_one_or_none()
    if conv is not None and scenario_engine.is_active(conv):
        return "active_scenario"
    return None


async def preview(db: AsyncSession, segment: dict[str, Any]) -> dict[str, Any]:
    ids = list((await db.execute(segment_query(segment))).scalars().all())
    freq = int(await settings_store.get_value(db, "touch_frequency_days"))
    excluded = {"unsubscribed": 0, "frequency": 0, "active_scenario": 0}
    sample: list[str] = []
    for i in range(0, len(ids), 500):
        rows = (await db.execute(select(Candidate).where(Candidate.id.in_(ids[i:i + 500])))).scalars().all()
        for c in rows:
            reason = await eligibility(db, c, freq)
            if reason:
                excluded[reason] += 1
            elif len(sample) < 5:
                sample.append(c.full_name)
    return {"total": len(ids), "eligible": len(ids) - sum(excluded.values()), "excluded": excluded, "sample": sample}


async def snapshot_recipients(db: AsyncSession, campaign: Campaign) -> int:
    ids = list((await db.execute(segment_query(campaign.segment))).scalars().all())
    existing = set((await db.execute(select(CampaignRecipient.candidate_id).where(CampaignRecipient.campaign_id == campaign.id))).scalars().all())
    new = [cid for cid in ids if cid not in existing]
    db.add_all([CampaignRecipient(campaign_id=campaign.id, candidate_id=cid, status="queued") for cid in new])
    await db.flush()
    return len(new)


async def schedule_tick(campaign_id: int, at: datetime | None = None) -> None:
    delay = max(0.0, ((at or now()) - now()).total_seconds())
    await enqueue("campaign_tick", campaign_id, defer_seconds=delay or None,
                  job_id=f"campaign:{campaign_id}:{int((at or now()).timestamp())}")


@task
async def campaign_tick(ctx: dict[str, Any], campaign_id: int) -> None:
    async with SessionLocal() as db:
        camp = await db.get(Campaign, campaign_id)
        if camp is None or camp.status not in ("scheduled", "running"):
            return
        if camp.scheduled_at and camp.scheduled_at > now() + timedelta(seconds=5):
            await schedule_tick(camp.id, camp.scheduled_at)
            return
        s = await settings_store.get_all(db)
        wh = s["working_hours"]
        nxt = policy.next_working_moment(wh)
        if nxt > now() + timedelta(seconds=5):
            if camp.status == "scheduled":
                camp.status = "running"
                camp.started_at = camp.started_at or now()
                await db.commit()
            await schedule_tick(camp.id, nxt)
            return
        daily_left = int(s["daily_send_limit"]) - await sent_today(db)
        if daily_left <= 0:
            tomorrow = (now().astimezone(policy.tz()) + timedelta(days=1)).replace(hour=0, minute=1).astimezone(UTC)
            await schedule_tick(camp.id, policy.next_working_moment(wh, tomorrow))
            return
        batch = min(int(s["rate_limit_per_minute"]), daily_left)
        if camp.status == "scheduled":
            camp.status = "running"
            camp.started_at = now()
        scenario = await db.get(Scenario, camp.scenario_id)
        recipients = (await db.execute(
            select(CampaignRecipient).where(CampaignRecipient.campaign_id == camp.id, CampaignRecipient.status == "queued")
            .order_by(CampaignRecipient.id).limit(batch))).scalars().all()
        to_send: list[list[int]] = []
        for r in recipients:
            r.processed_at = now()
            cand = await db.get(Candidate, r.candidate_id)
            if cand is None or cand.anonymized_at:
                r.status, r.skip_reason = "skipped", "deleted"
                continue
            reason = await eligibility(db, cand, int(s["touch_frequency_days"]))
            if reason:
                r.status, r.skip_reason = "skipped", reason
                continue
            if scenario is None or not scenario.is_active:
                r.status, r.skip_reason, r.error = "failed", "error", "сценарий удалён или выключен"
                continue
            try:
                async with db.begin_nested():
                    conv = await messaging.get_or_create_conversation(db, cand)
                    ids = await scenario_engine.start(db, conv, scenario, vacancy_id=camp.vacancy_id,
                                                      user_id=camp.created_by, campaign_id=camp.id)
                    if conv.context.get("outcome") == "error":
                        raise scenario_engine.ScenarioError(conv.context.get("reason") or "ошибка сценария")
            except (scenario_engine.ScenarioError, messaging.MessagingError) as e:
                r.status, r.skip_reason, r.error = "failed", "error", str(e)[:500]
                continue
            r.status = "sent"
            r.message_id = ids[0] if ids else None
            if ids:
                to_send.append(ids)
        left = (await db.execute(select(func.count()).select_from(CampaignRecipient).where(
            CampaignRecipient.campaign_id == camp.id, CampaignRecipient.status == "queued"))).scalar_one()
        if left == 0:
            camp.status = "done"
            camp.finished_at = now()
        await db.commit()
    for ids in to_send:
        await messaging.send_queued(ids)
    if left:
        await schedule_tick(campaign_id, now() + timedelta(seconds=TICK_SECONDS))


async def stats(db: AsyncSession, campaign_id: int) -> dict[str, Any]:
    rows = (await db.execute(select(CampaignRecipient.status, CampaignRecipient.skip_reason, func.count())
                             .where(CampaignRecipient.campaign_id == campaign_id)
                             .group_by(CampaignRecipient.status, CampaignRecipient.skip_reason))).all()
    by_status: dict[str, int] = {}
    skipped: dict[str, int] = {}
    for st, reason, n in rows:
        by_status[st] = by_status.get(st, 0) + n
        if st == "skipped":
            skipped[reason or "other"] = n
    msg_rows = (await db.execute(
        select(Message.status, func.count()).join(CampaignRecipient, CampaignRecipient.message_id == Message.id)
        .where(CampaignRecipient.campaign_id == campaign_id).group_by(Message.status))).all()
    ms = dict(msg_rows)
    delivered = ms.get("delivered", 0) + ms.get("read", 0)
    agg = (await db.execute(select(
        func.count(CampaignRecipient.replied_at), func.count().filter(CampaignRecipient.screening_result == "fit"),
        func.count(CampaignRecipient.booked_at)).where(CampaignRecipient.campaign_id == campaign_id))).one()
    replied, fit, booked = agg
    total = sum(by_status.values())
    return {
        "total": total, "queued": by_status.get("queued", 0), "sent": by_status.get("sent", 0),
        "skipped": by_status.get("skipped", 0), "skipped_by_reason": skipped, "failed": by_status.get("failed", 0) + ms.get("failed", 0),
        "delivered": delivered, "read": ms.get("read", 0), "replied": replied, "screening_fit": fit, "booked": booked,
    }
