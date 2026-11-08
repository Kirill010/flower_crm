"""Бизнес-логика CRM корпоративных поздравлений.

Функции работают с переданной SQLAlchemy-сессией и не зависят от интерфейса,
поэтому покрыты автоматическими тестами (tests/).
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from models import (BIRTHDAY_OCCASIONS, CLIENT_STAGE, STAGES, STATUS_CANCELLED, STATUS_DONE,
                    TRIAL_STAGE, Activity, AutoLog, CorporateClient, CorporateEmployee,
                    Holiday, Invoice, Order, Setting)

MONTHS_RU = ["", "январь", "февраль", "март", "апрель", "май", "июнь",
             "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
MONTHS_RU_GEN = ["", "января", "февраля", "марта", "апреля", "мая", "июня",
                 "июля", "августа", "сентября", "октября", "ноября", "декабря"]
WEEKDAYS_RU = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

JUBILEE_FROM = 25     # юбилейный возраст: с 25 лет и кратно 5
JUBILEE_STEP = 5
BIRTHDAY_WINDOW = 3   # ±дней: заказ рядом с датой ДР считается заказом на этот ДР


class BusinessError(Exception):
    """Понятная пользователю ошибка бизнес-правила."""


# ------------------------------------------------------------------ форматы
def fmt_money(value, currency: str = "") -> str:
    if value is None:
        return ""
    s = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    if s.endswith(",00"):
        s = s[:-3]
    return f"{s} {currency}" if currency else s


def fmt_date(d) -> str:
    return d.strftime("%d.%m.%Y") if d else ""


def fmt_day_month(d: date) -> str:
    return f"{d.day} {MONTHS_RU_GEN[d.month]}"


def days_label(n: int) -> str:
    if n == 0:
        return "сегодня"
    if n == 1:
        return "завтра"
    return f"через {n} дн."


# ------------------------------------------------------------------ настройки
DEFAULT_SETTINGS = {
    "company_name": "Диантус",
    "shop_contacts": "",
    "currency": "₽",
    "default_price": "3500",         # в ТЗ средний заказ 35 €; в рублях — 3 500 (как бюджет по умолчанию в прежней версии)
    "card_price": "0",
    "trial_discount": "30",          # скидка на пробное поздравление, %
    "lead_days": "3",                # за сколько дней создавать заказы на дни рождения
    "default_delivery_time": "10:00",
    "weekend_shift": "1",            # ДР в выходной, доставка в офис → в пятницу
    "invoice_due_days": "14",
    "plan_companies": "10",          # финансовая модель из ТЗ: 10 × 15 × 35 € = 5 250 €; в рублях 10 × 15 × 3 500 = 525 000
    "plan_per_company": "15",
    "plan_avg_check": "3500",
    "birthday_card_text": "{name}, с днём рождения! Коллектив «{company}» желает вам "
                          "счастья и отличного настроения.",
    "holiday_card_text": "{name}, поздравляем вас с праздником — {holiday}! Коллектив «{company}».",
}


def _num(raw, default, cast=float):
    try:
        return cast(str(raw).replace(",", ".").strip())
    except (TypeError, ValueError):
        return cast(default)


@dataclass
class AppSettings:
    company_name: str = DEFAULT_SETTINGS["company_name"]
    shop_contacts: str = ""
    currency: str = "₽"
    default_price: float = 3500.0
    card_price: float = 0.0
    trial_discount: float = 30.0
    lead_days: int = 3
    default_delivery_time: str = "10:00"
    weekend_shift: bool = True
    invoice_due_days: int = 14
    plan_companies: int = 10
    plan_per_company: int = 15
    plan_avg_check: float = 3500.0
    birthday_card_text: str = DEFAULT_SETTINGS["birthday_card_text"]
    holiday_card_text: str = DEFAULT_SETTINGS["holiday_card_text"]

    @property
    def plan_revenue(self) -> float:
        return self.plan_companies * self.plan_per_company * self.plan_avg_check

    @property
    def plan_orders(self) -> int:
        return self.plan_companies * self.plan_per_company

    @classmethod
    def from_raw(cls, raw: dict) -> "AppSettings":
        def get(key):
            value = raw.get(key)
            return DEFAULT_SETTINGS[key] if value is None else value

        return cls(
            company_name=str(get("company_name")),
            shop_contacts=str(get("shop_contacts")),
            currency=str(get("currency")),
            default_price=_num(get("default_price"), DEFAULT_SETTINGS["default_price"]),
            card_price=_num(get("card_price"), DEFAULT_SETTINGS["card_price"]),
            trial_discount=min(100.0, max(0.0, _num(get("trial_discount"), DEFAULT_SETTINGS["trial_discount"]))),
            lead_days=max(0, _num(get("lead_days"), DEFAULT_SETTINGS["lead_days"], int)),
            default_delivery_time=str(get("default_delivery_time")),
            weekend_shift=str(get("weekend_shift")) not in ("0", "", "False", "false"),
            invoice_due_days=max(0, _num(get("invoice_due_days"), DEFAULT_SETTINGS["invoice_due_days"], int)),
            plan_companies=max(0, _num(get("plan_companies"), DEFAULT_SETTINGS["plan_companies"], int)),
            plan_per_company=max(0, _num(get("plan_per_company"), DEFAULT_SETTINGS["plan_per_company"], int)),
            plan_avg_check=_num(get("plan_avg_check"), DEFAULT_SETTINGS["plan_avg_check"]),
            birthday_card_text=str(get("birthday_card_text")),
            holiday_card_text=str(get("holiday_card_text")),
        )


def load_settings(session: Session) -> AppSettings:
    return AppSettings.from_raw({s.key: s.value for s in session.query(Setting)})


def save_settings(session: Session, values: dict) -> None:
    for key, value in values.items():
        if key not in DEFAULT_SETTINGS:
            raise BusinessError(f"Неизвестная настройка: {key}")
        if isinstance(value, bool):
            value = "1" if value else "0"
        row = session.get(Setting, key)
        if row is None:
            session.add(Setting(key=key, value=str(value)))
        else:
            row.value = str(value)


# ------------------------------------------------------------------ даты
def occurrence(month: int, day: int, year: int) -> date:
    """Дата события в заданном году. 29 февраля в невисокосный год → 28 февраля."""
    if month == 2 and day == 29 and not calendar.isleap(year):
        return date(year, 2, 28)
    return date(year, month, day)


def next_birthday(birthday: date, today: date) -> date:
    d = occurrence(birthday.month, birthday.day, today.year)
    return d if d >= today else occurrence(birthday.month, birthday.day, today.year + 1)


def shift_for_weekend(d: date) -> date:
    """Суббота/воскресенье → предшествующая пятница."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d - timedelta(days=2)
    return d


