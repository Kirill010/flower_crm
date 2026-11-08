"""Фирменный стиль «Диантус»: палитра совпадает с сайтом, шрифты и эмблема на месте, стили собираются."""
import re
from pathlib import Path

import pytest
from PyQt5.QtGui import QFont, QFontDatabase, QFontMetrics
from PyQt5.QtWidgets import QApplication

import theme

SITE_CSS = Path(r"D:\Dianthus\1-site\app\static\style.css")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.skipif(not SITE_CSS.exists(), reason="style.css сайта не найден")
def test_palette_matches_site_css():
    """Цвета программы — те же, что в переменных :root на сайте."""
    css = SITE_CSS.read_text(encoding="utf-8")
    start = css.index(":root")
    root = css[start:css.index("}", start)]
    site = {name: value.lower() for name, value in re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", root)}
    ours = {
        "bg": theme.BG, "bg-soft": theme.BG_SOFT, "bg-card": theme.BG_CARD, "bg-warm": theme.BG_WARM,
        "primary": theme.PRIMARY, "primary-dark": theme.PRIMARY_DARK, "primary-light": theme.PRIMARY_LIGHT,
        "primary-pale": theme.PRIMARY_PALE, "primary-mist": theme.PRIMARY_MIST,
        "accent": theme.ACCENT, "accent-light": theme.ACCENT_LIGHT, "accent-pale": theme.ACCENT_PALE,
        "rose": theme.ROSE, "rose-light": theme.ROSE_LIGHT, "rose-pale": theme.ROSE_PALE,
        "bronze": theme.BRONZE, "bronze-light": theme.BRONZE_LIGHT, "bronze-pale": theme.BRONZE_PALE,
        "text": theme.TEXT, "border": theme.BORDER, "border-soft": theme.BORDER_SOFT,
    }
    for name, value in ours.items():
        assert site[name] == value.lower(), f"--{name}: на сайте {site[name]}, в программе {value}"


def test_brand_assets_are_in_place():
    for name in ("emblem.png", "emblem-96.png", "emblem-192.png", "dianthus.ico"):
        assert (theme.ASSETS / name).stat().st_size > 1000, name
    for name in ("Montserrat-Regular.ttf", "Montserrat-Bold.ttf", "DianthusDisplay-Regular.ttf",
                 "DianthusDisplay-Bold.ttf", "OFL-Montserrat.txt", "OFL-PlayfairDisplay.txt", "README.txt"):
        assert (theme.FONT_DIR / name).stat().st_size > 500, name


def test_fonts_load_and_cover_cyrillic(app):
    assert theme.load_fonts() is True
    families = set(QFontDatabase().families())
    assert theme.FONT_TEXT in families and theme.FONT_DISPLAY in families
    for family in (theme.FONT_TEXT, theme.FONT_DISPLAY):
        metrics = QFontMetrics(QFont(family))
        assert all(metrics.inFontUcs4(ord(ch)) for ch in "Диантус ёЁ№«»0123456789"), family


def test_stylesheet_is_complete_and_branded(app):
    css = theme.stylesheet()
    assert "$" not in css                                           # все токены подставлены
    for color in (theme.BG, theme.BG_CARD, theme.PRIMARY, theme.PRIMARY_DARK, theme.BORDER, theme.BG_WARM):
        assert color in css
    assert theme.FONT_TEXT in css and theme.FONT_DISPLAY in css
    for url in re.findall(r"url\(([^)]+)\)", css):                  # значки (стрелка списка, галочка) созданы
        assert Path(url).exists(), url


def test_apply_sets_font_icon_and_style(app):
    theme.apply(app)
    assert app.font().family() == theme.FONT_TEXT
    assert not app.windowIcon().isNull()
    assert app.styleSheet().count("QPushButton#primary") == 4
    pix = theme.emblem_pixmap(56)
    assert not pix.isNull() and round(pix.height() / pix.devicePixelRatio()) == 56   # 56 логических пикселей
