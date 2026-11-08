"""Тесты бизнес-логики (services.py). Опорная дата — среда 4 ноября 2026."""
from datetime import date

import pytest

from models import (Activity, CorporateClient, CorporateEmployee, Holiday, Invoice, Order)
from services import (AppSettings, BusinessError, attention_items, calc_price, client_report,
                      create_holiday_orders, dashboard_stats, delete_client, delete_employee,
                      delete_invoice, delete_order, generate_birthday_orders,
                      generate_monthly_invoices, invoice_status, load_settings, log_activity,
                      monthly_report, next_birthday, next_invoice_number, occurrence,
                      preview_holiday_orders, save_settings, shift_for_weekend,
                      upcoming_events)

TODAY = date(2026, 11, 4)   # среда


# ------------------------------------------------------------------ фабрики
def make_client(s, name="ООО Тест", stage="Клиент", fixed_price=40.0, **kw):
    c = CorporateClient(company_name=name, stage=stage, address="Офис, 1",
                        fixed_price=fixed_price, **kw)
    s.add(c)
    s.flush()
    return c


def make_emp(s, client, name="Иван Иванов", birthday=None, **kw):
    e = CorporateEmployee(client_id=client.id, full_name=name, birthday=birthday, **kw)
    s.add(e)
    s.flush()
    return e


def make_order(s, client, amount, day, status="Доставлен", emp=None, **kw):
    o = Order(client_id=client.id, employee_id=emp.id if emp else None, delivery_date=day,
              amount=amount, status=status, bouquet="Букет", **kw)
    s.add(o)
    s.flush()
    return o


def make_holiday(s, name="8 Марта", month=3, day=8, audience="female", **kw):
    h = Holiday(name=name, month=month, day=day, lead_days=7, audience=audience,
                is_active=True, **kw)
    s.add(h)
    s.flush()
    return h


# ------------------------------------------------------------------ даты
def test_occurrence_and_next_birthday():
    assert occurrence(2, 29, 2027) == date(2027, 2, 28)
    assert occurrence(2, 29, 2028) == date(2028, 2, 29)
    assert next_birthday(date(1990, 11, 4), TODAY) == TODAY                 # сегодня — ещё актуально
    assert next_birthday(date(1990, 11, 3), TODAY) == date(2027, 11, 3)
    assert next_birthday(date(1992, 2, 29), date(2027, 1, 1)) == date(2027, 2, 28)


def test_shift_for_weekend():
    assert shift_for_weekend(date(2026, 11, 7)) == date(2026, 11, 6)    # суббота
    assert shift_for_weekend(date(2026, 11, 8)) == date(2026, 11, 6)    # воскресенье
    assert shift_for_weekend(date(2026, 11, 5)) == date(2026, 11, 5)    # четверг


# ------------------------------------------------------------------ настройки
def test_settings_defaults_save_and_plan(session):
    st = load_settings(session)
    assert st.plan_revenue == 525000        # 10 × 15 × 3 500 ₽ (в ТЗ: 10 × 15 × 35 € = 5 250 €)
    assert st.currency == "₽" and st.default_price == 3500 and st.lead_days == 3
    assert st.company_name == "Диантус"
    save_settings(session, {"plan_companies": 5, "weekend_shift": False, "currency": "€"})
    st = load_settings(session)
    assert st.plan_revenue == 5 * 15 * 3500 and st.weekend_shift is False and st.currency == "€"
    with pytest.raises(BusinessError):
        save_settings(session, {"no_such_key": 1})


def test_settings_garbage_falls_back():
    st = AppSettings.from_raw({"default_price": "abc", "lead_days": "-5", "trial_discount": "500",
                               "plan_avg_check": "42,5"})
    assert st.default_price == 3500 and st.lead_days == 0
    assert st.trial_discount == 100 and st.plan_avg_check == 42.5


# ------------------------------------------------------------------ цены
def test_price_priority_and_adjustments():
    st = AppSettings(default_price=35.0)   # пробное −30% по умолчанию
    client = CorporateClient(fixed_price=40, discount=10)

    p = calc_price(client, CorporateEmployee(preferred_budget=50), st)
    assert (p.total, p.source, p.discount) == (50, "Бюджет получателя", 0)   # личный бюджет — итоговая цена

    p = calc_price(client, CorporateEmployee(preferred_budget=0), st)
    assert (p.base, p.discount, p.total, p.source) == (40, 4, 36, "Цена по договору")

    p = calc_price(CorporateClient(fixed_price=0, discount=0), None, st)
    assert (p.total, p.source) == (35, "Цена по умолчанию")

    assert calc_price(CorporateClient(fixed_price=0), None, st, trial=True).total == 24.5
    assert calc_price(CorporateClient(fixed_price=0), None, AppSettings(default_price=35.0, card_price=2),
                      with_card=True).total == 37

    gift = calc_price(client, None, st, service="Подарочный набор", extra=80)
    assert (gift.base, gift.total, gift.source) == (0, 80, "Цена вручную")
    assert "36" in calc_price(client, None, st).explain("€")


