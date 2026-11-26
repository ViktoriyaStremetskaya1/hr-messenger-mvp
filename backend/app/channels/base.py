"""Абстракция канала сообщений. Сценарии и рассылки работают только с этим интерфейсом,
поэтому добавление Telegram = новая реализация ChannelAdapter."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol


@dataclass
class Button:
    id: str
    title: str


@dataclass
class ListRow:
    id: str
    title: str
    description: str | None = None


@dataclass
class OutText:
    text: str
    kind: Literal["text"] = "text"


@dataclass
class OutButtons:
    text: str
    buttons: list[Button]
    header: str | None = None
    footer: str | None = None
    kind: Literal["buttons"] = "buttons"


@dataclass
class OutList:
    text: str
    button_label: str
    rows: list[ListRow]
    section_title: str | None = None
    kind: Literal["list"] = "list"


@dataclass
class OutTemplate:
    name: str
    language: str
    body_params: list[str] = field(default_factory=list)
    kind: Literal["template"] = "template"


Outbound = OutText | OutButtons | OutList | OutTemplate


@dataclass
class SendResult:
    ok: bool
    provider_message_id: str | None = None
    error_code: str | None = None
    error: str | None = None
    retryable: bool = False


@dataclass
class InboundMessage:
    provider_message_id: str
    contact_id: str  # для WhatsApp — wa_id (цифры номера)
    contact_name: str | None
    timestamp: datetime
    type: str  # text | button_reply | list_reply | media | unsupported
    text: str | None = None
    reply_id: str | None = None  # id нажатой кнопки / строки списка
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class StatusUpdate:
    provider_message_id: str
    status: str  # sent | delivered | read | failed
    timestamp: datetime
    error: str | None = None


class ChannelError(Exception):
    pass


class ChannelAdapter(Protocol):
    channel: str

    async def send(self, to: str, message: Outbound) -> SendResult: ...

    def verify_signature(self, raw_body: bytes, headers: dict[str, str]) -> bool: ...

    def parse_webhook(self, payload: dict[str, Any]) -> tuple[list[InboundMessage], list[StatusUpdate]]: ...

    async def list_templates(self) -> list[dict[str, Any]]: ...
