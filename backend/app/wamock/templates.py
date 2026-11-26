"""Шаблоны, которые мок отдаёт как «одобренные в Meta». Для боевого номера их нужно завести
в WhatsApp Manager с теми же именами (тексты — в docs/WHATSAPP_TEMPLATES.md)."""


def _t(name, lang, category, body, buttons, header=None):
    comps = []
    if header:
        comps.append({"type": "HEADER", "format": "TEXT", "text": header})
    comps.append({"type": "BODY", "text": body})
    if buttons:
        comps.append({"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": b} for b in buttons]})
    return {"id": f"mock_{name}_{lang}", "name": name, "language": lang, "status": "APPROVED", "category": category, "components": comps}


MOCK_TEMPLATES = [
    _t("language_choice", "ru", "UTILITY",
       "Здравствуйте! Сәлеметсіз бе!\nВыберите язык общения / Сөйлесу тілін таңдаңыз:", ["Русский", "Қазақша"]),
    _t("vacancy_offer", "ru", "MARKETING",
       "Здравствуйте, {{1}}! Банк приглашает вас на вакансию «{{2}}» в г. {{3}}. Хотите узнать подробности?",
       ["Да, интересно", "Нет, спасибо"]),
    _t("vacancy_offer", "kk", "MARKETING",
       "Сәлеметсіз бе, {{1}}! Банк сізді {{3}} қаласындағы «{{2}}» бос орнына шақырады. Толығырақ білгіңіз келе ме?",
       ["Иә, қызық", "Жоқ, рақмет"]),
    _t("missed_call", "ru", "MARKETING",
       "{{1}}, мы не смогли дозвониться вам по поводу вакансии «{{2}}». Удобно продолжить здесь, в WhatsApp?",
       ["Да", "Не актуально"]),
    _t("missed_call", "kk", "MARKETING",
       "{{1}}, «{{2}}» бос орны бойынша сізге хабарласа алмадық. Осы жерде, WhatsApp-та жалғастырайық па?",
       ["Иә", "Өзекті емес"]),
    _t("interview_reminder", "ru", "UTILITY",
       "Напоминаем: собеседование {{1}} в {{2}} по адресу: {{3}}.", ["Приду", "Перенести", "Отменить"]),
    _t("interview_reminder", "kk", "UTILITY",
       "Еске саламыз: сұхбат {{1}}, сағат {{2}}, мекенжайы: {{3}}.", ["Келемін", "Ауыстыру", "Бас тарту"]),
    _t("reserve_revival", "ru", "MARKETING",
       "{{1}}, здравствуйте! В банке появились новые вакансии. Рассмотрите предложения?", ["Да", "Нет"]),
    _t("reserve_revival", "kk", "MARKETING",
       "{{1}}, сәлеметсіз бе! Банкте жаңа бос орындар пайда болды. Ұсыныстарды қарастырасыз ба?", ["Иә", "Жоқ"]),
]
