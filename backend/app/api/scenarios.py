from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import client_ip, get_current_user, require_roles
from app.models import Candidate, Conversation, MessageTemplate, Role, Scenario, User, Vacancy
from app.scenario_library import LIBRARY, build, library_list
from app.schemas.common import ORM
from app.services import messaging, scenario_engine
from app.services.audit import log_action

router = APIRouter(tags=["scenarios"])


class ScenarioIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: str = Field(default="custom", max_length=32)
    description: str | None = None
    graph: dict[str, Any]
    is_active: bool = True


class ScenarioOut(ORM):
    id: int
    name: str
    kind: str
    description: str | None
    graph: dict[str, Any]
    version: int
    is_active: bool
    updated_at: datetime
    running: int = 0  # сколько диалогов сейчас идут по сценарию


class FromLibrary(BaseModel):
    key: str
    name: str | None = None


class StartIn(BaseModel):
    scenario_id: int
    vacancy_id: int | None = None


async def _approved(db: AsyncSession) -> set[tuple[str, str]]:
    rows = (await db.execute(select(MessageTemplate.name, MessageTemplate.language).where(MessageTemplate.status == "APPROVED"))).all()
    return {(r[0], r[1]) for r in rows}


async def _running(db: AsyncSession) -> dict[int, int]:
    rows = await db.execute(select(Conversation.scenario_id, func.count()).where(Conversation.current_node.isnot(None))
                            .group_by(Conversation.scenario_id))
    return {sid: n for sid, n in rows.all() if sid}


def _out(s: Scenario, running: dict[int, int]) -> ScenarioOut:
    o = ScenarioOut.model_validate(s)
    o.running = running.get(s.id, 0)
    return o


@router.get("/scenarios/library")
async def get_library(_: User = Depends(get_current_user)) -> list[dict[str, Any]]:
    return library_list()


@router.post("/scenarios/validate")
async def validate(graph: dict[str, Any], db: AsyncSession = Depends(get_session), _: User = Depends(get_current_user)) -> dict[str, Any]:
    errors = scenario_engine.validate_graph(graph, await _approved(db))
    return {"ok": not errors, "errors": errors}


@router.get("/scenarios", response_model=list[ScenarioOut])
async def list_scenarios(db: AsyncSession = Depends(get_session), _: User = Depends(get_current_user)):
    rows = (await db.execute(select(Scenario).order_by(Scenario.is_active.desc(), Scenario.name))).scalars().all()
    running = await _running(db)
    return [_out(s, running) for s in rows]


@router.get("/scenarios/{scenario_id}", response_model=ScenarioOut)
async def get_scenario(scenario_id: int, db: AsyncSession = Depends(get_session), _: User = Depends(get_current_user)):
    s = await db.get(Scenario, scenario_id)
    if not s:
        raise HTTPException(404, "Сценарий не найден")
    return _out(s, await _running(db))


def _check(graph: dict[str, Any]) -> None:
    errors = scenario_engine.validate_graph(graph)
    if errors:
        raise HTTPException(422, {"message": "В сценарии есть ошибки", "errors": errors})


@router.post("/scenarios", response_model=ScenarioOut, status_code=201)
async def create_scenario(data: ScenarioIn, request: Request, db: AsyncSession = Depends(get_session),
                          user: User = Depends(require_roles(Role.admin, Role.lead))):
    _check(data.graph)
    s = Scenario(**data.model_dump(), created_by=user.id)
    db.add(s)
    await db.flush()
    await log_action(db, user_id=user.id, action="scenario.create", entity="scenario", entity_id=s.id, diff={"name": s.name}, ip=client_ip(request))
    await db.commit()
    await db.refresh(s)
    return _out(s, {})


@router.post("/scenarios/from-library", response_model=ScenarioOut, status_code=201)
async def from_library(data: FromLibrary, request: Request, db: AsyncSession = Depends(get_session),
                       user: User = Depends(require_roles(Role.admin, Role.lead))):
    if data.key not in LIBRARY:
        raise HTTPException(404, "Шаблон сценария не найден")
    lib = LIBRARY[data.key]
    s = Scenario(name=data.name or lib["name"], kind=lib["kind"], description=lib["description"], graph=build(data.key), created_by=user.id)
    db.add(s)
    await db.flush()
    await log_action(db, user_id=user.id, action="scenario.create", entity="scenario", entity_id=s.id,
                     diff={"name": s.name, "from": data.key}, ip=client_ip(request))
    await db.commit()
    await db.refresh(s)
    return _out(s, {})


