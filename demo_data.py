"""Демонстрационные данные для режима `python crm.py --demo` (отдельная база demo.db).

Все компании и люди вымышлены. Даты считаются от «сегодня», чтобы календарь
и дашборд были заполнены в любой день.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from models import Activity, CorporateClient, CorporateEmployee, Invoice, Order
from services import (card_text_for, generate_monthly_invoices, load_settings, log_activity,
                      recipient_address, shift_month)

COMPANIES = [
    # название, сегмент, стадия, км, контакт, должность контакта, цена, адрес
    ("Юридическая компания «Паритет»", "Юридическая компания", "Клиент", 4.5, "Анна Крылова",
     "HR-менеджер", 4000, "ул. Правды, 12, офис 301"),
    ("Аудит-Консалт", "Бухгалтерская фирма", "Клиент", 8, "Игорь Лавров", "Руководитель", 3500,
     "пр-т Мира, 45, оф. 12"),
    ("Медицинский центр «Здоровье+»", "Медицинский центр", "Клиент", 12, "Елена Орлова",
     "Главная медсестра", 3500, "ул. Лесная, 7"),
    ("Банк «Северный путь»", "Банк", "Клиент", 6, "Дмитрий Белов", "Начальник отдела кадров", 4500,
     "ул. Банковская, 3"),
    ("IT-студия «Пиксель»", "IT-компания", "Клиент", 15, "Олег Громов", "Директор", 3500,
     "Технопарк, корп. 2, 5 этаж"),
    ("Завод «Прогресс»", "Производственное предприятие", "Пробное поздравление", 22, "Наталья Ким",
     "HR-директор", 0, "Промзона, 14"),
    ("Юридическая группа «Вердикт»", "Юридическая компания", "Встреча", 9, "Сергей Жуков",
     "Управляющий партнёр", 0, "ул. Гоголя, 21"),
    ("Бухгалтерия-Сервис", "Бухгалтерская фирма", "КП отправлено", 17, "Ирина Фомина",
     "Директор", 0, "ул. Новая, 8"),
    ("Клиника «Доктор Рядом»", "Медицинский центр", "Лид", 25, "", "", 0, "ул. Южная, 30"),
    ("ТехноПарк Софт", "IT-компания", "Отказ", 28, "Павел Назаров", "Руководитель", 0,
     "ул. Заводская, 2"),
]

MALE_NAMES = ["Алексей", "Сергей", "Дмитрий", "Андрей", "Михаил", "Игорь", "Олег", "Николай"]
FEMALE_NAMES = ["Мария", "Екатерина", "Ольга", "Наталья", "Анна", "Татьяна", "Елена", "Ирина"]
SURNAMES = ["Иванов", "Петров", "Сидоров", "Кузнецов", "Смирнов", "Попов", "Васильев", "Новиков",
            "Морозов", "Волков", "Соловьёв", "Козлов", "Лебедев", "Орлов", "Зайцев", "Павлов"]
POSITIONS = ["Менеджер", "Бухгалтер", "Юрист", "Аналитик", "Секретарь", "Специалист", "Администратор",
             "Руководитель отдела", "Врач", "Инженер"]
BOUQUETS = ["Розы", "Тюльпаны", "Пионы", "Орхидеи", "Хризантемы", "Корпоративный букет", "Гербера"]
MANAGERS = ["Мария", "Алексей"]
# дни от сегодня, на которые назначаем дни рождения: календарь на 2 недели будет живым
NEAR_BIRTHDAYS = [0, 1, 2, 3, 3, 5, 6, 8, 10, 12, 13, 20, 27]


def _person(rng: random.Random, used: set[str]) -> tuple[str, str]:
    while True:
        female = rng.random() < 0.55
        surname = rng.choice(SURNAMES) + ("а" if female else "")
        name = rng.choice(FEMALE_NAMES if female else MALE_NAMES)
        full = f"{surname} {name}"
        if full not in used:
            used.add(full)
            return full, "female" if female else "male"


def _history_order(st, client, emp, day: date, status: str, rng: random.Random) -> Order:
    price = emp.preferred_budget or client.fixed_price or st.default_price
    return Order(
        client_id=client.id, employee_id=emp.id, order_date=day - timedelta(days=3), event_date=day,
        delivery_date=day, delivery_time=rng.choice(["09:30", "10:00", "11:00", "12:30", "15:00"]),
        occasion="День рождения", service="Букет", bouquet=emp.preferred_bouquet or "Корпоративный букет",
        recipient_name=emp.full_name, recipient_phone=emp.phone,
        address=recipient_address(client, emp, []), with_card=bool(emp.with_card),
        card_text=card_text_for(st, emp.full_name, client.company_name, "День рождения"),
        amount=float(price), status=status, auto_created=rng.random() < 0.7)


def seed_demo(session, today: date | None = None, seed: int = 7) -> None:
    today = today or date.today()
    rng = random.Random(seed)
    st = load_settings(session)
    used: set[str] = set()
    near = list(NEAR_BIRTHDAYS)
    rng.shuffle(near)

    clients: list[CorporateClient] = []
    for i, (name, segment, stage, km, contact, position, price, address) in enumerate(COMPANIES):
        c = CorporateClient(
            company_name=name, segment=segment, stage=stage, distance_km=km, contact_person=contact,
            contact_position=position, phone=f"+7 (900) 100-{10 + i:02d}-{20 + i:02d}",
            email=f"office{i + 1}@example.com", address=address, fixed_price=float(price),
            manager=MANAGERS[i % 2], payment_terms="Раз в месяц по счёту", is_active=True,
            notes="Демо-данные." if i == 0 else None)
        if stage == "Клиент":
            c.contract_number = f"Д-{2026}/{i + 1:02d}"
            c.contract_start = today - timedelta(days=rng.randint(60, 300))
            c.contract_end = c.contract_start + timedelta(days=364)
        session.add(c)
        clients.append(c)
    session.flush()

    # один клиент — с договором, который скоро закончится (напоминание о продлении)
    clients[3].contract_end = today + timedelta(days=21)

    people: dict[int, list[CorporateEmployee]] = {}
    for c in clients:
        count = {"Клиент": 6, "Пробное поздравление": 4}.get(c.stage, 2)
        staff = []
        for k in range(count):
            full, gender = _person(rng, used)
            if near and c.stage in ("Клиент", "Пробное поздравление") and rng.random() < 0.7:
                offset = near.pop()
                birthday = (today + timedelta(days=offset)).replace(year=rng.randint(1966, 1999))
            else:
                birthday = date(rng.randint(1966, 1999), rng.randint(1, 12), rng.randint(1, 28))
            home = k % 5 == 4
            staff.append(CorporateEmployee(
                client_id=c.id, full_name=full, gender=gender, birthday=birthday,
                position="Директор" if k == 0 else rng.choice(POSITIONS),
                category="Руководитель" if k == 0 else "Сотрудник",
                phone=f"+7 (900) 2{rng.randint(10, 99)}-{rng.randint(10, 99)}-{rng.randint(10, 99)}",
                delivery_kind="Домой" if home else "Офис",
                home_address=f"ул. Садовая, {rng.randint(1, 80)}, кв. {rng.randint(1, 120)}" if home else None,
                preferred_bouquet=rng.choice(BOUQUETS) if k % 2 == 0 else None,
                preferred_budget=float(rng.choice([4500, 5000, 6000])) if k == 0 else None,
                with_card=True, is_active=True,
                notes="Аллергия на лилии" if k == 2 else None))
        session.add_all(staff)
        people[c.id] = staff
    session.flush()

    # история: доставленные заказы за 3 прошлых месяца и часть текущего
    for c in clients:
        if c.stage != "Клиент":
            continue
        for back in (3, 2, 1):
            year, month = shift_month(today.year, today.month, -back)
            for _ in range(rng.randint(2, 5)):
                day = date(year, month, rng.randint(1, 27))
                session.add(_history_order(st, c, rng.choice(people[c.id]), day, "Доставлен", rng))
        for _ in range(rng.randint(1, 3)):
            day = today - timedelta(days=rng.randint(1, max(1, today.day - 1)) if today.day > 1 else 1)
            if day.month == today.month:
                session.add(_history_order(st, c, rng.choice(people[c.id]), day, "Доставлен", rng))
    # пробное поздравление в компании «Завод»
    trial_client = clients[5]
    session.add(_history_order(st, trial_client, people[trial_client.id][0], today + timedelta(days=2),
                               "Готовится", rng))
    session.flush()
    session.query(Order).filter(Order.client_id == trial_client.id).update({Order.is_trial: True})
    session.flush()

    # счета: за позапрошлый месяц — почти все оплачены, за прошлый — висят
    y2, m2 = shift_month(today.year, today.month, -2)
    y1, m1 = shift_month(today.year, today.month, -1)
    for inv in generate_monthly_invoices(session, y2, m2, today=date(y2, m2, 28) + timedelta(days=5)):
        inv.paid = inv.client_id != clients[1].id            # одна компания не заплатила — просрочка
        inv.paid_date = min(inv.due_date - timedelta(days=3), today) if inv.paid else None
    for inv in generate_monthly_invoices(session, y1, m1, today=date(y1, m1, 28) + timedelta(days=3)):
        inv.paid = inv.client_id == clients[0].id
        inv.paid_date = min(inv.due_date - timedelta(days=2), today) if inv.paid else None
    session.add(Invoice(client_id=clients[4].id, number="СЧ-ДЕМО-1", issue_date=today - timedelta(days=3),
                        due_date=today + timedelta(days=11), amount=25000.0, paid=False,
                        description="Цветочное оформление офиса"))

    # воронка: контакты с компаниями-лидами и следующие шаги
    log_activity(session, clients[5].id, "Визит / встреча", "Познакомились с HR-директором", today - timedelta(days=12))
    log_activity(session, clients[5].id, "Пробное поздравление", "Согласовали пробное поздравление со скидкой",
                 today - timedelta(days=5), next_date=today + timedelta(days=3))
    log_activity(session, clients[6].id, "Визит / встреча", "Показали каталог, ждут решение партнёров",
                 today - timedelta(days=4), next_date=today + timedelta(days=1))
    log_activity(session, clients[7].id, "КП отправлено", "Отправили КП на почту", today - timedelta(days=6),
                 next_date=today - timedelta(days=1))
    session.add(Activity(client_id=clients[8].id, date=today - timedelta(days=2), kind="Звонок",
                         note="Список компаний в радиусе 25 км — позвонить в понедельник",
                         next_date=today + timedelta(days=4), done=False))
    session.flush()
