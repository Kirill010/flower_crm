"""Тесты экспорта (Excel, Word) и импорта списка получателей."""
from datetime import date, datetime

from docx import Document
from openpyxl import Workbook, load_workbook

import exports
from models import CorporateClient, CorporateEmployee
from services import AppSettings, fmt_money, generate_monthly_invoices
from test_services import make_client, make_emp, make_order


def _rows(path, sheet=None):
    wb = load_workbook(path)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    return [list(r) for r in ws.iter_rows(values_only=True)]


def _all_text(doc):
    """Текст документа Word: абзацы и ячейки таблиц (шапка и врезка лежат в таблицах)."""
    parts = [p.text for p in doc.paragraphs]
    parts += [cell.text for t in doc.tables for row in t.rows for cell in row.cells]
    return "\n".join(parts)


def _terms_table(doc):
    return next(t for t in doc.tables if any(r.cells[0].text == "Персональный менеджер" for r in t.rows))


# ------------------------------------------------------------------ заказы и лист доставки
def _order_rows():
    return [
        {"id": 2, "delivery_date": date(2026, 11, 5), "delivery_time": "14:00", "company": "Б", "recipient": "Борис",
         "phone": "2", "address": "ул. Б", "bouquet": "Тюльпаны", "card_text": "С ДР!", "gift": "Сладости",
         "amount": 40.0, "status": "Новый", "is_trial": True},
        {"id": 1, "delivery_date": date(2026, 11, 5), "delivery_time": "09:30", "company": "А", "recipient": "Анна",
         "phone": "1", "address": "ул. А", "bouquet": "Розы", "amount": 35.0, "status": "Готов"},
        {"id": 3, "delivery_date": date(2026, 11, 5), "delivery_time": "", "company": "В", "recipient": "Без времени",
         "amount": 1, "status": "Новый"},
        {"id": 4, "delivery_date": date(2026, 11, 5), "delivery_time": "10:00", "company": "Г", "recipient": "Отмена",
         "amount": 1, "status": "Отменён"},
        {"id": 5, "delivery_date": date(2026, 11, 6), "delivery_time": "10:00", "company": "Д", "recipient": "Другой день",
         "amount": 1, "status": "Новый"},
    ]


def test_orders_export(tmp_path):
    path = exports.export_orders_xlsx(tmp_path / "o.xlsx", _order_rows())
    rows = _rows(path)
    assert rows[0][:5] == ["№", "Дата доставки", "Время", "Компания", "Получатель"]
    assert len(rows) == 6 and rows[1][4] == "Борис" and rows[1][14] == "да"


def test_delivery_sheet_sorted_by_time_without_cancelled(tmp_path):
    path = exports.export_delivery_sheet_xlsx(tmp_path / "d.xlsx", _order_rows(), date(2026, 11, 5), "Цветы")
    rows = _rows(path)
    assert "05.11.2026" in rows[0][0] and "Цветы" in rows[0][0]
    assert rows[1][0] == "Заказов: 3"
    people = [r[1] for r in rows[4:]]
    assert people == ["Анна", "Борис", "Без времени"]                 # по времени; без времени — в конце
    assert rows[5][6] == "С ДР!; Сладости"


# ------------------------------------------------------------------ счёт и отчёты
def test_invoice_export(session, tmp_path):
    c = make_client(session, "ООО Плательщик", contract_number="Д-7", payment_terms="Раз в месяц по счёту")
    e = make_emp(session, c, "Анна", date(1990, 1, 1))
    make_order(session, c, 40, date(2026, 10, 5), emp=e, recipient_name="Анна", occasion="День рождения")
    make_order(session, c, 35, date(2026, 10, 9), recipient_name="Борис", occasion="8 Марта")
    inv = generate_monthly_invoices(session, 2026, 10, today=date(2026, 11, 2))[0]
    data = exports.invoice_export_data(session, inv.id)
    assert data["number"] == "СЧ-202610-001" and data["total"] == 75 and len(data["lines"]) == 2

    rows = _rows(exports.export_invoice_xlsx(tmp_path / "i.xlsx", data))
    flat = " | ".join(str(v) for r in rows for v in r if v is not None)
    assert "Счёт № СЧ-202610-001 от 02.11.2026" in flat and "ООО Плательщик" in flat and "Д-7" in flat
    assert "16.11.2026" in flat and rows[-1][3] == "Итого:" and rows[-1][4] == 75

    ws = load_workbook(tmp_path / "i.xlsx").worksheets[0]                  # фирменное оформление
    assert ws["A1"].font.name == "Georgia" and ws["A1"].font.color.rgb.endswith("35492F")
    assert len(ws._images) == 1                                            # эмблема в углу счёта
    header = next(c for row in ws.iter_rows() for c in row if c.value == "Дата")
    assert header.fill.fgColor.rgb.endswith("EDE4D3") and header.font.color.rgb.endswith("35492F")


