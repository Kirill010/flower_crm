"""Сборка фирменных материалов «Диантус» для CRM из файлов сайта (D:\\Dianthus\\1-site\\app\\static).

Нужен Python с fontTools, brotli и Pillow — они есть в venv сайта:

    D:\\Dianthus\\1-site\\.venv\\Scripts\\python.exe -I -B tools\\build_brand_assets.py [папка static сайта]

Что получается в папке assets/:
  * emblem.png, emblem-96.png, emblem-192.png — эмблема «Д» (из emblem.webp сайта);
  * dianthus.ico — иконка программы;
  * fonts/Montserrat-{Regular,Bold}.ttf — Montserrat (шрифт текста на сайте);
  * fonts/DianthusDisplay-{Regular,Bold}.ttf — шрифт заголовков на основе Playfair Display;
  * fonts/OFL-*.txt, fonts/README.txt — лицензии и описание.

Qt 5 не читает woff2 и переменные шрифты, поэтому из каждого woff2 делаются статические начертания
(400 и 700), а латинский и кириллический наборы склеиваются в один файл.

Лицензия шрифтов — SIL OFL 1.1. У Playfair Display зарезервировано имя («Reserved Font Name»), поэтому
изменённая версия названа «Dianthus Display»; у Montserrat имя не зарезервировано, оно сохранено.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from fontTools.merge import Merger, Options
from fontTools.ttLib import TTFont, newTable
from fontTools.varLib import instancer
from PIL import Image

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "assets"
SITE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"D:\Dianthus\1-site\app\static")

# (семейство в программе, префикс файлов сайта, исходное семейство, файл лицензии)
FAMILIES = [
    ("Montserrat", "montserrat", "Montserrat", "OFL-Montserrat.txt"),
    ("Dianthus Display", "playfair-display", "Playfair Display", "OFL-PlayfairDisplay.txt"),
]
WEIGHTS = {400: "Regular", 700: "Bold"}
SAMPLE = "Диантус — корпоративные поздравления: Ёё №1 0123456789 «»,.;:()+-×/%"


def static_instance(woff2: Path, weight: int, tmp: Path) -> Path:
    font = TTFont(woff2)
    font.flavor = None
    inst = instancer.instantiateVariableFont(font, {"wght": weight}, inplace=False)
    path = tmp / f"{woff2.stem}-{weight}.ttf"
    inst.save(path)
    return path


def merge_subsets(paths: list[Path]) -> TTFont:
    try:
        return Merger(options=Options(drop_tables=["STAT", "DSIG"])).merge([str(p) for p in paths])
    except Exception as exc:                                   # слияние таблиц кернинга может не получиться
        print("  слияние с GPOS/GSUB не удалось (%s), собираю без них" % exc)
        return Merger(options=Options(drop_tables=["STAT", "DSIG", "GPOS", "GSUB", "GDEF"])).merge(
            [str(p) for p in paths])


def finish(font: TTFont, family: str, style: str, weight: int, note: str) -> None:
    name = font["name"]
    keep = {i: name.getDebugName(i) for i in (0, 13, 14)}      # авторские права и лицензия — оставляем
    for rec in list(name.names):
        if rec.nameID in (1, 2, 3, 4, 6, 10, 16, 17, 21, 22, 25):
            name.names.remove(rec)
    ps = f"{family.replace(' ', '')}-{style}"
    for name_id, text in {1: family, 2: style, 3: f"{ps};Dianthus-CRM", 4: f"{family} {style}", 6: ps,
                          10: note}.items():
        name.setName(text, name_id, 3, 1, 0x409)
    if not keep[13]:
        name.setName("This Font Software is licensed under the SIL Open Font License, Version 1.1. "
                     "This license is available with a FAQ at: https://openfontlicense.org", 13, 3, 1, 0x409)
    if not keep[14]:
        name.setName("https://openfontlicense.org", 14, 3, 1, 0x409)
    os2 = font["OS/2"]
    os2.usWeightClass = weight
    bold = style == "Bold"
    os2.fsSelection = (os2.fsSelection & ~0b1100001) | (1 << 5 if bold else 1 << 6)
    font["head"].macStyle = 1 if bold else 0
    if "gasp" not in font:                                     # шрифт без хинтинга: просим сглаживание при любом размере
        gasp = newTable("gasp")
        gasp.version = 1
        gasp.gaspRange = {0xFFFF: 0x000F}
        font["gasp"] = gasp


def build_fonts() -> None:
    fonts_dir = OUT / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        for family, prefix, origin, license_file in FAMILIES:
            for weight, style in WEIGHTS.items():
                print(f"{family} {style} ({weight})")
                parts = [static_instance(SITE / "fonts" / f"{prefix}-{subset}-wght-normal.woff2", weight, tmp)
                         for subset in ("latin", "cyrillic")]
                font = merge_subsets(parts)
                note = (f"Статические начертания {style} из {origin} (SIL OFL 1.1): формат, набор символов "
                        "и имя семейства изменены для CRM «Диантус».")
                finish(font, family, style, weight, note)
                target = fonts_dir / f"{family.replace(' ', '')}-{style}.ttf"
                font.save(target)
                cmap = TTFont(target).getBestCmap()
                missing = sorted({ch for ch in SAMPLE if ord(ch) not in cmap and not ch.isspace()})
                print(f"  -> {target.name}: {target.stat().st_size // 1024} КБ, нет символов: {''.join(missing) or '—'}")
            shutil.copy2(SITE / "fonts" / license_file, fonts_dir / license_file)
    (fonts_dir / "README.txt").write_text(
        "Шрифты для CRM «Диантус» — те же, что на сайте: Montserrat (текст) и Playfair Display (заголовки).\n\n"
        "Qt 5 не читает woff2 и переменные шрифты, поэтому из woff2 сайта собраны статические файлы TTF\n"
        "(Regular и Bold, латиница и кириллица в одном файле). Сборка: tools/build_brand_assets.py.\n\n"
        "Лицензия — SIL Open Font License 1.1 (тексты рядом: OFL-Montserrat.txt, OFL-PlayfairDisplay.txt).\n"
        "У Playfair Display зарезервировано имя шрифта, поэтому изменённая версия называется «Dianthus Display».\n"
        "Montserrat сохранил своё имя: у него оно не зарезервировано.\n"
        "Шрифты нельзя продавать отдельно от программы; авторские права — у авторов шрифтов (см. файлы OFL).\n",
        encoding="utf-8")


def build_images() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    emblem = Image.open(SITE / "emblem.webp").convert("RGBA")
    emblem.save(OUT / "emblem.png", optimize=True)
    for size in (96, 192):
        emblem.resize((size, size), Image.LANCZOS).save(OUT / f"emblem-{size}.png", optimize=True)
    emblem.save(OUT / "dianthus.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("эмблема и иконка: ", ", ".join(sorted(p.name for p in OUT.glob("emblem*.png"))), "dianthus.ico")


if __name__ == "__main__":
    build_images()
    build_fonts()
    print("Готово:", OUT)
