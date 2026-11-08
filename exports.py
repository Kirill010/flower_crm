"""Экспорт и импорт: КП (Word), счета, листы доставки и отчёты (Excel), загрузка списка получателей.

Функции экспорта принимают обычные словари и списки (без ORM-объектов), поэтому
вызываются из интерфейса после закрытия сессии и легко тестируются.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties

import theme
from database import APP_DIR
from models import (RECIPIENT_CATEGORIES, CorporateClient, CorporateEmployee, Invoice, Order)
from services import AppSettings, fmt_date, fmt_money, invoice_status, load_settings

EXPORT_DIR = APP_DIR / "exports"

def _hex(color: str) -> str:
    return color.lstrip("#").upper()


# фирменные цвета «Диантус» (theme.py) для Excel и Word
_HEADER_FILL = PatternFill("solid", fgColor=_hex(theme.BG_WARM))
_TOTAL_FILL = PatternFill("solid", fgColor=_hex(theme.PRIMARY_MIST))
_THIN = Side(style="thin", color=_hex(theme.BORDER))
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_HEADER_FONT = Font(bold=True, color=_hex(theme.PRIMARY_DARK))
_TITLE_FONT = Font(name="Georgia", bold=True, size=15, color=_hex(theme.PRIMARY_DARK))
_LABEL_FONT = Font(bold=True, color=_hex(theme.BRONZE))


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\r\n]+', "_", name).strip() or "file"


def export_path(filename: str) -> Path:
    EXPORT_DIR.mkdir(exist_ok=True)
    return EXPORT_DIR / safe_filename(filename)


# ------------------------------------------------------------------ Excel: общие приёмы
def _table(ws, start_row: int, headers: list[str], rows: list[list], *,
           money_cols: tuple[int, ...] = (), date_cols: tuple[int, ...] = ()) -> int:
    for c, title in enumerate(headers, 1):
        cell = ws.cell(row=start_row, column=c, value=title)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.border = _BORDER
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for r, row in enumerate(rows, start_row + 1):
        for c, value in enumerate(row, 1):
            cell = ws.cell(row=r, column=c, value=value)
            cell.border = _BORDER
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if c in money_cols:
                cell.number_format = "#,##0.00"
            if c in date_cols:
                cell.number_format = "DD.MM.YYYY"
    return start_row + len(rows)


def _autosize(ws, min_width: int = 8, max_width: int = 48) -> None:
    widths: dict[int, int] = {}
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is not None:
                longest = max(len(part) for part in str(cell.value).split("\n"))
                widths[cell.column] = max(widths.get(cell.column, 0), longest)
    for col, width in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = max(min_width, min(max_width, width + 2))


def _add_logo(ws, anchor: str, size: int = 72) -> None:
    """Эмблема «Диантус» в углу листа (если файл эмблемы на месте)."""
    path = theme.ASSETS / "emblem-96.png"
    if not path.exists():
        return
    try:
        img = XLImage(str(path))             # для картинок в Excel openpyxl требует Pillow
    except ImportError:
        return                               # без Pillow счёт получится без эмблемы, но целым
    img.width = img.height = size
    ws.add_image(img, anchor)


def _landscape_fit(ws) -> None:
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)


# ------------------------------------------------------------------ Excel: заказы
ORDER_HEADERS = ["№", "Дата доставки", "Время", "Компания", "Получатель", "Телефон", "Адрес",
                 "Повод", "Услуга", "Букет", "Открытка", "Подарок", "Сумма", "Статус", "Пробное"]


def _order_line(r: dict) -> list:
    return [r.get("id"), r.get("delivery_date"), r.get("delivery_time") or "", r.get("company") or "",
            r.get("recipient") or "", r.get("phone") or "", r.get("address") or "",
            r.get("occasion") or "", r.get("service") or "", r.get("bouquet") or "",
            r.get("card_text") or "", r.get("gift") or "", r.get("amount") or 0,
            r.get("status") or "", "да" if r.get("is_trial") else ""]


def export_orders_xlsx(path, rows: list[dict]) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Заказы"
    _table(ws, 1, ORDER_HEADERS, [_order_line(r) for r in rows], money_cols=(13,), date_cols=(2,))
    ws.freeze_panes = "A2"
    _autosize(ws)
    _landscape_fit(ws)
    wb.save(path)
    return Path(path)


def export_delivery_sheet_xlsx(path, rows: list[dict], day: date, company_name: str = "") -> Path:
    """Лист курьера на день: по времени, с адресами, телефонами и текстом открытки."""
    items = sorted((r for r in rows if r.get("delivery_date") == day and r.get("status") != "Отменён"),
                   key=lambda r: (r.get("delivery_time") or "99:99", r.get("id") or 0))
    wb = Workbook()
    ws = wb.active
    ws.title = "Лист доставки"
    ws["A1"] = f"Лист доставки на {fmt_date(day)}" + (f" — {company_name}" if company_name else "")
    ws["A1"].font = _TITLE_FONT
    ws["A2"] = f"Заказов: {len(items)}"
    headers = ["Время", "Получатель", "Телефон", "Адрес", "Компания", "Букет", "Открытка / подарок",
               "Статус", "Отметка о доставке"]
    lines = [[r.get("delivery_time") or "—", r.get("recipient") or "", r.get("phone") or "",
              r.get("address") or "", r.get("company") or "", r.get("bouquet") or "",
              "; ".join(x for x in (r.get("card_text"), r.get("gift")) if x), r.get("status") or "", ""]
             for r in items]
    _table(ws, 4, headers, lines)
    _autosize(ws)
    ws.column_dimensions["I"].width = 22
    _landscape_fit(ws)
    wb.save(path)
    return Path(path)


# ------------------------------------------------------------------ Excel: счёт и отчёты
def invoice_export_data(session, invoice_id: int) -> dict:
    inv = session.get(Invoice, invoice_id)
    client = inv.client
    st = load_settings(session)
    orders = session.query(Order).filter(Order.invoice_id == inv.id).order_by(Order.delivery_date, Order.id).all()
    lines = [{"date": o.delivery_date, "recipient": o.recipient_name or "—", "occasion": o.occasion or "",
              "bouquet": o.bouquet or "", "amount": o.amount or 0} for o in orders]
    if not lines:
        lines = [{"date": inv.issue_date, "recipient": "", "occasion": inv.description or "Услуги",
                  "bouquet": "", "amount": inv.amount or 0}]
    return {"number": inv.number or f"№{inv.id}", "issue_date": inv.issue_date, "due_date": inv.due_date,
            "period_start": inv.period_start, "period_end": inv.period_end,
            "seller": st.company_name, "seller_contacts": st.shop_contacts,
            "client": client.company_name if client else "", "client_address": client.address if client else "",
            "contract": client.contract_number if client else "",
            "payment_terms": (client.payment_terms if client else "") or "",
            "lines": lines, "total": inv.amount or 0, "currency": st.currency,
            "status": invoice_status(inv)}


def export_invoice_xlsx(path, data: dict) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Счёт"
    ws["A1"] = f"Счёт № {data['number']} от {fmt_date(data['issue_date'])}"
    ws["A1"].font = _TITLE_FONT
    info = [("Исполнитель", data["seller"]), ("Контакты", data.get("seller_contacts") or ""),
            ("Плательщик", data["client"]), ("Адрес", data.get("client_address") or ""),
            ("Договор", data.get("contract") or "—"),
            ("Период", f"{fmt_date(data.get('period_start'))} – {fmt_date(data.get('period_end'))}"
             if data.get("period_start") else "—"),
            ("Оплатить до", fmt_date(data.get("due_date"))),
            ("Условия оплаты", data.get("payment_terms") or "")]
    row = 3
    for label, value in info:
        ws.cell(row=row, column=1, value=label).font = _LABEL_FONT
        ws.cell(row=row, column=2, value=value)
        row += 1
    headers = ["Дата", "Получатель", "Повод", "Букет / услуга", f"Сумма, {data['currency']}"]
    lines = [[ln["date"], ln["recipient"], ln["occasion"], ln["bouquet"], ln["amount"]] for ln in data["lines"]]
    end = _table(ws, row + 1, headers, lines, money_cols=(5,), date_cols=(1,))
    caption = ws.cell(row=end + 1, column=4, value="Итого:")
    total = ws.cell(row=end + 1, column=5, value=data["total"])
    for cell in (caption, total):
        cell.font = _HEADER_FONT
        cell.fill = _TOTAL_FILL
        cell.border = _BORDER
    caption.alignment = Alignment(horizontal="right")
    total.number_format = "#,##0.00"
    _autosize(ws)
    ws.column_dimensions["A"].width = 16
    _add_logo(ws, "E1")
    wb.save(path)
    return Path(path)


def export_report_xlsx(path, monthly: list[dict], clients: list[dict], currency: str = "") -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "По месяцам"
    headers = ["Месяц", "Компаний с заказами", "Поздравлений", "Доставлено", f"Выручка (факт), {currency}",
               f"Прогноз, {currency}", f"План, {currency}", "План выполнен, %", f"Средний чек, {currency}"]
    rows = [[m["label"], m["clients"], m["orders"], m["delivered"], m["revenue"], m["forecast"], m["plan"],
             round(m["plan_pct"], 1), round(m["avg_check"], 2) if m["avg_check"] is not None else ""]
            for m in monthly]
    _table(ws, 1, headers, rows, money_cols=(5, 6, 7, 9))
    _autosize(ws)
    ws2 = wb.create_sheet("По компаниям")
    headers2 = ["Компания", "Поздравлений", f"Выручка (факт), {currency}", f"Прогноз, {currency}",
                f"Выставлено счетов, {currency}", f"Долг по счетам, {currency}"]
    rows2 = [[c["company"], c["orders"], c["revenue"], c["forecast"], c["invoiced"], c["debt"]] for c in clients]
    _table(ws2, 1, headers2, rows2, money_cols=(3, 4, 5, 6))
    _autosize(ws2)
    wb.save(path)
    return Path(path)


# ------------------------------------------------------------------ Word: коммерческое предложение
KEY_OFFER = ("Мы берём на себя все заботы по поздравлению ваших сотрудников и партнёров. "
             "Вам достаточно один раз предоставить список дат, а мы обеспечим своевременную доставку "
             "цветов и подарков в течение всего года.")
PROBLEM = ("Во многих компаниях поздравления сотрудников организуются вручную. Это требует времени, "
           "кадровая служба или руководители забывают о датах, а закупка цветов происходит в последний момент.")
HOW_WE_WORK = ["ведём календарь дней рождения;", "заранее готовим букеты;",
               "доставляем цветы в офис или домой сотруднику;",
               "при необходимости добавляем открытки и подарки;",
               "обеспечиваем поздравления без участия заказчика."]
SERVICES_LIST = ["Букеты на дни рождения сотрудников.", "Цветы для руководителей и партнёров.",
                 "Поздравления с 8 Марта, Новым годом и другими праздниками.",
                 "Цветочное оформление офиса.", "Подарочные наборы с цветами, сладостями и открытками."]
ADVANTAGES = ["Персональный менеджер.", "Доставка точно в дату и время.", "Фиксированные корпоративные цены.",
              "Индивидуальный подход к каждому сотруднику.", "Возможность оплаты раз в месяц по счёту."]
HOW_TO_START = ["Вы один раз присылаете список сотрудников и дат (подойдёт таблица Excel).",
                "Мы заводим календарь и согласуем пожелания: букеты, бюджет, адреса доставки.",
                "Дальше мы сами готовим и доставляем поздравления — от вас ничего не требуется."]


HEAD_FONT = "Georgia"   # на сайте заголовки — Playfair Display; в Word берём Georgia: он есть на любом компьютере
BODY_FONT = "Calibri"

_TCPR_ORDER = ["tcW", "gridSpan", "vMerge", "tcBorders", "shd", "noWrap", "tcMar", "textDirection",
               "tcFitText", "vAlign", "hideMark"]


def _rgb(color: str) -> RGBColor:
    return RGBColor.from_string(_hex(color))


def _force_font(owner, name: str) -> None:
    """Шрифт для латиницы и кириллицы; убирает привязку к шрифтам темы Word (иначе она главнее)."""
    rpr = owner.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        rfonts.attrib.pop(qn(attr), None)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rfonts.set(qn(attr), name)


def _style_font(style, name: str, size: float, color: str, bold: bool | None = None) -> None:
    style.font.name = name
    style.font.size = Pt(size)
    style.font.color.rgb = _rgb(color)
    if bold is not None:
        style.font.bold = bold
    _force_font(style.element, name)


def _run(paragraph, text: str, *, font: str = BODY_FONT, size: float = 11.0, color: str = theme.TEXT,
         bold: bool = False, italic: bool = False, spacing: int | None = None):
    """Фрагмент текста с шрифтом и цветом. spacing — разрядка букв в двадцатых долях пункта."""
    run = paragraph.add_run(text)
    run.font.name = font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = _rgb(color)
    _force_font(run._r, font)
    if spacing:
        rpr = run._r.get_or_add_rPr()
        sp = OxmlElement("w:spacing")
        sp.set(qn("w:val"), str(spacing))
        sz = rpr.find(qn("w:sz"))
        if sz is not None:
            sz.addprevious(sp)           # по схеме spacing идёт перед sz
        else:
            rpr.append(sp)
    return run


def _bottom_rule(paragraph, color: str, size: int = 12) -> None:
    """Линия под абзацем. Вызывать сразу после создания абзаца, до настройки отступов."""
    p_pr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), "6")
    bottom.set(qn("w:color"), _hex(color))
    borders.append(bottom)
    p_pr.append(borders)


def _cell_format(cell, *, fill: str | None = None, borders: dict | None = None, pad: tuple = (80, 140)) -> None:
    """Заливка, рамки (край → (толщина, цвет); не указан — без линии) и поля ячейки. pad — (верх/низ, лево/право) в twips."""
    tc_pr = cell._tc.get_or_add_tcPr()
    if borders is not None:
        tc_borders = OxmlElement("w:tcBorders")
        for edge in ("top", "left", "bottom", "right"):
            el = OxmlElement(f"w:{edge}")
            spec = borders.get(edge)
            if spec is None:
                el.set(qn("w:val"), "nil")
            else:
                el.set(qn("w:val"), "single")
                el.set(qn("w:sz"), str(spec[0]))
                el.set(qn("w:space"), "0")
                el.set(qn("w:color"), _hex(spec[1]))
            tc_borders.append(el)
        tc_pr.append(tc_borders)
    if fill:
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), _hex(fill))
        tc_pr.append(shd)
    mar = OxmlElement("w:tcMar")
    for edge, value in (("top", pad[0]), ("left", pad[1]), ("bottom", pad[0]), ("right", pad[1])):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:w"), str(value))
        el.set(qn("w:type"), "dxa")
        mar.append(el)
    tc_pr.append(mar)
    children = list(tc_pr)               # элементы ячейки должны идти в порядке схемы, иначе Word ругается
    children.sort(key=lambda el: _TCPR_ORDER.index(el.tag.split("}")[1]) if el.tag.split("}")[1] in _TCPR_ORDER else 99)
    for el in children:
        tc_pr.remove(el)
    for el in children:
        tc_pr.append(el)


def _list(doc, items: list[str], style: str) -> None:
    """Список, который не рвётся между страницами: каждый пункт «держится» за следующий."""
    last = len(items) - 1
    for i, item in enumerate(items):
        doc.add_paragraph(item, style=style).paragraph_format.keep_with_next = i < last


def export_proposal_docx(path, st: AppSettings, client: dict | None = None, today: date | None = None) -> Path:
    """Коммерческое предложение по тексту ТЗ в стиле «Диантус». client — словарь с данными компании (или None)."""
    today = today or date.today()
    client = client or {}
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)               # A4
    section.left_margin = section.right_margin = Cm(2.0)
    section.top_margin = section.bottom_margin = Cm(1.8)
    doc.core_properties.title = "Коммерческое предложение"
    doc.core_properties.author = st.company_name

    _style_font(doc.styles["Normal"], BODY_FONT, 11, theme.TEXT)
    lang = OxmlElement("w:lang")
    lang.set(qn("w:val"), "ru-RU")
    lang.set(qn("w:eastAsia"), "ru-RU")
    doc.styles["Normal"].element.get_or_add_rPr().append(lang)
    h1 = doc.styles["Heading 1"]
    _style_font(h1, HEAD_FONT, 14, theme.PRIMARY_DARK, bold=True)
    h1.paragraph_format.space_before = Pt(16)
    h1.paragraph_format.space_after = Pt(4)
    for name in ("List Bullet", "List Number"):
        _style_font(doc.styles[name], BODY_FONT, 11, theme.TEXT)

    # --- шапка: эмблема и название
    head = doc.add_table(rows=1, cols=2)
    head.autofit = False
    left, right = head.rows[0].cells
    left.width, right.width = Cm(3.0), Cm(14.0)
    emblem = theme.ASSETS / "emblem-192.png"
    if emblem.exists():
        left.paragraphs[0].add_run().add_picture(str(emblem), width=Cm(2.5))
    _run(right.paragraphs[0], st.company_name, font=HEAD_FONT, size=26, color=theme.PRIMARY_DARK, bold=True)
    tagline = right.add_paragraph()
    _run(tagline, theme.BRAND_TAGLINE.upper(), size=9, color=theme.BRONZE, bold=True, spacing=40)
    for cell in (left, right):
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        _cell_format(cell, borders={}, pad=(0, 0))
        for par in cell.paragraphs:
            par.paragraph_format.space_after = Pt(0)
    rule = doc.add_paragraph()
    _bottom_rule(rule, theme.ACCENT, 12)                                      # медная линия, как на сайте
    rule.paragraph_format.space_before = Pt(2)
    rule.paragraph_format.space_after = Pt(6)

    title = doc.add_paragraph()
    _run(title, "Коммерческое предложение", font=HEAD_FONT, size=22, color=theme.PRIMARY_DARK, bold=True)
    title.paragraph_format.space_after = Pt(0)
    subtitle = doc.add_paragraph()
    _run(subtitle, "Корпоративные поздравления сотрудников и партнёров", size=12, color=theme.BRONZE, italic=True)
    if client.get("company_name"):
        contact = ", ".join(x for x in (client.get("contact_person"), client.get("contact_position")) if x)
        meta = doc.add_paragraph()
        _run(meta, "Для: ", bold=True, color=theme.PRIMARY_DARK)
        _run(meta, client["company_name"] + (f" — {contact}" if contact else ""))
        meta.paragraph_format.space_after = Pt(0)
    date_line = doc.add_paragraph()
    _run(date_line, "Дата: ", bold=True, color=theme.PRIMARY_DARK)
    _run(date_line, fmt_date(today))

    # --- ключевое предложение: светло-зелёная врезка с зелёной полосой слева
    doc.add_heading("Наше предложение", level=1)
    box = doc.add_table(rows=1, cols=1)
    cell = box.rows[0].cells[0]
    cell.width = Cm(17)
    quote = cell.paragraphs[0]
    _run(quote, "«" + KEY_OFFER + "»", font=HEAD_FONT, size=12.5, color=theme.PRIMARY_DARK, italic=True)
    quote.paragraph_format.space_after = Pt(0)
    _cell_format(cell, fill=theme.PRIMARY_MIST, borders={"left": (24, theme.PRIMARY)}, pad=(140, 240))

    doc.add_heading("Проблема, которую мы решаем", level=1)
    doc.add_paragraph(PROBLEM)
    doc.add_heading("Как мы работаем", level=1)
    doc.add_paragraph(f"{st.company_name} берёт организацию поздравлений на себя:")
    _list(doc, HOW_WE_WORK, "List Bullet")
    doc.add_heading("Услуги", level=1)
    _list(doc, SERVICES_LIST, "List Bullet")
    doc.add_heading("Почему с нами удобно", level=1)
    _list(doc, ADVANTAGES, "List Bullet")

    # --- условия: кремовый столбец названий и рамки цвета песка
    doc.add_heading("Условия сотрудничества", level=1)
    price = client.get("fixed_price") or st.default_price
    terms = [("Персональный менеджер", client.get("manager") or "назначается при подписании договора"),
             ("Стоимость стандартного букета", f"{fmt_money(price, st.currency)} — фиксированная корпоративная цена"),
             ("Пробное поздравление", f"со скидкой {st.trial_discount:g}%"),
             ("Оплата", client.get("payment_terms") or "раз в месяц по счёту"),
             ("Договор", "годовой, поздравления в течение всего года")]
    if client.get("discount"):
        terms.insert(2, ("Скидка по договору", f"{client['discount']:g}%"))
    table = doc.add_table(rows=0, cols=2)
    table.autofit = False
    edge = (4, theme.BORDER)
    for label, value in terms:
        c0, c1 = table.add_row().cells
        c0.width, c1.width = Cm(6.0), Cm(11.0)
        _run(c0.paragraphs[0], label, bold=True, color=theme.PRIMARY_DARK)
        _run(c1.paragraphs[0], value)
        c0.paragraphs[0].paragraph_format.space_after = Pt(0)
        c1.paragraphs[0].paragraph_format.space_after = Pt(0)
        _cell_format(c0, fill=theme.BG, borders={"top": edge, "left": edge, "bottom": edge, "right": edge})
        _cell_format(c1, borders={"top": edge, "left": edge, "bottom": edge, "right": edge})

    doc.add_heading("Как начать", level=1)
    _list(doc, HOW_TO_START, "List Number")

    closing = doc.add_paragraph()
    closing.paragraph_format.space_before = Pt(18)
    _run(closing, st.company_name, font=HEAD_FONT, size=13, color=theme.PRIMARY_DARK, bold=True)
    if st.shop_contacts:
        _run(doc.add_paragraph(), st.shop_contacts, color=theme.TEXT_MUTED)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _run(footer, " · ".join(x for x in (st.company_name, st.shop_contacts) if x), size=9, color=theme.TEXT_SOFT)
    doc.save(path)
    return Path(path)


def client_proposal_data(client: CorporateClient) -> dict:
    return {"company_name": client.company_name, "contact_person": client.contact_person,
            "contact_position": client.contact_position, "manager": client.manager,
            "fixed_price": client.fixed_price, "discount": client.discount,
            "payment_terms": client.payment_terms}


# ------------------------------------------------------------------ Excel: список получателей
TEMPLATE_HEADERS = ["ФИО", "Должность", "Дата рождения", "Пол", "Телефон", "Доставка",
                    "Домашний адрес", "Категория", "Любимый букет", "Бюджет", "Примечание"]

_HEADER_SYNONYMS = {
    "full_name": ("фио", "ф и о", "сотрудник", "имя", "фамилия имя", "фамилия имя отчество", "получатель"),
    "position": ("должность", "позиция"),
    "birthday": ("дата рождения", "день рождения", "др", "дата", "birthday"),
    "gender": ("пол",),
    "phone": ("телефон", "тел", "мобильный", "phone"),
    "delivery_kind": ("доставка", "куда доставлять", "место доставки"),
    "home_address": ("домашний адрес", "адрес домой", "адрес"),
    "category": ("категория", "тип"),
    "preferred_bouquet": ("любимый букет", "букет", "предпочтения"),
    "preferred_budget": ("бюджет", "сумма"),
    "notes": ("примечание", "заметки", "комментарий"),
}


def _norm(text) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[.:*,;()_\-/]", " ", str(text or "").lower())).strip()


def recipients_template_xlsx(path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Получатели"
    _table(ws, 1, TEMPLATE_HEADERS, [])
    _autosize(ws, min_width=14)
    example = wb.create_sheet("Пример заполнения")
    _table(example, 1, TEMPLATE_HEADERS, [
        ["Иванова Мария Сергеевна", "Главный бухгалтер", "15.05.1985", "Ж", "+7 900 000-00-01", "Офис", "",
         "Сотрудник", "Розы", 40, "Аллергия на лилии"],
        ["Петров Алексей", "Директор", "03.11", "М", "", "Домой", "ул. Садовая, 5, кв. 12", "Руководитель",
         "", "", "Год рождения неизвестен — достаточно дня и месяца"]])
    _autosize(example, min_width=14)
    wb.save(path)
    return Path(path)


@dataclass
class ImportResult:
    added: int = 0
    skipped_existing: int = 0
    no_gender: int = 0
    errors: list[str] = field(default_factory=list)


def _parse_birthday(value) -> tuple[date | None, bool]:
    """→ (дата, год известен). Дата без года получает условный високосный 2000."""
    if value in (None, ""):
        return None, True
    if isinstance(value, datetime):
        return value.date(), True
    if isinstance(value, date):
        return value, True
    if isinstance(value, (int, float)) and 1 < float(value) < 80000:       # серийный номер Excel
        return (datetime(1899, 12, 30) + timedelta(days=float(value))).date(), True
    text = str(value).strip()
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", text)
    if m:
        d, mo, y = map(int, m.groups())
        return date(y, mo, d), True
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?", text)
    if m:
        y, mo, d = map(int, m.groups())
        return date(y, mo, d), True
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})\.?", text)
    if m:
        d, mo = map(int, m.groups())
        return date(2000, mo, d), False
    raise ValueError(f"не удалось распознать дату «{text}»")


def _parse_gender(value) -> str | None:
    t = _norm(value)
    if t in ("ж", "жен", "женский", "female", "f"):
        return "female"
    if t in ("м", "муж", "мужской", "male", "m"):
        return "male"
    return None


def _parse_category(value) -> str:
    t = _norm(value)
    if t.startswith("рук"):
        return "Руководитель"
    if t.startswith("парт"):
        return "Партнёр"
    return RECIPIENT_CATEGORIES[0]


def _parse_money(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ".").replace(" ", "").replace(" ", ""))
    except ValueError:
        raise ValueError(f"не удалось распознать сумму «{value}»")


def import_recipients(session, client_id: int, path) -> ImportResult:
    """Загружает получателей из Excel. Существующих (по ФИО) не трогает. Ошибки — по строкам."""
    client = session.get(CorporateClient, client_id)
    if client is None:
        raise ValueError("Компания не найдена")
    wb = load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))

    header_idx, columns = None, {}
    for i, row in enumerate(rows[:15]):
        found = {}
        for c, cell in enumerate(row):
            norm = _norm(cell)
            for field_name, names in _HEADER_SYNONYMS.items():
                if norm in names and field_name not in found.values():
                    found[c] = field_name
                    break
        if "full_name" in found.values():
            header_idx, columns = i, found
            break
    res = ImportResult()
    if header_idx is None:
        res.errors.append("Не найден столбец «ФИО». Скачайте шаблон и заполните его.")
        return res

    # запросом, а не client.employees: список в сессии мог устареть после предыдущей загрузки
    existing = {name.casefold() for (name,) in session.query(CorporateEmployee.full_name)
                .filter(CorporateEmployee.client_id == client_id)}
    for offset, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        values = {name: row[c] if c < len(row) else None for c, name in columns.items()}
        if all(v in (None, "") for v in values.values()):
            continue
        name = str(values.get("full_name") or "").strip()
        if not name:
            res.errors.append(f"Строка {offset}: не указано ФИО")
            continue
        if name.casefold() in existing:
            res.skipped_existing += 1
            continue
        try:
            birthday, year_known = _parse_birthday(values.get("birthday"))
            budget = _parse_money(values.get("preferred_budget"))
        except ValueError as exc:
            res.errors.append(f"Строка {offset} ({name}): {exc}")
            continue
        kind_raw = _norm(values.get("delivery_kind"))
        delivery_kind = "Домой" if kind_raw.startswith("дом") else "Офис"
        gender = _parse_gender(values.get("gender"))
        if not gender:
            res.no_gender += 1
        session.add(CorporateEmployee(
            client_id=client_id, full_name=name,
            position=str(values.get("position") or "").strip() or None,
            category=_parse_category(values.get("category")), gender=gender,
            birthday=birthday, birth_year_known=year_known,
            phone=str(values.get("phone") or "").strip() or None,
            delivery_kind=delivery_kind,
            home_address=str(values.get("home_address") or "").strip() or None,
            preferred_bouquet=str(values.get("preferred_bouquet") or "").strip() or None,
            preferred_budget=budget, with_card=True, is_active=True,
            notes=str(values.get("notes") or "").strip() or None))
        existing.add(name.casefold())
        res.added += 1
    session.flush()
    return res