@router.put("/scenarios/{scenario_id}", response_model=ScenarioOut)
async def update_scenario(scenario_id: int, data: ScenarioIn, request: Request, db: AsyncSession = Depends(get_session),
                          user: User = Depends(require_roles(Role.admin, Role.lead))):
    s = await db.get(Scenario, scenario_id)
    if not s:
        raise HTTPException(404, "Сценарий не найден")
    _check(data.graph)
    graph_changed = s.graph != data.graph
    for k, v in data.model_dump().items():
        setattr(s, k, v)
    if graph_changed:
        s.version += 1
    await log_action(db, user_id=user.id, action="scenario.update", entity="scenario", entity_id=s.id,
                     diff={"name": s.name, "version": s.version, "graph_changed": graph_changed}, ip=client_ip(request))
    await db.commit()
    await db.refresh(s)
    return _out(s, await _running(db))


@router.delete("/scenarios/{scenario_id}", status_code=204)
async def delete_scenario(scenario_id: int, request: Request, db: AsyncSession = Depends(get_session),
                          user: User = Depends(require_roles(Role.admin, Role.lead))):
    s = await db.get(Scenario, scenario_id)
    if not s:
        raise HTTPException(404, "Сценарий не найден")
    if (await _running(db)).get(s.id):
        raise HTTPException(409, "По сценарию идут диалоги — выключите его вместо удаления")
    await db.delete(s)
    await log_action(db, user_id=user.id, action="scenario.delete", entity="scenario", entity_id=scenario_id, diff={"name": s.name}, ip=client_ip(request))
    await db.commit()


# ---------- Запуск для кандидата ----------

@router.post("/candidates/{candidate_id}/scenario")
async def start_for_candidate(candidate_id: int, data: StartIn, db: AsyncSession = Depends(get_session),
                              user: User = Depends(get_current_user)) -> dict[str, Any]:
    c = await db.get(Candidate, candidate_id)
    if not c or c.anonymized_at:
        raise HTTPException(404, "Кандидат не найден")
    s = await db.get(Scenario, data.scenario_id)
    if not s:
        raise HTTPException(404, "Сценарий не найден")
    if s.kind == "reminder":
        raise HTTPException(422, "Напоминания запускаются автоматически при записи на собеседование")
    needs_vacancy = any(n.get("type") == "template" and any("{vacancy}" in p for p in n.get("params") or [])
                        for n in s.graph.get("nodes", {}).values()) or s.kind in ("offer", "missed_call", "screening")
    if needs_vacancy and not data.vacancy_id:
        raise HTTPException(422, "Для этого сценария выберите вакансию")
    if data.vacancy_id and not await db.get(Vacancy, data.vacancy_id):
        raise HTTPException(422, "Вакансия не найдена")
    conv = await messaging.get_or_create_conversation(db, c)
    if scenario_engine.is_active(conv):
        raise HTTPException(409, "У кандидата уже идёт сценарий — сначала остановите его")
    try:
        ids = await scenario_engine.start(db, conv, s, vacancy_id=data.vacancy_id, user_id=user.id)
    except scenario_engine.ScenarioError as e:
        raise HTTPException(409, str(e)) from e
    if conv.context.get("outcome") == "error":
        await db.rollback()
        raise HTTPException(409, conv.context.get("reason") or "Не удалось запустить сценарий")
    await db.commit()
    await messaging.send_queued(ids)
    return {"ok": True, "messages": len(ids)}


@router.delete("/candidates/{candidate_id}/scenario")
async def stop_for_candidate(candidate_id: int, db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)) -> dict[str, bool]:
    conv = (await db.execute(select(Conversation).where(Conversation.candidate_id == candidate_id))).scalar_one_or_none()
    if conv is None or not scenario_engine.is_active(conv):
        raise HTTPException(409, "Сценарий не запущен")
    await scenario_engine.stop(db, conv, user.id)
    await db.commit()
    return {"ok": True}


@router.post("/candidates/{candidate_id}/bot")
async def return_to_bot(candidate_id: int, db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)) -> dict[str, bool]:
    """Вернуть диалог боту (если сценарий не завершён, он продолжит со следующего ответа кандидата)."""
    conv = (await db.execute(select(Conversation).where(Conversation.candidate_id == candidate_id))).scalar_one_or_none()
    if conv is None:
        raise HTTPException(404, "Диалога нет")
    conv.mode = "bot"
    conv.needs_reply = False
    await log_action(db, user_id=user.id, action="conversation.to_bot", entity="candidate", entity_id=candidate_id)
    await db.commit()
    return {"ok": True}
