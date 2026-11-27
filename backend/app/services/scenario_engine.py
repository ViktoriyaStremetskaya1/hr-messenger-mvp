"""Движок сценариев.

Граф сценария (Scenario.graph):
{
  "start": "<id узла>",
  "nodes": {
    "<id>": {"type": "...", ...параметры, "title": "подпись шага для конструктора"}
  }
}

Тексты задаются строкой или словарём {"ru": "...", "kk": "..."}; в текстах доступны подстановки
{name} {full_name} {vacancy} {city} {schedule} {salary} {address} {requirements} и ответы кандидата {<var>}.

Типы узлов:
- message        — текст; next
- template       — одобренный шаблон WhatsApp (единственный способ начать диалог вне 24-часового окна):
                   template, params[], options[{id, label{ru,kk}, next}], var, timeout_hours, on_timeout
- buttons        — вопрос с кнопками (до 3; больше — отправится списком до 10): text, options, var, timeout_hours, on_timeout
- question       — свободный ответ: text, var, expect ("text"|"number"), next, timeout_hours, on_timeout
- language       — выбор языка ru/kk (пропускается, если язык известен); next
- vacancy_choice — выбор вакансии из активных в городе кандидата (список); text, next, empty
- condition      — ветвление: rules[{var, op, value, next}], else. op: eq neq in not_in gte lte contains empty not_empty
- set            — screening (fit|unfit|review), status, reserve (bool), vars{}, interview (confirm|cancel); next
- booking        — запись на собеседование: список свободных слотов (до 9) + «нет удобного времени»;
                   text, confirm_text, no_slots_text, next (необязательно)
- handoff        — передача рекрутеру: text, reason
- end            — завершение: text (необязательно)
"""
import logging
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.base import Button, InboundMessage, ListRow, OutButtons, OutList, OutTemplate, OutText
from app.core.db import SessionLocal
from app.models import Application, CampaignRecipient, Candidate, Conversation, MessageTemplate, Scenario, Vacancy
from app.services import messaging, policy, settings_store
from app.services.audit import log_action
from app.tasks import enqueue, task

log = logging.getLogger(__name__)

NODE_TYPES = {"message", "template", "buttons", "question", "language", "vacancy_choice", "condition", "set",
              "booking", "handoff", "end"}
WAITING_TYPES = {"template", "buttons", "question", "language", "vacancy_choice", "booking"}
OPS = {"eq", "neq", "in", "not_in", "gte", "lte", "contains", "empty", "not_empty"}
MAX_STEPS = 50
MAX_RETRIES = 2

REPROMPT = {"ru": "Пожалуйста, выберите один из вариантов 👇", "kk": "Төмендегі нұсқалардың бірін таңдаңыз 👇"}
REPROMPT_NUMBER = {"ru": "Пожалуйста, ответьте числом.", "kk": "Сан түрінде жауап беріңіз."}
HANDOFF_DEFAULT = {"ru": "Спасибо! Рекрутер свяжется с вами в ближайшее время.",
                   "kk": "Рақмет! Рекрутер жақын арада сізбен байланысады."}
BOOKING_TEXT = {"ru": "Выберите удобное время собеседования 👇", "kk": "Сұхбатқа ыңғайлы уақытты таңдаңыз 👇"}
BOOKING_CONFIRM = {
    "ru": "Готово! Вы записаны на собеседование {interview_date} в {interview_time}.\n📍 {address}\nМы напомним за день и за 2 часа. Если планы изменятся — просто напишите нам.",
    "kk": "Дайын! Сіз сұхбатқа жазылдыңыз: {interview_date}, сағат {interview_time}.\n📍 {address}\nБір күн және 2 сағат бұрын еске саламыз. Жоспарыңыз өзгерсе — бізге жазыңыз.",
}
BOOKING_NO_SLOTS = {"ru": "Сейчас свободного времени для собеседования нет — рекрутер свяжется с вами и предложит время.",
                    "kk": "Қазір сұхбатқа бос уақыт жоқ — рекрутер хабарласып, уақыт ұсынады."}
