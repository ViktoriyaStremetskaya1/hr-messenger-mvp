from enum import StrEnum


class Role(StrEnum):
    admin = "admin"
    lead = "lead"  # руководитель подбора
    recruiter = "recruiter"


class ApplicationStatus(StrEnum):
    new = "new"  # новый
    in_campaign = "in_campaign"  # в рассылке
    replied = "replied"  # ответил
    booked = "booked"  # записан на интервью
    attended = "attended"  # пришёл
    no_show = "no_show"  # не пришёл
    offer = "offer"  # оффер
    hired = "hired"  # вышел


class ScreeningResult(StrEnum):
    fit = "fit"  # подходит
    unfit = "unfit"  # не подходит
    review = "review"  # на ревью


class Language(StrEnum):
    ru = "ru"
    kk = "kk"


class Channel(StrEnum):
    whatsapp = "whatsapp"
    telegram = "telegram"  # на будущее


class Direction(StrEnum):
    inbound = "in"
    outbound = "out"


class MessageStatus(StrEnum):
    queued = "queued"
    sent = "sent"
    delivered = "delivered"
    read = "read"
    failed = "failed"
    received = "received"  # входящее


STATUS_RANK = {"queued": 0, "sent": 1, "delivered": 2, "read": 3}


class ConversationMode(StrEnum):
    bot = "bot"
    human = "human"
