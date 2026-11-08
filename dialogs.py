"""Диалоги редактирования. Каждый диалог сам открывает сессию БД и сохраняет изменения."""
from __future__ import annotations

import re
from datetime import date, timedelta

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                             QFormLayout, QGroupBox, QHBoxLayout, QLineEdit, QPlainTextEdit,
                             QVBoxLayout)
from sqlalchemy import or_

from database import session_scope
from models import (ACTIVITY_KINDS, DELIVERY_KINDS, GENDERS, HOLIDAY_AUDIENCES, OCCASIONS,
                    ORDER_STATUSES, RECIPIENT_CATEGORIES, SEGMENTS, SERVICES, STAGES, STATUS_CANCELLED,
                    TRIAL_STAGE, CorporateClient, CorporateEmployee, Holiday, Invoice, Order)
from services import (MONTHS_RU, BusinessError, calc_price, card_text_for, create_holiday_orders,
                      fmt_date, fmt_money, generate_monthly_invoices, holiday_date, load_settings,
                      log_activity, next_invoice_number, preview_holiday_orders, recipient_address,
                      shift_month, uninvoiced_orders)
from widgets import (MoneySpin, OptionalDate, combo_value, date_edit, fill_combo, info, int_spin,
                     make_button, muted, qdate, set_combo, warn)

TIME_SLOTS = [""] + [f"{h:02d}:{m:02d}" for h in range(8, 21) for m in (0, 30)]
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def normalize_time(text: str) -> str | None:
    """«9:30» → «09:30»; пусто → ''; ошибка → None."""
    text = (text or "").strip()
    if not text:
        return ""
    m = _TIME_RE.match(text)
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


class FormDialog(QDialog):
    """Основа диалога: форма сверху, «Сохранить/Отмена» снизу. Наследник переопределяет validate и save."""

    def __init__(self, title: str, width: int = 480, use_form: bool = True, save_text: str = "Сохранить",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        self.setModal(True)
        self.saved_id = None
        root = QVBoxLayout(self)
        self.body = QVBoxLayout()
        root.addLayout(self.body)
        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignRight)
        self.form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        if use_form:
            self.body.addLayout(self.form)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.save_button = self.buttons.button(QDialogButtonBox.Save)
        self.save_button.setText(save_text)
        self.save_button.setObjectName("primary")
        self.buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        self.buttons.accepted.connect(self._on_save)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

    def validate(self) -> str | None:
        return None

    def save(self) -> None:
        raise NotImplementedError

    def _on_save(self) -> None:
        error = self.validate()
        if error:
            warn(self, "Проверьте данные", error)
            return
        try:
            self.save()
        except BusinessError as exc:
            warn(self, "Нельзя сохранить", str(exc))
            return
        self.accept()


def _line(text: str = "") -> QLineEdit:
    return QLineEdit(text)


def _percent_spin(maximum: float = 100) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(0, maximum)
    spin.setDecimals(1)
    spin.setSuffix(" %")
    spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
    return spin