BOOKING_OTHER = {"ru": "Нет удобного времени", "kk": "Ыңғайлы уақыт жоқ"}
BOOKING_OTHER_REPLY = {"ru": "Хорошо! Рекрутер свяжется с вами и подберёт другое время.",
                       "kk": "Жақсы! Рекрутер хабарласып, басқа уақыт ұсынады."}
SLOT_TAKEN = {"ru": "Это время только что заняли 😔 Выберите, пожалуйста, другое.", "kk": "Бұл уақытты жаңа ғана біреу алды 😔 Басқасын таңдаңыз."}
LANG_BUTTONS = [Button("lang:ru", "Русский"), Button("lang:kk", "Қазақша")]
LANG_TEXT = "Выберите язык общения / Сөйлесу тілін таңдаңыз:"


class ScenarioError(Exception):
    pass


# ---------------- Валидация ----------------

def validate_graph(graph: dict[str, Any], template_names: set[tuple[str, str]] | None = None) -> list[str]:
    errors: list[str] = []
    nodes = graph.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        return ["В сценарии нет шагов"]
    start = graph.get("start")
    if start not in nodes:
        errors.append("Не указан первый шаг (start)")

    def ref(nid: str, field: str, target: Any, required: bool = True) -> None:
        if target is None:
            if required:
                errors.append(f"Шаг «{nid}»: не указан переход «{field}»")
        elif target not in nodes:
            errors.append(f"Шаг «{nid}»: переход «{field}» ведёт на несуществующий шаг «{target}»")

    for nid, n in nodes.items():
        t = n.get("type")
        if t not in NODE_TYPES:
            errors.append(f"Шаг «{nid}»: неизвестный тип «{t}»")
            continue
        if t in ("message", "question", "language", "set", "vacancy_choice"):
            ref(nid, "next", n.get("next"), required=t != "message")
        if t in ("message", "buttons", "question") and not _has_text(n.get("text")):
            errors.append(f"Шаг «{nid}»: пустой текст")
        if t in ("template", "buttons"):
            opts = n.get("options") or []
            if not opts:
                errors.append(f"Шаг «{nid}»: нет вариантов ответа")
            if t == "buttons" and len(opts) > 10:
                errors.append(f"Шаг «{nid}»: больше 10 вариантов (лимит WhatsApp)")
            for o in opts:
                if not o.get("id"):
                    errors.append(f"Шаг «{nid}»: у варианта нет id")
                ref(nid, f"вариант «{o.get('id')}»", o.get("next"))
                for lang, label in (o.get("label") or {}).items():
                    if t == "buttons" and len(opts) <= 3 and len(label) > 20:
                        errors.append(f"Шаг «{nid}»: текст кнопки «{label}» ({lang}) длиннее 20 символов")
        if t == "template":
            if not n.get("template"):
                errors.append(f"Шаг «{nid}»: не выбран шаблон")
            elif template_names is not None and not any(name == n["template"] for name, _ in template_names):
                errors.append(f"Шаг «{nid}»: шаблон «{n['template']}» не найден среди одобренных")
        if t in WAITING_TYPES and n.get("timeout_hours"):
            ref(nid, "on_timeout", n.get("on_timeout"), required=False)
        if t == "condition":
            for r in n.get("rules") or []:
                if r.get("op") not in OPS:
                    errors.append(f"Шаг «{nid}»: неизвестная операция «{r.get('op')}»")
                ref(nid, "правило", r.get("next"))
            ref(nid, "иначе", n.get("else"))
        if t == "set" and n.get("screening") not in (None, "fit", "unfit", "review"):
            errors.append(f"Шаг «{nid}»: неверный результат скрининга")
        if t == "vacancy_choice":
            ref(nid, "empty", n.get("empty"), required=False)
        if t == "booking":
            ref(nid, "next", n.get("next"), required=False)
        if t == "set" and n.get("interview") not in (None, "confirm", "cancel"):
            errors.append(f"Шаг «{nid}»: неверное действие с собеседованием")
    return errors