def turning_age(emp: CorporateEmployee, on_date: date) -> int | None:
    if not emp.birthday or emp.birth_year_known is False:
        return None
    return on_date.year - emp.birthday.year


def is_jubilee(age: int | None) -> bool:
    return age is not None and age >= JUBILEE_FROM and age % JUBILEE_STEP == 0


def month_bounds(d: date) -> tuple[date, date]:
    return d.replace(day=1), date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


# ------------------------------------------------------------------ цены
@dataclass
class Price:
    base: float = 0.0
    source: str = ""
    discount_pct: float = 0.0
    discount: float = 0.0
    trial_pct: float = 0.0
    trial: float = 0.0
    card: float = 0.0
    extra: float = 0.0
    total: float = 0.0

    def explain(self, currency: str = "") -> str:
        m = lambda v: fmt_money(v, currency)  # noqa: E731
        text = f"{self.source}: {m(self.base)}"
        if self.discount:
            text += f" − скидка по договору {self.discount_pct:g}% ({m(self.discount)})"
        if self.trial:
            text += f" − пробное поздравление {self.trial_pct:g}% ({m(self.trial)})"
        if self.card:
            text += f" + открытка {m(self.card)}"
        if self.extra:
            text += f" + доп. услуги {m(self.extra)}"
        return text + f" = {m(self.total)}"


def calc_price(client: CorporateClient | None, employee: CorporateEmployee | None,
               st: AppSettings, *, service: str = "Букет", trial: bool = False,
               with_card: bool = False, extra: float = 0.0) -> Price:
    """Цена заказа.

    Букет: личный бюджет получателя → иначе цена по договору (со скидкой по договору)
    → иначе цена по умолчанию из настроек. Для подарочных наборов и оформления офиса
    цену вводят вручную (extra). Пробное поздравление — скидка из настроек.
    """
    p = Price()
    if service != "Букет":
        p.source = "Цена вручную"
    elif employee is not None and (employee.preferred_budget or 0) > 0:
        p.base, p.source = float(employee.preferred_budget), "Бюджет получателя"
    else:
        fixed = float(client.fixed_price or 0) if client is not None else 0.0
        if fixed > 0:
            p.base, p.source = fixed, "Цена по договору"
        else:
            p.base, p.source = st.default_price, "Цена по умолчанию"
        p.discount_pct = float(client.discount or 0) if client is not None else 0.0
    p.discount = round(p.base * p.discount_pct / 100, 2)
    after_discount = p.base - p.discount
    if trial:
        p.trial_pct = st.trial_discount
        p.trial = round(after_discount * st.trial_discount / 100, 2)
    if with_card:
        p.card = st.card_price
    p.extra = float(extra or 0)
    p.total = round(after_discount - p.trial + p.card + p.extra, 2)
    return p