def test_manual_invoice_without_orders_exports_one_line(session, tmp_path):
    from models import Invoice
    c = make_client(session)
    inv = Invoice(client_id=c.id, number="РУЧ-1", issue_date=date(2026, 11, 1), amount=500, description="Оформление офиса")
    session.add(inv)
    session.flush()
    data = exports.invoice_export_data(session, inv.id)
    assert data["lines"][0]["amount"] == 500 and data["lines"][0]["occasion"] == "Оформление офиса"


def test_report_export(tmp_path):
    monthly = [{"label": "Октябрь 2026", "clients": 3, "orders": 20, "delivered": 18, "revenue": 630.0,
                "forecast": 700.0, "plan": 5250.0, "plan_pct": 12.0, "avg_check": 35.0}]
    clients = [{"company": "А", "orders": 5, "revenue": 175.0, "forecast": 200.0, "invoiced": 175.0, "debt": 0.0}]
    path = exports.export_report_xlsx(tmp_path / "r.xlsx", monthly, clients, "€")
    assert _rows(path, "По месяцам")[1][:4] == ["Октябрь 2026", 3, 20, 18]
    assert _rows(path, "По компаниям")[1][0] == "А"


# ------------------------------------------------------------------ коммерческое предложение
def test_proposal_docx_contains_offer_and_terms(tmp_path):
    st = AppSettings(company_name="Цветы и подарки", shop_contacts="тел. +7 900 000-00-00", currency="€")
    client = {"company_name": "ООО Ромашка", "contact_person": "Иван Петров", "contact_position": "HR",
              "manager": "Мария", "fixed_price": 40, "discount": 5, "payment_terms": "Раз в месяц по счёту"}
    path = exports.export_proposal_docx(tmp_path / "kp.docx", st, client, today=date(2026, 11, 7))
    doc = Document(path)
    text = _all_text(doc)
    assert "Коммерческое предложение" in text and "Для: ООО Ромашка — Иван Петров, HR" in text
    assert "Вам достаточно один раз предоставить список дат" in text
    assert "Цветы и подарки" in text and "тел. +7 900 000-00-00" in text
    table = {r.cells[0].text: r.cells[1].text for r in _terms_table(doc).rows}
    assert table["Персональный менеджер"] == "Мария"
    assert "40" in table["Стоимость стандартного букета"] and table["Скидка по договору"] == "5%"
    assert "30%" in table["Пробное поздравление"]


def test_generic_proposal_without_client(tmp_path):
    path = exports.export_proposal_docx(tmp_path / "kp.docx", AppSettings(), None, today=date(2026, 11, 7))
    table = {r.cells[0].text: r.cells[1].text for r in _terms_table(Document(path)).rows}
    assert fmt_money(3500, "₽") in table["Стоимость стандартного букета"]   # цена по умолчанию из настроек


def test_proposal_uses_dianthus_brand(tmp_path):
    from docx.shared import RGBColor
    path = exports.export_proposal_docx(tmp_path / "kp.docx", AppSettings(), None, today=date(2026, 11, 7))
    doc = Document(path)
    assert len(doc.inline_shapes) == 1                                   # эмблема в шапке
    text = _all_text(doc)
    assert "Диантус" in text and "КОРПОРАТИВНЫЕ ПОЗДРАВЛЕНИЯ" in text
    h1 = doc.styles["Heading 1"].font
    assert h1.name == "Georgia" and h1.color.rgb == RGBColor.from_string("35492F")
    xml = "".join(cell._tc.xml for t in doc.tables for r in t.rows for cell in r.cells)
    assert 'w:fill="ECF1E8"' in xml        # врезка с ключевым предложением
    assert 'w:fill="F5EFE4"' in xml        # столбец названий в таблице условий
    assert 'w:color="4A6741"' in xml       # зелёная полоса слева у врезки
    assert 'w:color="C97B4A"' in doc.element.xml          # медная линия под шапкой


