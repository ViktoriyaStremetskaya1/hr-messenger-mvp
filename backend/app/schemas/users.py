from datetime import datetime

from pydantic import BaseModel, Field

from app.models import Role
from app.schemas.common import ORM


class LoginIn(BaseModel):
    login: str
    password: str


class UserOut(ORM):
    id: int
    login: str
    full_name: str
    role: Role
    is_active: bool
    last_login_at: datetime | None = None


class UserCreate(BaseModel):
    login: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")
    full_name: str = Field(min_length=1, max_length=255)
    role: Role
    password: str = Field(min_length=8, max_length=128)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