def _has_text(v: Any) -> bool:
    return bool(v.strip()) if isinstance(v, str) else isinstance(v, dict) and any(str(x).strip() for x in v.values())


def starts_with_template(graph: dict[str, Any], language: str | None = None) -> bool:
    """Начнётся ли сценарий с шаблона (обязательно, если 24-часовое окно закрыто)."""
    n = graph["nodes"][graph["start"]]
    seen = 0
    while n.get("type") == "language" and language and seen < 5:
        n = graph["nodes"].get(n.get("next"), {})
        seen += 1
    return n.get("type") == "template" or (n.get("type") == "language" and not language)


# ---------------- Подстановки ----------------

def tr(v: Any, lang: str) -> str:
    if isinstance(v, dict):
        return v.get(lang) or v.get("ru") or next(iter(v.values()), "")
    return v or ""


def first_name(full_name: str) -> str:
    parts = full_name.split()
    if len(parts) >= 2:
        return parts[1]  # «Фамилия Имя [Отчество]»
    return parts[0] if parts else ""


def money(a: int | None, b: int | None) -> str:
    f = lambda n: f"{n:,}".replace(",", " ")  # noqa: E731
    if a and b:
        return f"{f(a)}–{f(b)} ₸"
    if a:
        return f"от {f(a)} ₸"
    if b:
        return f"до {f(b)} ₸"
    return "по итогам собеседования"


def render(text: str, vars_: dict[str, Any]) -> str:
    return re.sub(r"\{([a-z_][a-z0-9_]*)\}", lambda m: str(vars_.get(m.group(1), m.group(0))), text)


async def build_vars(db: AsyncSession, conv: Conversation, candidate: Candidate) -> dict[str, Any]:
    ctx = conv.context or {}
    v: dict[str, Any] = {"name": first_name(candidate.full_name), "full_name": candidate.full_name,
                         "city": candidate.city or ""}
    vac = await db.get(Vacancy, ctx.get("vacancy_id")) if ctx.get("vacancy_id") else None
    if vac:
        v.update(vacancy=vac.title, city=candidate.city or vac.city, vacancy_city=vac.city,
                 schedule=vac.schedule or "уточнит рекрутер", salary=money(vac.salary_from, vac.salary_to),
                 address=vac.office_address or "уточнит рекрутер", requirements=vac.requirements or "")
    v.update({k: val.get("label") if isinstance(val, dict) else val for k, val in (ctx.get("vars") or {}).items()})
    v.update({k: val for k, val in (ctx.get("extra") or {}).items()})
    return v


# ---------------- Состояние ----------------

def _ctx(conv: Conversation, **updates: Any) -> dict[str, Any]:
    c = dict(conv.context or {})
    c.update(updates)
    conv.context = c  # переприсваиваем, чтобы SQLAlchemy заметил изменение JSONB
    return c


def is_active(conv: Conversation) -> bool:
    return bool(conv.scenario_id and conv.current_node)


def _goto(conv: Conversation, node_id: str | None) -> None:
    conv.current_node = node_id
    _ctx(conv, waiting=False, retries=0)
    if node_id is None:
        _ctx(conv, outcome=(conv.context or {}).get("outcome") or "completed", finished_at=datetime.now(UTC).isoformat())


def _finish(conv: Conversation, outcome: str, reason: str | None = None) -> None:
    _ctx(conv, outcome=outcome, reason=reason, finished_at=datetime.now(UTC).isoformat(), waiting=False)
    conv.current_node = None


async def _application(db: AsyncSession, conv: Conversation) -> Application | None:
    vid = (conv.context or {}).get("vacancy_id")
    if not vid:
        return None
    return (await db.execute(select(Application).where(Application.candidate_id == conv.candidate_id,
                                                         Application.vacancy_id == vid))).scalar_one_or_none()


async def _ensure_application(db: AsyncSession, conv: Conversation, vacancy_id: int, user_id: int | None) -> Application:
    _ctx(conv, vacancy_id=vacancy_id)
    app = await _application(db, conv)
    if app is None:
        app = Application(candidate_id=conv.candidate_id, vacancy_id=vacancy_id, recruiter_id=user_id or conv.assignee_id,
                          status="in_campaign", screening_answers={})
        db.add(app)
        await db.flush()
    return app


