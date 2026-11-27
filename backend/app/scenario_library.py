"""Готовые сценарии (создаются из конструктора кнопкой «Из шаблона», дальше редактируются).

Казахские тексты — черновые, их стоит вычитать носителю языка.
"""
from copy import deepcopy
from typing import Any


def L(ru: str, kk: str) -> dict[str, str]:  # noqa: N802
    return {"ru": ru, "kk": kk}


YES = L("Да", "Иә")
NO = L("Нет", "Жоқ")


def screening_nodes() -> dict[str, Any]:
    """Скрининг: город → график → опыт → готовность выйти → автоматический результат."""
    return {
        "s_city": {"type": "buttons", "title": "Скрининг: город",
                   "text": L("Офис находится по адресу: {address}. Вам удобно добираться?",
                             "Кеңсе мекенжайы: {address}. Сізге жету ыңғайлы ма?"),
                   "var": "city_ok", "timeout_hours": 24,
                   "options": [{"id": "yes", "label": YES, "next": "s_schedule"},
                               {"id": "no", "label": NO, "next": "s_schedule"}]},
        "s_schedule": {"type": "buttons", "title": "Скрининг: график",
                       "text": L("График работы: {schedule}. Вам подходит?", "Жұмыс кестесі: {schedule}. Сізге сәйкес пе?"),
                       "var": "schedule_ok", "timeout_hours": 24,
                       "options": [{"id": "yes", "label": YES, "next": "s_exp"},
                                   {"id": "no", "label": NO, "next": "s_exp"}]},
        "s_exp": {"type": "buttons", "title": "Скрининг: опыт",
                  "text": L("Есть ли у вас опыт работы с клиентами или в банке?",
                            "Клиенттермен немесе банкте жұмыс тәжірибеңіз бар ма?"),
                  "var": "experience", "timeout_hours": 24,
                  "options": [{"id": "none", "label": L("Нет опыта", "Тәжірибе жоқ"), "next": "s_start"},
                              {"id": "lt1", "label": L("До 1 года", "1 жылға дейін"), "next": "s_start"},
                              {"id": "gt1", "label": L("Больше 1 года", "1 жылдан көп"), "next": "s_start"}]},
        "s_start": {"type": "buttons", "title": "Скрининг: готовность выйти",
                    "text": L("Когда вы готовы выйти на работу?", "Жұмысқа қашан шыға аласыз?"),
                    "var": "start", "timeout_hours": 24,
                    "options": [{"id": "week", "label": L("В течение недели", "Бір апта ішінде"), "next": "s_check"},
                                {"id": "month", "label": L("В течение месяца", "Бір ай ішінде"), "next": "s_check"},
                                {"id": "later", "label": L("Позже", "Кейінірек"), "next": "s_check"}]},
        "s_check": {"type": "condition", "title": "Итог скрининга",
                    "rules": [{"var": "city_ok", "op": "eq", "value": "no", "next": "s_unfit"},
                              {"var": "schedule_ok", "op": "eq", "value": "no", "next": "s_unfit"},
                              {"var": "start", "op": "eq", "value": "later", "next": "s_review"}],
                    "else": "s_fit"},
        "s_fit": {"type": "set", "title": "Подходит", "screening": "fit", "next": "s_booking"},
        "s_booking": {"type": "booking", "title": "Запись на собеседование",
                      "text": L("Отлично, по ответам вы нам подходите! 🎉 Выберите удобное время собеседования 👇",
                                "Тамаша, жауаптарыңыз бойынша сіз бізге сәйкессіз! 🎉 Сұхбатқа ыңғайлы уақытты таңдаңыз 👇")},
        "s_review": {"type": "set", "title": "На ревью", "screening": "review", "next": "s_review_msg"},
        "s_review_msg": {"type": "handoff", "title": "Передать рекрутеру", "reason": "скрининг на ревью",
                         "text": L("Спасибо за ответы! Рекрутер изучит их и свяжется с вами.",
                                   "Жауаптарыңызға рақмет! Рекрутер оларды қарап, сізбен байланысады.")},
        "s_unfit": {"type": "set", "title": "Не подходит", "screening": "unfit", "next": "s_reserve_q"},
        **reserve_nodes("s_reserve_q", L("Спасибо за ответы! К сожалению, сейчас эта вакансия вам не подходит. Сообщать вам о других вакансиях?",
                          "Жауаптарыңызға рақмет! Өкінішке қарай, бұл бос орын қазір сізге сәйкес келмейді. Басқа бос орындар туралы хабарлайық па?")),
    }