# ------------------------------------------------------------------ клиенты
def client_serves(client: CorporateClient, on_date: date) -> bool:
    """Обслуживается по договору: стадия «Клиент», не в архиве, договор не истёк."""
    return bool(client.is_active and client.stage == CLIENT_STAGE
                and (client.contract_end is None or client.contract_end >= on_date))


def serving_clients(session: Session, on_date: date) -> dict[int, CorporateClient]:
    rows = session.query(CorporateClient).filter(
        CorporateClient.is_active.is_(True), CorporateClient.stage == CLIENT_STAGE).all()
    return {c.id: c for c in rows if client_serves(c, on_date)}


def active_clients(session: Session, stages=(CLIENT_STAGE, TRIAL_STAGE)) -> dict[int, CorporateClient]:
    rows = session.query(CorporateClient).filter(
        CorporateClient.is_active.is_(True), CorporateClient.stage.in_(stages)).all()
    return {c.id: c for c in rows}


# ------------------------------------------------------------------ автозаказы
@dataclass
class GenResult:
    created: list[Order] = field(default_factory=list)
    existing: int = 0
    skipped_gender: int = 0
    warnings: list[str] = field(default_factory=list)


def _render_card(template: str, name: str, company: str, holiday: str = "") -> str:
    return (template.replace("{name}", name).replace("{company}", company)
            .replace("{holiday}", holiday))


def card_text_for(st: AppSettings, name: str, company: str, occasion: str) -> str:
    """Текст открытки по шаблону из настроек: для ДР и юбилеев — свой, для праздников — свой."""
    template = st.birthday_card_text if occasion in BIRTHDAY_OCCASIONS else st.holiday_card_text
    return _render_card(template, name, company, occasion)


def recipient_address(client: CorporateClient, emp: CorporateEmployee, warnings: list[str]) -> str:
    """Куда везти: домой (если так указано и адрес есть) или в офис компании."""
    if (emp.delivery_kind or "Офис") == "Домой":
        if emp.home_address:
            return emp.home_address
        warnings.append(f"{emp.full_name}: доставка домой, но домашний адрес не указан — "
                        "подставлен адрес офиса")
    return client.address or ""


def _new_auto_order(st: AppSettings, client: CorporateClient, emp: CorporateEmployee, *,
                    occasion: str, event_date: date, today: date, key: str,
                    card_template: str, holiday_name: str = "", bouquet: str | None = None,
                    amount: float | None = None, note: str = "",
                    warnings: list[str]) -> Order:
    delivery, shifted = event_date, False
    if (emp.delivery_kind or "Офис") == "Офис" and st.weekend_shift and event_date.weekday() >= 5:
        candidate = shift_for_weekend(event_date)
        if candidate >= today:
            delivery, shifted = candidate, True
    with_card = bool(emp.with_card)
    price = calc_price(client, emp, st, with_card=with_card)
    address_warnings: list[str] = []
    address = recipient_address(client, emp, address_warnings)
    warnings.extend(address_warnings)
    notes = [n for n in (note, "событие в выходной — доставка в пятницу" if shifted else "",
                         "нет домашнего адреса — подставлен адрес офиса" if address_warnings else "") if n]
    return Order(
        client_id=client.id, employee_id=emp.id, order_date=today, event_date=event_date,
        delivery_date=delivery, delivery_time=st.default_delivery_time, occasion=occasion,
        service="Букет", bouquet=bouquet or emp.preferred_bouquet or "Корпоративный букет",
        recipient_name=emp.full_name, recipient_phone=emp.phone or "",
        address=address, with_card=with_card,
        card_text=_render_card(card_template, emp.full_name, client.company_name, holiday_name)
        if with_card else "",
        amount=amount if amount else price.total, status="Новый", auto_created=True,
        source_key=key, comment="Автозаказ" + (": " + "; ".join(notes) if notes else ""))


def _birthday_dates_in(session: Session, emp_ids, start: date, end: date) -> dict[int, list[date]]:
    """Даты (доставки и события) существующих заказов на ДР рядом с окном [start, end]."""
    out: dict[int, list[date]] = defaultdict(list)
    if not emp_ids:
        return out
    pad = timedelta(days=BIRTHDAY_WINDOW)
    # любой статус, включая «Отменён»: если менеджер уже решал этот ДР, заново не создаём
    rows = session.query(Order.employee_id, Order.delivery_date, Order.event_date).filter(
        Order.employee_id.in_(list(emp_ids)), Order.occasion.in_(BIRTHDAY_OCCASIONS),
        Order.delivery_date.between(start - pad, end + pad))
    for emp_id, delivery, event in rows:
        out[emp_id].append(delivery)
        if event:
            out[emp_id].append(event)
    return out