async def _store_answer(db: AsyncSession, conv: Conversation, var: str | None, value: str, label: str, question: str) -> None:
    if not var:
        return
    vars_ = dict((conv.context or {}).get("vars") or {})
    vars_[var] = {"value": value, "label": label}
    _ctx(conv, vars=vars_)
    app = await _application(db, conv)
    if app is not None:
        answers = dict(app.screening_answers or {})
        answers[var] = {"question": question, "answer": label}
        app.screening_answers = answers


async def campaign_recipient(db: AsyncSession, conv: Conversation) -> CampaignRecipient | None:
    cid = (conv.context or {}).get("campaign_id")
    if not cid:
        return None
    return (await db.execute(select(CampaignRecipient).where(CampaignRecipient.campaign_id == cid,
                                                               CampaignRecipient.candidate_id == conv.candidate_id))).scalar_one_or_none()


# ---------------- Запуск ----------------

async def load_graph(db: AsyncSession, conv: Conversation) -> dict[str, Any] | None:
    if not conv.scenario_id:
        return None
    sc = await db.get(Scenario, conv.scenario_id)
    return sc.graph if sc else None


async def start(db: AsyncSession, conv: Conversation, scenario: Scenario, *, vacancy_id: int | None = None,
                user_id: int | None = None, extra: dict[str, Any] | None = None, campaign_id: int | None = None) -> list[int]:
    """Запускает сценарий в диалоге. Возвращает id исходящих сообщений (отправить после commit)."""
    candidate = await db.get(Candidate, conv.candidate_id)
    if candidate.unsubscribed_at:  # type: ignore[union-attr]
        raise ScenarioError("Кандидат отписался от сообщений")
    if not scenario.is_active:
        raise ScenarioError("Сценарий выключен")
    errors = validate_graph(scenario.graph)
    if errors:
        raise ScenarioError("Сценарий содержит ошибки: " + "; ".join(errors[:3]))
    if not messaging.window_open(conv) and not starts_with_template(scenario.graph, candidate.language):  # type: ignore[union-attr]
        raise ScenarioError("24-часовое окно закрыто: этот сценарий можно запустить, только если он начинается с шаблона")
    conv.scenario_id = scenario.id
    conv.mode = "bot"
    conv.context = {"vars": {}, "extra": extra or {}, "scenario_version": scenario.version,
                    "started_at": datetime.now(UTC).isoformat(), "step": 0, "retries": 0, "waiting": False,
                    "campaign_id": campaign_id}
    if vacancy_id:
        app = await _ensure_application(db, conv, vacancy_id, user_id)
        if app.status == "new":
            app.status = "in_campaign"
        if campaign_id:
            app.campaign_id = campaign_id
    conv.current_node = scenario.graph["start"]
    await log_action(db, user_id=user_id, action="scenario.start", entity="candidate", entity_id=conv.candidate_id,
                     diff={"scenario_id": scenario.id, "vacancy_id": vacancy_id, "campaign_id": campaign_id})
    return await run(db, conv)


async def stop(db: AsyncSession, conv: Conversation, user_id: int | None, reason: str = "остановлен рекрутером") -> None:
    if is_active(conv):
        _finish(conv, "stopped", reason)
        conv.mode = "human"
        await log_action(db, user_id=user_id, action="scenario.stop", entity="candidate", entity_id=conv.candidate_id,
                         diff={"scenario_id": conv.scenario_id})


# ---------------- Исполнение ----------------

async def _send(db: AsyncSession, conv: Conversation, out: Any, template: MessageTemplate | None = None) -> int:
    campaign_id = (conv.context or {}).get("campaign_id")
    msg = await messaging.queue_message(db, conv, out, template=template, campaign_id=campaign_id)
    return msg.id