# ------------------------------------------------------------------ автозаказы на ДР
def test_birthday_orders_only_inside_lead_window(session):
    c = make_client(session)
    make_emp(session, c, "В окне", date(1990, 11, 6))
    make_emp(session, c, "Вне окна", date(1990, 11, 20))
    res = generate_birthday_orders(session, TODAY, lead_days=3)
    assert [o.recipient_name for o in res.created] == ["В окне"]
    o = res.created[0]
    assert (o.delivery_date, o.status, o.auto_created) == (date(2026, 11, 6), "Новый", True)
    assert (o.amount, o.address, o.delivery_time, o.occasion) == (40.0, "Офис, 1", "10:00", "День рождения")
    assert "В окне" in o.card_text and "ООО Тест" in o.card_text


def test_generation_is_idempotent_and_deleted_order_does_not_return(session):
    c = make_client(session)
    make_emp(session, c, "Именинник", date(1990, 11, 5))
    first = generate_birthday_orders(session, TODAY, 3)
    assert len(first.created) == 1
    second = generate_birthday_orders(session, TODAY, 3)
    assert second.created == [] and second.existing == 1
    session.delete(first.created[0])
    session.flush()
    assert generate_birthday_orders(session, TODAY, 3).created == []   # удалили сознательно


def test_only_contract_clients_are_served(session):
    ok = make_client(session, "Ок")
    lead = make_client(session, "Лид", stage="Лид")
    trial = make_client(session, "Пробный", stage="Пробное поздравление")
    archived = make_client(session, "Архив", is_active=False)
    expired = make_client(session, "Истёк", contract_end=date(2026, 11, 1))
    for c in (ok, lead, trial, archived, expired):
        make_emp(session, c, f"Сотрудник {c.company_name}", date(1990, 11, 5))
    make_emp(session, ok, "Уволен", date(1990, 11, 5), is_active=False)
    make_emp(session, ok, "Без даты", None)
    res = generate_birthday_orders(session, TODAY, 3)
    assert [o.recipient_name for o in res.created] == ["Сотрудник Ок"]


def test_contract_ending_inside_window(session):
    c = make_client(session, contract_end=date(2026, 11, 5))
    make_emp(session, c, "Раньше", date(1990, 11, 5))
    make_emp(session, c, "Позже", date(1990, 11, 7))
    res = generate_birthday_orders(session, TODAY, 3)
    assert [o.recipient_name for o in res.created] == ["Раньше"]


def test_office_delivery_on_weekend_moves_to_friday_home_stays(session):
    c = make_client(session)
    make_emp(session, c, "Офисный", date(1990, 11, 7))                     # суббота
    make_emp(session, c, "Домашний", date(1990, 11, 7), delivery_kind="Домой", home_address="ул. Дом, 5")
    res = generate_birthday_orders(session, date(2026, 11, 5), 3)
    by = {o.recipient_name: o for o in res.created}
    assert (by["Офисный"].delivery_date, by["Офисный"].event_date) == (date(2026, 11, 6), date(2026, 11, 7))
    assert "пятницу" in by["Офисный"].comment
    assert (by["Домашний"].delivery_date, by["Домашний"].address) == (date(2026, 11, 7), "ул. Дом, 5")


def test_weekend_shift_can_be_disabled(session):
    save_settings(session, {"weekend_shift": False})
    c = make_client(session)
    make_emp(session, c, "Офисный", date(1990, 11, 7))
    res = generate_birthday_orders(session, date(2026, 11, 5), 3)
    assert res.created[0].delivery_date == date(2026, 11, 7)


def test_home_delivery_without_address_warns_and_uses_office(session):
    c = make_client(session)
    make_emp(session, c, "Без адреса", date(1990, 11, 5), delivery_kind="Домой")
    res = generate_birthday_orders(session, TODAY, 3)
    assert res.created[0].address == "Офис, 1"
    assert any("домашний адрес" in w for w in res.warnings)


