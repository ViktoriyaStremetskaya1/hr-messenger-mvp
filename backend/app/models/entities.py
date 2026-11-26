from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _now_col() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = _now_col()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


candidate_tags = Table(
    "candidate_tags",
    Base.metadata,
    Column("candidate_id", ForeignKey("candidates.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    color: Mapped[str] = mapped_column(String(16), default="gray", server_default="gray")


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255))
    phone_enc: Mapped[str] = mapped_column(Text)  # AES-GCM
    phone_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # HMAC
    phone_last4: Mapped[str] = mapped_column(String(4))
    city: Mapped[str | None] = mapped_column(String(128), index=True)
    source: Mapped[str | None] = mapped_column(String(128))
    desired_position: Mapped[str | None] = mapped_column(String(255))  # из импорта, если вакансия не найдена
    language: Mapped[str | None] = mapped_column(String(2))
    notes: Mapped[str | None] = mapped_column(Text)
    is_reserve: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_touch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Согласие на обработку ПДн — в MVP не используется, поля заложены на будущее
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_channel: Mapped[str | None] = mapped_column(String(32))
    consent_text_version: Mapped[str | None] = mapped_column(String(32))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    anonymized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now_col()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tags: Mapped[list[Tag]] = relationship(secondary=candidate_tags, lazy="selectin")
    applications: Mapped[list["Application"]] = relationship(
        back_populates="candidate", lazy="selectin", cascade="all, delete-orphan"
    )


class Vacancy(Base):
    __tablename__ = "vacancies"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    city: Mapped[str] = mapped_column(String(128), index=True)
    schedule: Mapped[str | None] = mapped_column(String(255))
    salary_from: Mapped[int | None] = mapped_column(Integer)
    salary_to: Mapped[int | None] = mapped_column(Integer)
    requirements: Mapped[str | None] = mapped_column(Text)
    office_address: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    # Частые вопросы: [{"q": "...", "a": "..."}] — источник истины для бота/ИИ
    faq: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _now_col()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Application(Base):
    """Отклик/участие кандидата в подборе на конкретную вакансию. Здесь живёт статус воронки."""

    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("candidate_id", "vacancy_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    vacancy_id: Mapped[int] = mapped_column(ForeignKey("vacancies.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="new", server_default="new", index=True)
    screening_result: Mapped[str | None] = mapped_column(String(8))
    screening_answers: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    recruiter_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    campaign_id: Mapped[int | None] = mapped_column(Integer)  # FK появится на этапе рассылок
    created_at: Mapped[datetime] = _now_col()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    candidate: Mapped[Candidate] = relationship(back_populates="applications")
    vacancy: Mapped[Vacancy] = relationship(lazy="selectin")


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = _now_col()


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    diff: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class MessageTemplate(Base):
    """Шаблон WhatsApp (одобряется в Meta). Первое сообщение кандидату — только через шаблон."""

    __tablename__ = "message_templates"
    __table_args__ = (UniqueConstraint("name", "language"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))  # имя шаблона в Meta
    language: Mapped[str] = mapped_column(String(8))  # ru | kk
    category: Mapped[str] = mapped_column(String(32), default="MARKETING")  # MARKETING | UTILITY
    status: Mapped[str] = mapped_column(String(16), default="LOCAL")  # APPROVED | PENDING | REJECTED | LOCAL
    header: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)  # текст с плейсхолдерами {{1}}, {{2}}
    footer: Mapped[str | None] = mapped_column(Text)
    buttons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    provider_id: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("candidate_id", "channel"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(16), default="whatsapp")
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    mode: Mapped[str] = mapped_column(String(8), default="bot", server_default="bot")
    # Состояние сценария (этап 3)
    scenario_id: Mapped[int | None] = mapped_column(Integer)
    current_node: Mapped[str | None] = mapped_column(String(64))
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    unread_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = _now_col()

    candidate: Mapped[Candidate] = relationship(lazy="selectin")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    direction: Mapped[str] = mapped_column(String(3))  # in | out
    type: Mapped[str] = mapped_column(String(24))  # text | template | buttons | list | button_reply | list_reply | media | unsupported
    body: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    provider_message_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    error: Mapped[str | None] = mapped_column(Text)
    campaign_id: Mapped[int | None] = mapped_column(Integer, index=True)  # FK — этап 4
    template_id: Mapped[int | None] = mapped_column(ForeignKey("message_templates.id", ondelete="SET NULL"))
    sent_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))  # null = бот/система
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebhookEvent(Base):
    """Сырые входящие события провайдера — для отладки и повторной обработки."""

    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(String(16))
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