def _options_out(node_id: str, text: str, options: list[dict[str, Any]], lang: str, list_label: str) -> Any:
    if len(options) <= 3:
        return OutButtons(text=text, buttons=[Button(f"{node_id}:{o['id']}", tr(o.get("label"), lang)) for o in options])
    return OutList(text=text, button_label=list_label,
                   rows=[ListRow(f"{node_id}:{o['id']}", tr(o.get("label"), lang)) for o in options[:10]])


async def _wait(conv: Conversation, node: dict[str, Any]) -> None:
    step = int((conv.context or {}).get("step", 0)) + 1
    _ctx(conv, waiting=True, step=step)
    if node.get("timeout_hours"):
        await enqueue("scenario_timeout", conv.id, step, defer_seconds=float(node["timeout_hours"]) * 3600)


async def _template_for(db: AsyncSession, name: str, lang: str) -> MessageTemplate | None:
    rows = (await db.execute(select(MessageTemplate).where(MessageTemplate.name == name,
                                                           MessageTemplate.status == "APPROVED"))).scalars().all()
    by_lang = {t.language: t for t in rows}
    return by_lang.get(lang) or by_lang.get("ru") or next(iter(by_lang.values()), None)


def _eval(rule: dict[str, Any], vars_: dict[str, Any]) -> bool:
    raw = vars_.get(rule.get("var", ""))
    val = raw.get("value") if isinstance(raw, dict) else raw
    op, target = rule.get("op"), rule.get("value")
    s = "" if val is None else str(val).strip().lower()
    try:
        if op == "eq":
            return s == str(target).strip().lower()
        if op == "neq":
            return s != str(target).strip().lower()
        if op == "in":
            return s in [str(x).strip().lower() for x in target or []]
        if op == "not_in":
            return s not in [str(x).strip().lower() for x in target or []]
        if op == "gte":
            return val is not None and float(val) >= float(target)
        if op == "lte":
            return val is not None and float(val) <= float(target)
        if op == "contains":
            return str(target).strip().lower() in s
        if op == "empty":
            return s == ""
        if op == "not_empty":
            return s != ""
    except (TypeError, ValueError):
        return False
    return False


