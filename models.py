"""Модели данных CRM «Корпоративные поздравления».

Основа — ТЗ «Корпоративное обслуживание компаний по доставке цветов и подарков».
Имена старых таблиц и колонок сохранены: новые поля только добавляются,
поэтому прежняя база flower.db открывается без потери данных (см. database.migrate).
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (Boolean, Column, Date, DateTime, Float, ForeignKey, Index,
                        Integer, String, Text)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

# ---------------------------------------------------------------- справочники
# Воронка привлечения из ТЗ: список компаний → КП → визит → пробное поздравление → годовой договор
STAGES = ["Лид", "КП отправлено", "Встреча", "Пробное поздравление", "Клиент", "Отказ"]
CLIENT_STAGE = "Клиент"          # по этой стадии идёт обслуживание и автозаказы
TRIAL_STAGE = "Пробное поздравление"

# Целевая аудитория из ТЗ
SEGMENTS = ["Юридическая компания", "Бухгалтерская фирма", "Медицинский центр",
            "Банк", "IT-компания", "Производственное предприятие", "Другое"]

ORDER_STATUSES = ["Новый", "Готовится", "Готов", "В пути", "Доставлен", "Отменён"]
STATUS_DONE = "Доставлен"
STATUS_CANCELLED = "Отменён"

# Услуги из ТЗ: букеты, подарочные наборы, оформление офиса
SERVICES = ["Букет", "Подарочный набор", "Оформление офиса"]

OCCASIONS = ["День рождения", "Юбилей", "8 Марта", "23 Февраля", "Новый год",
             "Профессиональный праздник", "Руководитель / партнёр",
             "Корпоративное мероприятие", "Другое"]
BIRTHDAY_OCCASIONS = ("День рождения", "Юбилей")

RECIPIENT_CATEGORIES = ["Сотрудник", "Руководитель", "Партнёр"]
DELIVERY_KINDS = ["Офис", "Домой"]
GENDERS = [("", "не указан"), ("female", "женский"), ("male", "мужской")]
HOLIDAY_AUDIENCES = [("all", "все"), ("female", "только женщины"), ("male", "только мужчины")]
ACTIVITY_KINDS = ["Звонок", "Письмо", "КП отправлено", "Визит / встреча",
                  "Пробное поздравление", "Договор подписан", "Другое"]


class CorporateClient(Base):
    """Компания-клиент или потенциальный клиент (стадия воронки в поле stage)."""
    __tablename__ = "corporate_clients"

    id = Column(Integer, primary_key=True)
    company_name = Column(String(200), nullable=False)
    contact_person = Column(String(150))
    contact_position = Column(String(100))      # HR-менеджер, руководитель…
    phone = Column(String(30))
    email = Column(String(120))
    address = Column(String(250))                # адрес офиса — доставка по умолчанию
    segment = Column(String(60))
    distance_km = Column(Float)                  # до магазина (план: радиус 20–30 км)
    stage = Column(String(40), default="Лид")
    manager = Column(String(100))                # персональный менеджер
    contract_number = Column(String(50))
    contract_start = Column(Date)
    contract_end = Column(Date)
    payment_terms = Column(String(120), default="Раз в месяц по счёту")
    fixed_price = Column(Float, default=0.0)     # корпоративная цена букета; 0 = цена по умолчанию
    discount = Column(Float, default=0.0)        # скидка по договору, %
    notes = Column(Text)
    is_active = Column(Boolean, default=True)    # False = в архиве
    created_at = Column(DateTime, default=datetime.now)

    employees = relationship("CorporateEmployee", back_populates="client",
                             cascade="all, delete-orphan",
                             order_by="CorporateEmployee.full_name")
    orders = relationship("Order", back_populates="client")
    invoices = relationship("Invoice", back_populates="client")
    activities = relationship("Activity", back_populates="client",
                              cascade="all, delete-orphan")


class CorporateEmployee(Base):
    """Получатель поздравлений: сотрудник, руководитель или партнёр компании."""
    __tablename__ = "corporate_employees"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("corporate_clients.id"))
    full_name = Column(String(150), nullable=False)
    position = Column(String(100))
    category = Column(String(30), default="Сотрудник")
    gender = Column(String(10))                  # 'female' | 'male' | пусто
    birthday = Column(Date)
    birth_year_known = Column(Boolean, default=True)   # False: год — условный (2000)
    phone = Column(String(30))
    delivery_kind = Column(String(20), default="Офис")  # Офис | Домой
    home_address = Column(String(250))
    preferred_bouquet = Column(String(150))
    preferred_budget = Column(Float)             # индивидуальная цена; пусто/0 = по договору
    with_card = Column(Boolean, default=True)
    notes = Column(Text)                         # аллергии, пожелания
    is_active = Column(Boolean, default=True)

    client = relationship("CorporateClient", back_populates="employees")


class Invoice(Base):
    """Счёт за период (оплата раз в месяц по счёту)."""
    __tablename__ = "invoices"
    __table_args__ = (Index("ix_invoices_number", "number", unique=True),)

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("corporate_clients.id"))
    number = Column(String(30))
    issue_date = Column(Date, default=date.today)
    due_date = Column(Date)
    period_start = Column(Date)
    period_end = Column(Date)
    amount = Column(Float, default=0.0)
    paid = Column(Boolean, default=False)
    paid_date = Column(Date)
    description = Column(Text)

    client = relationship("CorporateClient", back_populates="invoices")
    orders = relationship("Order", back_populates="invoice")


class Order(Base):
    """Одно поздравление: кому, когда, куда, что и за сколько."""
    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_source_key", "source_key", unique=True),)

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("corporate_clients.id"))
    employee_id = Column(Integer, ForeignKey("corporate_employees.id"))  # пусто — заказ на компанию
    order_date = Column(Date, default=date.today)
    event_date = Column(Date)                    # дата события (день рождения, праздник)
    delivery_date = Column(Date, nullable=False)
    delivery_time = Column(String(5))            # «ЧЧ:ММ»
    occasion = Column(String(100))
    service = Column(String(40), default="Букет")
    bouquet = Column(String(150))
    recipient_name = Column(String(150))         # копия на момент заказа
    recipient_phone = Column(String(30))
    address = Column(String(250))
    with_card = Column(Boolean, default=False)
    card_text = Column(Text)
    gift = Column(String(200))
    is_trial = Column(Boolean, default=False)    # пробное поздравление со скидкой
    amount = Column(Float, default=0.0)
    status = Column(String(50), default="Новый")
    auto_created = Column(Boolean, default=False)
    source_key = Column(String(80))              # ключ автозаказа: защита от дублей
    invoice_id = Column(Integer, ForeignKey("invoices.id"))
    comment = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    client = relationship("CorporateClient", back_populates="orders")
    employee = relationship("CorporateEmployee")
    invoice = relationship("Invoice", back_populates="orders")


class Holiday(Base):
    """Праздник для массовых поздравлений (8 Марта, Новый год, профессиональные)."""
    __tablename__ = "holidays"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    month = Column(Integer)
    day = Column(Integer)                        # день доставки
    lead_days = Column(Integer, default=7)       # за сколько дней напоминать
    audience = Column(String(10), default="all")  # all | female | male
    segment = Column(String(60))                 # только для компаний этого сегмента
    is_active = Column(Boolean, default=True)


class Activity(Base):
    """Журнал контактов с компанией: звонок, визит, КП… и следующий шаг."""
    __tablename__ = "activities"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("corporate_clients.id"), nullable=False)
    date = Column(Date, default=date.today)
    kind = Column(String(40))
    note = Column(Text)
    next_date = Column(Date)                     # когда вернуться к компании
    done = Column(Boolean, default=False)

    client = relationship("CorporateClient", back_populates="activities")


class AutoLog(Base):
    """Какие автозаказы уже создавались. Удалённый заказ заново не появится."""
    __tablename__ = "auto_log"

    id = Column(Integer, primary_key=True)
    source_key = Column(String(80), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.now)


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(50), primary_key=True)
    value = Column(Text)