def generate_birthday_orders(session: Session, today: date | None = None,
                             lead_days: int | None = None) -> GenResult:
    """Создаёт заказы на дни рождения на ближайшие lead_days дней («заранее готовим букеты»).

    Идемпотентно: повторный запуск не плодит дубли, а удалённый вручную заказ не
    возвращается (ключ хранится в auto_log). Только компании со стадией «Клиент».
    """
    today = today or date.today()
    st = load_settings(session)
    lead = st.lead_days if lead_days is None else lead_days
    horizon = today + timedelta(days=lead)
    res = GenResult()

    clients = serving_clients(session, today)   # точная проверка договора — ниже, по дате события
    if not clients:
        return res
    emps = session.query(CorporateEmployee).filter(
        CorporateEmployee.is_active.is_(True), CorporateEmployee.birthday.isnot(None),
        CorporateEmployee.client_id.in_(list(clients))).order_by(CorporateEmployee.id).all()
    logged = {k for (k,) in session.query(AutoLog.source_key).filter(AutoLog.source_key.like("bday:%"))}
    manual = _birthday_dates_in(session, [e.id for e in emps], today, horizon)

    for emp in emps:
        client = clients[emp.client_id]
        for year in sorted({today.year, horizon.year}):
            ev = occurrence(emp.birthday.month, emp.birthday.day, year)
            if not (today <= ev <= horizon) or not client_serves(client, ev):
                continue
            key = f"bday:{emp.id}:{ev.isoformat()}"
            if key in logged or any(abs((d - ev).days) <= BIRTHDAY_WINDOW for d in manual.get(emp.id, [])):
                res.existing += 1
                continue
            age = turning_age(emp, ev)
            jubilee = is_jubilee(age)
            order = _new_auto_order(
                st, client, emp, occasion="Юбилей" if jubilee else "День рождения",
                event_date=ev, today=today, key=key, card_template=st.birthday_card_text,
                note=f"юбилей, {age} лет" if jubilee else "", warnings=res.warnings)
            session.add(order)
            session.add(AutoLog(source_key=key))
            res.created.append(order)
    session.flush()
    return res


# ------------------------------------------------------------------ праздники
def holiday_date(holiday: Holiday, year: int) -> date:
    return occurrence(holiday.month, holiday.day, year)


@dataclass
class HolidayPreview:
    holiday: Holiday
    date: date
    recipients: list[CorporateEmployee]   # кому заказ ещё не создан
    clients: dict[int, CorporateClient]
    existing: int = 0
    skipped_gender: int = 0


def preview_holiday_orders(session: Session, holiday: Holiday, year: int) -> HolidayPreview:
    ev = holiday_date(holiday, year)
    clients = serving_clients(session, ev)
    prev = HolidayPreview(holiday=holiday, date=ev, recipients=[], clients=clients)
    if not clients:
        return prev
    emps = session.query(CorporateEmployee).filter(
        CorporateEmployee.is_active.is_(True),
        CorporateEmployee.client_id.in_(list(clients))).order_by(CorporateEmployee.id).all()
    prefix = f"hol:{holiday.id}:{year}:"
    logged = {k for (k,) in session.query(AutoLog.source_key).filter(AutoLog.source_key.like(prefix + "%"))}
    ordered = {emp_id for (emp_id,) in session.query(Order.employee_id).filter(
        Order.occasion == holiday.name, Order.employee_id.isnot(None),
        or_(Order.event_date == ev, Order.delivery_date == ev))}
    for emp in emps:
        client = clients[emp.client_id]
        if holiday.segment and (client.segment or "") != holiday.segment:
            continue
        if holiday.audience in ("female", "male") and emp.gender != holiday.audience:
            if not emp.gender:
                prev.skipped_gender += 1
            continue
        if prefix + str(emp.id) in logged or emp.id in ordered:
            prev.existing += 1
            continue
        prev.recipients.append(emp)
    return prev