async def run(db: AsyncSession, conv: Conversation) -> list[int]:
    graph = await load_graph(db, conv)
    if not graph:
        return []
    nodes = graph["nodes"]
    candidate = await db.get(Candidate, conv.candidate_id)
    ids: list[int] = []
    try:
        for _ in range(MAX_STEPS):
            nid = conv.current_node
            if not nid or (conv.context or {}).get("waiting"):
                break
            node = nodes.get(nid)
            if node is None:
                _finish(conv, "error", f"шаг «{nid}» не найден")
                break
            lang = candidate.language or "ru"  # type: ignore[union-attr]
            v = await build_vars(db, conv, candidate)  # type: ignore[arg-type]
            t = node["type"]
            text = render(tr(node.get("text"), lang), v)

            if t == "message":
                ids.append(await _send(db, conv, OutText(text)))
                _goto(conv, node.get("next"))
            elif t == "template":
                tpl = await _template_for(db, node["template"], lang)
                if tpl is None:
                    raise ScenarioError(f"Шаблон «{node['template']}» не найден или не одобрен")
                params = [render(p, v) for p in node.get("params") or []]
                ids.append(await _send(db, conv, OutTemplate(tpl.name, tpl.language, params), template=tpl))
                await _wait(conv, node)
            elif t == "buttons":
                ids.append(await _send(db, conv, _options_out(nid, text, node["options"], lang,
                                                              "Выбрать" if lang == "ru" else "Таңдау")))
                await _wait(conv, node)
            elif t == "question":
                ids.append(await _send(db, conv, OutText(text)))
                await _wait(conv, node)
            elif t == "language":
                if candidate.language:  # type: ignore[union-attr]
                    _goto(conv, node.get("next"))
                    continue
                if messaging.window_open(conv):
                    ids.append(await _send(db, conv, OutButtons(LANG_TEXT, LANG_BUTTONS)))
                else:
                    tpl = await _template_for(db, "language_choice", "ru")
                    if tpl is None:
                        raise ScenarioError("Шаблон language_choice не найден или не одобрен")
                    ids.append(await _send(db, conv, OutTemplate(tpl.name, tpl.language, []), template=tpl))
                await _wait(conv, node)
            elif t == "vacancy_choice":
                stmt = select(Vacancy).where(Vacancy.is_active.is_(True))
                if candidate.city:  # type: ignore[union-attr]
                    stmt = stmt.where(Vacancy.city.ilike(candidate.city))  # type: ignore[union-attr]
                vacs = (await db.execute(stmt.order_by(Vacancy.title).limit(10))).scalars().all()
                if not vacs:
                    _goto(conv, node.get("empty") or node.get("next"))
                    if not node.get("empty"):
                        _finish(conv, "handoff", "нет подходящих вакансий")
                        conv.mode = "human"
                    continue
                rows = [ListRow(f"{nid}:vac:{x.id}", x.title, f"{x.city}, {money(x.salary_from, x.salary_to)}") for x in vacs]
                ids.append(await _send(db, conv, OutList(text or "Выберите вакансию:", "Вакансии" if lang == "ru" else "Бос орындар", rows)))
                await _wait(conv, node)
            elif t == "condition":
                nxt = node.get("else")
                for rule in node.get("rules") or []:
                    if _eval(rule, (conv.context or {}).get("vars") or {}):
                        nxt = rule.get("next")
                        break
                _goto(conv, nxt)
            elif t == "set":
                app = await _application(db, conv)
                if node.get("screening") and app:
                    app.screening_result = node["screening"]
                if node.get("screening") and (rcp := await campaign_recipient(db, conv)):
                    rcp.screening_result = node["screening"]
                if node.get("status") and app:
                    app.status = node["status"]
                if "reserve" in node:
                    candidate.is_reserve = bool(node["reserve"])  # type: ignore[union-attr]
                if node.get("interview"):
                    from app.models import Interview
                    from app.services import interviews

                    iid = ((conv.context or {}).get("extra") or {}).get("interview_id")
                    iv = await db.get(Interview, iid) if iid else None
                    if iv is not None and iv.status == "booked":
                        if node["interview"] == "confirm":
                            iv.confirmed_at = datetime.now(UTC)
                        else:
                            await interviews.set_status(db, iv, "cancelled", reason="отменил кандидат")
                if node.get("vars"):
                    vars_ = dict((conv.context or {}).get("vars") or {})
                    vars_.update({k: {"value": val, "label": val} for k, val in node["vars"].items()})
                    _ctx(conv, vars=vars_)
                _goto(conv, node.get("next"))
            elif t == "booking":
                from app.services import interviews

                slots = await interviews.available_slots(db, (conv.context or {}).get("vacancy_id"))
                if not slots:
                    ids.append(await _send(db, conv, OutText(render(tr(node.get("no_slots_text") or BOOKING_NO_SLOTS, lang), v))))
                    _finish(conv, "handoff", "нет свободных слотов")
                    conv.mode = "human"
                    continue
                rows = []
                for sl in slots:
                    addr = await interviews.slot_address(db, sl, (conv.context or {}).get("vacancy_id"))
                    rows.append(ListRow(f"{nid}:slot:{sl.id}", f"{interviews.fmt_date(sl.starts_at, lang)} · {interviews.fmt_time(sl.starts_at)}", addr))
                rows.append(ListRow(f"{nid}:other", tr(BOOKING_OTHER, lang)))
                ids.append(await _send(db, conv, OutList(text or tr(BOOKING_TEXT, lang), "Время" if lang == "ru" else "Уақыт", rows,
                                                         section_title="Свободное время" if lang == "ru" else "Бос уақыт")))
                await _wait(conv, node)
            elif t == "handoff":
                msg = text or tr(HANDOFF_DEFAULT, lang)
                ids.append(await _send(db, conv, OutText(msg)))
                _finish(conv, "handoff", node.get("reason"))
                conv.mode = "human"
            elif t == "end":
                if text:
                    ids.append(await _send(db, conv, OutText(text)))
                _finish(conv, "completed")
    except (messaging.MessagingError, ScenarioError) as e:
        log.warning("Сценарий в диалоге %s остановлен: %s", conv.id, e)
        _finish(conv, "error", str(e))
        conv.mode = "human"
    return ids


