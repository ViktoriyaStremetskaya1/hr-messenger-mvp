"""Шаблоны WhatsApp — единый источник текстов.

- Песочница (wa-mock) отдаёт их как «одобренные».
- `python -m app.push_templates` отправляет их в Meta на модерацию.

Правила Meta: имя — латиница/цифры/_, переменные {{1}}, {{2}}… по порядку, к каждой нужен пример,
переменные нумеруются по порядку появления в тексте (одинаково для ru и kk —
код подставляет параметры в одном порядке), текст не может начинаться или заканчиваться переменной, до 3 кнопок быстрого ответа (до 25 символов).
Правьте тексты здесь, затем снова запустите push_templates (уже поданные шаблоны с тем же именем
и языком меняются в WhatsApp Manager).
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TemplateDef:
    name: str
    language: str  # ru | kk
    category: str  # MARKETING | UTILITY
    body: str
    buttons: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()  # примеры значений для {{1}}, {{2}}… — требует Meta
    note: str = field(default="", compare=False)


TEMPLATES: list[TemplateDef] = [
    TemplateDef(
        "language_choice", "ru", "UTILITY",
        "Здравствуйте! Сәлеметсіз бе!\nВыберите язык общения / Сөйлесу тілін таңдаңыз:",
        ("Русский", "Қазақша"),
        note="Первое касание, если язык кандидата неизвестен",
    ),
    TemplateDef(
        "vacancy_offer", "ru", "MARKETING",
        "Здравствуйте, {{1}}! Приглашаем вас на вакансию «{{2}}» в г. {{3}}. Хотите узнать подробности?",
        ("Да, интересно", "Нет, спасибо"), ("Асель", "Операционист", "Алматы"),
    ),
    TemplateDef(
        "vacancy_offer", "kk", "MARKETING",
        "Сәлеметсіз бе, {{1}}! Сізді «{{2}}» бос орнына шақырамыз, қала: {{3}}. Толығырақ білгіңіз келе ме?",
        ("Иә, қызық", "Жоқ, рақмет"), ("Әсел", "Операционист", "Алматы"),
    ),
    TemplateDef(
        "missed_call", "ru", "MARKETING",
        "Здравствуйте, {{1}}! Мы не смогли дозвониться вам по поводу вакансии «{{2}}». Удобно продолжить здесь, в WhatsApp?",
        ("Да", "Не актуально"), ("Асель", "Оператор колл-центра"),
    ),
    TemplateDef(
        "missed_call", "kk", "MARKETING",
        "Сәлеметсіз бе, {{1}}! «{{2}}» бос орны бойынша сізге хабарласа алмадық. Осы жерде, WhatsApp-та жалғастырайық па?",
        ("Иә", "Өзекті емес"), ("Әсел", "Колл-орталық операторы"),
    ),
    TemplateDef(
        "interview_reminder", "ru", "UTILITY",
        "Напоминаем: собеседование {{1}} в {{2}} по адресу: {{3}}. Пожалуйста, подтвердите участие.",
        ("Приду", "Перенести", "Отменить"), ("28 ноября", "10:00", "г. Алматы, пр. Абая, 10"),
    ),
    TemplateDef(
        "interview_reminder", "kk", "UTILITY",
        "Еске саламыз: сұхбат {{1}}, сағат {{2}}, мекенжайы: {{3}}. Қатысуыңызды растаңыз.",
        ("Келемін", "Ауыстыру", "Бас тарту"), ("28 қараша", "10:00", "Алматы қ., Абай даңғ., 10"),
    ),
    TemplateDef(
        "reserve_revival", "ru", "MARKETING",
        "Здравствуйте, {{1}}! У нас появились новые вакансии, которые могут вам подойти. Рассмотрите предложения?",
        ("Да", "Нет"), ("Асель",),
    ),
    TemplateDef(
        "reserve_revival", "kk", "MARKETING",
        "Сәлеметсіз бе, {{1}}! Сізге сәйкес келуі мүмкін жаңа бос орындар пайда болды. Ұсыныстарды қарастырасыз ба?",
        ("Иә", "Жоқ"), ("Әсел",),
    ),
]


def to_meta_components(t: TemplateDef) -> list[dict]:
    body: dict = {"type": "BODY", "text": t.body}
    if t.examples:
        body["example"] = {"body_text": [list(t.examples)]}
    comps = [body]
    if t.buttons:
        comps.append({"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": b} for b in t.buttons]})
    return comps


def as_meta_records(status: str = "APPROVED") -> list[dict]:
    """В формате ответа GET /{waba}/message_templates."""
    return [
        {"id": f"mock_{t.name}_{t.language}", "name": t.name, "language": t.language, "status": status,
         "category": t.category, "components": to_meta_components(t)}
        for t in TEMPLATES
    ]