# ------------------------------------------------------------------ компания
class ClientDialog(FormDialog):
    def __init__(self, client_id: int | None = None, stage: str | None = None, parent=None):
        super().__init__("Компания" if client_id else "Новая компания", width=900, use_form=False, parent=parent)
        self.client_id = client_id
        with session_scope() as s:
            st = load_settings(s)
            managers = sorted({m for (m,) in s.query(CorporateClient.manager).distinct() if m})
            c = s.get(CorporateClient, client_id) if client_id else None
        cur = st.currency

        self.name = _line()
        self.stage = QComboBox()
        fill_combo(self.stage, STAGES, stage or "Лид")
        self.segment = QComboBox()
        self.segment.setEditable(True)
        fill_combo(self.segment, [""] + SEGMENTS)
        self.distance = QDoubleSpinBox()
        self.distance.setRange(0, 1000)
        self.distance.setDecimals(1)
        self.distance.setSuffix(" км")
        self.distance.setSpecialValueText("не указано")
        self.distance.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.contact = _line()
        self.contact_position = _line()
        self.phone = _line()
        self.email = _line()
        self.address = _line()
        self.manager = QComboBox()
        self.manager.setEditable(True)
        fill_combo(self.manager, [""] + managers)
        self.contract_number = _line()
        self.contract_start = OptionalDate()
        self.contract_end = OptionalDate()
        self.payment_terms = _line("Раз в месяц по счёту")
        self.fixed_price = MoneySpin(cur)
        self.fixed_price.setSpecialValueText(f"по умолчанию ({fmt_money(st.default_price, cur)})")
        self.discount = _percent_spin()
        self.notes = QPlainTextEdit()
        self.notes.setFixedHeight(64)
        self.archived = QCheckBox("В архиве: скрыть из списков, автозаказы не создаются")

        left = QGroupBox("Компания и контакты")
        lf = QFormLayout(left)
        for label, widget in (("Название *", self.name), ("Стадия", self.stage), ("Сегмент", self.segment),
                              ("Расстояние от магазина", self.distance), ("Контактное лицо", self.contact),
                              ("Должность контакта", self.contact_position), ("Телефон", self.phone),
                              ("Email", self.email), ("Адрес офиса", self.address)):
            lf.addRow(label, widget)
        right = QGroupBox("Договор и цены")
        rf = QFormLayout(right)
        for label, widget in (("Персональный менеджер", self.manager), ("№ договора", self.contract_number),
                              ("Договор с", self.contract_start), ("Договор до", self.contract_end),
                              ("Условия оплаты", self.payment_terms), ("Цена букета по договору", self.fixed_price),
                              ("Скидка по договору", self.discount)):
            rf.addRow(label, widget)
        cols = QHBoxLayout()
        cols.addWidget(left, 1)
        cols.addWidget(right, 1)
        self.body.addLayout(cols)
        self.body.addWidget(muted("Заметки"))
        self.body.addWidget(self.notes)
        self.body.addWidget(self.archived)
        self.body.addWidget(muted(
            "Автозаказы на дни рождения создаются только для компаний со стадией «Клиент» и действующим договором. "
            "Цену букета можно переопределить для получателя (его личный бюджет).", "hint"))

        if c is not None:
            self.name.setText(c.company_name or "")
            set_combo(self.stage, c.stage or "Лид")
            set_combo(self.segment, c.segment or "")
            self.distance.setValue(c.distance_km or 0)
            self.contact.setText(c.contact_person or "")
            self.contact_position.setText(c.contact_position or "")
            self.phone.setText(c.phone or "")
            self.email.setText(c.email or "")
            self.address.setText(c.address or "")
            set_combo(self.manager, c.manager or "")
            self.contract_number.setText(c.contract_number or "")
            self.contract_start.set_value(c.contract_start)
            self.contract_end.set_value(c.contract_end)
            self.payment_terms.setText(c.payment_terms or "")
            self.fixed_price.setValue(c.fixed_price or 0)
            self.discount.setValue(c.discount or 0)
            self.notes.setPlainText(c.notes or "")
            self.archived.setChecked(c.is_active is False)

    def validate(self) -> str | None:
        if not self.name.text().strip():
            return "Введите название компании."
        start, end = self.contract_start.value(), self.contract_end.value()
        if start and end and end < start:
            return "Дата окончания договора раньше даты начала."
        return None

    def save(self) -> None:
        with session_scope() as s:
            if self.client_id:
                c = s.get(CorporateClient, self.client_id)
            else:
                c = CorporateClient()
                s.add(c)
            c.company_name = self.name.text().strip()
            c.stage = self.stage.currentData()
            c.segment = combo_value(self.segment) or None
            c.distance_km = self.distance.value() or None
            c.contact_person = self.contact.text().strip() or None
            c.contact_position = self.contact_position.text().strip() or None
            c.phone = self.phone.text().strip() or None
            c.email = self.email.text().strip() or None
            c.address = self.address.text().strip() or None
            c.manager = combo_value(self.manager) or None
            c.contract_number = self.contract_number.text().strip() or None
            c.contract_start = self.contract_start.value()
            c.contract_end = self.contract_end.value()
            c.payment_terms = self.payment_terms.text().strip() or None
            c.fixed_price = self.fixed_price.value()
            c.discount = self.discount.value()
            c.notes = self.notes.toPlainText().strip() or None
            c.is_active = not self.archived.isChecked()
            s.flush()
            self.saved_id = c.id