def _match_option(node_id: str, options: list[dict[str, Any]], m: InboundMessage) -> dict[str, Any] | None:
    rid = m.reply_id or ""
    if rid.startswith(f"{node_id}:"):
        oid = rid[len(node_id) + 1:]
        return next((o for o in options if o["id"] == oid), None)
    probe = (rid if m.type == "button_reply" and ":" not in rid else m.text or "").strip().casefold()
    if not probe:
        return None
    for o in options:
        labels = [str(x).strip().casefold() for x in (o.get("label") or {}).values()]
        if probe in labels or probe == o["id"].casefold():
            return o
    return None


async def _reprompt(db: AsyncSession, conv: Conversation, node_id: str, node: dict[str, Any], lang: str,
                    texts: dict[str, str] = REPROMPT) -> list[int]:
    retries = int((conv.context or {}).get("retries", 0)) + 1
    if retries > MAX_RETRIES:
        _finish(conv, "handoff", "кандидат не выбрал вариант")
        conv.mode = "human"
        return [await _send(db, conv, OutText(tr(HANDOFF_DEFAULT, lang)))]
    _ctx(conv, retries=retries)
    t = node["type"]
    if t == "booking":
        _ctx(conv, waiting=False)
        return await run(db, conv)
    if t in ("template", "buttons"):
        return [await _send(db, conv, _options_out(node_id, tr(texts, lang), node["options"], lang, "Выбрать"))]
    if t == "language":
        return [await _send(db, conv, OutButtons(LANG_TEXT, LANG_BUTTONS))]
    return [await _send(db, conv, OutText(tr(texts, lang)))]