def test_feb29_and_new_year_boundary(session):
    c = make_client(session)
    make_emp(session, c, "Високосный", date(1992, 2, 29))
    assert generate_birthday_orders(session, date(2027, 2, 25), 5).created[0].event_date == date(2027, 2, 28)
    make_emp(session, c, "НГ", date(1990, 1, 2))
    res = generate_birthday_orders(session, date(2026, 12, 30), 5)
    assert [o.event_date for o in res.created] == [date(2027, 1, 2)]


def test_jubilee_occasion(session):
    c = make_client(session)
    make_emp(session, c, "Юбиляр", date(1976, 11, 5))                                  # 50 лет
    make_emp(session, c, "Обычный", date(1990, 11, 5))                                 # 36
    make_emp(session, c, "Год неизвестен", date(1976, 11, 5), birth_year_known=False)  # возраст неизвестен
    res = generate_birthday_orders(session, TODAY, 3)
    occasions = {o.recipient_name: o.occasion for o in res.created}
    assert occasions == {"Юбиляр": "Юбилей", "Обычный": "День рождения", "Год неизвестен": "День рождения"}


def test_existing_orders_block_generation_even_cancelled(session):
    c = make_client(session)
    e1 = make_emp(session, c, "Ручной", date(1990, 11, 5))
    e2 = make_emp(session, c, "Отменённый", date(1990, 11, 5))
    make_order(session, c, 50, date(2026, 11, 5), "Новый", emp=e1, occasion="День рождения")
    make_order(session, c, 50, date(2026, 11, 5), "Отменён", emp=e2, occasion="День рождения")
    res = generate_birthday_orders(session, TODAY, 3)
    assert res.created == [] and res.existing == 2


# ------------------------------------------------------------------ праздники
def test_holiday_orders_follow_audience_and_are_idempotent(session):
    c = make_client(session, "А")
    make_emp(session, c, "Анна", date(1990, 1, 1), gender="female")
    make_emp(session, c, "Борис", date(1990, 1, 1), gender="male")
    make_emp(session, c, "Без пола", date(1990, 1, 1))
    h = make_holiday(session)
    prev = preview_holiday_orders(session, h, 2027)
    assert [e.full_name for e in prev.recipients] == ["Анна"] and prev.skipped_gender == 1

    res = create_holiday_orders(session, h, 2027, bouquet="Тюльпаны", today=date(2027, 3, 1))
    assert len(res.created) == 1
    o = res.created[0]
    assert (o.occasion, o.bouquet, o.delivery_date) == ("8 Марта", "Тюльпаны", date(2027, 3, 8))
    assert "8 Марта" in o.card_text

    again = create_holiday_orders(session, h, 2027, today=date(2027, 3, 1))
    assert again.created == [] and again.existing == 1


def test_holiday_amount_override(session):
    c = make_client(session)
    make_emp(session, c, "Анна", date(1990, 1, 1), gender="female", preferred_budget=99)
    res = create_holiday_orders(session, make_holiday(session), 2027, amount=60, today=date(2027, 3, 1))
    assert res.created[0].amount == 60


def test_professional_holiday_only_for_its_segment(session):
    law = make_client(session, "Юр", segment="Юридическая компания")
    it = make_client(session, "ИТ", segment="IT-компания")
    make_emp(session, law, "Юрист", date(1990, 1, 1))
    make_emp(session, it, "Айтишник", date(1990, 1, 1))
    h = make_holiday(session, "День юриста", 12, 3, audience="all", segment="Юридическая компания")
    assert [e.full_name for e in preview_holiday_orders(session, h, 2026).recipients] == ["Юрист"]


# ------------------------------------------------------------------ счета
def test_monthly_invoices(session):
    a, b = make_client(session, "А"), make_client(session, "Б")
    o1 = make_order(session, a, 40, date(2026, 10, 5))
    o2 = make_order(session, a, 35, date(2026, 10, 20))
    cancelled = make_order(session, a, 50, date(2026, 10, 25), "Отменён")
    unfinished = make_order(session, a, 45, date(2026, 10, 28), "Новый")
    o5 = make_order(session, b, 60, date(2026, 10, 30))
    september = make_order(session, a, 99, date(2026, 9, 30))
    today = date(2026, 11, 2)

    invs = generate_monthly_invoices(session, 2026, 10, today=today)
    assert [(i.client_id, i.amount, i.number) for i in invs] == [
        (a.id, 75.0, "СЧ-202610-001"), (b.id, 60.0, "СЧ-202610-002")]
    assert invs[0].due_date == date(2026, 11, 16) and invs[0].period_end == date(2026, 10, 31)
    assert o1.invoice_id == o2.invoice_id == invs[0].id and o5.invoice_id == invs[1].id
    assert cancelled.invoice_id is None and unfinished.invoice_id is None and september.invoice_id is None

    assert generate_monthly_invoices(session, 2026, 10, today=today) == []     # повтор — ничего нового
    late = make_order(session, a, 20, date(2026, 10, 31))                      # доставлен «задним числом»
    more = generate_monthly_invoices(session, 2026, 10, today=today)
    assert [(i.amount, i.number) for i in more] == [(20.0, "СЧ-202610-003")] and late.invoice_id == more[0].id
    assert next_invoice_number(session, 2026, 10) == "СЧ-202610-004"