# ------------------------------------------------------------------ получатель
class RecipientDialog(FormDialog):
    def __init__(self, client_id: int | None = None, employee_id: int | None = None, parent=None):
        super().__init__("Получатель поздравлений" if employee_id else "Новый получатель", width=560, parent=parent)
        self.employee_id = employee_id
        with session_scope() as s:
            st = load_settings(s)
            clients = [(c.company_name, c.id) for c in s.query(CorporateClient)
                       .filter(or_(CorporateClient.is_active.is_(True), CorporateClient.id == client_id))
                       .order_by(CorporateClient.company_name)]
            e = s.get(CorporateEmployee, employee_id) if employee_id else None
            if e is not None:
                client_id = e.client_id
        cur = st.currency

        self.client = QComboBox()
        fill_combo(self.client, clients, client_id)
        self.full_name = _line()
        self.position = _line()
        self.category = QComboBox()
        fill_combo(self.category, RECIPIENT_CATEGORIES)
        self.gender = QComboBox()
        fill_combo(self.gender, [(label, value) for value, label in GENDERS])
        self.birthday = OptionalDate(date(1990, 1, 1))
        self.year_unknown = QCheckBox("Год рождения неизвестен (нужны только день и месяц)")
        self.phone = _line()
        self.delivery_kind = QComboBox()
        fill_combo(self.delivery_kind, DELIVERY_KINDS)
        self.home_address = _line()
        self.bouquet = _line()
        self.budget = MoneySpin(cur)
        self.budget.setSpecialValueText("по договору компании")
        self.with_card = QCheckBox("Добавлять открытку")
        self.with_card.setChecked(True)
        self.notes = _line()
        self.active = QCheckBox("Активен (получает поздравления)")
        self.active.setChecked(True)

        for label, widget in (("Компания *", self.client), ("ФИО *", self.full_name), ("Должность", self.position),
                              ("Категория", self.category), ("Пол", self.gender),
                              ("День рождения", self.birthday), ("", self.year_unknown), ("Телефон", self.phone),
                              ("Куда доставлять", self.delivery_kind), ("Домашний адрес", self.home_address),
                              ("Любимый букет", self.bouquet), ("Личный бюджет", self.budget),
                              ("", self.with_card), ("Пожелания", self.notes), ("", self.active)):
            self.form.addRow(label, widget)
        self.form.addRow("", muted("Пол нужен для массовых поздравлений: 8 Марта — женщинам, 23 Февраля — мужчинам.",
                                   "hint"))
        self.delivery_kind.currentIndexChanged.connect(self._sync_address)

        if e is not None:
            self.full_name.setText(e.full_name or "")
            self.position.setText(e.position or "")
            set_combo(self.category, e.category or RECIPIENT_CATEGORIES[0])
            set_combo(self.gender, e.gender or "")
            self.birthday.set_value(e.birthday)
            self.year_unknown.setChecked(e.birth_year_known is False)
            self.phone.setText(e.phone or "")
            set_combo(self.delivery_kind, e.delivery_kind or "Офис")
            self.home_address.setText(e.home_address or "")
            self.bouquet.setText(e.preferred_bouquet or "")
            self.budget.setValue(e.preferred_budget or 0)
            self.with_card.setChecked(e.with_card is not False)
            self.notes.setText(e.notes or "")
            self.active.setChecked(e.is_active is not False)
        self._sync_address()

    def _sync_address(self) -> None:
        self.home_address.setEnabled(self.delivery_kind.currentData() == "Домой")

    def validate(self) -> str | None:
        if self.client.currentData() is None:
            return "Выберите компанию. Если её нет в списке, сначала добавьте компанию."
        if not self.full_name.text().strip():
            return "Введите ФИО."
        if self.delivery_kind.currentData() == "Домой" and not self.home_address.text().strip():
            return "Для доставки домой укажите домашний адрес."
        return None

    def save(self) -> None:
        birthday = self.birthday.value()
        year_known = True
        if birthday and self.year_unknown.isChecked():
            birthday, year_known = date(2000, birthday.month, birthday.day), False   # 2000 — високосный
        with session_scope() as s:
            if self.employee_id:
                e = s.get(CorporateEmployee, self.employee_id)
            else:
                e = CorporateEmployee()
                s.add(e)
            e.client_id = self.client.currentData()
            e.full_name = self.full_name.text().strip()
            e.position = self.position.text().strip() or None
            e.category = self.category.currentData()
            e.gender = self.gender.currentData() or None
            e.birthday = birthday
            e.birth_year_known = year_known
            e.phone = self.phone.text().strip() or None
            e.delivery_kind = self.delivery_kind.currentData()
            e.home_address = self.home_address.text().strip() or None
            e.preferred_bouquet = self.bouquet.text().strip() or None
            e.preferred_budget = self.budget.value() or None
            e.with_card = self.with_card.isChecked()
            e.notes = self.notes.text().strip() or None
            e.is_active = self.active.isChecked()
            s.flush()
            self.saved_id = e.id