# ------------------------------------------------------------------ импорт получателей
def _make_import_file(path, with_title=True):
    wb = Workbook()
    ws = wb.active
    if with_title:
        ws.append(["Список сотрудников компании", None, None])
        ws.append([])
    ws.append(["ФИО", "Должность", "Дата рождения", "Пол", "Телефон", "Доставка", "Адрес", "Категория", "Бюджет"])
    ws.append(["Иванова Мария", "Бухгалтер", datetime(1985, 5, 15), "Ж", "+7 1", "Офис", None, "Сотрудник", "45,5"])
    ws.append(["Петров Алексей", "Директор", "03.11", "муж", None, "Домой", "ул. Садовая, 5", "Руководитель", None])
    ws.append(["Сидоров Олег", None, "21.07.1990", None, None, None, None, "Партнёр", None])
    ws.append([None, "Без имени", "01.01.1990"])
    ws.append(["Кривая Дата", None, "завтра", "ж"])
    ws.append(["Кривая Сумма", None, "01.02.1990", "ж", None, None, None, None, "много"])
    ws.append(["иванова мария", None, "01.01.1990"])                      # дубликат по ФИО
    ws.append([None, None, None])                                          # пустая строка
    wb.save(path)


def test_import_recipients(session, tmp_path):
    c = make_client(session)
    path = tmp_path / "list.xlsx"
    _make_import_file(path)
    res = exports.import_recipients(session, c.id, path)
    assert (res.added, res.skipped_existing, res.no_gender) == (3, 1, 1)
    assert len(res.errors) == 3
    assert any("не указано ФИО" in e for e in res.errors)
    assert any("Кривая Дата" in e and "дату" in e for e in res.errors)
    assert any("Кривая Сумма" in e and "сумму" in e for e in res.errors)

    people = {e.full_name: e for e in session.query(CorporateEmployee).filter_by(client_id=c.id)}
    maria, alexey, oleg = people["Иванова Мария"], people["Петров Алексей"], people["Сидоров Олег"]
    assert (maria.birthday, maria.birth_year_known, maria.gender, maria.preferred_budget) == \
           (date(1985, 5, 15), True, "female", 45.5)
    assert (alexey.birthday, alexey.birth_year_known, alexey.gender) == (date(2000, 11, 3), False, "male")
    assert (alexey.delivery_kind, alexey.home_address, alexey.category) == ("Домой", "ул. Садовая, 5", "Руководитель")
    assert (oleg.birthday, oleg.gender, oleg.category, oleg.delivery_kind) == (date(1990, 7, 21), None, "Партнёр", "Офис")
    assert maria.with_card is True and maria.is_active is True

    again = exports.import_recipients(session, c.id, path)               # повторная загрузка не плодит дубли
    assert again.added == 0 and again.skipped_existing >= 3


def test_import_header_on_first_row_and_template(session, tmp_path):
    c = make_client(session)
    path = tmp_path / "plain.xlsx"
    _make_import_file(path, with_title=False)
    assert exports.import_recipients(session, c.id, path).added == 3

    tpl = exports.recipients_template_xlsx(tmp_path / "tpl.xlsx")
    wb = load_workbook(tpl)
    assert wb.sheetnames == ["Получатели", "Пример заполнения"]
    assert [cell.value for cell in wb["Получатели"][1]] == exports.TEMPLATE_HEADERS
    assert wb["Получатели"].max_row == 1                                  # пустой шаблон: пример на другом листе
    empty = make_client(session, "Пустая")
    assert exports.import_recipients(session, empty.id, tpl).added == 0   # пустой шаблон безопасен
    example = exports.import_recipients(session, empty.id, tpl)           # (лист примера не читается)
    assert example.errors == []


def test_import_without_name_column(session, tmp_path):
    c = make_client(session)
    wb = Workbook()
    wb.active.append(["Телефон", "Дата"])
    wb.active.append(["1", "01.01.1990"])
    path = tmp_path / "bad.xlsx"
    wb.save(path)
    res = exports.import_recipients(session, c.id, path)
    assert res.added == 0 and "ФИО" in res.errors[0]
    assert session.query(CorporateClient).count() == 1


def test_safe_filename():
    assert exports.safe_filename('КП: ООО "Ромашка"/1') == "КП_ ООО _Ромашка_1"
