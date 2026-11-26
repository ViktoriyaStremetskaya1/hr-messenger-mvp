"""Интерфейсы внешних интеграций (пока заглушки).

- JobBoardSource — источник кандидатов с job-сайтов (hh.kz).
- AtsSink — передача кандидатов во внутренние системы (ATS банка, «Моя Команда»).
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass
class ExternalCandidate:
    external_id: str
    full_name: str
    phone: str
    city: str | None = None
    vacancy_title: str | None = None
    source: str = "hh.kz"


class JobBoardSource(Protocol):
    name: str

    async def fetch_new_candidates(self, since_iso: str) -> list[ExternalCandidate]: ...


class AtsSink(Protocol):
    name: str

    async def push_candidate(self, candidate_id: int, status: str, payload: dict) -> str | None:
        """Возвращает внешний ID записи или None."""
        ...


class HhKzSourceStub:
    name = "hh.kz"

    async def fetch_new_candidates(self, since_iso: str) -> list[ExternalCandidate]:
        return []


class AtsSinkStub:
    name = "ats-stub"

    async def push_candidate(self, candidate_id: int, status: str, payload: dict) -> str | None:
        return None


class MoyaKomandaSinkStub(AtsSinkStub):
    name = "moya-komanda-stub"
