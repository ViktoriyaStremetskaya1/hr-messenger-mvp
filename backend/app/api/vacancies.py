from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import client_ip, get_current_user, require_roles
from app.models import Application, Role, User, Vacancy
from app.schemas.vacancies import VacancyIn, VacancyOut
from app.services.audit import changes, log_action

router = APIRouter(prefix="/vacancies", tags=["vacancies"])


async def _counts(db: AsyncSession, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    rows = await db.execute(
        select(Application.vacancy_id, func.count()).where(Application.vacancy_id.in_(ids)).group_by(Application.vacancy_id)
    )
    return dict(rows.all())


def _out(v: Vacancy, count: int) -> VacancyOut:
    out = VacancyOut.model_validate(v)
    out.candidates_count = count
    return out


@router.get("", response_model=list[VacancyOut])
async def list_vacancies(
    city: str | None = None,
    active: bool | None = None,
    q: str | None = None,
    db: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    stmt = select(Vacancy).order_by(Vacancy.is_active.desc(), Vacancy.title)
    if city:
        stmt = stmt.where(func.lower(Vacancy.city) == city.lower())
    if active is not None:
        stmt = stmt.where(Vacancy.is_active == active)
    if q:
        stmt = stmt.where(Vacancy.title.ilike(f"%{q}%"))
    items = (await db.execute(stmt)).scalars().all()
    counts = await _counts(db, [v.id for v in items])
    return [_out(v, counts.get(v.id, 0)) for v in items]


@router.get("/{vacancy_id}", response_model=VacancyOut)
async def get_vacancy(vacancy_id: int, db: AsyncSession = Depends(get_session), _: User = Depends(get_current_user)):
    v = await db.get(Vacancy, vacancy_id)
    if not v:
        raise HTTPException(404, "Вакансия не найдена")
    return _out(v, (await _counts(db, [v.id])).get(v.id, 0))


@router.post("", response_model=VacancyOut, status_code=201)
async def create_vacancy(
    data: VacancyIn, request: Request, db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)
):
    v = Vacancy(**data.model_dump(mode="json"), owner_id=user.id)
    db.add(v)
    await db.flush()
    await log_action(db, user_id=user.id, action="vacancy.create", entity="vacancy", entity_id=v.id,
                     diff={"title": v.title, "city": v.city}, ip=client_ip(request))
    await db.commit()
    await db.refresh(v)
    return _out(v, 0)


@router.put("/{vacancy_id}", response_model=VacancyOut)
async def update_vacancy(
    vacancy_id: int, data: VacancyIn, request: Request,
    db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user),
):
    v = await db.get(Vacancy, vacancy_id)
    if not v:
        raise HTTPException(404, "Вакансия не найдена")
    diff = changes(v, data.model_dump(mode="json"))
    await log_action(db, user_id=user.id, action="vacancy.update", entity="vacancy", entity_id=v.id, diff=diff, ip=client_ip(request))
    await db.commit()
    await db.refresh(v)
    return _out(v, (await _counts(db, [v.id])).get(v.id, 0))


@router.delete("/{vacancy_id}", status_code=204)
async def delete_vacancy(
    vacancy_id: int, request: Request,
    db: AsyncSession = Depends(get_session), user: User = Depends(require_roles(Role.admin, Role.lead)),
):
    v = await db.get(Vacancy, vacancy_id)
    if not v:
        raise HTTPException(404, "Вакансия не найдена")
    if (await _counts(db, [v.id])).get(v.id):
        raise HTTPException(409, "По вакансии есть кандидаты — переведите её в архив вместо удаления")
    await db.delete(v)
    await log_action(db, user_id=user.id, action="vacancy.delete", entity="vacancy", entity_id=vacancy_id,
                     diff={"title": v.title}, ip=client_ip(request))
    await db.commit()