def reserve_nodes(qid: str, question: dict[str, str]) -> dict[str, Any]:
    return {
        qid: {"type": "buttons", "title": "Предложить кадровый резерв", "text": question, "var": "reserve_ok",
                      "options": [{"id": "yes", "label": L("Да, сообщайте", "Иә, хабарлаңыз"), "next": "reserve_set"},
                                  {"id": "no", "label": NO, "next": "bye"}]},
        "reserve_set": {"type": "set", "title": "В резерв", "reserve": True, "next": "bye"},
        "bye": {"type": "end", "title": "Завершение",
                "text": L("Спасибо! Хорошего дня 🙂", "Рақмет! Күніңіз сәтті өтсін 🙂")},
    }


DETAILS = {"type": "message", "title": "Коротко о вакансии",
           "text": L("Коротко о вакансии «{vacancy}»:\n📍 {address}\n🕘 График: {schedule}\n💰 Доход: {salary}\n\nЗадам 4 коротких вопроса — это займёт минуту.",
                     "«{vacancy}» бос орны туралы қысқаша:\n📍 {address}\n🕘 Кесте: {schedule}\n💰 Табыс: {salary}\n\n4 қысқа сұрақ қоямын — бір минут қана."),
           "next": "s_city"}

LANG = {"type": "language", "title": "Выбор языка"}


def _offer() -> dict[str, Any]:
    return {"start": "lang", "nodes": {
        "lang": {**LANG, "next": "offer"},
        "offer": {"type": "template", "title": "Предложение вакансии (шаблон)", "template": "vacancy_offer",
                  "params": ["{name}", "{vacancy}", "{city}"], "var": "interested", "timeout_hours": 48,
                  "options": [{"id": "yes", "label": L("Да, интересно", "Иә, қызық"), "next": "details"},
                              {"id": "no", "label": L("Нет, спасибо", "Жоқ, рақмет"), "next": "reserve_q"}]},
        "details": DETAILS,
        **screening_nodes(),
        **reserve_nodes("reserve_q", L("Понимаем! Можно сообщать вам о других вакансиях?", "Түсінікті! Басқа бос орындар туралы хабарлайық па?")),
    }}


def _missed_call() -> dict[str, Any]:
    g = _offer()
    g["nodes"]["offer"] = {"type": "template", "title": "Недозвон (шаблон)", "template": "missed_call",
                           "params": ["{name}", "{vacancy}"], "var": "interested", "timeout_hours": 48,
                           "options": [{"id": "yes", "label": YES, "next": "details"},
                                       {"id": "no", "label": L("Не актуально", "Өзекті емес"), "next": "reserve_q"}]}
    return g


def _screening() -> dict[str, Any]:
    nodes = {"lang": {**LANG, "next": "intro"},
             "intro": {**DETAILS, "title": "Вступление",
                       "text": L("Задам 4 коротких вопроса о вакансии «{vacancy}» — это займёт минуту.",
                                 "«{vacancy}» бос орны бойынша 4 қысқа сұрақ қоямын — бір минут қана.")},
             **screening_nodes()}
    return {"start": "lang", "nodes": nodes}