# ------------------------------------------------------------------ заказ
class OrderDialog(FormDialog):
    """Заказ с живым расчётом цены. Пока вы не правили сумму вручную, она пересчитывается сама."""

    def __init__(self, order_id: int | None = None, client_id: int | None = None,
                 employee_id: int | None = None, occasion: str | None = None,
                 delivery_date: date | None = None, parent=None):
        super().__init__("Заказ" if order_id else "Новый заказ", width=680, parent=parent)
        self.order_id = order_id
        self._ready = False
        self._programmatic = False
        self._amount_touched = bool(order_id)
        self._auto: dict[str, str] = {}
        self._invoice_number = None

        with session_scope() as s:
            self.st = load_settings(s)
            clients = [(c.company_name + ("" if c.is_active else " (архив)"), c.id)
                       for c in s.query(CorporateClient).order_by(CorporateClient.company_name)]
            order = s.get(Order, order_id) if order_id else None
            if order is not None:
                client_id, employee_id = order.client_id, order.employee_id
                if order.invoice_id:
                    inv = s.get(Invoice, order.invoice_id)
                    self._invoice_number = inv.number if inv else None
        st, cur = self.st, self.st.currency
        self._order = order

        self.client = QComboBox()
        fill_combo(self.client, clients, client_id)
        self.recipient = QComboBox()
        self.service = QComboBox()
        fill_combo(self.service, SERVICES)
        self.occasion = QComboBox()
        self.occasion.setEditable(True)
        fill_combo(self.occasion, OCCASIONS)
        self.delivery_date = date_edit(delivery_date or date.today() + timedelta(days=1))
        self.delivery_time = QComboBox()
        self.delivery_time.setEditable(True)
        fill_combo(self.delivery_time, TIME_SLOTS)
        self.address = _line()
        self.phone = _line()
        self.bouquet = _line()
        self.bouquet.setPlaceholderText("Корпоративный букет")
        self.with_card = QCheckBox()
        self.with_card.setToolTip("Добавить открытку")
        self.card_text = _line()
        self.card_text.setPlaceholderText("Текст открытки")
        self.gift = _line()
        self.gift.setPlaceholderText("например: сладости, шампанское")
        self.trial = QCheckBox(f"Пробное поздравление (скидка {st.trial_discount:g}%)")
        self.extra = MoneySpin(cur)
        self.price_label = muted("", "hint")
        self.amount = MoneySpin(cur)
        self.recalc_button = make_button("Пересчитать", self._reset_amount)
        self.status = QComboBox()
        fill_combo(self.status, ORDER_STATUSES)
        self.comment = _line()

        amount_row = QHBoxLayout()
        amount_row.addWidget(self.amount, 1)
        amount_row.addWidget(self.recalc_button)
        card_row = QHBoxLayout()
        card_row.addWidget(self.with_card)
        card_row.addWidget(self.card_text, 1)
        for label, widget in (("Компания *", self.client), ("Получатель", self.recipient), ("Услуга", self.service),
                              ("Повод", self.occasion), ("Дата доставки", self.delivery_date),
                              ("Время доставки", self.delivery_time), ("Адрес доставки", self.address),
                              ("Телефон получателя", self.phone), ("Букет", self.bouquet)):
            self.form.addRow(label, widget)
        self.form.addRow("Открытка", card_row)
        for label, widget in (("Подарок", self.gift), ("", self.trial), ("Доп. услуги", self.extra)):
            self.form.addRow(label, widget)
        self.form.addRow("", self.price_label)
        self.form.addRow("Сумма заказа", amount_row)
        self.form.addRow("Статус", self.status)
        self.form.addRow("Комментарий", self.comment)
        if self._invoice_number:
            self.form.addRow("", muted(f"Заказ включён в счёт {self._invoice_number}: сумму менять и отменять заказ нельзя.",
                                       "hint"))

        # начальные значения
        self._load_recipients(employee_id)
        if order is not None:
            self._fill_from_order(order)
        else:
            set_combo(self.occasion, occasion or "День рождения")
            set_combo(self.delivery_time, st.default_delivery_time)
            self._autofill_from_recipient(initial=True)
            self._recalc()

        self.client.currentIndexChanged.connect(self._on_client)
        self.recipient.currentIndexChanged.connect(lambda _: self._autofill_from_recipient())
        self.occasion.currentTextChanged.connect(lambda _: self._autofill_from_recipient(card_only=True))
        self.service.currentIndexChanged.connect(lambda _: self._recalc())
        self.trial.toggled.connect(lambda _: self._recalc())
        self.with_card.toggled.connect(self._on_card_toggled)
        self.extra.valueChanged.connect(lambda _: self._recalc())
        self.amount.valueChanged.connect(self._on_amount_edited)
        self._ready = True

    # ---- заполнение
    def _load_recipients(self, select_id: int | None) -> None:
        self.recipient.blockSignals(True)
        self.recipient.clear()
        self.recipient.addItem("— без получателя (заказ на компанию) —", None)
        cid = self.client.currentData()
        if cid is not None:
            with session_scope() as s:
                rows = s.query(CorporateEmployee).filter(
                    CorporateEmployee.client_id == cid,
                    or_(CorporateEmployee.is_active.is_(True), CorporateEmployee.id == select_id)
                ).order_by(CorporateEmployee.full_name).all()
                for e in rows:
                    self.recipient.addItem(e.full_name, e.id)
        set_combo(self.recipient, select_id)
        self.recipient.blockSignals(False)

    def _fill_from_order(self, o: Order) -> None:
        set_combo(self.service, o.service or "Букет")
        set_combo(self.occasion, o.occasion or "")
        if o.delivery_date:
            self.delivery_date.setDate(qdate(o.delivery_date))
        set_combo(self.delivery_time, o.delivery_time or "")
        self.address.setText(o.address or "")
        self.phone.setText(o.recipient_phone or "")
        self.bouquet.setText(o.bouquet or "")
        self.with_card.setChecked(bool(o.with_card))
        self.card_text.setText(o.card_text or "")
        self.card_text.setCursorPosition(0)
        self.card_text.setEnabled(bool(o.with_card))
        self.gift.setText(o.gift or "")
        self.trial.setChecked(bool(o.is_trial))
        self._set_amount(o.amount or 0)
        set_combo(self.status, o.status or "Новый")
        self.comment.setText(o.comment or "")
        if o.employee_id is None and o.recipient_name:
            self.recipient.setItemText(0, f"— {o.recipient_name} (карточка удалена) —")
        self.price_label.setText("Сумма сохранена в заказе. Нажмите «Пересчитать», чтобы взять цену из условий договора.")
        if o.invoice_id:
            self.amount.setEnabled(False)
            self.recalc_button.setEnabled(False)

    def _set_amount(self, value: float) -> None:
        self._programmatic = True
        self.amount.setValue(value)
        self._programmatic = False

    def _autofill(self, key: str, widget: QLineEdit, value: str) -> None:
        """Подставляет значение, только если поле пустое или там то, что подставили мы."""
        current = widget.text()
        if not current or current == self._auto.get(key):
            widget.setText(value)
            widget.setCursorPosition(0)          # показываем начало текста, а не хвост
            self._auto[key] = value

    def _autofill_from_recipient(self, initial: bool = False, card_only: bool = False) -> None:
        if not self._ready and not initial:
            return
        cid, rid = self.client.currentData(), self.recipient.currentData()
        if cid is None:
            return
        with session_scope() as s:
            client = s.get(CorporateClient, cid)
            emp = s.get(CorporateEmployee, rid) if rid else None
            address = recipient_address(client, emp, []) if emp else (client.address or "")
            phone = (emp.phone if emp else client.phone) or ""
            bouquet = (emp.preferred_bouquet if emp else "") or ""
            with_card = bool(emp.with_card) if emp else False
            card = card_text_for(self.st, emp.full_name, client.company_name, combo_value(self.occasion)) if emp else ""
            trial_default = client.stage == TRIAL_STAGE
        if not card_only:
            self._autofill("address", self.address, address)
            self._autofill("phone", self.phone, phone)
            self._autofill("bouquet", self.bouquet, bouquet)
            if initial or not self.order_id:
                self.with_card.setChecked(with_card)
                if initial:
                    self.trial.setChecked(trial_default)
        if self.with_card.isChecked():
            self._autofill("card", self.card_text, card)
        self._recalc()

    def _on_client(self) -> None:
        self._load_recipients(None)
        self._autofill_from_recipient()

    def _on_card_toggled(self, checked: bool) -> None:
        self.card_text.setEnabled(checked)
        if checked:
            self._autofill_from_recipient(card_only=True)
        self._recalc()

    # ---- цена
    def _recalc(self) -> None:
        if self.client.currentData() is None:
            return
        with session_scope() as s:
            client = s.get(CorporateClient, self.client.currentData())
            rid = self.recipient.currentData()
            emp = s.get(CorporateEmployee, rid) if rid else None
            price = calc_price(client, emp, self.st, service=self.service.currentText(),
                               trial=self.trial.isChecked(), with_card=self.with_card.isChecked(),
                               extra=self.extra.value())
        self.price_label.setText("Расчёт: " + price.explain(self.st.currency))
        if not self._amount_touched:
            self._set_amount(price.total)

    def _reset_amount(self) -> None:
        self._amount_touched = False
        self._recalc()

    def _on_amount_edited(self, _value: float) -> None:
        if self._ready and not self._programmatic:
            self._amount_touched = True

    # ---- сохранение
    def validate(self) -> str | None:
        if self.client.currentData() is None:
            return "Выберите компанию. Если её нет в списке, сначала добавьте компанию."
        if normalize_time(self.delivery_time.currentText()) is None:
            return "Время доставки укажите как ЧЧ:ММ, например 10:30, или оставьте пустым."
        if self.with_card.isChecked() and not self.card_text.text().strip():
            return "Включена открытка. Напишите её текст или снимите галочку."
        return None

    def save(self) -> None:
        new_amount = self.amount.value()
        status = self.status.currentData()
        with session_scope() as s:
            rid = self.recipient.currentData()
            emp = s.get(CorporateEmployee, rid) if rid else None
            if self.order_id:
                o = s.get(Order, self.order_id)
                if o.invoice_id and (abs((o.amount or 0) - new_amount) > 0.005 or status == STATUS_CANCELLED):
                    raise BusinessError("Заказ уже включён в счёт: менять сумму или отменять его нельзя.\n"
                                        "Сначала удалите счёт во вкладке «Счета».")
            else:
                # в сессию добавляем после заполнения: иначе автосброс запишет пустой заказ
                o = Order(order_date=date.today(), auto_created=False)
            o.client_id = self.client.currentData()
            o.employee_id = rid
            if emp is not None:
                o.recipient_name = emp.full_name
            elif not self.order_id:
                o.recipient_name = None
            o.recipient_phone = self.phone.text().strip() or None
            o.delivery_date = self.delivery_date.date().toPyDate()
            if o.event_date is None:
                o.event_date = o.delivery_date
            o.delivery_time = normalize_time(self.delivery_time.currentText()) or None
            o.occasion = combo_value(self.occasion) or None
            o.service = self.service.currentText()
            o.bouquet = self.bouquet.text().strip() or ("Корпоративный букет" if o.service == "Букет" else o.service)
            o.address = self.address.text().strip() or None
            o.with_card = self.with_card.isChecked()
            o.card_text = self.card_text.text().strip() if o.with_card else None
            o.gift = self.gift.text().strip() or None
            o.is_trial = self.trial.isChecked()
            o.amount = new_amount
            o.status = status
            o.comment = self.comment.text().strip() or None
            if not self.order_id:
                s.add(o)
            s.flush()
            self.saved_id = o.id


