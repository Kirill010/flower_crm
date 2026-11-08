"""Вкладки главного окна: главная, компании, заказы, счета, праздники, отчёты, настройки."""
from __future__ import annotations

import os
from datetime import date, timedelta

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QAbstractSpinBox, QCheckBox, QComboBox, QDialog, QFileDialog,
                             QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QProgressBar, QSplitter, QTabWidget, QVBoxLayout,
                             QWidget)
from sqlalchemy import func

import database
import exports
from database import session_scope
from dialogs import (TIME_SLOTS, ActivityDialog, ClientDialog, DateDialog, HolidayDialog,
                     HolidayOrdersDialog, InvoiceDialog, MonthInvoicesDialog, OrderDialog,
                     RecipientDialog, normalize_time)
from models import (GENDERS, ORDER_STATUSES, STAGES, STATUS_CANCELLED, STATUS_DONE, Activity,
                    CorporateClient, CorporateEmployee, Holiday, Invoice, Order)
from services import (DEFAULT_SETTINGS, WEEKDAYS_RU, BusinessError, attention_items, client_report,
                      dashboard_stats, days_label, delete_client, delete_employee, delete_invoice, delete_order,
                      fmt_date, fmt_day_month, fmt_money, holiday_date, invoice_status,
                      load_settings, month_bounds, monthly_report, save_settings, shift_month,
                      turning_age, upcoming_events)
from theme import COLORS, ROW_BG
from widgets import (Col, DataTable, KpiCard, MoneySpin, PanelTable, combo_value, confirm,
                     fill_combo, heading, info, int_spin, make_button, muted, set_combo, warn)

GENDER_LABEL = dict(GENDERS)
AUDIENCE_LABEL = {"all": "все", "female": "только женщины", "male": "только мужчины"}
TODAY_BG = ROW_BG["today"]


# ------------------------------------------------------------------ общее
class BaseTab(QWidget):
    changed = pyqtSignal()        # данные изменились — главному окну обновить все вкладки

    def refresh(self) -> None:
        raise NotImplementedError

    def select_id(self, ref) -> None:
        pass


def period_bounds(key: str, today: date) -> tuple[date | None, date | None]:
    if key == "today":
        return today, today
    if key == "tomorrow":
        return today + timedelta(days=1), today + timedelta(days=1)
    if key == "week":
        return today, today + timedelta(days=7)
    if key == "month":
        return month_bounds(today)
    if key == "prev_month":
        y, m = shift_month(today.year, today.month, -1)
        return month_bounds(date(y, m, 1))
    if key == "quarter":
        y, m = shift_month(today.year, today.month, -2)
        return date(y, m, 1), month_bounds(today)[1]
    if key == "year":
        return date(today.year, 1, 1), date(today.year, 12, 31)
    return None, None


def ask_save_path(parent, title: str, filename: str, pattern: str) -> str:
    path, _ = QFileDialog.getSaveFileName(parent, title, str(exports.export_path(filename)), pattern)
    return path


def offer_open(parent, path) -> None:
    if confirm(parent, "Файл сохранён", f"{path}\n\nОткрыть файл?", yes="Открыть", no="Закрыть"):
        if hasattr(os, "startfile"):
            try:
                os.startfile(str(path))
            except OSError:
                pass


def button_row(*widgets) -> QHBoxLayout:
    """Ряд кнопок; None — растяжка (всё после неё прижимается вправо)."""
    row = QHBoxLayout()
    for w in widgets:
        if w is None:
            row.addStretch(1)
        else:
            row.addWidget(w)
    return row


def order_row_style(status: str, day: date | None, today: date) -> dict:
    if status == STATUS_CANCELLED:
        return {"_fg": COLORS["muted"]}
    if status == STATUS_DONE or day is None:
        return {}
    if day < today:
        return {"_bg": ROW_BG["overdue"], "_tip": "Доставка просрочена"}
    if day == today:
        return {"_bg": TODAY_BG}
    return {}


