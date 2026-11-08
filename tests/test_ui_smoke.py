"""Дымовые тесты интерфейса: настоящие окна и диалоги в headless-режиме (QT_QPA_PLATFORM=offscreen).

Если задана переменная CRM_SHOT_DIR, тест сохраняет скриншоты вкладок и диалогов в эту папку.
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QDialog

import database
import dialogs
import tabs
import ui
from demo_data import seed_demo
from models import (Activity, CorporateClient, CorporateEmployee, Holiday, Invoice, Order)
from services import (BusinessError, generate_monthly_invoices, load_settings)
import theme
from widgets import Col, DataTable

SHOT_DIR = os.environ.get("CRM_SHOT_DIR")


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    theme.apply(app)
    return app


@pytest.fixture
def errors(monkeypatch):
    """Исключения в слотах PyQt попадают в sys.excepthook — собираем их, чтобы тест их увидел."""
    collected = []
    monkeypatch.setattr(sys, "excepthook", lambda t, e, tb: collected.append(e))
    yield collected
    assert collected == [], f"необработанные ошибки в интерфейсе: {collected!r}"


@pytest.fixture
def messages(monkeypatch):
    """Подменяет модальные окна сообщений; confirm() всегда отвечает «да»."""
    log = []
    for module in (tabs, dialogs, ui):
        for name in ("info", "warn"):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, lambda parent, title, text, _n=name: log.append((_n, title, text)))
    monkeypatch.setattr(tabs, "confirm", lambda *a, **k: True)
    return log


@pytest.fixture
def demo_db(tmp_path):
    database.init_db(tmp_path / "demo.db")
    with database.session_scope() as s:
        seed_demo(s)
    return tmp_path / "demo.db"


def shot(widget, name):
    if SHOT_DIR:
        Path(SHOT_DIR).mkdir(parents=True, exist_ok=True)
        widget.show()
        QApplication.processEvents()
        widget.grab().save(str(Path(SHOT_DIR) / f"{name}.png"))


def make_window(qapp, demo=True):
    window = ui.MainWindow(demo=demo)
    window.resize(1380, 840)
    window.show()
    qapp.processEvents()
    return window


# ------------------------------------------------------------------ таблица
def test_data_table_keeps_query_order_and_sorts_by_value(qapp):
    table = DataTable([Col("N", "id", "int"), Col("Дата", "d", "date"), Col("Сумма", "m", "money")])
    rows = [{"id": 1, "d": date(2026, 3, 1), "m": 100}, {"id": 2, "d": date(2025, 12, 1), "m": 9},
            {"id": 3, "d": None, "m": 1000}]
    table.set_rows(rows, "€")
    assert [table.item(r, 0).data(Qt.UserRole) for r in range(3)] == [1, 2, 3]      # порядок запроса сохранён
    assert table.item(0, 2).text() == "100 €"
    table.sortByColumn(2, Qt.AscendingOrder)                                         # 9 < 100 < 1000, а не по тексту
    assert [table.item(r, 0).data(Qt.UserRole) for r in range(3)] == [2, 1, 3]
    table.select_id(1)
    assert table.current_id() == 1
    table.set_rows(rows[:2])                                                         # выбор переживает обновление
    assert table.current_id() == 1


# ------------------------------------------------------------------ окно
def test_main_window_with_demo_data(qapp, demo_db, errors):
    window = make_window(qapp)
    assert window.tabs.count() == 7
    assert "демо" in window.windowTitle()
    dash = window.dashboard
    assert dash.k_revenue.value.text() not in ("—", "") and dash.events.rowCount() > 0
    assert dash.attention.count() > 0 and "Воронка" in dash.funnel_label.text()
    assert window.companies.table.rowCount() == 10
    assert window.orders.table.rowCount() > 0
    assert window.invoices.table.rowCount() > 0 and window.holidays.table.rowCount() == 3
    assert window.reports.monthly.rowCount() == 12 and window.reports.by_client.rowCount() > 0
    window.companies.table.select_id(1)                  # чтобы нижняя карточка компании была заполнена
    for i, key in enumerate(("dashboard", "clients", "orders", "invoices", "holidays", "reports", "settings")):
        window.tabs.setCurrentIndex(i)
        qapp.processEvents()
        shot(window, f"{i + 1}-{key}")
    window.close()


ARCHIVE_DB = Path(__file__).resolve().parents[1] / "_archive" / "v1-2026-07" / "flower.db"


@pytest.mark.skipif(not ARCHIVE_DB.exists(), reason="архивная копия flower.db не найдена")
def test_window_opens_on_migrated_real_legacy_database(qapp, tmp_path, errors):
    """Ваша прежняя flower.db (копия) после обновления схемы открывается и показывает старые данные."""
    import shutil
    copy = tmp_path / "flower.db"
    shutil.copy2(ARCHIVE_DB, copy)
    database.init_db(copy)
    window = make_window(qapp, demo=False)
    assert window.companies.table.rowCount() == 2 and window.orders.period.findData("all") >= 0
    window.orders.period.setCurrentIndex(window.orders.period.findData("all"))
    assert window.orders.table.rowCount() == 4
    window.tabs.setCurrentWidget(window.invoices)
    assert window.invoices.table.rowCount() == 1
    shot(window, "legacy-db-dashboard")
    window.close()


def test_window_on_empty_database_does_not_crash(qapp, tmp_path, errors):
    database.init_db(tmp_path / "empty.db")
    window = make_window(qapp, demo=False)
    assert "Начните" in window.dashboard.attention.item(0).text()         # подсказка, с чего начать
    assert window.companies.table.rowCount() == 0
    assert all(not b.isEnabled() for b, needs in window.companies.p_people._buttons if needs)
    window.close()


def test_companies_details_follow_selection(qapp, demo_db, errors):
    window = make_window(qapp)
    tab = window.companies
    tab.table.select_id(1)
    qapp.processEvents()
    assert tab.p_people.table.rowCount() > 0 and tab.p_orders.table.rowCount() > 0
    assert tab.detail.tabText(0).startswith("Получатели (")
    tab.table.clearSelection()
    qapp.processEvents()
    assert tab.p_people.table.rowCount() == 0
    tab.stage_filter.setCurrentIndex(tab.stage_filter.findData("Лид"))
    assert 0 < tab.table.rowCount() < 10
    tab.stage_filter.setCurrentIndex(0)
    tab.search.setText("паритет")
    assert tab.table.rowCount() == 1
    tab.search.clear()
    window.close()


def test_orders_filters_and_status_buttons(qapp, demo_db, errors, messages):
    window = make_window(qapp)
    orders = window.orders
    orders.period.setCurrentIndex(orders.period.findData("all"))
    total = orders.table.rowCount()
    orders.status.setCurrentIndex(orders.status.findData("Доставлен"))
    delivered = orders.table.rowCount()
    assert 0 < delivered < total
    orders.status.setCurrentIndex(0)

    with database.session_scope() as s:
        target = s.query(Order).filter(Order.status == "Новый").order_by(Order.delivery_date).first()
        target_id = target.id
    orders.table.select_id(target_id)
    orders.set_status("Готов")
    orders.table.select_id(target_id)
    orders.set_status("Доставлен")
    with database.session_scope() as s:
        assert s.get(Order, target_id).status == "Доставлен"
    orders.search.setText("ZZZ-нет-такого")
    assert orders.table.rowCount() == 0
    window.close()


def test_run_autogen_creates_orders_and_shows_report(qapp, demo_db, errors, messages):
    window = make_window(qapp)
    window.run_autogen(days=30, manual=True)
    assert messages and messages[-1][1] == "Автозаказы"
    window.run_autogen(days=30, manual=True)                         # второй запуск: новых нет
    assert "Новых заказов нет" in messages[-1][2]
    window.close()


def test_navigation_from_dashboard(qapp, demo_db, errors):
    window = make_window(qapp)
    window.goto("invoices", None)
    assert window.tabs.currentWidget() is window.invoices
    with database.session_scope() as s:
        client_id = s.query(CorporateClient).filter(CorporateClient.stage == "Отказ").one().id
    window.goto("clients", client_id)                                # клиент скрыт фильтром — вкладка сама снимет фильтры
    assert window.companies.table.current_id() == client_id
    window.close()


# ------------------------------------------------------------------ диалоги
def test_order_dialog_price_follows_options_until_amount_edited(qapp, demo_db, errors):
    with database.session_scope() as s:
        client = s.query(CorporateClient).filter(CorporateClient.stage == "Клиент").order_by(CorporateClient.id).first()
        emp = s.query(CorporateEmployee).filter(CorporateEmployee.client_id == client.id,
                                                CorporateEmployee.preferred_budget.is_(None)).first()
        ids = (client.id, emp.id)
        base = client.fixed_price
    dlg = dialogs.OrderDialog(client_id=ids[0], employee_id=ids[1])
    assert dlg.amount.value() == base and "Цена по договору" in dlg.price_label.text()
    assert dlg.address.text() and dlg.card_text.text() and dlg.delivery_time.currentText() == "10:00"
    shot(dlg, "dialog-order")
    dlg.trial.setChecked(True)
    assert dlg.amount.value() == pytest.approx(base * 0.7)             # пробное: −30%
    dlg.amount.setValue(77)                                             # руками — больше не трогаем
    dlg.trial.setChecked(False)
    assert dlg.amount.value() == 77
    dlg.recalc_button.click()
    assert dlg.amount.value() == base

    dlg.delivery_time.setEditText("9:30")
    dlg._on_save()
    with database.session_scope() as s:
        o = s.get(Order, dlg.saved_id)
        assert (o.client_id, o.employee_id, o.delivery_time, o.status, o.auto_created) == (ids[0], ids[1], "09:30", "Новый", False)
        assert o.recipient_name and o.address and o.event_date == o.delivery_date and o.amount == base


def test_order_dialog_rejects_bad_time_and_invoiced_changes(qapp, demo_db, errors, messages):
    with database.session_scope() as s:
        o = s.query(Order).filter(Order.invoice_id.isnot(None)).first()
        order_id, amount = o.id, o.amount
    dlg = dialogs.OrderDialog(order_id=order_id)
    assert not dlg.amount.isEnabled()
    dlg.delivery_time.setEditText("25:99")
    dlg._on_save()
    assert dlg.result() != QDialog.Accepted and "ЧЧ:ММ" in messages[-1][2]
    dlg.delivery_time.setEditText("10:00")
    dlg.status.setCurrentIndex(dlg.status.findData("Отменён"))
    dlg._on_save()
    assert "включён в счёт" in messages[-1][2]
    with database.session_scope() as s:
        assert s.get(Order, order_id).status != "Отменён" and s.get(Order, order_id).amount == amount


def test_recipient_dialog_year_unknown_and_home_address(qapp, demo_db, errors, messages):
    with database.session_scope() as s:
        cid = s.query(CorporateClient).first().id
    dlg = dialogs.RecipientDialog(client_id=cid)
    shot(dlg, "dialog-recipient")
    dlg.full_name.setText("Тестова Анна")
    dlg.birthday.set_value(date(1991, 2, 28))
    dlg.year_unknown.setChecked(True)
    dlg.delivery_kind.setCurrentIndex(dlg.delivery_kind.findData("Домой"))
    dlg._on_save()                                                   # домашний адрес не указан → отказ
    assert dlg.saved_id is None and "домашний адрес" in messages[-1][2]
    dlg.home_address.setText("ул. Тестовая, 1")
    dlg.gender.setCurrentIndex(dlg.gender.findData("female"))
    dlg._on_save()
    with database.session_scope() as s:
        e = s.get(CorporateEmployee, dlg.saved_id)
        assert (e.birthday, e.birth_year_known, e.delivery_kind, e.gender) == (date(2000, 2, 28), False, "Домой", "female")
    reopened = dialogs.RecipientDialog(employee_id=dlg.saved_id)
    assert reopened.year_unknown.isChecked() and reopened.home_address.isEnabled()


def test_client_dialog_roundtrip_and_validation(qapp, demo_db, errors, messages):
    dlg = dialogs.ClientDialog()
    shot(dlg, "dialog-client")
    dlg._on_save()
    assert "название" in messages[-1][2].lower() and dlg.saved_id is None
    dlg.name.setText("ООО Новая")
    dlg.segment.setEditText("Банк")
    dlg.fixed_price.setValue(42)
    dlg.contract_start.set_value(date(2026, 11, 1))
    dlg.contract_end.set_value(date(2026, 10, 1))
    dlg._on_save()
    assert "раньше" in messages[-1][2]
    dlg.contract_end.set_value(date(2027, 10, 31))
    dlg._on_save()
    again = dialogs.ClientDialog(client_id=dlg.saved_id)
    assert (again.name.text(), again.segment.currentText(), again.fixed_price.value(), again.stage.currentData()) == \
           ("ООО Новая", "Банк", 42, "Лид")
    assert again.contract_end.value() == date(2027, 10, 31)


def test_invoice_dialog_autonumber_and_uniqueness(qapp, demo_db, errors, messages):
    with database.session_scope() as s:
        cid = s.query(CorporateClient).first().id
        existing = s.query(Invoice).first().number
    dlg = dialogs.InvoiceDialog(client_id=cid)
    dlg.amount.setValue(120)
    dlg._on_save()
    with database.session_scope() as s:
        number = s.get(Invoice, dlg.saved_id).number
    assert number.startswith("СЧ-")
    dup = dialogs.InvoiceDialog(client_id=cid)
    dup.amount.setValue(10)
    dup.number.setText(existing)
    dup._on_save()
    assert "уже есть" in messages[-1][2] and dup.saved_id is None


def test_month_invoices_and_holiday_orders_dialogs(qapp, demo_db, errors, messages):
    with database.session_scope() as s:
        s.query(Order).update({Order.invoice_id: None})           # освободить заказы
        s.query(Invoice).delete()
    dlg = dialogs.MonthInvoicesDialog()
    shot(dlg, "dialog-month-invoices")
    for month in range(1, 13):                                      # найдём месяц с заказами
        dlg.month.setCurrentIndex(month - 1)
        for year in (date.today().year,):
            dlg.year.setValue(year)
            if dlg.save_button.isEnabled():
                break
        if dlg.save_button.isEnabled():
            break
    assert dlg.save_button.isEnabled()
    dlg._on_save()
    assert "Выставлено счетов" in messages[-1][2]

    with database.session_scope() as s:
        hid = s.query(Holiday).filter(Holiday.name == "8 Марта").one().id
    hd = dialogs.HolidayOrdersDialog(hid)
    shot(hd, "dialog-holiday-orders")
    assert "Будет создано заказов" in hd.preview.text() and hd.save_button.isEnabled()
    hd._on_save()
    assert "Создано заказов" in messages[-1][2]
    again = dialogs.HolidayOrdersDialog(hid)                       # повторное открытие: создавать уже нечего
    assert "Будет создано заказов: 0" in again.preview.text() and not again.save_button.isEnabled()


def test_activity_dialog_moves_funnel(qapp, demo_db, errors):
    with database.session_scope() as s:
        lead = s.query(CorporateClient).filter(CorporateClient.stage == "Лид").one().id
    dlg = dialogs.ActivityDialog(lead)
    dlg.kind.setCurrentIndex(dlg.kind.findData("КП отправлено"))
    dlg.note.setPlainText("отправили")
    dlg._on_save()
    with database.session_scope() as s:
        assert s.get(CorporateClient, lead).stage == "КП отправлено"
        assert s.query(Activity).filter(Activity.client_id == lead, Activity.note == "отправили").count() == 1


def test_holiday_dialog_validation(qapp, tmp_path, errors, messages):
    database.init_db(tmp_path / "h.db")
    dlg = dialogs.HolidayDialog()
    dlg._on_save()
    assert "название" in messages[-1][2].lower()
    dlg.name.setText("Тест")
    dlg.month.setCurrentIndex(dlg.month.findData(2))
    dlg.day.setValue(31)
    dlg._on_save()
    assert "нет в календаре" in messages[-1][2]
    dlg.day.setValue(10)
    dlg._on_save()
    with database.session_scope() as s:
        h = s.get(Holiday, dlg.saved_id)
        assert (h.name, h.month, h.day, h.audience) == ("Тест", 2, 10, "all")


@pytest.fixture
def file_dialogs(monkeypatch, tmp_path):
    """Подменяет диалоги выбора файла и «открыть файл»: тест сам решает, куда сохранять."""
    state = {"save": [], "open": None}

    def fake_save(parent, title, filename, pattern):
        path = tmp_path / ("out-" + str(len(state["save"])) + Path(filename).suffix)
        state["save"].append(path)
        return str(path)

    monkeypatch.setattr(tabs, "ask_save_path", fake_save)
    monkeypatch.setattr(tabs, "offer_open", lambda parent, path: None)
    monkeypatch.setattr(tabs.QFileDialog, "getOpenFileName", lambda *a, **k: (str(state["open"]), ""))
    monkeypatch.setattr(dialogs.DateDialog, "exec_", lambda self: QDialog.Accepted)
    return state


def test_exports_and_import_through_tabs(qapp, demo_db, errors, messages, file_dialogs, tmp_path):
    from docx import Document
    from openpyxl import Workbook, load_workbook
    window = make_window(qapp)
    comp, orders, inv, reports = window.companies, window.orders, window.invoices, window.reports

    comp.table.select_id(1)
    comp.export_proposal()
    assert "Коммерческое предложение" in "\n".join(p.text for p in Document(file_dialogs["save"][-1]).paragraphs)
    comp.download_template()
    assert load_workbook(file_dialogs["save"][-1]).sheetnames[0] == "Получатели"

    wb = Workbook()
    wb.active.append(["ФИО", "Дата рождения", "Пол"])
    wb.active.append(["Загруженная Анна", "03.04.1990", "ж"])
    wb.active.append(["Загруженный Борис", "кривая дата", "м"])
    file_dialogs["open"] = tmp_path / "people.xlsx"
    wb.save(file_dialogs["open"])
    comp.import_list()
    assert "Добавлено получателей: 1" in messages[-1][2] and "Загруженный Борис" in messages[-1][2]
    with database.session_scope() as s:
        assert s.query(CorporateEmployee).filter_by(client_id=1, full_name="Загруженная Анна").count() == 1

    orders.period.setCurrentIndex(orders.period.findData("all"))
    orders.export_orders()
    assert load_workbook(file_dialogs["save"][-1]).worksheets[0].max_row == orders.table.rowCount() + 1
    orders.delivery_sheet()                                          # на сегодня заказы есть
    assert load_workbook(file_dialogs["save"][-1]).sheetnames == ["Лист доставки"]

    inv.table.select_id(inv.table.item(0, 0).data(Qt.UserRole))
    inv.export_invoice()
    assert "Счёт №" in str(load_workbook(file_dialogs["save"][-1]).worksheets[0]["A1"].value)
    reports.export()
    assert load_workbook(file_dialogs["save"][-1]).sheetnames == ["По месяцам", "По компаниям"]
    window.close()


def test_delete_archive_and_payment_actions(qapp, demo_db, errors, messages):
    window = make_window(qapp)
    comp, orders, inv, holidays = window.companies, window.orders, window.invoices, window.holidays

    comp.table.select_id(1)                                         # у компании есть заказы и счета
    comp.delete_client()
    assert "архив" in messages[-1][2]
    with database.session_scope() as s:
        assert s.get(CorporateClient, 1) is not None
    comp.toggle_archive()
    with database.session_scope() as s:
        assert s.get(CorporateClient, 1).is_active is False
    comp.show_archive.setChecked(True)
    comp.table.select_id(1)
    comp.toggle_archive()
    with database.session_scope() as s:
        assert s.get(CorporateClient, 1).is_active is True

    with database.session_scope() as s:
        empty_lead = s.query(CorporateClient).filter(CorporateClient.stage == "Лид").one().id
        act = s.query(Activity).filter(Activity.client_id == empty_lead).first()
        act_id = act.id
    comp.table.select_id(empty_lead)
    comp.p_activities.table.select_id(act_id)
    comp.complete_activity(act_id)
    with database.session_scope() as s:
        assert s.get(Activity, act_id).done is True
    comp.delete_client()                                            # лид без заказов и счетов удаляется
    with database.session_scope() as s:
        assert s.get(CorporateClient, empty_lead) is None

    with database.session_scope() as s:
        unpaid = s.query(Invoice).filter(Invoice.paid.is_(False)).first().id
    inv.table.select_id(unpaid)
    inv.toggle_paid()
    with database.session_scope() as s:
        assert s.get(Invoice, unpaid).paid is True and s.get(Invoice, unpaid).paid_date == date.today()
    inv.toggle_paid()
    with database.session_scope() as s:
        assert s.get(Invoice, unpaid).paid is False and s.get(Invoice, unpaid).paid_date is None
        linked = [o.id for o in s.query(Order).filter(Order.invoice_id == unpaid)]
    assert linked
    inv.delete()
    with database.session_scope() as s:
        assert s.get(Invoice, unpaid) is None
        assert all(s.get(Order, i).invoice_id is None for i in linked)   # заказы освободились

    orders.period.setCurrentIndex(orders.period.findData("all"))
    with database.session_scope() as s:
        invoiced = s.query(Order).filter(Order.invoice_id.isnot(None)).first().id
        free = s.query(Order).filter(Order.invoice_id.is_(None)).first().id
    orders.table.select_id(invoiced)
    orders.delete_order()
    assert "включён в счёт" in messages[-1][2]
    orders.table.select_id(invoiced)
    orders.set_status("Отменён")
    assert "уже включён в счёт" in messages[-1][2]
    orders.table.select_id(free)
    orders.delete_order()
    with database.session_scope() as s:
        assert s.get(Order, free) is None

    holidays.table.select_id(holidays.table.item(0, 0).data(Qt.UserRole))
    holidays.delete()
    assert holidays.table.rowCount() == 2
    window.close()


def test_settings_tab_save_changes_currency(qapp, demo_db, errors, messages):
    window = make_window(qapp)
    st = window.settings
    assert "₽" in window.dashboard.k_revenue.value.text()          # по умолчанию рубли
    st.currency.setEditText("€")
    st.default_price.setValue(36)
    st.save()
    with database.session_scope() as s:
        cfg = load_settings(s)
    assert cfg.currency == "€" and cfg.default_price == 36
    assert "€" in window.dashboard.k_revenue.value.text()
    st.delivery_time.setEditText("99:99")
    st.save()
    assert "ЧЧ:ММ" in messages[-1][2]
    window.close()