# ------------------------------------------------------------------ счёт
class InvoiceDialog(FormDialog):
    def __init__(self, invoice_id: int | None = None, client_id: int | None = None, parent=None):
        super().__init__("Счёт" if invoice_id else "Новый счёт", width=520, parent=parent)
        self.invoice_id = invoice_id
        with session_scope() as s:
            st = load_settings(s)
            clients = [(c.company_name, c.id) for c in s.query(CorporateClient).order_by(CorporateClient.company_name)]
            inv = s.get(Invoice, invoice_id) if invoice_id else None
            if inv is not None:
                client_id = inv.client_id
        self.st = st
        self.client = QComboBox()
        fill_combo(self.client, clients, client_id)
        self.number = _line()
        self.number.setPlaceholderText("присвоится автоматически")
        self.issue_date = date_edit()
        self.due_date = date_edit(date.today() + timedelta(days=st.invoice_due_days))
        self.period_start = OptionalDate()
        self.period_end = OptionalDate()
        self.amount = MoneySpin(st.currency)
        self.description = _line()
        self.paid = QCheckBox("Оплачен")
        self.paid_date = OptionalDate()
        for label, widget in (("Компания *", self.client), ("Номер", self.number), ("Дата счёта", self.issue_date),
                              ("Оплатить до", self.due_date), ("Период с", self.period_start),
                              ("Период по", self.period_end), ("Сумма *", self.amount),
                              ("Описание", self.description), ("", self.paid), ("Дата оплаты", self.paid_date)):
            self.form.addRow(label, widget)
        self.paid.toggled.connect(self._on_paid)
        if inv is not None:
            self.number.setText(inv.number or "")
            if inv.issue_date:
                self.issue_date.setDate(qdate(inv.issue_date))
            if inv.due_date:
                self.due_date.setDate(qdate(inv.due_date))
            self.period_start.set_value(inv.period_start)
            self.period_end.set_value(inv.period_end)
            self.amount.setValue(inv.amount or 0)
            self.description.setText(inv.description or "")
            self.paid.setChecked(bool(inv.paid))
            self.paid_date.set_value(inv.paid_date)

    def _on_paid(self, checked: bool) -> None:
        if checked and self.paid_date.value() is None:
            self.paid_date.set_value(date.today())
        if not checked:
            self.paid_date.set_value(None)

    def validate(self) -> str | None:
        if self.client.currentData() is None:
            return "Выберите компанию."
        if self.amount.value() <= 0:
            return "Укажите сумму счёта."
        return None

    def save(self) -> None:
        with session_scope() as s:
            inv = s.get(Invoice, self.invoice_id) if self.invoice_id else Invoice()
            inv.client_id = self.client.currentData()
            issue = self.issue_date.date().toPyDate()
            inv.issue_date = issue
            number = self.number.text().strip()
            if not number:
                number = inv.number or next_invoice_number(s, issue.year, issue.month)
            elif s.query(Invoice.id).filter(Invoice.number == number, Invoice.id != (inv.id or 0)).first():
                raise BusinessError(f"Счёт с номером {number} уже есть.")
            inv.number = number
            inv.due_date = self.due_date.date().toPyDate()
            inv.period_start = self.period_start.value()
            inv.period_end = self.period_end.value()
            inv.amount = self.amount.value()
            inv.description = self.description.text().strip() or None
            inv.paid = self.paid.isChecked()
            inv.paid_date = self.paid_date.value() if inv.paid else None
            if not self.invoice_id:
                s.add(inv)
            s.flush()
            self.saved_id = inv.id