async def handle_inbound(db: AsyncSession, conv: Conversation, m: InboundMessage) -> list[int]:
    """Вызывается на каждое входящее, пока диалог у бота."""
    if not is_active(conv) or not (conv.context or {}).get("waiting"):
        return []
    graph = await load_graph(db, conv)
    if not graph:
        return []
    nid = conv.current_node
    node = graph["nodes"].get(nid)  # type: ignore[arg-type]
    if node is None:
        return []
    candidate = await db.get(Candidate, conv.candidate_id)
    lang = candidate.language or "ru"  # type: ignore[union-attr]
    t = node["type"]
    question = render(tr(node.get("text"), lang), await build_vars(db, conv, candidate))  # type: ignore[arg-type]
    try:
        if t in ("template", "buttons"):
            opt = _match_option(nid, node.get("options") or [], m)  # type: ignore[arg-type]
            if opt is None:
                return await _reprompt(db, conv, nid, node, lang)  # type: ignore[arg-type]
            await _store_answer(db, conv, node.get("var"), opt["id"], tr(opt.get("label"), lang), question or node.get("template", ""))
            _goto(conv, opt["next"])
        elif t == "language":
            probe = f"{m.reply_id or ''} {m.text or ''}".casefold()
            chosen = "kk" if ("lang:kk" in probe or "қаз" in probe or "каз" in probe) else "ru" if ("lang:ru" in probe or "рус" in probe) else None
            if chosen is None:
                return await _reprompt(db, conv, nid, node, lang)  # type: ignore[arg-type]
            candidate.language = chosen  # type: ignore[union-attr]
            _goto(conv, node.get("next"))
        elif t == "question":
            answer = (m.text or "").strip()[:500]
            if node.get("expect") == "number":
                digits = re.findall(r"\d+(?:[.,]\d+)?", answer)
                if not digits:
                    return await _reprompt(db, conv, nid, node, lang, REPROMPT_NUMBER)  # type: ignore[arg-type]
                answer = digits[0].replace(",", ".")
            if not answer:
                return await _reprompt(db, conv, nid, node, lang)  # type: ignore[arg-type]
            await _store_answer(db, conv, node.get("var"), answer, answer, question)
            _goto(conv, node.get("next"))
        elif t == "booking":
            from app.services import interviews

            rid = m.reply_id or ""
            if rid == f"{nid}:other" or (m.text or "").strip().casefold() in {x.casefold() for x in BOOKING_OTHER.values()}:
                ids = [await _send(db, conv, OutText(tr(BOOKING_OTHER_REPLY, lang)))]
                _finish(conv, "handoff", "кандидату не подошло время")
                conv.mode = "human"
                return ids
            if not rid.startswith(f"{nid}:slot:"):
                return await _reprompt(db, conv, nid, node, lang)  # type: ignore[arg-type]
            slot_id = int(rid.rsplit(":", 1)[1])
            replaces = ((conv.context or {}).get("extra") or {}).get("interview_id")
            try:
                async with db.begin_nested():
                    iv = await interviews.book(db, candidate_id=conv.candidate_id, slot_id=slot_id,
                                               vacancy_id=(conv.context or {}).get("vacancy_id"), via="bot", replaces=replaces)
            except interviews.SlotUnavailable:
                ids = [await _send(db, conv, OutText(tr(SLOT_TAKEN, lang)))]
                return ids + await _reprompt(db, conv, nid, node, lang)  # type: ignore[arg-type]
            sl = iv.slot
            addr = await interviews.slot_address(db, sl, (conv.context or {}).get("vacancy_id"))
            extra = {**((conv.context or {}).get("extra") or {}), "interview_id": iv.id,
                     "interview_date": interviews.fmt_date(sl.starts_at, lang), "interview_time": interviews.fmt_time(sl.starts_at),
                     "address": addr}
            _ctx(conv, extra=extra)
            await _store_answer(db, conv, node.get("var") or "interview", str(iv.id),
                                f"{extra['interview_date']} {extra['interview_time']}", question)
            v2 = await build_vars(db, conv, candidate)  # type: ignore[arg-type]
            ids = [await _send(db, conv, OutText(render(tr(node.get("confirm_text") or BOOKING_CONFIRM, lang), v2)))]
            if node.get("next"):
                _goto(conv, node["next"])
                return ids + await run(db, conv)
            _finish(conv, "booked")
            return ids
        elif t == "vacancy_choice":
            rid = m.reply_id or ""
            if not rid.startswith(f"{nid}:vac:"):
                return await _reprompt(db, conv, nid, node, lang)  # type: ignore[arg-type]
            vid = int(rid.rsplit(":", 1)[1])
            if not await db.get(Vacancy, vid):
                return await _reprompt(db, conv, nid, node, lang)  # type: ignore[arg-type]
            await _ensure_application(db, conv, vid, None)
            _goto(conv, node.get("next"))
    except messaging.MessagingError as e:
        _finish(conv, "error", str(e))
        conv.mode = "human"
        return []
    return await run(db, conv)


@task
async def scenario_timeout(ctx: dict[str, Any], conversation_id: int, step: int) -> None:
    """Кандидат не ответил за timeout_hours."""
    async with SessionLocal() as db:
        conv = await db.get(Conversation, conversation_id)
        if conv is None or not is_active(conv) or conv.mode != "bot":
            return
        c = conv.context or {}
        if not c.get("waiting") or int(c.get("step", -1)) != step:
            return  # кандидат уже ответил
        wh = await settings_store.get_value(db, "working_hours")
        nxt = policy.next_working_moment(wh)
        delay = (nxt - datetime.now(UTC)).total_seconds()
        if delay > 60:  # ночь/выходной — догоняющее сообщение отправим в рабочее время
            await enqueue("scenario_timeout", conversation_id, step, defer_seconds=delay)
            return
        graph = await load_graph(db, conv)
        node = graph["nodes"].get(conv.current_node) if graph else None  # type: ignore[union-attr,arg-type]
        on_timeout = node.get("on_timeout") if node else None
        if on_timeout:
            _goto(conv, on_timeout)
            ids = await run(db, conv)
        else:
            _finish(conv, "no_reply", "кандидат не ответил")
            ids = []
        await db.commit()
    await messaging.send_queued(ids)
