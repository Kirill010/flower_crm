"""Главное окно приложения."""
from __future__ import annotations

from datetime import date

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QKeySequence
from PyQt5.QtWidgets import (QDialog, QHBoxLayout, QLabel, QMainWindow, QShortcut, QTabWidget,
                             QVBoxLayout, QWidget)

import database
import theme
from database import session_scope
from dialogs import OrderDialog
from models import CorporateClient
from services import MONTHS_RU_GEN, fmt_date, generate_birthday_orders, load_settings
from tabs import (CompaniesTab, DashboardTab, HolidaysTab, InvoicesTab, OrdersTab, ReportsTab,
                  SettingsTab)
from widgets import info, make_button

WEEKDAYS_FULL = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


class MainWindow(QMainWindow):
    def __init__(self, demo: bool = False):
        super().__init__()
        self.demo = demo
        self._refreshing = False
        self._last_day = date.today()
        self.resize(1380, 840)

        central = QWidget()
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(10, 10, 10, 4)

        header = QHBoxLayout()
        header.setSpacing(14)
        self.logo = QLabel()
        self.logo.setPixmap(theme.emblem_pixmap(56))
        header.addWidget(self.logo)
        brand_box = QVBoxLayout()
        brand_box.setSpacing(0)
        self.brand_title = QLabel(theme.BRAND_NAME)
        self.brand_title.setObjectName("brandTitle")
        self.brand_sub = QLabel(theme.BRAND_TAGLINE.upper())
        self.brand_sub.setObjectName("brandSub")
        spaced = self.brand_sub.font()
        spaced.setLetterSpacing(QFont.AbsoluteSpacing, 2.0)       # разрядка, как у логотипа
        self.brand_sub.setFont(spaced)
        brand_box.addWidget(self.brand_title)
        brand_box.addWidget(self.brand_sub)
        header.addLayout(brand_box)
        header.addSpacing(24)
        self.date_label = QLabel()
        self.date_label.setObjectName("muted")
        header.addWidget(self.date_label)
        if demo:
            badge = QLabel("ДЕМО-РЕЖИМ: вымышленные данные, отдельная база demo.db")
            badge.setObjectName("demoBadge")
            header.addWidget(badge)
        header.addStretch(1)
        header.addWidget(make_button("Новый заказ", self.new_order, primary=True, tip="Ctrl+N"))
        header.addWidget(make_button("Обновить", self.refresh_all, tip="F5"))
        lay.addLayout(header)

        self.dashboard = DashboardTab()
        self.companies = CompaniesTab()
        self.orders = OrdersTab()
        self.invoices = InvoicesTab()
        self.holidays = HolidaysTab()
        self.reports = ReportsTab()
        self.settings = SettingsTab()
        self.tab_map = {"dashboard": self.dashboard, "clients": self.companies, "orders": self.orders,
                        "invoices": self.invoices, "holidays": self.holidays, "reports": self.reports,
                        "settings": self.settings}
        self.tabs = QTabWidget()
        for key, title in (("dashboard", "Главная"), ("clients", "Компании"), ("orders", "Заказы"),
                           ("invoices", "Счета"), ("holidays", "Праздники"), ("reports", "Отчёты"),
                           ("settings", "Настройки")):
            self.tabs.addTab(self.tab_map[key], title)
        lay.addWidget(self.tabs, 1)

        for tab in self.tab_map.values():
            tab.changed.connect(self.refresh_all)
        self.dashboard.navigate.connect(self.goto)
        self.dashboard.autogen_requested.connect(lambda days: self.run_autogen(days, manual=True))
        self.settings.saved.connect(self.refresh_all)

        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.new_order)
        QShortcut(QKeySequence("F5"), self, activated=self.refresh_all)

        self.statusBar().addPermanentWidget(QLabel(f"База: {database.db_path()}"))
        self.timer = QTimer(self)                 # программа может работать сутками: подхватываем новый день
        self.timer.timeout.connect(self._on_timer)
        self.timer.start(30 * 60 * 1000)

        self.refresh_all()
        QTimer.singleShot(0, lambda: self.run_autogen())

    # ---- обновление
    def refresh_all(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        try:
            today = date.today()
            self._last_day = today
            with session_scope() as s:
                st = load_settings(s)
            self.setWindowTitle(f"{st.company_name} — CRM корпоративных поздравлений" + (" [демо]" if self.demo else ""))
            self.brand_title.setText(st.company_name)
            self.date_label.setText(f"Сегодня: {WEEKDAYS_FULL[today.weekday()]}, {today.day} {MONTHS_RU_GEN[today.month]} {today.year}")
            for tab in self.tab_map.values():
                tab.refresh()
        finally:
            self._refreshing = False

    def _on_timer(self) -> None:
        new_day = date.today() != self._last_day
        self.run_autogen()
        if new_day:
            self.refresh_all()

    # ---- автозаказы
    def run_autogen(self, days: int | None = None, manual: bool = False) -> None:
        """Создаёт заказы на ближайшие дни рождения. При запуске работает тихо, по кнопке — с отчётом."""
        with session_scope() as s:
            res = generate_birthday_orders(s, lead_days=days)
            created = [(o.recipient_name, o.client_id, o.event_date) for o in res.created]
            names = {c.id: c.company_name for c in s.query(CorporateClient)}
            existing, warnings = res.existing, list(res.warnings)
            lead = days if days is not None else load_settings(s).lead_days
        if created:
            self.statusBar().showMessage(f"Создано заказов на дни рождения: {len(created)}", 20000)
            self.refresh_all()
        if not manual:
            return
        if created:
            lines = [f"{who} ({names.get(cid, '—')}) — {fmt_date(ev)}" for who, cid, ev in created[:12]]
            more = f"\n… и ещё {len(created) - 12}" if len(created) > 12 else ""
            text = f"Создано заказов: {len(created)}\n\n" + "\n".join(lines) + more
        else:
            text = f"Новых заказов нет: на ближайшие {lead} дн. всё уже создано"
            if existing:
                text += f" (заказов на дни рождения: {existing})"
            text += ".\nАвтозаказы создаются для компаний со стадией «Клиент»."
        if warnings:
            text += "\n\nОбратите внимание:\n" + "\n".join(warnings[:8])
        info(self, "Автозаказы", text)

    # ---- навигация и действия
    def goto(self, target: str, ref=None) -> None:
        tab = self.tab_map.get(target)
        if tab is None:
            return
        self.tabs.setCurrentWidget(tab)
        tab.select_id(ref)

    def new_order(self) -> None:
        dlg = OrderDialog(parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self.refresh_all()
            self.goto("orders", dlg.saved_id)