def test_invoice_status():
    today = date(2026, 11, 4)
    assert invoice_status(Invoice(paid=True, due_date=date(2020, 1, 1)), today) == "Оплачен"
    assert invoice_status(Invoice(paid=False, due_date=date(2026, 11, 3)), today) == "Просрочен"
    assert invoice_status(Invoice(paid=False, due_date=date(2026, 11, 4)), today) == "Ожидает оплаты"


# ------------------------------------------------------------------ воронка
def test_activity_moves_stage_forward_only(session):
    c = make_client(session, "Новая", stage="Лид")
    log_activity(session, c.id, "КП отправлено", on_date=date(2026, 11, 1))
    assert c.stage == "КП отправлено"
    log_activity(session, c.id, "Звонок")
    assert c.stage == "КП отправлено"
    log_activity(session, c.id, "Визит / встреча")
    assert c.stage == "Встреча"
    log_activity(session, c.id, "КП отправлено")      # назад не двигаем
    assert c.stage == "Встреча"
    log_activity(session, c.id, "Договор подписан", on_date=date(2026, 11, 7))
    assert (c.stage, c.contract_start, c.contract_end) == ("Клиент", date(2026, 11, 7), date(2027, 11, 6))
    log_activity(session, c.id, "Пробное поздравление")
    assert c.stage == "Клиент"


def test_refusal_is_revived_only_by_contract(session):
    c = make_client(session, "Отказ", stage="Отказ")
    log_activity(session, c.id, "Визит / встреча")
    assert c.stage == "Отказ"
    log_activity(session, c.id, "Договор подписан")
    assert c.stage == "Клиент"


def test_contract_signing_keeps_existing_contract_end(session):
    c = make_client(session, "С датами", stage="Встреча", contract_end=date(2027, 3, 1))
    log_activity(session, c.id, "Договор подписан", on_date=date(2026, 11, 7))
    assert c.contract_end == date(2027, 3, 1)


def test_unknown_client_activity_raises(session):
    with pytest.raises(BusinessError):
        log_activity(session, 999, "Звонок")


# ------------------------------------------------------------------ удаление
def test_delete_rules(session):
    c = make_client(session)
    e = make_emp(session, c, "Кто-то", date(1990, 1, 1))
    o = make_order(session, c, 40, date(2026, 11, 1), emp=e, recipient_name="Кто-то")
    with pytest.raises(BusinessError):
        delete_client(session, c.id)                      # есть заказы
    delete_employee(session, e.id)
    session.flush()
    session.refresh(o)
    assert o.employee_id is None and o.recipient_name == "Кто-то"   # история сохранена

    empty = make_client(session, "Пустая")
    delete_client(session, empty.id)
    session.flush()
    assert session.get(CorporateClient, empty.id) is None


def test_invoice_and_order_deletion(session):
    c = make_client(session)
    o = make_order(session, c, 40, date(2026, 10, 5))
    inv = generate_monthly_invoices(session, 2026, 10, today=date(2026, 11, 2))[0]
    with pytest.raises(BusinessError):
        delete_order(session, o.id)                       # заказ уже в счёте
    delete_invoice(session, inv.id)
    session.flush()
    session.refresh(o)
    assert o.invoice_id is None
    delete_order(session, o.id)
    session.flush()
    assert session.get(Order, o.id) is None


# ------------------------------------------------------------------ календарь
def test_upcoming_events_show_missing_orders(session):
    c = make_client(session)
    trial = make_client(session, "Пробный", stage="Пробное поздравление")
    lead = make_client(session, "Лид", stage="Лид")
    make_emp(session, c, "С заказом", date(1990, 11, 5))
    make_emp(session, c, "Без заказа", date(1990, 11, 6))
    make_emp(session, trial, "Пробный получатель", date(1990, 11, 6))
    make_emp(session, lead, "Из лида", date(1990, 11, 6))
    generate_birthday_orders(session, TODAY, lead_days=1)           # только на 5 ноября
    events = {e.who: e for e in upcoming_events(session, TODAY, days=5)}
    assert events["С заказом"].order_id is not None and events["С заказом"].order_status == "Новый"
    assert events["Без заказа"].order_id is None and events["Без заказа"].days == 2
    assert "Пробный получатель" in events and "Из лида" not in events


