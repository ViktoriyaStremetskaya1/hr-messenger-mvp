from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORM


class MessageOut(ORM):
    id: int
    direction: str
    type: str
    body: str | None
    payload: dict[str, Any]
    status: str
    error: str | None
    sent_by_user_id: int | None
    campaign_id: int | None
    created_at: datetime
    sent_at: datetime | None
    delivered_at: datetime | None
    read_at: datetime | None


class ConversationOut(ORM):
    id: int
    channel: str
    assignee_id: int | None
    mode: str
    last_inbound_at: datetime | None
    last_message_at: datetime | None
    unread_count: int


class ScenarioState(BaseModel):
    scenario_id: int
    scenario_name: str
    current_node: str | None
    current_title: str | None
    waiting: bool
    outcome: str | None
    reason: str | None
    vacancy_id: int | None
    answers: dict[str, Any]


class ConversationView(BaseModel):
    conversation: ConversationOut | None
    scenario: ScenarioState | None = None
    messages: list[MessageOut]
    window_open: bool
    window_expires_at: datetime | None
    unsubscribed: bool


class SendIn(BaseModel):
    kind: Literal["text", "template"]
    text: str | None = Field(default=None, max_length=4096)
    template_id: int | None = None
    params: list[str] = []


class TemplateBase(BaseModel):
    name: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_]+$")
    language: Literal["ru", "kk"]
    category: Literal["MARKETING", "UTILITY"] = "MARKETING"
    header: str | None = None
    body: str = Field(min_length=1, max_length=1024)
    footer: str | None = None
    buttons: list[dict[str, Any]] = []


class TemplateIn(TemplateBase):
    pass


class TemplateOut(TemplateBase, ORM):
    id: int
    status: str
    params_count: int = 0
    updated_at: datetime