class MonthInvoicesDialog(FormDialog):
    """Формирует счета за выбранный месяц по доставленным заказам."""

    def __init__(self, parent=None):
        super().__init__("Счета за месяц", width=460, save_text="Сформировать счета", parent=parent)
        today = date.today()
        year, month = shift_month(today.year, today.month, -1)
        self.month = QComboBox()
        fill_combo(self.month, [(MONTHS_RU[i].capitalize(), i) for i in range(1, 13)], month)
        self.year = int_spin(2020, 2100, year)
        self.preview = muted("")
        self.form.addRow("Месяц", self.month)
        self.form.addRow("Год", self.year)
        self.form.addRow("", self.preview)
        self.form.addRow("", muted("В счёт попадают доставленные заказы, которых ещё нет ни в одном счёте. "
                                   "Каждой компании выставляется один счёт.", "hint"))
        self.month.currentIndexChanged.connect(self._update)
        self.year.valueChanged.connect(self._update)
        self.result_text = ""
        self._update()

    def _update(self) -> None:
        with session_scope() as s:
            n, total = uninvoiced_orders(s, self.year.value(), self.month.currentData())
            cur = load_settings(s).currency
        self.preview.setText(f"К выставлению: {n} заказов на {fmt_money(total, cur)}" if n
                             else "Нет доставленных заказов без счёта за этот месяц.")
        self.save_button.setEnabled(n > 0)

    def save(self) -> None:
        with session_scope() as s:
            cur = load_settings(s).currency
            invoices = generate_monthly_invoices(s, self.year.value(), self.month.currentData())
            names = {c.id: c.company_name for c in s.query(CorporateClient)}
            lines = [f"{names.get(i.client_id, '—')} — {i.number}, {fmt_money(i.amount, cur)}" for i in invoices]
        self.result_text = f"Выставлено счетов: {len(lines)}\n\n" + "\n".join(lines)
        info(self, "Счета сформированы", self.result_text)


