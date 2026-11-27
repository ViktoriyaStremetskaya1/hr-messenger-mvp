"""Сегмент кандидатов для рассылки.

segment = {
  "candidate_ids": [..],          # конкретные кандидаты (выбор в списке)
  "cities": ["Алматы"], "vacancy_ids": [1], "statuses": ["new"], "screening": ["fit"],
  "is_reserve": true|false|null, "tag_ids": [..], "languages": ["ru","kk","none"], "sources": [..]
}
Все условия объединяются через И; внутри списка — ИЛИ.
"""
from typing import Any

from sqlalchemy import Select, and_, exists, func, or_, select

from app.models import Application, Candidate, candidate_tags


def segment_query(seg: dict[str, Any]) -> Select:
    stmt = select(Candidate.id).where(Candidate.anonymized_at.is_(None))
    if seg.get("candidate_ids"):
        stmt = stmt.where(Candidate.id.in_(seg["candidate_ids"]))
    if seg.get("cities"):
        stmt = stmt.where(func.lower(Candidate.city).in_([c.lower() for c in seg["cities"]]))
    if seg.get("is_reserve") is not None:
        stmt = stmt.where(Candidate.is_reserve.is_(bool(seg["is_reserve"])))
    if seg.get("sources"):
        stmt = stmt.where(Candidate.source.in_(seg["sources"]))
    if seg.get("languages"):
        langs = [x for x in seg["languages"] if x != "none"]
        conds = [Candidate.language.in_(langs)] if langs else []
        if "none" in seg["languages"]:
            conds.append(Candidate.language.is_(None))
        stmt = stmt.where(or_(*conds))
    app_conds = [Application.candidate_id == Candidate.id]
    if seg.get("vacancy_ids"):
        app_conds.append(Application.vacancy_id.in_(seg["vacancy_ids"]))
    if seg.get("statuses"):
        app_conds.append(Application.status.in_(seg["statuses"]))
    if seg.get("screening"):
        app_conds.append(Application.screening_result.in_(seg["screening"]))
    if len(app_conds) > 1:
        cond = exists().where(and_(*app_conds))
        if seg.get("statuses") and "new" in seg["statuses"] and not seg.get("vacancy_ids") and not seg.get("screening"):
            cond = or_(cond, ~exists().where(Application.candidate_id == Candidate.id))
        stmt = stmt.where(cond)
    if seg.get("tag_ids"):
        stmt = stmt.where(exists().where(and_(candidate_tags.c.candidate_id == Candidate.id,
                                              candidate_tags.c.tag_id.in_(seg["tag_ids"]))))
    return stmt
