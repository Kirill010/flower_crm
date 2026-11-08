"""Фирменный стиль «Диантус»: палитра, шрифты, эмблема и таблица стилей Qt.

Цвета, шрифты и скругления взяты из style.css сайта (1-site/app/static): кремовый фон, оливково-зелёный
основной цвет, медный акцент, Montserrat для текста и Playfair Display для заголовков.
Файлы шрифтов и эмблема лежат в assets/ (собираются скриптом tools/build_brand_assets.py).
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from string import Template

log = logging.getLogger("crm.theme")

ASSETS = Path(__file__).resolve().parent / "assets"
FONT_DIR = ASSETS / "fonts"

# ---------------------------------------------------------------- палитра (переменные :root сайта)
BG = "#f5efe4"            # фон окна
BG_SOFT = "#faf6ef"       # чередующиеся строки
BG_CARD = "#fffdf8"       # карточки, поля, таблицы
BG_WARM = "#ede4d3"       # заголовки таблиц, неактивные вкладки

PRIMARY = "#4a6741"       # оливково-зелёный
PRIMARY_DARK = "#35492f"
PRIMARY_LIGHT = "#8ba38c"
PRIMARY_PALE = "#d8e2d0"  # выделение строки
PRIMARY_MIST = "#ecf1e8"

ACCENT = "#c97b4a"        # медный
ACCENT_LIGHT = "#e0a878"
ACCENT_PALE = "#f4e2d2"
ACCENT_DARK = "#a55f35"

ROSE = "#c88a92"
ROSE_LIGHT = "#e5b8bd"
ROSE_PALE = "#f4e0e3"
ROSE_DARK = "#a95f68"

BRONZE = "#8c6d52"
BRONZE_LIGHT = "#b8997a"
BRONZE_PALE = "#e8dcca"

TEXT = "#2b2b2b"
TEXT_MUTED = "#5f5a50"    # вариант сайта с повышенным контрастом
TEXT_SOFT = "#6b665b"

BORDER = "#e5dcc9"
BORDER_SOFT = "#efe7d5"

# ---------------------------------------------------------------- состояния
DANGER = "#9b4a56"        # темнее розового сайта: читается на кремовом фоне
WARNING = ACCENT_DARK
INFO = PRIMARY
MUTED = "#8a857a"

COLORS = {"danger": DANGER, "warning": WARNING, "info": INFO, "muted": MUTED}
ROW_BG = {
    "no_order": ACCENT_PALE,     # событие без заказа
    "holiday": PRIMARY_MIST,     # праздник в календаре
    "overdue": "#f2d3d7",        # просрочено
    "today": "#f7efd6",          # сегодня / скоро истекает
}

FONT_TEXT = "Montserrat"
FONT_DISPLAY = "Dianthus Display"      # на основе Playfair Display (см. assets/fonts/README.txt)
FONT_FALLBACK_TEXT = "Segoe UI"
FONT_FALLBACK_DISPLAY = "Georgia"
TEXT_PT = 9.5
TABLE_PT = 9

BRAND_NAME = "Диантус"
BRAND_TAGLINE = "корпоративные поздравления"


# ---------------------------------------------------------------- шрифты, иконка, эмблема
def load_fonts() -> bool:
    """Подключает встроенные шрифты. Возвращает True, если Montserrat найден."""
    from PyQt5.QtGui import QFontDatabase
    ok = False
    for path in sorted(FONT_DIR.glob("*.ttf")):
        if QFontDatabase.addApplicationFont(str(path)) < 0:
            log.warning("Не удалось загрузить шрифт %s", path.name)
        elif path.name.startswith("Montserrat"):
            ok = True
    return ok


def app_icon():
    from PyQt5.QtGui import QIcon
    return QIcon(str(ASSETS / "dianthus.ico"))


def emblem_pixmap(height: int):
    """Эмблема «Д» высотой height логических пикселей. Рисуется в физических: чёткая при масштабе Windows 125–200%."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QGuiApplication, QPixmap
    screen = QGuiApplication.primaryScreen()
    ratio = screen.devicePixelRatio() if screen is not None else 1.0
    physical = int(round(height * ratio))
    pix = QPixmap(str(ASSETS / ("emblem-192.png" if physical > 96 else "emblem-96.png")))
    if pix.isNull():
        return pix
    pix = pix.scaledToHeight(physical, Qt.SmoothTransformation)
    pix.setDevicePixelRatio(ratio)
    return pix