def test_calendar_includes_holiday_with_counts(session):
    c = make_client(session)
    make_emp(session, c, "Анна", date(1990, 1, 1), gender="female")
    # «8 Марта» уже есть среди праздников новой базы
    ev = [e for e in upcoming_events(session, date(2027, 3, 1), days=10) if e.kind == "Праздник"]
    assert len(ev) == 1 and ev[0].who == "8 Марта" and "получателей: 1" in ev[0].note


# ------------------------------------------------------------------ статистика
def test_dashboard_excludes_cancelled(session):
    c = make_client(session)
    make_client(session, "Лид", stage="Лид")
    make_order(session, c, 40, date(2026, 11, 2))
    make_order(session, c, 35, date(2026, 11, 10), "Новый")
    make_order(session, c, 500, date(2026, 11, 3), "Отменён")
    make_order(session, c, 70, date(2026, 10, 20))                          # другой месяц
    session.add_all([Invoice(client_id=c.id, number="A", amount=100, paid=False, due_date=date(2026, 11, 1)),
                     Invoice(client_id=c.id, number="B", amount=30, paid=False, due_date=date(2026, 12, 1)),
                     Invoice(client_id=c.id, number="C", amount=900, paid=True, due_date=date(2026, 10, 1))])
    session.flush()
    stats = dashboard_stats(session, TODAY)
    assert (stats["fact_revenue"], stats["fact_orders"]) == (40, 1)
    assert (stats["forecast_revenue"], stats["forecast_orders"]) == (75, 2)
    assert (stats["receivable"], stats["overdue"]) == (130, 100)
    assert (stats["plan_revenue"], stats["clients_serving"], stats["avg_check"]) == (525000, 1, 40)
    assert stats["funnel"]["Клиент"] == 1 and stats["funnel"]["Лид"] == 1


def test_monthly_and_client_reports(session):
    a, b = make_client(session, "А"), make_client(session, "Б")
    make_order(session, a, 40, date(2026, 10, 5))
    make_order(session, a, 60, date(2026, 10, 6), "Новый")
    make_order(session, b, 35, date(2026, 11, 2))
    session.add(Invoice(client_id=a.id, number="X", amount=40, paid=False, issue_date=date(2026, 10, 31),
                        due_date=date(2026, 11, 14)))
    session.flush()
    rows = monthly_report(session, months=3, today=TODAY)
    assert [r["label"] for r in rows] == ["Сентябрь 2026", "Октябрь 2026", "Ноябрь 2026"]
    assert (rows[1]["revenue"], rows[1]["forecast"], rows[1]["orders"], rows[1]["delivered"]) == (40, 100, 2, 1)
    assert rows[2]["revenue"] == 35 and rows[0]["orders"] == 0

    rep = {r["company"]: r for r in client_report(session, date(2026, 10, 1), date(2026, 10, 31))}
    assert (rep["А"]["orders"], rep["А"]["revenue"], rep["А"]["invoiced"], rep["А"]["debt"]) == (2, 40, 40, 40)


def test_attention_items(session):
    c = make_client(session, "Внимание", contract_end=date(2026, 11, 14))
    emp = make_emp(session, c, "Анна", date(1990, 1, 1), gender="female")
    make_order(session, c, 40, date(2026, 11, 3), "Новый", emp=emp, recipient_name="Анна", delivery_time="10:00")
    make_order(session, c, 40, date(2026, 11, 5), "Новый", emp=emp, recipient_name="Анна", delivery_time="")
    session.add(Invoice(client_id=c.id, number="СЧ-1", amount=100, paid=False, due_date=date(2026, 10, 30)))
    session.add(Activity(client_id=c.id, kind="Звонок", note="уточнить список", next_date=TODAY, done=False))
    make_holiday(session, "Праздник", 11, 6, audience="all")
    session.flush()

    items = attention_items(session, TODAY)
    texts = " | ".join(i["text"] for i in items)
    assert "Не доставлен заказ" in texts and "просрочен на 5 дн." in texts
    assert "ещё не взят в работу" in texts and "Не указано время доставки" in texts
    assert "заканчивается 14.11.2026" in texts and "уточнить список" in texts
    assert "«Праздник» через 2 дн." in texts
    levels = [i["level"] for i in items]
    assert levels == sorted(levels, key={"danger": 0, "warning": 1, "info": 2}.get)   # опасное — сверху
