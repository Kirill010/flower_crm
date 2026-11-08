"""Общие виджеты. Цвета и шрифты — в theme.py (фирменный стиль «Диантус»)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from PyQt5.QtCore import QDate, Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QAbstractItemView, QAbstractSpinBox, QCheckBox, QComboBox, QDateEdit,
                             QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                             QSizePolicy, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
                             QWidget)

from services import fmt_date, fmt_money


# ------------------------------------------------------------------ мелочи
def qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def make_button(text: str, slot=None, primary: bool = False, tip: str | None = None) -> QPushButton:
    btn = QPushButton(text)
    if primary:
        btn.setObjectName("primary")
    if tip:
        btn.setToolTip(tip)
    if slot is not None:
        btn.clicked.connect(lambda _checked=False: slot())
    return btn


def heading(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("h2")
    return lab


def muted(text: str = "", name: str = "muted") -> QLabel:
    lab = QLabel(text)
    lab.setObjectName(name)
    lab.setWordWrap(True)
    lab.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)   # в форме занимает всю ширину
    return lab


def int_spin(minimum: int, maximum: int, value: int | None = None, suffix: str = "") -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    if suffix:
        spin.setSuffix(" " + suffix.strip())
    spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
    if value is not None:
        spin.setValue(value)
    return spin


def fill_combo(combo: QComboBox, items, current=None) -> None:
    """items: список строк или пар (подпись, значение)."""
    combo.blockSignals(True)
    combo.clear()
    for item in items:
        if isinstance(item, tuple):
            combo.addItem(item[0], item[1])
        else:
            combo.addItem(item, item)
    if current is not None:
        set_combo(combo, current)
    combo.blockSignals(False)


def set_combo(combo: QComboBox, value) -> None:
    idx = combo.findData(value)
    if idx < 0 and isinstance(value, str):
        idx = combo.findText(value)
    if idx >= 0:
        combo.setCurrentIndex(idx)
    elif combo.isEditable() and value:
        combo.setEditText(str(value))


def combo_value(combo: QComboBox):
    """Значение: data выбранного пункта, а для редактируемого списка — введённый текст."""
    if combo.isEditable():
        text = combo.currentText().strip()
        idx = combo.findText(text)
        return combo.itemData(idx) if idx >= 0 and combo.itemData(idx) is not None else text
    return combo.currentData()


def confirm(parent, title: str, text: str, yes: str = "Да", no: str = "Нет") -> bool:
    box = QMessageBox(QMessageBox.Question, title, text, QMessageBox.NoButton, parent)
    accept = box.addButton(yes, QMessageBox.AcceptRole)
    box.addButton(no, QMessageBox.RejectRole)
    box.exec_()
    return box.clickedButton() is accept


def info(parent, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


def warn(parent, title: str, text: str) -> None:
    QMessageBox.warning(parent, title, text)


# ------------------------------------------------------------------ поля ввода
class MoneySpin(QDoubleSpinBox):
    def __init__(self, suffix: str = "", maximum: float = 10_000_000, parent=None):
        super().__init__(parent)
        self.setDecimals(2)
        self.setRange(0, maximum)
        self.setGroupSeparatorShown(True)
        self.setSingleStep(5)
        self.setSuffix(f" {suffix}" if suffix else "")
        self.setButtonSymbols(QDoubleSpinBox.NoButtons)


class OptionalDate(QWidget):
    """Дата, которую можно не указывать: флажок + календарь."""
    changed = pyqtSignal()

    def __init__(self, default: date | None = None, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.check = QCheckBox()
        self.edit = QDateEdit()
        self.edit.setCalendarPopup(True)
        self.edit.setDisplayFormat("dd.MM.yyyy")
        self.edit.setMinimumWidth(135)
        self.edit.setDate(qdate(default or date.today()))
        self.edit.setEnabled(False)
        self.check.toggled.connect(self.edit.setEnabled)
        self.check.toggled.connect(lambda _: self.changed.emit())
        self.edit.dateChanged.connect(lambda _: self.changed.emit())
        lay.addWidget(self.check)
        lay.addWidget(self.edit, 1)

    def value(self) -> date | None:
        return self.edit.date().toPyDate() if self.check.isChecked() else None

    def set_value(self, d: date | None) -> None:
        if d:
            self.edit.setDate(qdate(d))
        self.check.setChecked(bool(d))


def date_edit(value: date | None = None) -> QDateEdit:
    edit = QDateEdit()
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("dd.MM.yyyy")
    edit.setMinimumWidth(135)
    edit.setDate(qdate(value or date.today()))
    return edit


class KpiCard(QFrame):
    """Карточка показателя: заголовок, крупное значение, пояснение."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("kpi")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("kpiTitle")
        self.value = QLabel("—")
        self.value.setObjectName("kpiValue")
        self.sub = QLabel("")
        self.sub.setObjectName("kpiSub")
        self.sub.setWordWrap(True)
        for w in (self.title, self.value, self.sub):
            lay.addWidget(w)

    def set(self, value: str, sub: str = "") -> None:
        self.value.setText(value)
        self.sub.setText(sub)