# ------------------------------------------------------------------ главная
class DashboardTab(BaseTab):
    navigate = pyqtSignal(str, object)        # (вкладка, id записи)
    autogen_requested = pyqtSignal(int)       # создать заказы на N ближайших дней

    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        cards = QHBoxLayout()
        self.k_revenue = KpiCard("Выручка за месяц")
        self.k_orders = KpiCard("Поздравлений за месяц")
        self.k_clients = KpiCard("Компаний-клиентов")
        self.k_avg = KpiCard("Средний чек")
        self.k_debt = KpiCard("Долг по счетам")
        for card in (self.k_revenue, self.k_orders, self.k_clients, self.k_avg, self.k_debt):
            cards.addWidget(card, 1)
        root.addLayout(cards)

        self.plan_label = muted("")
        self.plan_bar = QProgressBar()
        self.plan_bar.setRange(0, 100)
        self.plan_bar.setTextVisible(False)       # подпись — рядом: на тёмной полосе текст плохо читается
        self.plan_pct = QLabel("")
        self.funnel_label = muted("")
        root.addWidget(self.plan_label)
        bar_row = QHBoxLayout()
        bar_row.addWidget(self.plan_bar, 1)
        bar_row.addWidget(self.plan_pct)
        root.addLayout(bar_row)
        root.addWidget(self.funnel_label)

        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        head.addWidget(heading("Календарь поздравлений"))
        head.addStretch(1)
        self.period = QComboBox()
        fill_combo(self.period, [("7 дней", 7), ("14 дней", 14), ("30 дней", 30)], 14)
        head.addWidget(muted("Показать:"))
        head.addWidget(self.period)
        ll.addLayout(head)
        self.events = DataTable([
            Col("Дата", "date", "date", 100), Col("", "wd", "text", 38), Col("Когда", "when", "text", 115),
            Col("Событие", "kind", "text", 140), Col("Кому", "who", "text", 175),
            Col("Компания", "company", "text", 215), Col("Заказ", "order", "text", 140),
            Col("Примечание", "note", "text", 150)])
        ll.addWidget(self.events, 1)
        self.open_btn = make_button("Открыть / создать заказ", self._open_selected)
        self.autogen_btn = make_button("Создать недостающие заказы", self._autogen, primary=True)
        ll.addLayout(button_row(self.open_btn, self.autogen_btn, None))
        ll.addWidget(muted("Оранжевым выделены события без заказа. Заказы на дни рождения создаются автоматически "
                           "при запуске для компаний со стадией «Клиент».", "hint"))

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.attention_title = heading("Требует внимания")
        rl.addWidget(self.attention_title)
        self.attention = QListWidget()
        self.attention.setWordWrap(True)
        self.attention.itemDoubleClicked.connect(self._on_attention)
        rl.addWidget(self.attention, 1)
        rl.addWidget(muted("Двойной щелчок — перейти к записи.", "hint"))

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        self._events: list = []
        self.period.currentIndexChanged.connect(lambda _: self.refresh())
        self.events.activated_id.connect(self._open_event)

    def refresh(self) -> None:
        today = date.today()
        days = self.period.currentData()
        with session_scope() as s:
            stats = dashboard_stats(s, today)
            events = upcoming_events(s, today, days)
            items = attention_items(s, today)
        cur = stats["currency"]

        self.k_revenue.set(fmt_money(stats["fact_revenue"], cur),
                           f"прогноз {fmt_money(stats['forecast_revenue'], cur)} · план {fmt_money(stats['plan_revenue'], cur)}")
        self.k_orders.set(f"{stats['fact_orders']} / {stats['forecast_orders']}",
                          f"доставлено / всего в месяце · цель {stats['plan_orders']}")
        self.k_clients.set(str(stats["clients_serving"]),
                           f"цель {stats['plan_companies']} · с заказами в месяце: {stats['clients_in_month']}")
        self.k_avg.set(fmt_money(stats["avg_check"], cur) if stats["avg_check"] is not None else "—",
                       f"по финмодели {fmt_money(stats['plan_avg_check'], cur)}")
        self.k_debt.set(fmt_money(stats["receivable"], cur), f"просрочено {fmt_money(stats['overdue'], cur)}")

        self.plan_label.setText(
            f"План на {stats['month_label']} по финансовой модели из ТЗ: {stats['plan_companies']} компаний × "
            f"{stats['plan_orders'] // max(1, stats['plan_companies'])} поздравлений × "
            f"{fmt_money(stats['plan_avg_check'], cur)} = {fmt_money(stats['plan_revenue'], cur)} в месяц")
        self.plan_bar.setValue(min(100, int(round(stats["plan_pct"]))))
        self.plan_pct.setText(f"факт {stats['plan_pct']:.0f}% · с учётом запланированных {stats['forecast_pct']:.0f}%")
        funnel = stats["funnel"]
        self.funnel_label.setText("Воронка привлечения:  " + "  →  ".join(
            f"{stage}: {funnel[stage]}" for stage in STAGES if stage != "Отказ") + f"      (отказов: {funnel['Отказ']})")

        self._events = events
        rows = []
        for i, ev in enumerate(events):
            holiday = ev.holiday_id is not None
            if holiday:
                order_text, bg = "—", ROW_BG["holiday"]
            elif ev.order_id:
                order_text, bg = f"№{ev.order_id} · {ev.order_status}", None
            else:
                order_text, bg = "нет заказа", ROW_BG["no_order"]
            row = {"id": i, "date": ev.date, "wd": WEEKDAYS_RU[ev.date.weekday()], "when": days_label(ev.days),
                   "kind": ev.kind, "who": ev.who, "company": ev.client_name, "order": order_text, "note": ev.note}
            if bg:
                row["_bg"] = bg
            if ev.order_status == STATUS_CANCELLED:
                row["_fg"] = COLORS["muted"]
            rows.append(row)
        self.events.set_rows(rows)
        self.autogen_btn.setText(f"Создать недостающие заказы на {days} дн.")

        self.attention.clear()
        self.attention_title.setText(f"Требует внимания ({len(items)})" if items else "Требует внимания")
        if not items:
            if sum(funnel.values()) == 0:             # пустая база: подсказываем, с чего начать
                hints = ["Начните с вкладки «Компании»: добавьте первую компанию.",
                         "Загрузите список сотрудников с датами рождения (кнопка «Загрузить список (Excel)») — "
                         "дальше поздравления создаются сами.",
                         "Когда договор подписан, поставьте компании стадию «Клиент»."]
            else:
                hints = ["Всё в порядке: срочных дел нет"]
            for text in hints:
                hint_item = QListWidgetItem(text)
                hint_item.setFlags(Qt.NoItemFlags)
                self.attention.addItem(hint_item)
        for item in items:
            li = QListWidgetItem("● " + item["text"])
            li.setForeground(QColor(COLORS[item["level"]]))
            li.setData(Qt.UserRole, (item["target"], item["ref"]))
            self.attention.addItem(li)

    def _open_event(self, index: int) -> None:
        ev = self._events[index]
        if ev.holiday_id is not None:
            self.navigate.emit("holidays", ev.holiday_id)
            return
        if ev.order_id:
            dlg = OrderDialog(order_id=ev.order_id, parent=self)
        else:
            dlg = OrderDialog(client_id=ev.client_id, employee_id=ev.employee_id, occasion=ev.kind,
                              delivery_date=ev.date, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self.changed.emit()

    def _open_selected(self) -> None:
        index = self.events.current_id()
        if index is None:
            warn(self, "Календарь", "Выберите событие в списке.")
            return
        self._open_event(index)

    def _autogen(self) -> None:
        self.autogen_requested.emit(self.period.currentData())

    def _on_attention(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.UserRole)
        if data:
            self.navigate.emit(data[0], data[1])


# ------------------------------------------------------------------ компании
class CompaniesTab(BaseTab):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск: название, контакт, телефон, менеджер…")
        self.search.setClearButtonEnabled(True)
        self.stage_filter = QComboBox()
        fill_combo(self.stage_filter, [("Все стадии", None)] + [(s, s) for s in STAGES])
        self.show_archive = QCheckBox("Показывать архив")
        filters.addWidget(self.search, 1)
        filters.addWidget(self.stage_filter)
        filters.addWidget(self.show_archive)
        root.addLayout(filters)

        splitter = QSplitter(Qt.Vertical)
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        self.table = DataTable([
            Col("Компания", "name", "text", 230), Col("Стадия", "stage", "text", 155),
            Col("Сегмент", "segment", "text", 170), Col("Контакт", "contact", "text", 125),
            Col("Телефон", "phone", "text", 125), Col("Км", "km", "float", 50),
            Col("Менеджер", "manager", "text", 90), Col("Договор до", "contract_end", "date", 100),
            Col("Получателей", "people", "int", 105), Col("След. шаг", "next", "date", 100),
            Col("Цена букета", "price", "money", 105)])
        tl.addWidget(self.table, 1)
        self.btn_add = make_button("Добавить компанию", self.add_client, primary=True)
        self.btn_edit = make_button("Изменить", self.edit_client)
        self.btn_archive = make_button("В архив / вернуть", self.toggle_archive)
        self.btn_delete = make_button("Удалить", self.delete_client)
        self.btn_kp = make_button("Коммерческое предложение (Word)", self.export_proposal)
        self.btn_import = make_button("Загрузить список (Excel)", self.import_list,
                                      tip="Один раз загрузите список сотрудников и дат — дальше поздравления идут сами")
        self.btn_template = make_button("Шаблон списка", self.download_template)
        tl.addLayout(button_row(self.btn_add, self.btn_edit, self.btn_archive, self.btn_delete, None,
                                self.btn_import, self.btn_template, self.btn_kp))

        self.detail = QTabWidget()
        self.p_people = PanelTable(
            [Col("ФИО", "name", "text", 210), Col("Должность", "position", "text", 150),
             Col("Категория", "category", "text", 110), Col("День рождения", "birthday", "birthday", 135),
             Col("Исполняется", "age", "int", 115), Col("Пол", "gender", "text", 85),
             Col("Доставка", "delivery", "text", 90), Col("Любимый букет", "bouquet", "text", 145),
             Col("Бюджет", "budget", "money", 90), Col("Активен", "active", "bool", 85)],
            [("Добавить получателя", self.add_person, False), ("Изменить", self.edit_person, True),
             ("Удалить", self.delete_person, True)])
        self.p_activities = PanelTable(
            [Col("Дата", "date", "date", 90), Col("Что было", "kind", "text", 160),
             Col("Итог / заметка", "note", "text", 380), Col("Следующий шаг до", "next", "date", 155),
             Col("Сделано", "done", "bool", 90)],
            [("Добавить контакт", self.add_activity, False), ("Отметить сделанным", self.complete_activity, True),
             ("Удалить", self.delete_activity, True)])
        self.p_orders = PanelTable(
            [Col("Дата", "date", "date", 90), Col("Время", "time", "text", 60), Col("Получатель", "who", "text", 190),
             Col("Повод", "occasion", "text", 140), Col("Букет", "bouquet", "text", 150),
             Col("Сумма", "amount", "money", 90), Col("Статус", "status", "text", 100)],
            [("Добавить заказ", self.add_order, False), ("Открыть", self.edit_order, True)])
        self.p_invoices = PanelTable(
            [Col("Номер", "number", "text", 140), Col("Дата", "date", "date", 95),
             Col("Оплатить до", "due", "date", 115), Col("Сумма", "amount", "money", 100),
             Col("Статус", "status", "text", 130)],
            [("Открыть", self.edit_invoice, True)])
        self.detail.addTab(self.p_people, "Получатели")
        self.detail.addTab(self.p_activities, "Контакты и следующие шаги")
        self.detail.addTab(self.p_orders, "Заказы")
        self.detail.addTab(self.p_invoices, "Счета")
        self.panels = (self.p_people, self.p_activities, self.p_orders, self.p_invoices)

        splitter.addWidget(top)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        self.search.textChanged.connect(lambda _: self.refresh())
        self.stage_filter.currentIndexChanged.connect(lambda _: self.refresh())
        self.show_archive.toggled.connect(lambda _: self.refresh())
        self.table.itemSelectionChanged.connect(self._load_details)
        self.table.activated_id.connect(lambda cid: self.edit_client(cid))
        self.p_people.table.activated_id.connect(self.edit_person)
        self.p_orders.table.activated_id.connect(self.edit_order)
        self.p_invoices.table.activated_id.connect(self.edit_invoice)

    # ---- данные
    def refresh(self) -> None:
        today = date.today()
        stage = self.stage_filter.currentData()
        needle = self.search.text().strip().casefold()
        with session_scope() as s:
            cur = load_settings(s).currency
            q = s.query(CorporateClient)
            if not self.show_archive.isChecked():
                q = q.filter(CorporateClient.is_active.is_(True))
            if stage:
                q = q.filter(CorporateClient.stage == stage)
            clients = q.order_by(CorporateClient.company_name).all()
            people = dict(s.query(CorporateEmployee.client_id, func.count(CorporateEmployee.id))
                          .filter(CorporateEmployee.is_active.is_(True)).group_by(CorporateEmployee.client_id))
            nexts = dict(s.query(Activity.client_id, func.min(Activity.next_date))
                         .filter(Activity.done.is_(False), Activity.next_date.isnot(None))
                         .group_by(Activity.client_id))
            rows = []
            for c in clients:
                hay = " ".join(str(x or "") for x in (c.company_name, c.contact_person, c.phone, c.manager,
                                                      c.segment, c.email, c.address)).casefold()
                if needle and needle not in hay:
                    continue
                row = {"id": c.id, "name": c.company_name, "stage": c.stage, "segment": c.segment,
                       "contact": c.contact_person, "phone": c.phone, "km": c.distance_km, "manager": c.manager,
                       "contract_end": c.contract_end, "people": people.get(c.id, 0), "next": nexts.get(c.id),
                       "price": c.fixed_price or None}
                if c.is_active is False or c.stage == "Отказ":
                    row["_fg"] = COLORS["muted"]
                elif c.stage == "Клиент" and c.contract_end:
                    left = (c.contract_end - today).days
                    if left < 0:
                        row.update({"_bg": ROW_BG["overdue"], "_tip": "Договор истёк — автозаказы остановлены"})
                    elif left <= 30:
                        row.update({"_bg": TODAY_BG, "_tip": f"Договор заканчивается через {left} дн."})
                rows.append(row)
        self.table.set_rows(rows, cur)
        self._load_details()

    def _load_details(self) -> None:
        cid = self.table.current_id()
        for panel in self.panels:
            panel.set_enabled(cid is not None)
        if cid is None:
            for panel in self.panels:
                panel.table.set_rows([])
            return
        today = date.today()
        with session_scope() as s:
            cur = load_settings(s).currency
            people = []
            for e in s.query(CorporateEmployee).filter(CorporateEmployee.client_id == cid) \
                    .order_by(CorporateEmployee.full_name):
                age = turning_age(e, date(today.year, e.birthday.month, min(e.birthday.day, 28))) \
                    if e.birthday else None
                row = {"id": e.id, "name": e.full_name, "position": e.position, "category": e.category,
                       "birthday": (e.birthday, e.birth_year_known is not False) if e.birthday else None,
                       "age": age, "gender": GENDER_LABEL.get(e.gender or "", ""), "delivery": e.delivery_kind,
                       "bouquet": e.preferred_bouquet, "budget": e.preferred_budget or None,
                       "active": e.is_active is not False}
                if e.is_active is False:
                    row["_fg"] = COLORS["muted"]
                people.append(row)
            activities = []
            for a in s.query(Activity).filter(Activity.client_id == cid) \
                    .order_by(Activity.date.desc(), Activity.id.desc()):
                row = {"id": a.id, "date": a.date, "kind": a.kind, "note": a.note, "next": a.next_date,
                       "done": bool(a.done)}
                if a.done:
                    row["_fg"] = COLORS["muted"]
                elif a.next_date and a.next_date < today:
                    row["_bg"] = ROW_BG["overdue"]
                activities.append(row)
            orders = []
            for o in s.query(Order).filter(Order.client_id == cid).order_by(Order.delivery_date.desc(), Order.id.desc()):
                row = {"id": o.id, "date": o.delivery_date, "time": o.delivery_time, "who": o.recipient_name or "—",
                       "occasion": o.occasion, "bouquet": o.bouquet, "amount": o.amount, "status": o.status}
                row.update(order_row_style(o.status, o.delivery_date, today))
                orders.append(row)
            invoices = []
            for inv in s.query(Invoice).filter(Invoice.client_id == cid).order_by(Invoice.issue_date.desc()):
                status = invoice_status(inv, today)
                row = {"id": inv.id, "number": inv.number, "date": inv.issue_date, "due": inv.due_date,
                       "amount": inv.amount, "status": status}
                if status == "Просрочен":
                    row["_bg"] = ROW_BG["overdue"]
                invoices.append(row)
        self.p_people.table.set_rows(people, cur)
        self.p_activities.table.set_rows(activities, cur)
        self.p_orders.table.set_rows(orders, cur)
        self.p_invoices.table.set_rows(invoices, cur)
        self.detail.setTabText(0, f"Получатели ({len(people)})")
        self.detail.setTabText(1, f"Контакты и следующие шаги ({sum(1 for a in activities if not a['done'])})")
        self.detail.setTabText(2, f"Заказы ({len(orders)})")
        self.detail.setTabText(3, f"Счета ({len(invoices)})")

    def select_id(self, ref) -> None:
        if ref is None:
            return
        if not self.table.select_id(ref):
            self.show_archive.setChecked(True)
            self.stage_filter.setCurrentIndex(0)
            self.search.clear()
            self.refresh()
            self.table.select_id(ref)

    def _need_client(self) -> int | None:
        cid = self.table.current_id()
        if cid is None:
            warn(self, "Компании", "Выберите компанию в списке.")
        return cid

    # ---- компании
    def add_client(self) -> None:
        stage = self.stage_filter.currentData()
        dlg = ClientDialog(stage=stage, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self.changed.emit()
            self.table.select_id(dlg.saved_id)

    def edit_client(self, cid: int | None = None) -> None:
        cid = cid or self._need_client()
        if cid is None:
            return
        dlg = ClientDialog(client_id=cid, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self.changed.emit()

    def toggle_archive(self) -> None:
        cid = self._need_client()
        if cid is None:
            return
        with session_scope() as s:
            c = s.get(CorporateClient, cid)
            if c.is_active is not False and not confirm(
                    self, "В архив", f"Перенести «{c.company_name}» в архив?\n"
                    "История заказов и счетов сохранится, автозаказы создаваться не будут."):
                return
            c.is_active = not (c.is_active is not False)
        self.changed.emit()

    def delete_client(self) -> None:
        cid = self._need_client()
        if cid is None:
            return
        with session_scope() as s:
            name = s.get(CorporateClient, cid).company_name
        if not confirm(self, "Удаление", f"Удалить компанию «{name}» вместе с получателями и журналом контактов?\n"
                                         "Действие нельзя отменить."):
            return
        try:
            with session_scope() as s:
                delete_client(s, cid)
        except BusinessError as exc:
            warn(self, "Удалить нельзя", str(exc))
            return
        self.changed.emit()

    def export_proposal(self) -> None:
        cid = self.table.current_id()
        with session_scope() as s:
            st = load_settings(s)
            client = s.get(CorporateClient, cid) if cid else None
            data = exports.client_proposal_data(client) if client else None
        name = f"КП {data['company_name']}.docx" if data else "КП.docx"
        path = ask_save_path(self, "Коммерческое предложение", name, "Документ Word (*.docx)")
        if not path:
            return
        exports.export_proposal_docx(path, st, data)
        offer_open(self, path)

    def import_list(self) -> None:
        cid = self._need_client()
        if cid is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Список сотрудников", "", "Excel (*.xlsx)")
        if not path:
            return
        try:
            with session_scope() as s:
                res = exports.import_recipients(s, cid, path)
        except Exception as exc:                      # файл повреждён, открыт в Excel и т.п.
            warn(self, "Не удалось прочитать файл", str(exc))
            return
        lines = [f"Добавлено получателей: {res.added}"]
        if res.skipped_existing:
            lines.append(f"Уже были в списке: {res.skipped_existing}")
        if res.no_gender:
            lines.append(f"Без указанного пола: {res.no_gender} (не получат поздравления 8 Марта и 23 Февраля)")
        if res.errors:
            lines.append("\nНе загружено:\n" + "\n".join(res.errors[:12]))
        info(self, "Загрузка списка", "\n".join(lines))
        self.changed.emit()

    def download_template(self) -> None:
        path = ask_save_path(self, "Шаблон списка получателей", "Шаблон списка сотрудников.xlsx", "Excel (*.xlsx)")
        if path:
            exports.recipients_template_xlsx(path)
            offer_open(self, path)

    # ---- получатели
    def add_person(self, _=None) -> None:
        cid = self._need_client()
        if cid is None:
            return
        if RecipientDialog(client_id=cid, parent=self).exec_() == QDialog.Accepted:
            self.changed.emit()

    def edit_person(self, eid: int | None) -> None:
        if eid is not None and RecipientDialog(employee_id=eid, parent=self).exec_() == QDialog.Accepted:
            self.changed.emit()

    def delete_person(self, eid: int | None) -> None:
        if eid is None:
            return
        with session_scope() as s:
            name = s.get(CorporateEmployee, eid).full_name
        if confirm(self, "Удаление", f"Удалить получателя «{name}»?\nЗаказы в истории останутся."):
            with session_scope() as s:
                delete_employee(s, eid)
            self.changed.emit()

    # ---- контакты
    def add_activity(self, _=None) -> None:
        cid = self._need_client()
        if cid is not None and ActivityDialog(cid, parent=self).exec_() == QDialog.Accepted:
            self.changed.emit()

    def complete_activity(self, aid: int | None) -> None:
        if aid is None:
            return
        with session_scope() as s:
            a = s.get(Activity, aid)
            a.done = True
        self.changed.emit()

    def delete_activity(self, aid: int | None) -> None:
        if aid is not None and confirm(self, "Удаление", "Удалить запись о контакте?"):
            with session_scope() as s:
                a = s.get(Activity, aid)
                if a is not None:
                    s.delete(a)
            self.changed.emit()

    # ---- заказы и счета компании
    def add_order(self, _=None) -> None:
        cid = self._need_client()
        if cid is not None and OrderDialog(client_id=cid, parent=self).exec_() == QDialog.Accepted:
            self.changed.emit()

    def edit_order(self, oid: int | None) -> None:
        if oid is not None and OrderDialog(order_id=oid, parent=self).exec_() == QDialog.Accepted:
            self.changed.emit()

    def edit_invoice(self, iid: int | None) -> None:
        if iid is not None and InvoiceDialog(invoice_id=iid, parent=self).exec_() == QDialog.Accepted:
            self.changed.emit()


# ------------------------------------------------------------------ заказы
class OrdersTab(BaseTab):
    PERIODS = [("Этот месяц", "month"), ("Сегодня", "today"), ("Завтра", "tomorrow"),
               ("Ближайшие 7 дней", "week"), ("Прошлый месяц", "prev_month"), ("Все даты", "all")]

    def __init__(self):
        super().__init__()
        self._rows: list[dict] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        filters = QHBoxLayout()
        self.period = QComboBox()
        fill_combo(self.period, self.PERIODS)
        self.status = QComboBox()
        fill_combo(self.status, [("Все статусы", None), ("Не завершённые", "open")] + [(s, s) for s in ORDER_STATUSES])
        self.company = QComboBox()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск: получатель, букет, адрес, повод, комментарий…")
        self.search.setClearButtonEnabled(True)
        for w in (self.period, self.status, self.company):
            filters.addWidget(w)
        filters.addWidget(self.search, 1)
        root.addLayout(filters)

        self.table = DataTable([
            Col("№", "id", "int", 55), Col("Дата", "delivery_date", "date", 90), Col("Время", "delivery_time", "text", 60),
            Col("Компания", "company", "text", 180), Col("Получатель", "recipient", "text", 170),
            Col("Повод", "occasion", "text", 120), Col("Букет", "bouquet", "text", 140),
            Col("Адрес", "address", "text", 200), Col("Сумма", "amount", "money", 90),
            Col("Статус", "status", "text", 100), Col("Счёт", "invoice", "text", 120)])
        root.addWidget(self.table, 1)
        self.summary = muted("")
        root.addWidget(self.summary)

        self.btn_ready = make_button("Готов", lambda: self.set_status("Готов"))
        self.btn_way = make_button("В пути", lambda: self.set_status("В пути"))
        self.btn_done = make_button("Доставлен", lambda: self.set_status("Доставлен"), primary=True)
        self.btn_cancel = make_button("Отменить заказ", lambda: self.set_status(STATUS_CANCELLED))
        root.addLayout(button_row(
            make_button("Добавить", self.add_order, primary=True), make_button("Изменить", self.edit_order),
            make_button("Удалить", self.delete_order), self.btn_ready, self.btn_way, self.btn_done, self.btn_cancel,
            None, make_button("Лист доставки…", self.delivery_sheet,
                              tip="Лист курьера на выбранный день: по времени, с адресами и телефонами"),
            make_button("Экспорт в Excel…", self.export_orders)))

        for w in (self.period, self.status, self.company):
            w.currentIndexChanged.connect(lambda _: self.refresh())
        self.search.textChanged.connect(lambda _: self.refresh())
        self.table.activated_id.connect(lambda oid: self.edit_order(oid))

    def _fetch(self, start, end, status=None, client_id=None, needle: str = "") -> list[dict]:
        today = date.today()
        with session_scope() as s:
            names = {c.id: c.company_name for c in s.query(CorporateClient)}
            numbers = dict(s.query(Invoice.id, Invoice.number))
            q = s.query(Order)
            if start:
                q = q.filter(Order.delivery_date >= start)
            if end:
                q = q.filter(Order.delivery_date <= end)
            if status == "open":
                q = q.filter(Order.status.notin_((STATUS_DONE, STATUS_CANCELLED)))
            elif status:
                q = q.filter(Order.status == status)
            if client_id:
                q = q.filter(Order.client_id == client_id)
            rows = []
            for o in q.order_by(Order.delivery_date, Order.delivery_time, Order.id):
                row = {"id": o.id, "delivery_date": o.delivery_date, "delivery_time": o.delivery_time or "",
                       "company": names.get(o.client_id, "—"), "recipient": o.recipient_name or "— на компанию",
                       "phone": o.recipient_phone or "", "address": o.address or "", "occasion": o.occasion or "",
                       "service": o.service or "", "bouquet": o.bouquet or "",
                       "card_text": (o.card_text or "") if o.with_card else "", "gift": o.gift or "",
                       "amount": o.amount or 0, "status": o.status or "", "is_trial": bool(o.is_trial),
                       "invoice": numbers.get(o.invoice_id, "") if o.invoice_id else "", "comment": o.comment or ""}
                row.update(order_row_style(row["status"], o.delivery_date, today))
                rows.append(row)
        if needle:
            needle = needle.casefold()
            rows = [r for r in rows if needle in " ".join(
                str(r[k]) for k in ("company", "recipient", "bouquet", "address", "occasion", "comment", "phone")).casefold()]
        return rows

    def refresh(self) -> None:
        with session_scope() as s:
            cur = load_settings(s).currency
            companies = [(c.company_name, c.id) for c in s.query(CorporateClient).order_by(CorporateClient.company_name)]
        current = self.company.currentData()
        fill_combo(self.company, [("Все компании", None)] + companies, current)
        start, end = period_bounds(self.period.currentData(), date.today())
        self._rows = self._fetch(start, end, self.status.currentData(), self.company.currentData(),
                                 self.search.text().strip())
        self.table.set_rows(self._rows, cur)
        total = sum(r["amount"] for r in self._rows if r["status"] != STATUS_CANCELLED)
        done = sum(r["amount"] for r in self._rows if r["status"] == STATUS_DONE)
        self.summary.setText(f"Показано заказов: {len(self._rows)} · на сумму {fmt_money(total, cur)} "
                             f"(доставлено на {fmt_money(done, cur)}). Отменённые в сумму не входят.")

    def select_id(self, ref) -> None:
        if ref is not None and not self.table.select_id(ref):
            self.period.setCurrentIndex(self.period.findData("all"))
            self.status.setCurrentIndex(0)
            self.company.setCurrentIndex(0)
            self.search.clear()
            self.refresh()
            self.table.select_id(ref)

    def _need_order(self) -> int | None:
        oid = self.table.current_id()
        if oid is None:
            warn(self, "Заказы", "Выберите заказ в списке.")
        return oid

    def add_order(self) -> None:
        dlg = OrderDialog(parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self.changed.emit()
            self.table.select_id(dlg.saved_id)

    def edit_order(self, oid: int | None = None) -> None:
        oid = oid or self._need_order()
        if oid is not None and OrderDialog(order_id=oid, parent=self).exec_() == QDialog.Accepted:
            self.changed.emit()

    def delete_order(self) -> None:
        oid = self._need_order()
        if oid is None or not confirm(self, "Удаление", f"Удалить заказ №{oid}?\n"
                                                         "Если заказ не нужен, но его надо сохранить в истории, "
                                                         "лучше нажмите «Отменить заказ»."):
            return
        try:
            with session_scope() as s:
                delete_order(s, oid)
        except BusinessError as exc:
            warn(self, "Удалить нельзя", str(exc))
            return
        self.changed.emit()

    def set_status(self, status: str) -> None:
        oid = self._need_order()
        if oid is None:
            return
        try:
            with session_scope() as s:
                o = s.get(Order, oid)
                if o.invoice_id and status == STATUS_CANCELLED:
                    raise BusinessError("Заказ уже включён в счёт — отменить его нельзя.\n"
                                        "Сначала удалите счёт во вкладке «Счета».")
                o.status = status
        except BusinessError as exc:
            warn(self, "Нельзя изменить", str(exc))
            return
        self.changed.emit()

    def delivery_sheet(self) -> None:
        dlg = DateDialog("Лист доставки", "День доставки", date.today(), parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return
        day = dlg.value()
        rows = self._fetch(day, day)
        if not any(r["status"] != STATUS_CANCELLED for r in rows):
            info(self, "Лист доставки", f"На {fmt_date(day)} нет заказов.")
            return
        with session_scope() as s:
            company = load_settings(s).company_name
        path = ask_save_path(self, "Лист доставки", f"Лист доставки {day:%Y-%m-%d}.xlsx", "Excel (*.xlsx)")
        if path:
            exports.export_delivery_sheet_xlsx(path, rows, day, company)
            offer_open(self, path)

    def export_orders(self) -> None:
        if not self._rows:
            info(self, "Экспорт", "В списке нет заказов.")
            return
        path = ask_save_path(self, "Экспорт заказов", f"Заказы {date.today():%Y-%m-%d}.xlsx", "Excel (*.xlsx)")
        if path:
            exports.export_orders_xlsx(path, self._rows)
            offer_open(self, path)


# ------------------------------------------------------------------ счета
class InvoicesTab(BaseTab):
    STATUSES = ["Ожидает оплаты", "Просрочен", "Оплачен"]

    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        filters = QHBoxLayout()
        self.status = QComboBox()
        fill_combo(self.status, [("Все статусы", None)] + [(s, s) for s in self.STATUSES])
        self.company = QComboBox()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по номеру или описанию…")
        self.search.setClearButtonEnabled(True)
        filters.addWidget(self.status)
        filters.addWidget(self.company)
        filters.addWidget(self.search, 1)
        root.addLayout(filters)
        self.table = DataTable([
            Col("Номер", "number", "text", 130), Col("Компания", "company", "text", 220), Col("Дата", "issue", "date", 95),
            Col("Оплатить до", "due", "date", 115), Col("Период", "period", "text", 195), Col("Сумма", "amount", "money", 100),
            Col("Статус", "status", "text", 125), Col("Оплачен", "paid_date", "date", 100),
            Col("Описание", "description", "text", 260)])
        root.addWidget(self.table, 1)
        self.summary = muted("")
        root.addWidget(self.summary)
        root.addLayout(button_row(
            make_button("Сформировать счета за месяц…", self.generate, primary=True,
                        tip="Каждой компании — один счёт за доставленные в месяце заказы"),
            make_button("Добавить", self.add), make_button("Изменить", self.edit),
            make_button("Отметить оплату / снять", self.toggle_paid), make_button("Удалить", self.delete),
            None, make_button("Экспорт счёта в Excel…", self.export_invoice)))
        for w in (self.status, self.company):
            w.currentIndexChanged.connect(lambda _: self.refresh())
        self.search.textChanged.connect(lambda _: self.refresh())
        self.table.activated_id.connect(lambda iid: self.edit(iid))

    def refresh(self) -> None:
        today = date.today()
        needle = self.search.text().strip().casefold()
        with session_scope() as s:
            cur = load_settings(s).currency
            names = {c.id: c.company_name for c in s.query(CorporateClient)}
            current = self.company.currentData()
            fill_combo(self.company, [("Все компании", None)] + sorted(
                [(n, i) for i, n in names.items()]), current)
            q = s.query(Invoice)
            if self.company.currentData():
                q = q.filter(Invoice.client_id == self.company.currentData())
            rows = []
            for inv in q.order_by(Invoice.issue_date.desc(), Invoice.id.desc()):
                status = invoice_status(inv, today)
                if self.status.currentData() and status != self.status.currentData():
                    continue
                if needle and needle not in f"{inv.number or ''} {inv.description or ''}".casefold():
                    continue
                period = (f"{fmt_date(inv.period_start)} – {fmt_date(inv.period_end)}" if inv.period_start else "")
                row = {"id": inv.id, "number": inv.number, "company": names.get(inv.client_id, "—"),
                       "issue": inv.issue_date, "due": inv.due_date, "period": period, "amount": inv.amount,
                       "status": status, "paid_date": inv.paid_date, "description": inv.description}
                if status == "Просрочен":
                    row["_bg"] = ROW_BG["overdue"]
                elif status == "Оплачен":
                    row["_fg"] = COLORS["muted"]
                rows.append(row)
        self.table.set_rows(rows, cur)
        unpaid = sum(r["amount"] or 0 for r in rows if r["status"] != "Оплачен")
        overdue = sum(r["amount"] or 0 for r in rows if r["status"] == "Просрочен")
        paid = sum(r["amount"] or 0 for r in rows if r["status"] == "Оплачен")
        self.summary.setText(f"Показано счетов: {len(rows)} · к оплате {fmt_money(unpaid, cur)} "
                             f"(просрочено {fmt_money(overdue, cur)}) · оплачено {fmt_money(paid, cur)}")

    def select_id(self, ref) -> None:
        if ref is not None and not self.table.select_id(ref):
            self.status.setCurrentIndex(0)
            self.company.setCurrentIndex(0)
            self.search.clear()
            self.refresh()
            self.table.select_id(ref)

    def _need(self) -> int | None:
        iid = self.table.current_id()
        if iid is None:
            warn(self, "Счета", "Выберите счёт в списке.")
        return iid

    def generate(self) -> None:
        dlg = MonthInvoicesDialog(parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self.changed.emit()

    def add(self) -> None:
        dlg = InvoiceDialog(parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self.changed.emit()
            self.table.select_id(dlg.saved_id)

    def edit(self, iid: int | None = None) -> None:
        iid = iid or self._need()
        if iid is not None and InvoiceDialog(invoice_id=iid, parent=self).exec_() == QDialog.Accepted:
            self.changed.emit()

    def toggle_paid(self) -> None:
        iid = self._need()
        if iid is None:
            return
        with session_scope() as s:
            inv = s.get(Invoice, iid)
            inv.paid = not bool(inv.paid)
            inv.paid_date = date.today() if inv.paid else None
        self.changed.emit()

    def delete(self) -> None:
        iid = self._need()
        if iid is None or not confirm(self, "Удаление", "Удалить счёт?\nЗаказы из него освободятся и "
                                                         "попадут в следующий счёт за этот месяц."):
            return
        with session_scope() as s:
            delete_invoice(s, iid)
        self.changed.emit()

    def export_invoice(self) -> None:
        iid = self._need()
        if iid is None:
            return
        with session_scope() as s:
            data = exports.invoice_export_data(s, iid)
        path = ask_save_path(self, "Экспорт счёта", f"Счёт {data['number']}.xlsx", "Excel (*.xlsx)")
        if path:
            exports.export_invoice_xlsx(path, data)
            offer_open(self, path)


# ------------------------------------------------------------------ праздники
class HolidaysTab(BaseTab):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        root.addWidget(heading("Праздники для массовых поздравлений"))
        root.addWidget(muted("8 Марта, 23 Февраля, Новый год и профессиональные праздники. Нажмите «Создать заказы» — "
                             "программа создаст заказы всем подходящим получателям компаний-клиентов и покажет, "
                             "сколько их будет, до создания.", "hint"))
        self.table = DataTable([
            Col("Праздник", "name", "text", 220), Col("День доставки", "when", "text", 130),
            Col("Кого поздравляем", "audience", "text", 165), Col("Сегмент", "segment", "text", 200),
            Col("Напомнить за", "lead", "text", 125), Col("Ближайшая дата", "next", "date", 140),
            Col("Использовать", "active", "bool", 115)])
        root.addWidget(self.table, 1)
        root.addLayout(button_row(
            make_button("Создать заказы на праздник…", self.create_orders, primary=True),
            make_button("Добавить", self.add), make_button("Изменить", self.edit),
            make_button("Удалить", self.delete), None))
        self.table.activated_id.connect(lambda hid: self.edit(hid))

    def refresh(self) -> None:
        today = date.today()
        with session_scope() as s:
            rows = []
            for h in s.query(Holiday).order_by(Holiday.month, Holiday.day):
                nxt = holiday_date(h, today.year)
                if nxt < today:
                    nxt = holiday_date(h, today.year + 1)
                row = {"id": h.id, "name": h.name, "when": fmt_day_month(date(2000, h.month, h.day)),
                       "audience": AUDIENCE_LABEL.get(h.audience or "all", ""), "segment": h.segment or "все",
                       "lead": f"{h.lead_days} дн.", "next": nxt, "active": h.is_active is not False}
                if h.is_active is False:
                    row["_fg"] = COLORS["muted"]
                rows.append(row)
        self.table.set_rows(rows)

    def select_id(self, ref) -> None:
        if ref is not None:
            self.table.select_id(ref)

    def _need(self) -> int | None:
        hid = self.table.current_id()
        if hid is None:
            warn(self, "Праздники", "Выберите праздник в списке.")
        return hid

    def create_orders(self) -> None:
        hid = self._need()
        if hid is not None and HolidayOrdersDialog(hid, parent=self).exec_() == QDialog.Accepted:
            self.changed.emit()

    def add(self) -> None:
        dlg = HolidayDialog(parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self.changed.emit()
            self.table.select_id(dlg.saved_id)

    def edit(self, hid: int | None = None) -> None:
        hid = hid or self._need()
        if hid is not None and HolidayDialog(holiday_id=hid, parent=self).exec_() == QDialog.Accepted:
            self.changed.emit()

    def delete(self) -> None:
        hid = self._need()
        if hid is None or not confirm(self, "Удаление", "Удалить праздник?\nУже созданные заказы останутся."):
            return
        with session_scope() as s:
            h = s.get(Holiday, hid)
            if h is not None:
                s.delete(h)
        self.changed.emit()


# ------------------------------------------------------------------ отчёты
class ReportsTab(BaseTab):
    PERIODS = [("Этот месяц", "month"), ("Прошлый месяц", "prev_month"), ("Последние 3 месяца", "quarter"),
               ("Этот год", "year"), ("Всё время", "all")]

    def __init__(self):
        super().__init__()
        self._monthly: list[dict] = []
        self._clients: list[dict] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(heading("Выручка по месяцам: факт против плана"))
        head.addStretch(1)
        head.addWidget(make_button("Экспорт отчёта в Excel…", self.export))
        root.addLayout(head)
        self.monthly = DataTable([
            Col("Месяц", "label", "text", 150), Col("Компаний с заказами", "clients", "int", 175),
            Col("Поздравлений", "orders", "int", 125), Col("Доставлено", "delivered", "int", 110),
            Col("Выручка (факт)", "revenue", "money", 140), Col("Прогноз", "forecast", "money", 110),
            Col("План", "plan", "money", 110), Col("Выполнение плана", "plan_pct", "pct", 155),
            Col("Средний чек", "avg_check", "money", 125)])
        root.addWidget(self.monthly, 3)
        head2 = QHBoxLayout()
        head2.addWidget(heading("По компаниям"))
        head2.addStretch(1)
        self.period = QComboBox()
        fill_combo(self.period, self.PERIODS)
        head2.addWidget(self.period)
        root.addLayout(head2)
        self.by_client = DataTable([
            Col("Компания", "company", "text", 260), Col("Поздравлений", "orders", "int", 125),
            Col("Выручка (факт)", "revenue", "money", 140), Col("Прогноз", "forecast", "money", 110),
            Col("Выставлено счетов", "invoiced", "money", 160), Col("Долг по счетам", "debt", "money", 140)])
        root.addWidget(self.by_client, 3)
        self.period.currentIndexChanged.connect(lambda _: self.refresh())

    def refresh(self) -> None:
        today = date.today()
        start, end = period_bounds(self.period.currentData(), today)
        with session_scope() as s:
            cur = load_settings(s).currency
            monthly = monthly_report(s, 12, today)
            clients = client_report(s, start or date(2000, 1, 1), end or date(2100, 1, 1))
        self._monthly, self._clients, self._cur = monthly, clients, cur
        self.monthly.set_rows([dict(m, id=i) for i, m in reversed(list(enumerate(monthly)))], cur)
        self.by_client.set_rows(clients, cur)

    def export(self) -> None:
        path = ask_save_path(self, "Отчёт", f"Отчёт {date.today():%Y-%m-%d}.xlsx", "Excel (*.xlsx)")
        if path:
            exports.export_report_xlsx(path, self._monthly, self._clients, self._cur)
            offer_open(self, path)


# ------------------------------------------------------------------ настройки
class SettingsTab(BaseTab):
    saved = pyqtSignal()

    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        form_box = QWidget()
        form_box.setMaximumWidth(980)                 # на широком экране поля не растягиваются на всю ширину
        form = QFormLayout(form_box)
        form.setContentsMargins(0, 0, 0, 0)
        form.setLabelAlignment(Qt.AlignRight)
        self.company_name = QLineEdit()
        self.shop_contacts = QLineEdit()
        self.shop_contacts.setPlaceholderText("телефон, сайт, email — попадут в КП и счета")
        self.currency = QComboBox()
        self.currency.setEditable(True)
        fill_combo(self.currency, ["₽", "€", "$"])
        self.default_price = MoneySpin()
        self.card_price = MoneySpin()
        self.trial_discount = int_spin(0, 100, suffix="%")
        self.lead_days = int_spin(0, 30, suffix="дн.")
        self.delivery_time = QComboBox()
        self.delivery_time.setEditable(True)
        fill_combo(self.delivery_time, TIME_SLOTS)
        self.weekend_shift = QCheckBox("День рождения в выходной: доставка в офис — в пятницу")
        self.invoice_due_days = int_spin(0, 90, suffix="дн.")
        self.plan_companies = int_spin(0, 10000)
        self.plan_per_company = int_spin(0, 10000)
        self.plan_avg_check = MoneySpin()
        self.birthday_card_text = QLineEdit()
        self.holiday_card_text = QLineEdit()
        rows = (("Название компании", self.company_name), ("Контакты компании", self.shop_contacts),
                ("Валюта", self.currency), ("Цена букета по умолчанию", self.default_price),
                ("Цена открытки", self.card_price), ("Скидка на пробное поздравление", self.trial_discount),
                ("Создавать заказы на ДР за", self.lead_days), ("Время доставки по умолчанию", self.delivery_time),
                ("", self.weekend_shift), ("Срок оплаты счёта", self.invoice_due_days),
                ("План: компаний-клиентов", self.plan_companies), ("План: поздравлений в месяц от компании", self.plan_per_company),
                ("План: средний заказ", self.plan_avg_check), ("Текст открытки (день рождения)", self.birthday_card_text),
                ("Текст открытки (праздник)", self.holiday_card_text))
        for label, widget in rows:
            if isinstance(widget, (QComboBox, QAbstractSpinBox)):
                widget.setMaximumWidth(260)           # числа и списки — компактно, текст — во всю ширину формы
            form.addRow(label, widget)
        root.addWidget(form_box)                      # растёт до 980 px и прижата влево
        root.addWidget(muted("В тексте открытки можно использовать {name} — ФИО получателя, {company} — компания, "
                             "{holiday} — название праздника. План по умолчанию — финансовая модель из ТЗ: "
                             "10 компаний × 15 поздравлений в месяц × средний заказ (в ТЗ 35 €, здесь 3 500 ₽ — "
                             "всего 525 000 ₽ в месяц).", "hint"))
        self.location = muted("")
        root.addWidget(self.location)
        root.addLayout(button_row(
            make_button("Сохранить настройки", self.save, primary=True),
            make_button("Создать резервную копию", self.backup),
            make_button("Открыть папку с данными", self.open_folder), None))
        root.addStretch(1)

    def refresh(self) -> None:
        with session_scope() as s:
            st = load_settings(s)
        self.company_name.setText(st.company_name)
        self.shop_contacts.setText(st.shop_contacts)
        set_combo(self.currency, st.currency)
        self.default_price.setValue(st.default_price)
        self.card_price.setValue(st.card_price)
        self.trial_discount.setValue(int(st.trial_discount))
        self.lead_days.setValue(st.lead_days)
        set_combo(self.delivery_time, st.default_delivery_time)
        self.weekend_shift.setChecked(st.weekend_shift)
        self.invoice_due_days.setValue(st.invoice_due_days)
        self.plan_companies.setValue(st.plan_companies)
        self.plan_per_company.setValue(st.plan_per_company)
        self.plan_avg_check.setValue(st.plan_avg_check)
        self.birthday_card_text.setText(st.birthday_card_text)
        self.holiday_card_text.setText(st.holiday_card_text)
        for line in (self.birthday_card_text, self.holiday_card_text, self.shop_contacts):
            line.setCursorPosition(0)                 # показываем начало текста, а не хвост
        self.location.setText(f"База данных: {database.db_path()}\nРезервные копии: {database.backup_dir()} "
                              "(автоматически раз в день и перед обновлением схемы)")

    def save(self) -> None:
        time_text = normalize_time(self.delivery_time.currentText())
        if time_text is None:
            warn(self, "Настройки", "Время доставки укажите как ЧЧ:ММ, например 10:00.")
            return
        with session_scope() as s:
            save_settings(s, {
                "company_name": self.company_name.text().strip() or DEFAULT_SETTINGS["company_name"],
                "shop_contacts": self.shop_contacts.text().strip(),
                "currency": combo_value(self.currency) or DEFAULT_SETTINGS["currency"],
                "default_price": self.default_price.value(), "card_price": self.card_price.value(),
                "trial_discount": self.trial_discount.value(), "lead_days": self.lead_days.value(),
                "default_delivery_time": time_text or "10:00", "weekend_shift": self.weekend_shift.isChecked(),
                "invoice_due_days": self.invoice_due_days.value(), "plan_companies": self.plan_companies.value(),
                "plan_per_company": self.plan_per_company.value(), "plan_avg_check": self.plan_avg_check.value(),
                "birthday_card_text": self.birthday_card_text.text().strip(),
                "holiday_card_text": self.holiday_card_text.text().strip()})
        info(self, "Настройки", "Настройки сохранены.")
        self.saved.emit()

    def backup(self) -> None:
        dest = database.backup_database("manual")
        info(self, "Резервная копия", f"Копия базы сохранена:\n{dest}")

    def open_folder(self) -> None:
        folder = database.db_path().parent
        if hasattr(os, "startfile"):
            try:
                os.startfile(str(folder))
            except OSError:
                pass