def _reminder() -> dict[str, Any]:
    return {"start": "remind", "nodes": {
        "remind": {"type": "template", "title": "Напоминание (шаблон)", "template": "interview_reminder",
                   "params": ["{interview_date}", "{interview_time}", "{address}"], "var": "confirm",
                   "options": [{"id": "come", "label": L("Приду", "Келемін"), "next": "confirm"},
                               {"id": "resched", "label": L("Перенести", "Ауыстыру"), "next": "resched"},
                               {"id": "cancel", "label": L("Отменить", "Бас тарту"), "next": "cancel_set"}]},
        "confirm": {"type": "set", "title": "Отметить подтверждение", "interview": "confirm", "next": "ok"},
        "cancel_set": {"type": "set", "title": "Отменить запись", "interview": "cancel", "next": "cancel"},
        "ok": {"type": "end", "title": "Подтвердил",
               "text": L("Отлично, ждём вас! Возьмите с собой удостоверение личности.", "Тамаша, сізді күтеміз! Жеке куәлігіңізді ала келіңіз.")},
        "resched": {"type": "booking", "title": "Перенос: выбор нового времени",
                    "text": L("Хорошо, давайте перенесём. Выберите новое время 👇", "Жақсы, ауыстырайық. Жаңа уақытты таңдаңыз 👇")},
        "cancel": {"type": "end", "title": "Отменил",
                   "text": L("Жаль! Если передумаете — просто напишите нам.", "Өкінішті! Ойыңыз өзгерсе — бізге жазыңыз.")},
    }}


def _reserve_revival() -> dict[str, Any]:
    return {"start": "revive", "nodes": {
        "revive": {"type": "template", "title": "Реанимация резерва (шаблон)", "template": "reserve_revival",
                   "params": ["{name}"], "var": "interested", "timeout_hours": 72,
                   "options": [{"id": "yes", "label": YES, "next": "choose"},
                               {"id": "no", "label": NO, "next": "rev_bye"}]},
        "choose": {"type": "vacancy_choice", "title": "Выбор вакансии",
                   "text": L("Вот открытые вакансии. Выберите интересную 👇", "Ашық бос орындар. Қызықтысын таңдаңыз 👇"),
                   "next": "details", "empty": "no_vac"},
        "no_vac": {"type": "handoff", "title": "Нет вакансий", "reason": "нет подходящих вакансий",
                   "text": L("Сейчас подходящих вакансий в вашем городе нет — рекрутер свяжется с вами, как только появятся.",
                             "Қазір қалаңызда сәйкес бос орын жоқ — пайда болған кезде рекрутер хабарласады.")},
        "rev_bye": {"type": "end", "title": "Отказ",
                    "text": L("Хорошо, не будем беспокоить. Хорошего дня!", "Жақсы, мазаламаймыз. Күніңіз сәтті өтсін!")},
        "details": DETAILS,
        **screening_nodes(),
    }}


LIBRARY: dict[str, dict[str, Any]] = {
    "offer": {"name": "Предложение вакансии", "kind": "offer", "builder": _offer,
              "description": "Выбор языка → шаблон с вакансией → детали → скрининг → запись. При отказе — предложение резерва."},
    "missed_call": {"name": "Недозвон", "kind": "missed_call", "builder": _missed_call,
                    "description": "Кандидат не взял трубку: продолжаем в WhatsApp → скрининг → запись."},
    "screening": {"name": "Скрининг", "kind": "screening", "builder": _screening,
                  "description": "4 вопроса-фильтра (город/адрес, график, опыт, готовность выйти) и автоматический результат. Нужен открытый диалог (окно 24 ч)."},
    "reminder": {"name": "Напоминание о собеседовании", "kind": "reminder", "builder": _reminder,
                 "description": "Шаблон-напоминание с кнопками «Приду / Перенести / Отменить». Запускается автоматически за сутки и за 2 часа до собеседования."},
    "reserve_revival": {"name": "Реанимация резерва", "kind": "reserve_revival", "builder": _reserve_revival,
                        "description": "Кандидатам из резерва: новые вакансии в городе → выбор → скрининг → запись."},
}


def library_list() -> list[dict[str, Any]]:
    return [{"key": k, "name": v["name"], "kind": v["kind"], "description": v["description"], "graph": deepcopy(v["builder"]())}
            for k, v in LIBRARY.items()]


def build(key: str) -> dict[str, Any]:
    return deepcopy(LIBRARY[key]["builder"]())