# ------------------------------------------------------------------ таблицы
@dataclass
class Col:
    title: str
    key: str
    kind: str = "text"        # text | date | birthday | money | int | float | pct | bool
    width: int | None = None


class SortItem(QTableWidgetItem):
    """Сортирует по ключу в UserRole+1 (даты — по дате, суммы — по числу, а не по тексту)."""

    def __lt__(self, other):
        a, b = self.data(Qt.UserRole + 1), other.data(Qt.UserRole + 1)
        if a is not None and b is not None:
            try:
                return a < b
            except TypeError:
                pass
        return super().__lt__(other)


class DataTable(QTableWidget):
    """Таблица по описанию столбцов; строки — словари. Ключи строки: id, _bg, _fg, _tip."""
    activated_id = pyqtSignal(int)     # двойной щелчок по строке

    def __init__(self, columns: list[Col], parent=None):
        super().__init__(0, len(columns), parent)
        self.columns = columns
        self.currency = ""
        self.setHorizontalHeaderLabels([c.title for c in columns])
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.ElideRight)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(28)
        header = self.horizontalHeader()
        header.setHighlightSections(False)
        header.setStretchLastSection(columns[-1].kind == "text")   # числа у правого края не растягиваем
        for i, col in enumerate(columns):
            self.setColumnWidth(i, col.width or 110)
        header.setSortIndicator(-1, Qt.AscendingOrder)   # порядок строк задаёт запрос, пока не нажат заголовок
        self.setSortingEnabled(True)
        self._fit_state = 0          # 0 — не подгоняли, 1 — по заголовкам (данных ещё нет), 2 — по данным
        self._adjusting = False      # True, пока ширину меняем мы, а не пользователь
        self._user_sized: set[int] = set()
        header.sectionResized.connect(self._on_section_resized)
        self.itemDoubleClicked.connect(self._on_double_click)

    # ---- ширина колонок по реальному шрифту
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._fit_state == 0:
            self._fit_columns()

    def _on_section_resized(self, index: int, _old: int, _new: int) -> None:
        if self._fit_state and not self._adjusting:      # колонку растянул пользователь — больше её не трогаем
            self._user_sized.add(index)

    def _column_cap(self, col: Col) -> int:
        return int(max(col.width or 100, 120) * 1.6)

    def _fit_columns(self) -> None:
        """Подгоняет колонки под заголовки и данные. Ширины из описания служат ориентиром для потолка:
        шрифт на разных компьютерах разный, и фиксированные ширины обрезают текст."""
        last = len(self.columns) - 1
        stretch_last = self.horizontalHeader().stretchLastSection()
        self._adjusting = True
        try:
            for i, col in enumerate(self.columns):
                if i == last and stretch_last:
                    continue
                self.resizeColumnToContents(i)
                self.setColumnWidth(i, min(self.columnWidth(i) + 6, self._column_cap(col)))
        finally:
            self._adjusting = False
        self._fit_state = 2 if self.rowCount() else 1

    def _grow_columns(self) -> None:
        """После обновления данных расширяет колонки, которым стало тесно. Не сужает и не трогает
        колонки, ширину которых меняли вручную."""
        header = self.horizontalHeader()
        last = len(self.columns) - 1
        stretch_last = header.stretchLastSection()
        self._adjusting = True
        try:
            for i, col in enumerate(self.columns):
                if i in self._user_sized or (i == last and stretch_last):
                    continue
                need = min(max(self.sizeHintForColumn(i), header.sectionSizeHint(i)) + 6, self._column_cap(col))
                if need > self.columnWidth(i):
                    self.setColumnWidth(i, need)
        finally:
            self._adjusting = False

    def _on_double_click(self, item) -> None:
        rid = self.item(item.row(), 0).data(Qt.UserRole)
        if rid is not None:
            self.activated_id.emit(int(rid))

    def _text(self, value, col: Col) -> str:
        if value is None or value == "":
            return ""
        if col.kind == "date":
            return fmt_date(value) if isinstance(value, date) else str(value)
        if col.kind == "birthday":                  # значение: (дата, известен ли год)
            d, year_known = value
            return d.strftime("%d.%m.%Y") if year_known else d.strftime("%d.%m")
        if col.kind == "money":
            return fmt_money(value, self.currency)
        if col.kind == "bool":
            return "Да" if value else "Нет"
        if col.kind == "pct":
            return f"{value:.0f}%"
        if col.kind == "int":
            return str(int(value))
        if col.kind == "float":
            return f"{value:g}"
        return str(value)

    @staticmethod
    def _sort_key(value, col: Col):
        if col.kind == "date":
            return value.toordinal() if isinstance(value, date) else 0
        if col.kind == "birthday":                  # по месяцу и дню, а не по году
            return value[0].month * 100 + value[0].day if value else 0
        if col.kind in ("money", "int", "float", "bool", "pct"):
            return float(value) if value not in (None, "") else float("-inf")
        return str(value or "").casefold()

    def set_rows(self, rows: list[dict], currency: str | None = None) -> None:
        if currency is not None:
            self.currency = currency
        selected = self.current_id()
        self.setSortingEnabled(False)          # иначе строки «прыгают» во время заполнения
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            bg = QColor(row["_bg"]) if row.get("_bg") else None
            fg = QColor(row["_fg"]) if row.get("_fg") else None
            for c, col in enumerate(self.columns):
                value = row.get(col.key)
                item = SortItem(self._text(value, col))
                item.setData(Qt.UserRole + 1, self._sort_key(value, col))
                if col.kind in ("money", "int", "float", "pct"):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if bg:
                    item.setBackground(bg)
                if fg:
                    item.setForeground(fg)
                if row.get("_tip"):
                    item.setToolTip(row["_tip"])
                if c == 0:
                    item.setData(Qt.UserRole, row.get("id"))
                self.setItem(r, c, item)
        self.setSortingEnabled(True)
        if rows and self.isVisible():
            if self._fit_state < 2:
                self._fit_columns()          # первые данные уже на экране — подгоняем
            else:
                self._grow_columns()         # данные обновились — расширяем, если стало тесно
        if selected is not None:
            self.select_id(selected)

    def current_id(self):
        sel = self.selectionModel()
        rows = sel.selectedRows() if sel else []
        if not rows:
            return None
        item = self.item(rows[0].row(), 0)
        value = item.data(Qt.UserRole) if item else None
        return int(value) if value is not None else None

    def select_id(self, rid) -> bool:
        for r in range(self.rowCount()):
            item = self.item(r, 0)
            if item is not None and item.data(Qt.UserRole) == rid:
                self.selectRow(r)
                self.scrollToItem(item)
                return True
        return False

    def row_count(self) -> int:
        return self.rowCount()


class PanelTable(QWidget):
    """Таблица с рядом кнопок. Кнопка: (подпись, функция(id или None), нужна ли выбранная строка)."""

    def __init__(self, columns: list[Col], buttons: list[tuple], parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        self.table = DataTable(columns)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        self._buttons: list[tuple[QPushButton, bool]] = []
        for text, fn, needs_selection in buttons:
            btn = make_button(text, lambda fn=fn: fn(self.table.current_id()))
            self._buttons.append((btn, needs_selection))
            row.addWidget(btn)
        row.addStretch(1)
        lay.addLayout(row)
        self._enabled = True
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        self._sync_buttons()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        has_row = self.table.current_id() is not None
        for btn, needs in self._buttons:
            btn.setEnabled(self._enabled and (has_row or not needs))