def create_holiday_orders(session: Session, holiday: Holiday, year: int, *,
                          bouquet: str | None = None, amount: float | None = None,
                          today: date | None = None) -> GenResult:
    """Массовые заказы на праздник всем подходящим получателям (повторно не дублирует)."""
    today = today or date.today()
    st = load_settings(session)
    prev = preview_holiday_orders(session, holiday, year)
    res = GenResult(existing=prev.existing, skipped_gender=prev.skipped_gender)
    for emp in prev.recipients:
        order = _new_auto_order(
            st, prev.clients[emp.client_id], emp, occasion=holiday.name, event_date=prev.date,
            today=today, key=f"hol:{holiday.id}:{year}:{emp.id}",
            card_template=st.holiday_card_text, holiday_name=holiday.name,
            bouquet=bouquet or "Праздничный букет", amount=amount or None,
            note=f"массовый заказ: {holiday.name}", warnings=res.warnings)
        session.add(order)
        session.add(AutoLog(source_key=order.source_key))
        res.created.append(order)
    session.flush()
    return res


# ------------------------------------------------------------------ календарь
@dataclass
class CalendarEvent:
    date: date
    days: int
    kind: str                     # «День рождения», «Юбилей», название праздника
    who: str
    client_id: int | None = None
    client_name: str = ""
    employee_id: int | None = None
    holiday_id: int | None = None
    order_id: int | None = None
    order_status: str = ""
    note: str = ""


def upcoming_events(session: Session, today: date | None = None, days: int = 14) -> list[CalendarEvent]:
    """Дни рождения и праздники на ближайшие дни с признаком «заказ создан»."""
    today = today or date.today()
    end = today + timedelta(days=days)
    events: list[CalendarEvent] = []
    clients = active_clients(session)

    if clients:
        emps = session.query(CorporateEmployee).filter(
            CorporateEmployee.is_active.is_(True), CorporateEmployee.birthday.isnot(None),
            CorporateEmployee.client_id.in_(list(clients))).all()
        pad = timedelta(days=BIRTHDAY_WINDOW)
        orders_by_emp: dict[int, list[Order]] = defaultdict(list)
        for o in session.query(Order).filter(
                Order.employee_id.in_([e.id for e in emps] or [0]),
                Order.occasion.in_(BIRTHDAY_OCCASIONS),
                Order.delivery_date.between(today - pad, end + pad)):
            orders_by_emp[o.employee_id].append(o)
        for emp in emps:
            client = clients[emp.client_id]
            for year in sorted({today.year, end.year}):
                ev = occurrence(emp.birthday.month, emp.birthday.day, year)
                if not (today <= ev <= end):
                    continue
                age = turning_age(emp, ev)
                jubilee = is_jubilee(age)
                match = next((o for o in orders_by_emp.get(emp.id, [])
                              if abs((o.delivery_date - ev).days) <= BIRTHDAY_WINDOW), None)
                events.append(CalendarEvent(
                    date=ev, days=(ev - today).days, kind="Юбилей" if jubilee else "День рождения",
                    who=emp.full_name, client_id=client.id, client_name=client.company_name,
                    employee_id=emp.id, order_id=match.id if match else None,
                    order_status=match.status if match else "",
                    note=f"{age} лет" if jubilee else (f"исполняется {age}" if age else "")))

    for h in session.query(Holiday).filter(Holiday.is_active.is_(True)):
        for year in sorted({today.year, end.year}):
            ev = holiday_date(h, year)
            if today <= ev <= end:
                prev = preview_holiday_orders(session, h, year)
                total = len(prev.recipients) + prev.existing
                events.append(CalendarEvent(
                    date=ev, days=(ev - today).days, kind="Праздник", who=h.name,
                    holiday_id=h.id,
                    note=f"получателей: {total}, заказов создано: {prev.existing}"))
    events.sort(key=lambda e: (e.date, e.kind == "Праздник", e.who))
    return events


# ------------------------------------------------------------------ воронка
STAGE_BY_ACTIVITY = {
    "КП отправлено": "КП отправлено",
    "Визит / встреча": "Встреча",
    "Пробное поздравление": TRIAL_STAGE,
    "Договор подписан": CLIENT_STAGE,
}


def _advance_stage(client: CorporateClient, target: str, on_date: date) -> None:
    current = client.stage or "Лид"
    if target == CLIENT_STAGE:
        client.stage = CLIENT_STAGE
        if not client.contract_start:
            client.contract_start = on_date
        if not client.contract_end:        # годовой договор из ТЗ
            client.contract_end = occurrence(client.contract_start.month, client.contract_start.day,
                                             client.contract_start.year + 1) - timedelta(days=1)
        return
    if current in (CLIENT_STAGE, "Отказ"):
        return
    if STAGES.index(target) > STAGES.index(current):
        client.stage = target


