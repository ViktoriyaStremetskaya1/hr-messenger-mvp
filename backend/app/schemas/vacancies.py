from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import ORM


class FaqItem(BaseModel):
    q: str = Field(min_length=1, max_length=500)
    a: str = Field(min_length=1, max_length=2000)


class VacancyBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    city: str = Field(min_length=1, max_length=128)
    schedule: str | None = Field(default=None, max_length=255)
    salary_from: int | None = Field(default=None, ge=0)
    salary_to: int | None = Field(default=None, ge=0)
    requirements: str | None = None
    office_address: str | None = None
    description: str | None = None
    faq: list[FaqItem] = []
    is_active: bool = True

    @model_validator(mode="after")
    def _salary(self) -> "VacancyBase":
        if self.salary_from and self.salary_to and self.salary_from > self.salary_to:
            raise ValueError("Зарплата «от» больше, чем «до»")
        return self


class VacancyIn(VacancyBase):
    pass


class VacancyOut(VacancyBase, ORM):
    id: int
    owner_id: int | None
    created_at: datetime
    updated_at: datetime
    candidates_count: int = 0


class VacancyShort(ORM):
    id: int
    title: str
    city: str