# ------------------------------------------------------------------ контакт (воронка)
class ActivityDialog(FormDialog):
    def __init__(self, client_id: int, parent=None):
        super().__init__("Контакт с компанией", width=520, parent=parent)
        self.client_id = client_id
        self.kind = QComboBox()
        fill_combo(self.kind, ACTIVITY_KINDS)
        self.date = date_edit()
        self.note = QPlainTextEdit()
        self.note.setFixedHeight(80)
        self.next_date = OptionalDate(date.today() + timedelta(days=3))
        for label, widget in (("Что было", self.kind), ("Дата", self.date), ("Итог / заметка", self.note),
                              ("Следующий шаг до", self.next_date)):
            self.form.addRow(label, widget)
        self.form.addRow("", muted("«КП отправлено», «Визит / встреча», «Пробное поздравление» и «Договор подписан» "
                                   "сами переводят компанию на нужную стадию воронки. При подписании договора "
                                   "ставятся даты годового договора.", "hint"))

    def save(self) -> None:
        with session_scope() as s:
            act = log_activity(s, self.client_id, self.kind.currentData(), self.note.toPlainText().strip(),
                               self.date.date().toPyDate(), self.next_date.value())
            s.flush()
            self.saved_id = act.id


# ------------------------------------------------------------------ праздники
class HolidayDialog(FormDialog):
    def __init__(self, holiday_id: int | None = None, parent=None):
        super().__init__("Праздник" if holiday_id else "Новый праздник", width=480, parent=parent)
        self.holiday_id = holiday_id
        with session_scope() as s:
            h = s.get(Holiday, holiday_id) if holiday_id else None
        self.name = _line()
        self.month = QComboBox()
        fill_combo(self.month, [(MONTHS_RU[i].capitalize(), i) for i in range(1, 13)], date.today().month)
        self.day = int_spin(1, 31, 1)
        self.lead = int_spin(0, 60, 7, "дн.")
        self.audience = QComboBox()
        fill_combo(self.audience, [(label, value) for value, label in HOLIDAY_AUDIENCES])
        self.segment = QComboBox()
        self.segment.setEditable(True)
        fill_combo(self.segment, [""] + SEGMENTS)
        self.active = QCheckBox("Использовать")
        self.active.setChecked(True)
        for label, widget in (("Название *", self.name), ("Месяц", self.month), ("День доставки", self.day),
                              ("Напомнить за", self.lead), ("Кого поздравляем", self.audience),
                              ("Только для сегмента", self.segment), ("", self.active)):
            self.form.addRow(label, widget)
        self.form.addRow("", muted("Дата — это день ДОСТАВКИ. Для профессионального праздника укажите сегмент, "
                                   "тогда заказы создаются только компаниям этого сегмента.", "hint"))
        if h is not None:
            self.name.setText(h.name or "")
            set_combo(self.month, h.month)
            self.day.setValue(h.day or 1)
            self.lead.setValue(h.lead_days if h.lead_days is not None else 7)
            set_combo(self.audience, h.audience or "all")
            set_combo(self.segment, h.segment or "")
            self.active.setChecked(h.is_active is not False)

    def validate(self) -> str | None:
        if not self.name.text().strip():
            return "Введите название праздника."
        try:
            date(2000, self.month.currentData(), self.day.value())
        except ValueError:
            return "Такой даты нет в календаре."
        return None

    def save(self) -> None:
        with session_scope() as s:
            if self.holiday_id:
                h = s.get(Holiday, self.holiday_id)
            else:
                h = Holiday()
                s.add(h)
            h.name = self.name.text().strip()
            h.month = self.month.currentData()
            h.day = self.day.value()
            h.lead_days = self.lead.value()
            h.audience = self.audience.currentData()
            h.segment = combo_value(self.segment) or None
            h.is_active = self.active.isChecked()
            s.flush()
            self.saved_id = h.id


