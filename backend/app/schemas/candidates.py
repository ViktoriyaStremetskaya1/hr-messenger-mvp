from datetime import datetime

from pydantic import BaseModel, Field

from app.models import ApplicationStatus, ScreeningResult
from app.models.enums import Language
from app.schemas.common import ORM
from app.schemas.vacancies import VacancyShort


class TagOut(ORM):
    id: int
    name: str
    color: str


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    color: str = Field(default="gray", max_length=16)


class ApplicationOut(ORM):
    id: int
    vacancy: VacancyShort
    status: ApplicationStatus
    screening_result: ScreeningResult | None
    recruiter_id: int | None
    updated_at: datetime


class CandidateOut(ORM):
    id: int
    full_name: str
    phone_masked: str
    city: str | None
    source: str | None
    desired_position: str | None
    language: Language | None
    notes: str | None
    is_reserve: bool
    unsubscribed_at: datetime | None
    last_touch_at: datetime | None
    owner_id: int | None
    created_at: datetime
    tags: list[TagOut]
    applications: list[ApplicationOut]
    status: ApplicationStatus  # статус последней по времени заявки или «новый»


class CandidateCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    phone: str
    city: str | None = Field(default=None, max_length=128)
    source: str | None = Field(default=None, max_length=128)
    language: Language | None = None
    notes: str | None = None
    is_reserve: bool = False
    vacancy_id: int | None = None
    tag_ids: list[int] = []


class CandidateUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    city: str | None = Field(default=None, max_length=128)
    source: str | None = Field(default=None, max_length=128)
    language: Language | None = None
    notes: str | None = None
    is_reserve: bool | None = None
    owner_id: int | None = None
    tag_ids: list[int] | None = None


class ApplicationIn(BaseModel):
    vacancy_id: int


class ApplicationUpdate(BaseModel):
    status: ApplicationStatus | None = None
    screening_result: ScreeningResult | None = None
    recruiter_id: int | None = None


class BulkAction(BaseModel):
    candidate_ids: list[int] = Field(min_length=1, max_length=5000)
    action: str = Field(pattern="^(add_tag|remove_tag|set_reserve|unset_reserve|assign_vacancy)$")
    tag_id: int | None = None
    vacancy_id: int | None = None


class ImportPreview(BaseModel):
    file_name: str
    headers: list[str]
    mapping: dict[str, str | None]  # поле -> заголовок
    sample: list[list[str]]
    total_rows: int


class ImportCommit(BaseModel):
    mapping: dict[str, str | None]
    default_vacancy_id: int | None = None
    default_source: str | None = None
    mark_reserve: bool = False
    tag_ids: list[int] = []


class ImportResult(BaseModel):
    job_id: int
    total: int
    created: int
    updated: int
    duplicates_in_file: int
    errors: list[dict]
    unmatched_vacancies: list[str]