def log_activity(session: Session, client_id: int, kind: str, note: str = "",
                 on_date: date | None = None, next_date: date | None = None) -> Activity:
    """Записывает контакт и сам двигает компанию по воронке (но не назад)."""
    client = session.get(CorporateClient, client_id)
    if client is None:
        raise BusinessError("Компания не найдена")
    on_date = on_date or date.today()
    act = Activity(client_id=client_id, date=on_date, kind=kind, note=note,
                   next_date=next_date, done=False)
    session.add(act)
    target = STAGE_BY_ACTIVITY.get(kind)
    if target:
        _advance_stage(client, target, on_date)
    return act


# ------------------------------------------------------------------ удаление
def delete_client(session: Session, client_id: int) -> None:
    client = session.get(CorporateClient, client_id)
    if client is None:
        return
    if session.query(Order.id).filter(Order.client_id == client_id).first() or \
            session.query(Invoice.id).filter(Invoice.client_id == client_id).first():
        raise BusinessError("У компании есть заказы или счета, удалять её нельзя.\n"
                            "Переведите компанию в архив — история сохранится.")
    session.delete(client)


def delete_employee(session: Session, employee_id: int) -> None:
    emp = session.get(CorporateEmployee, employee_id)
    if emp is None:
        return
    # история заказов сохраняется: имя и адрес получателя уже записаны в заказе
    session.query(Order).filter(Order.employee_id == employee_id).update({Order.employee_id: None})
    session.delete(emp)


def delete_order(session: Session, order_id: int) -> None:
    order = session.get(Order, order_id)
    if order is None:
        return
    if order.invoice_id:
        raise BusinessError("Заказ включён в счёт. Сначала удалите счёт или отмените заказ.")
    session.delete(order)


def delete_invoice(session: Session, invoice_id: int) -> None:
    inv = session.get(Invoice, invoice_id)
    if inv is None:
        return
    session.query(Order).filter(Order.invoice_id == invoice_id).update({Order.invoice_id: None})
    session.delete(inv)


# ------------------------------------------------------------------ счета
def invoice_status(inv: Invoice, today: date | None = None) -> str:
    today = today or date.today()
    if inv.paid:
        return "Оплачен"
    if inv.due_date and inv.due_date < today:
        return "Просрочен"
    return "Ожидает оплаты"


def next_invoice_number(session: Session, year: int, month: int) -> str:
    prefix = f"СЧ-{year}{month:02d}-"
    last = 0
    for (num,) in session.query(Invoice.number).filter(Invoice.number.like(prefix + "%")):
        try:
            last = max(last, int(num.rsplit("-", 1)[1]))
        except (ValueError, IndexError):
            continue
    return f"{prefix}{last + 1:03d}"


def generate_monthly_invoices(session: Session, year: int, month: int,
                              today: date | None = None) -> list[Invoice]:
    """Счёт каждой компании за доставленные в месяце заказы («оплата раз в месяц по счёту»).

    Заказ попадает в счёт один раз: повторный запуск за тот же месяц ничего не создаст.
    """
    today = today or date.today()
    st = load_settings(session)
    start, end = month_bounds(date(year, month, 1))
    orders = session.query(Order).filter(
        Order.client_id.isnot(None), Order.invoice_id.is_(None), Order.status == STATUS_DONE,
        Order.delivery_date.between(start, end)).order_by(Order.client_id, Order.delivery_date).all()
    by_client: dict[int, list[Order]] = defaultdict(list)
    for o in orders:
        by_client[o.client_id].append(o)
    created = []
    for client_id, items in by_client.items():
        total = round(sum(o.amount or 0 for o in items), 2)
        if total <= 0:
            continue
        inv = Invoice(
            client_id=client_id, number=next_invoice_number(session, year, month),
            issue_date=today, due_date=today + timedelta(days=st.invoice_due_days),
            period_start=start, period_end=end, amount=total, paid=False,
            description=f"Поздравления за {MONTHS_RU[month]} {year}: {len(items)} шт.")
        session.add(inv)
        session.flush()
        for o in items:
            o.invoice_id = inv.id
        created.append(inv)
    return created


def uninvoiced_orders(session: Session, year: int, month: int) -> tuple[int, float]:
    start, end = month_bounds(date(year, month, 1))
    n, total = session.query(func.count(Order.id), func.coalesce(func.sum(Order.amount), 0.0)).filter(
        Order.client_id.isnot(None), Order.invoice_id.is_(None), Order.status == STATUS_DONE,
        Order.delivery_date.between(start, end)).one()
    return int(n), float(total)


# ------------------------------------------------------------------ статистика
def _sum_orders(session: Session, start: date, end: date, delivered_only: bool = False) -> tuple[int, float]:
    q = session.query(func.count(Order.id), func.coalesce(func.sum(Order.amount), 0.0)).filter(
        Order.delivery_date.between(start, end), Order.status != STATUS_CANCELLED)
    if delivered_only:
        q = q.filter(Order.status == STATUS_DONE)
    n, total = q.one()
    return int(n), float(total)