def _icon_png(name: str, draw) -> str | None:
    """Рисуем стрелку списка и «птичку» сами: не зависим от темы Windows."""
    try:
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QPainter, QPixmap
        folder = Path(tempfile.gettempdir()) / "dianthus_crm"
        folder.mkdir(exist_ok=True)
        path = folder / name
        pix = QPixmap(16, 16)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        draw(painter)
        painter.end()
        return path.as_posix() if pix.save(str(path)) else None
    except Exception:
        log.exception("Не удалось создать значок %s", name)
        return None


def _draw_arrow(p) -> None:
    from PyQt5.QtCore import QPoint, Qt
    from PyQt5.QtGui import QColor, QPolygon
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(PRIMARY))
    p.drawPolygon(QPolygon([QPoint(3, 5), QPoint(13, 5), QPoint(8, 11)]))


def _draw_check(p) -> None:
    from PyQt5.QtCore import QPointF, Qt
    from PyQt5.QtGui import QColor, QPen
    pen = QPen(QColor("#ffffff"), 2.2)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawPolyline(QPointF(3.5, 8.5), QPointF(6.8, 11.5), QPointF(12.5, 4.8))


# ---------------------------------------------------------------- таблица стилей
_QSS = Template("""
* { font-family: "$font_text", "$font_text_fb", sans-serif; font-size: ${pt}pt; color: $text; }
QMainWindow, QDialog { background: $bg; }
QToolTip { color: $text; background: $bg_card; border: 1px solid $bronze_light; padding: 4px 6px; }

/* вкладки */
QTabWidget::pane { border: 1px solid $border; background: $bg_card; border-radius: 12px; top: -1px; }
QTabBar::tab { background: $bg_warm; color: $text_muted; padding: 8px 18px; margin-right: 3px;
               border: 1px solid $border; border-top: 3px solid $bg_warm; border-bottom: none;
               border-top-left-radius: 10px; border-top-right-radius: 10px; }
QTabBar::tab:selected { background: $bg_card; color: $primary_dark; border-top: 3px solid $primary; }
QTabBar::tab:hover:!selected { background: $bg_soft; color: $primary_dark; }

/* кнопки: «пилюли», как на сайте */
QPushButton { background: $bg_card; color: $primary_dark; border: 1.5px solid $border; border-radius: 15px;
              padding: 6px 16px; }
QPushButton:hover { background: $bg_warm; border-color: $bronze_light; }
QPushButton:pressed { background: $bronze_pale; }
QPushButton:disabled { color: #a59f92; background: $bg_soft; border-color: $border_soft; }
QPushButton#primary { color: #ffffff; font-weight: 700; border: none; padding: 7px 20px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $primary, stop:1 $primary_dark); }
QPushButton#primary:hover { background: $primary_dark; }
QPushButton#primary:pressed { background: #2b3a26; }
QPushButton#primary:disabled { background: $primary_light; color: #f3f6f0; }

/* таблицы: чуть мельче основного текста — Montserrat широкий, а колонок много */
QTableWidget { background: $bg_card; alternate-background-color: $bg_soft; gridline-color: $border_soft;
               selection-background-color: $primary_pale; selection-color: $text; border: 1px solid $border;
               border-radius: 8px; font-size: ${table_pt}pt; }
QHeaderView { background: $bg_warm; border: none; }
QHeaderView::section { background: $bg_warm; color: $primary_dark; padding: 7px 6px; border: none;
                       border-right: 1px solid $border; border-bottom: 1px solid $border; font-weight: 700;
                       font-size: ${table_pt}pt; }
QTableCornerButton::section { background: $bg_warm; border: none; }

/* поля ввода */
QLineEdit, QComboBox, QDateEdit, QDoubleSpinBox, QSpinBox, QPlainTextEdit, QTextEdit {
    background: $bg_card; border: 1.5px solid $border; border-radius: 10px; padding: 5px 10px;
    selection-background-color: $primary_pale; selection-color: $text; }
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QPlainTextEdit:focus {
    border: 1.5px solid $primary_light; background: #ffffff; }
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled, QDoubleSpinBox:disabled, QSpinBox:disabled {
    background: $bg_soft; color: #9a9588; }
QListWidget { background: $bg_card; border: 1px solid $border; border-radius: 10px; padding: 4px; }
QListWidget::item { padding: 4px 2px; }
QComboBox QAbstractItemView { background: $bg_card; border: 1px solid $border; outline: 0;
                              selection-background-color: $primary_pale; selection-color: $text; }
QComboBox::drop-down, QDateEdit::drop-down { subcontrol-origin: padding; subcontrol-position: center right;
    width: 24px; border: none; border-left: 1px solid $border_soft; }
$arrow_rule
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1.5px solid $bronze_light; border-radius: 5px;
                       background: $bg_card; }
QCheckBox::indicator:checked { background: $primary; border-color: $primary_dark; $check_rule }
QCheckBox::indicator:disabled { background: $bg_soft; border-color: $border; }

/* карточки и группы */
QGroupBox { border: 1px solid $border; border-radius: 12px; margin-top: 16px; padding: 14px 10px 8px 10px;
            background: $bg_card; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; color: $primary_dark;
                   font-family: "$font_display", "$font_display_fb", serif; font-weight: 700; font-size: 11pt; }
QFrame#kpi { background: $bg_card; border: 1px solid $border; border-radius: 14px; }
QLabel#kpiTitle { color: $text_muted; font-size: 8.5pt; }
QLabel#kpiValue { font-family: "$font_display", "$font_display_fb", serif; font-size: 20pt; font-weight: 700;
                  color: $primary_dark; }
QLabel#kpiSub { color: $text_soft; font-size: 8.5pt; }
QLabel#h2 { font-family: "$font_display", "$font_display_fb", serif; font-size: 13pt; font-weight: 700;
            color: $primary_dark; }
QLabel#brandTitle { font-family: "$font_display", "$font_display_fb", serif; font-size: 22pt; font-weight: 700;
                    color: $primary_dark; }
QLabel#brandSub { color: $bronze; font-size: 8pt; font-weight: 700; }
QLabel#muted { color: $text_muted; }
QLabel#hint { color: $text_soft; font-size: 8.5pt; }
QLabel#demoBadge { background: $accent_pale; color: $accent_dark; border-radius: 12px; padding: 4px 12px;
                   font-weight: 700; }

QProgressBar { border: 1.5px solid $border; border-radius: 7px; background: $bg_card; height: 12px; }
QProgressBar::chunk { border-radius: 5px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $primary_light, stop:1 $primary); }
QSplitter::handle { background: $border_soft; }
QStatusBar { background: $bg_warm; color: $text_muted; }
QStatusBar QLabel { color: $text_muted; }

/* полосы прокрутки */
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: $primary_pale; border-radius: 5px; min-height: 32px; }
QScrollBar::handle:vertical:hover { background: $primary_light; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle:horizontal { background: $primary_pale; border-radius: 5px; min-width: 32px; }
QScrollBar::handle:horizontal:hover { background: $primary_light; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
""")


