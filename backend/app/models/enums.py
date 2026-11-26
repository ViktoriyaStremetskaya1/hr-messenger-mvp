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