def dashboard_stats(session: Session, today: date | None = None) -> dict:
    """Цифры главной страницы. Отменённые заказы нигде не учитываются."""
    today = today or date.today()
    st = load_settings(session)
    start, end = month_bounds(today)
    fact_n, fact_sum = _sum_orders(session, start, end, delivered_only=True)
    all_n, all_sum = _sum_orders(session, start, end)
    clients_in_month = session.query(func.count(func.distinct(Order.client_id))).filter(
        Order.delivery_date.between(start, end), Order.status != STATUS_CANCELLED,
        Order.client_id.isnot(None)).scalar() or 0
    unpaid = session.query(Invoice).filter(or_(Invoice.paid.is_(False), Invoice.paid.is_(None)))
    receivable = float(unpaid.with_entities(func.coalesce(func.sum(Invoice.amount), 0.0)).scalar())
    overdue = float(unpaid.filter(Invoice.due_date < today)
                    .with_entities(func.coalesce(func.sum(Invoice.amount), 0.0)).scalar())
    funnel = {stage: 0 for stage in STAGES}
    for stage, n in session.query(CorporateClient.stage, func.count(CorporateClient.id)).filter(
            CorporateClient.is_active.is_(True)).group_by(CorporateClient.stage):
        funnel[stage if stage in funnel else "Лид"] += n
    avg_source_n, avg_source_sum = (fact_n, fact_sum) if fact_n else (all_n, all_sum)
    return {
        "month_label": f"{MONTHS_RU[today.month]} {today.year}",
        "plan_revenue": st.plan_revenue, "plan_orders": st.plan_orders,
        "plan_companies": st.plan_companies, "plan_avg_check": st.plan_avg_check,
        "fact_revenue": fact_sum, "fact_orders": fact_n,
        "forecast_revenue": all_sum, "forecast_orders": all_n,
        "avg_check": (avg_source_sum / avg_source_n) if avg_source_n else None,
        "plan_pct": (fact_sum / st.plan_revenue * 100) if st.plan_revenue else 0.0,
        "forecast_pct": (all_sum / st.plan_revenue * 100) if st.plan_revenue else 0.0,
        "clients_serving": len(serving_clients(session, today)),
        "clients_in_month": int(clients_in_month),
        "receivable": receivable, "overdue": overdue, "funnel": funnel,
        "currency": st.currency,
    }


def monthly_report(session: Session, months: int = 12, today: date | None = None) -> list[dict]:
    today = today or date.today()
    st = load_settings(session)
    rows = []
    for i in range(months - 1, -1, -1):
        y, m = shift_month(today.year, today.month, -i)
        start, end = month_bounds(date(y, m, 1))
        n_all, sum_all = _sum_orders(session, start, end)
        n_done, sum_done = _sum_orders(session, start, end, delivered_only=True)
        clients = session.query(func.count(func.distinct(Order.client_id))).filter(
            Order.delivery_date.between(start, end), Order.status != STATUS_CANCELLED,
            Order.client_id.isnot(None)).scalar() or 0
        rows.append({
            "year": y, "month": m, "label": f"{MONTHS_RU[m].capitalize()} {y}",
            "clients": int(clients), "orders": n_all, "delivered": n_done,
            "revenue": sum_done, "forecast": sum_all, "plan": st.plan_revenue,
            "plan_pct": (sum_done / st.plan_revenue * 100) if st.plan_revenue else 0.0,
            "avg_check": (sum_done / n_done) if n_done else None,
        })
    return rows


def client_report(session: Session, start: date, end: date) -> list[dict]:
    names = {c.id: c.company_name for c in session.query(CorporateClient)}
    orders: dict[int, list[float]] = defaultdict(lambda: [0, 0.0, 0.0])   # шт, доставлено, прогноз
    for cid, status, amount in session.query(Order.client_id, Order.status, Order.amount).filter(
            Order.delivery_date.between(start, end), Order.status != STATUS_CANCELLED,
            Order.client_id.isnot(None)):
        orders[cid][0] += 1
        orders[cid][2] += amount or 0
        if status == STATUS_DONE:
            orders[cid][1] += amount or 0
    invoiced: dict[int, float] = defaultdict(float)
    for cid, amount in session.query(Invoice.client_id, Invoice.amount).filter(
            Invoice.issue_date.between(start, end)):
        invoiced[cid] += amount or 0
    debt: dict[int, float] = defaultdict(float)
    for cid, amount in session.query(Invoice.client_id, Invoice.amount).filter(
            or_(Invoice.paid.is_(False), Invoice.paid.is_(None))):
        debt[cid] += amount or 0
    rows = []
    for cid in sorted(set(orders) | set(invoiced) | set(debt), key=lambda c: names.get(c, "")):
        n, done, forecast = orders.get(cid, [0, 0.0, 0.0])
        rows.append({"id": cid, "company": names.get(cid, "—"), "orders": int(n),
                     "revenue": done, "forecast": forecast,
                     "invoiced": invoiced.get(cid, 0.0), "debt": debt.get(cid, 0.0)})
    return rows