def stylesheet() -> str:
    """Таблица стилей приложения. Вызывать после создания QApplication (рисует значки)."""
    arrow = _icon_png("dianthus-arrow-down.png", _draw_arrow)
    check = _icon_png("dianthus-check.png", _draw_check)
    return _QSS.substitute(
        font_text=FONT_TEXT, font_text_fb=FONT_FALLBACK_TEXT, font_display=FONT_DISPLAY,
        font_display_fb=FONT_FALLBACK_DISPLAY, pt=TEXT_PT, table_pt=TABLE_PT,
        arrow_rule=(f"QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url({arrow}); width: 12px; height: 12px; }}"
                    if arrow else ""),
        check_rule=f"image: url({check});" if check else "",
        bg=BG, bg_soft=BG_SOFT, bg_card=BG_CARD, bg_warm=BG_WARM,
        primary=PRIMARY, primary_dark=PRIMARY_DARK, primary_light=PRIMARY_LIGHT, primary_pale=PRIMARY_PALE,
        accent_pale=ACCENT_PALE, accent_dark=ACCENT_DARK, bronze=BRONZE, bronze_light=BRONZE_LIGHT,
        bronze_pale=BRONZE_PALE, text=TEXT, text_muted=TEXT_MUTED, text_soft=TEXT_SOFT, border=BORDER,
        border_soft=BORDER_SOFT)


def apply(app) -> None:
    """Применяет фирменный стиль к приложению: шрифты, иконка, таблица стилей."""
    from PyQt5.QtGui import QFont
    load_fonts()
    font = QFont(FONT_TEXT)
    font.setPointSizeF(TEXT_PT)
    app.setFont(font)
    app.setWindowIcon(app_icon())
    app.setStyleSheet(stylesheet())