class HolidayOrdersDialog(FormDialog):
    """Массовые заказы на праздник: сначала показывает, сколько заказов будет создано."""

    def __init__(self, holiday_id: int, parent=None):
        super().__init__("Заказы на праздник", width=540, save_text="Создать заказы", parent=parent)
        self.holiday_id = holiday_id
        today = date.today()
        with session_scope() as s:
            h = s.get(Holiday, holiday_id)
            self.holiday_name = h.name
            st = load_settings(s)
            first = holiday_date(h, today.year)
            year = today.year if first >= today else today.year + 1
        self.currency = st.currency
        self.year = int_spin(today.year - 1, today.year + 3, year)
        self.bouquet = _line("Праздничный букет")
        self.amount = MoneySpin(st.currency)
        self.amount.setSpecialValueText("по цене договора / бюджету получателя")
        self.preview = muted("")
        self.result = None
        self.form.addRow("Праздник", muted(h.name if h else ""))
        self.form.addRow("Год", self.year)
        self.form.addRow("Букет", self.bouquet)
        self.form.addRow("Сумма одного заказа", self.amount)
        self.form.addRow("", self.preview)
        self.year.valueChanged.connect(self._update)
        self._update()

    def _update(self) -> None:
        with session_scope() as s:
            h = s.get(Holiday, self.holiday_id)
            prev = preview_holiday_orders(s, h, self.year.value())
            lines = [f"Дата доставки: {fmt_date(prev.date)}",
                     f"Компаний по договору: {len(prev.clients)}",
                     f"Будет создано заказов: {len(prev.recipients)}"]
            if prev.existing:
                lines.append(f"Уже созданы ранее: {prev.existing}")
            if prev.skipped_gender:
                lines.append(f"Пропущено из-за неуказанного пола: {prev.skipped_gender} "
                             "(укажите пол в карточке получателя)")
            count = len(prev.recipients)
        self.preview.setText("\n".join(lines))
        self.save_button.setEnabled(count > 0)

    def save(self) -> None:
        with session_scope() as s:
            h = s.get(Holiday, self.holiday_id)
            res = create_holiday_orders(s, h, self.year.value(), bouquet=self.bouquet.text().strip() or None,
                                        amount=self.amount.value() or None)
            total = sum(o.amount or 0 for o in res.created)
            text = f"Создано заказов: {len(res.created)} на {fmt_money(total, self.currency)}."
            if res.warnings:
                text += "\n\nОбратите внимание:\n" + "\n".join(res.warnings[:8])
            self.result = text
        info(self, self.holiday_name, text)


class DateDialog(FormDialog):
    def __init__(self, title: str, label: str, default: date | None = None, parent=None):
        super().__init__(title, width=320, save_text="Продолжить", parent=parent)
        self.edit = date_edit(default)
        self.form.addRow(label, self.edit)

    def value(self) -> date:
        return self.edit.date().toPyDate()

    def save(self) -> None:
        pass