def attention_items(session: Session, today: date | None = None) -> list[dict]:
    """Что требует внимания сегодня: уровни danger → warning → info."""
    today = today or date.today()
    st = load_settings(session)
    names = {c.id: c.company_name for c in session.query(CorporateClient)}
    items: list[dict] = []

    def add(level: str, text: str, target: str, ref=None) -> None:
        items.append({"level": level, "text": text, "target": target, "ref": ref})

    def who(o: Order) -> str:
        return f"{o.recipient_name or 'без получателя'} ({names.get(o.client_id, '—')})"

    closed_statuses = (STATUS_DONE, STATUS_CANCELLED)
    for o in session.query(Order).filter(Order.delivery_date < today,
                                         Order.status.notin_(closed_statuses)).order_by(Order.delivery_date):
        add("danger", f"Не доставлен заказ №{o.id} на {fmt_date(o.delivery_date)}: {who(o)}", "orders", o.id)

    soon = today + timedelta(days=2)
    for o in session.query(Order).filter(Order.delivery_date.between(today, soon),
                                         Order.status == "Новый").order_by(Order.delivery_date):
        add("warning", f"Заказ №{o.id} на {fmt_day_month(o.delivery_date)} ещё не взят в работу: {who(o)}",
            "orders", o.id)

    for o in session.query(Order).filter(
            Order.delivery_date.between(today, today + timedelta(days=3)),
            Order.status.notin_(closed_statuses),
            or_(Order.delivery_time.is_(None), Order.delivery_time == "")).order_by(Order.delivery_date):
        add("warning", f"Не указано время доставки: заказ №{o.id} на {fmt_day_month(o.delivery_date)}, {who(o)}",
            "orders", o.id)

    for inv in session.query(Invoice).filter(or_(Invoice.paid.is_(False), Invoice.paid.is_(None)),
                                             Invoice.due_date < today).order_by(Invoice.due_date):
        late = (today - inv.due_date).days
        add("danger", f"Счёт {inv.number or '№' + str(inv.id)} ({names.get(inv.client_id, '—')}) "
                      f"просрочен на {late} дн.: {fmt_money(inv.amount, st.currency)}", "invoices", inv.id)

    for c in session.query(CorporateClient).filter(
            CorporateClient.is_active.is_(True), CorporateClient.stage == CLIENT_STAGE,
            CorporateClient.contract_end.isnot(None)).order_by(CorporateClient.contract_end):
        left = (c.contract_end - today).days
        if left < 0:
            add("danger", f"Договор с «{c.company_name}» истёк {fmt_date(c.contract_end)} — "
                          "автозаказы остановлены", "clients", c.id)
        elif left <= 30:
            add("warning", f"Договор с «{c.company_name}» заканчивается {fmt_date(c.contract_end)} "
                           f"(через {left} дн.) — предложите продление", "clients", c.id)

    for a in session.query(Activity).filter(Activity.done.is_(False), Activity.next_date.isnot(None),
                                            Activity.next_date <= today).order_by(Activity.next_date):
        add("info", f"Вернуться к «{names.get(a.client_id, '—')}» ({fmt_date(a.next_date)}): "
                    f"{(a.note or a.kind or '').strip()}", "clients", a.client_id)

    for h in session.query(Holiday).filter(Holiday.is_active.is_(True)):
        for year in sorted({today.year, today.year + 1}):
            ev = holiday_date(h, year)
            days = (ev - today).days
            if 0 <= days <= (h.lead_days or 7):
                prev = preview_holiday_orders(session, h, year)
                if prev.recipients:
                    add("warning", f"«{h.name}» {days_label(days)}: заказы не созданы для "
                                   f"{len(prev.recipients)} получателей", "holidays", h.id)
                break

    for i in range(1, 4):
        y, m = shift_month(today.year, today.month, -i)
        n, total = uninvoiced_orders(session, y, m)
        if n:
            add("warning", f"Не выставлены счета за {MONTHS_RU[m]} {y}: {n} заказов на "
                           f"{fmt_money(total, st.currency)}", "invoices", None)

    order = {"danger": 0, "warning": 1, "info": 2}
    items.sort(key=lambda i: order[i["level"]])
    return items
