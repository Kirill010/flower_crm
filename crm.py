#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# pyinstaller --onefile --windowed --name "MuzflowersCRM" --icon=myicon.ico --hidden-import=apscheduler.schedulers.qt --hidden-import=apscheduler.executors.pool crm.py

import sys
import os
import shutil
import logging
import uuid
from datetime import date, datetime, timedelta
from contextlib import contextmanager

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QTableWidget, QTableWidgetItem, QPushButton, QLabel,
    QLineEdit, QComboBox, QDateEdit, QTextEdit, QDialog, QFormLayout,
    QMessageBox, QFileDialog, QHeaderView, QSpinBox, QDoubleSpinBox,
    QGroupBox, QCheckBox, QAction, QListWidget, QListWidgetItem,
    QShortcut, QSplitter, QProgressBar, QFrame
)
from PyQt5.QtCore import Qt, QDate, QTimer
from PyQt5.QtGui import QColor, QKeySequence, QPixmap, QFont

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Date, Boolean,
    Text, ForeignKey, DateTime, func, UniqueConstraint, Index
)
from sqlalchemy.orm import sessionmaker, relationship, scoped_session, declarative_base
from sqlalchemy.exc import SQLAlchemyError

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.qt import QtScheduler

# --- 1. Настройка логирования ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("muzflowers.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MuzflowersCRM")

# --- 2. Конфигурация ---
DB_PATH = 'muzflowers.db'
BACKUP_DIR = 'backups'
MEDIA_DIR = 'media'
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(MEDIA_DIR, exist_ok=True)
os.makedirs(os.path.join(MEDIA_DIR, 'products'), exist_ok=True)

# Настройка: сколько дней можно хранить скоропортящийся товар
PERISHABLE_DAYS = 3  # можно изменить через настройки позже

# --- 3. Стили интерфейса (улучшенный дизайн) ---
STYLE = """
/* Основные цвета: свежий, светлый, с акцентами розового и зелёного */
QMainWindow, QDialog {
    background-color: #FDFBF7;
    color: #333333;
    font-family: 'Segoe UI', 'Arial', sans-serif;
}

/* Вкладки */
QTabWidget::pane {
    border: 2px solid #E8E0D5;
    background-color: #FFFFFF;
    border-radius: 10px;
    margin-top: -1px;
}
QTabBar::tab {
    background-color: #F4F0EA;
    color: #555555;
    padding: 8px 16px;
    border: 2px solid #E8E0D5;
    border-bottom: none;
    border-radius: 10px 10px 0 0;
    margin-right: 3px;
    font-weight: bold;
    font-size: 12px;
}
QTabBar::tab:selected {
    background-color: #F38BA8;
    color: #FFFFFF;
    border-color: #F38BA8;
}
QTabBar::tab:hover {
    background-color: #FADADD;
    color: #333333;
}

/* Таблицы - улучшенный дизайн с рамками */
QTableWidget {
    background-color: #FFFFFF;
    color: #333333;
    gridline-color: #E8E0D5;
    alternate-background-color: #F9F7F4;
    border: 2px solid #E8E0D5;
    border-radius: 8px;
    selection-background-color: #FADADD;
    selection-color: #333333;
}
QTableWidget::item {
    padding: 8px 12px;
    border: 1px solid #F0EBE5;
}
QTableWidget::item:selected {
    background-color: #FADADD;
    color: #333333;
}
QHeaderView::section {
    background-color: #F38BA8;
    color: #FFFFFF;
    padding: 12px 16px;
    border: none;
    font-weight: bold;
    font-size: 13px;
}
QHeaderView::section:horizontal {
    border-right: 1px solid #D45A7A;
}
QHeaderView::section:last {
    border-right: none;
}
QTableWidget QTableCornerButton::section {
    background-color: #F38BA8;
    border: none;
}

/* Кнопки */
QPushButton {
    background-color: #F38BA8;
    color: #FFFFFF;
    border: none;
    padding: 10px 22px;
    border-radius: 25px;
    font-weight: bold;
    font-size: 14px;
}
QPushButton:hover {
    background-color: #E57393;
}
QPushButton:pressed {
    background-color: #D45A7A;
}
QPushButton:disabled {
    background-color: #D0C8BE;
    color: #888888;
}
QPushButton#secondary {
    background-color: #E8E0D5;
    color: #555555;
}
QPushButton#secondary:hover {
    background-color: #D5CCC0;
}
QPushButton#success {
    background-color: #88C4A3;
}
QPushButton#danger {
    background-color: #E57373;
}
QPushButton#primary {
    background-color: #F38BA8;
}

/* Поля ввода */
QLineEdit, QComboBox, QDateEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QListWidget {
    background-color: #FFFFFF;
    color: #333333;
    border: 2px solid #E8E0D5;
    padding: 8px 14px;
    border-radius: 20px;
    font-size: 13px;
}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTextEdit:focus {
    border: 2px solid #F38BA8;
}

/* Заголовки */
QLabel {
    color: #333333;
    font-size: 13px;
}
QLabel#title {
    font-size: 28px;
    font-weight: bold;
    color: #F38BA8;
}
QLabel#subtitle {
    font-size: 14px;
    color: #888888;
}
QLabel#section-title {
    font-size: 18px;
    font-weight: bold;
    color: #F38BA8;
    padding: 10px 0;
}

/* Групповые рамки */
QGroupBox {
    border: 2px solid #E8E0D5;
    border-radius: 12px;
    margin-top: 18px;
    padding-top: 22px;
    background-color: #FFFFFF;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 15px;
    padding: 0 12px;
    color: #F38BA8;
    font-weight: bold;
    font-size: 15px;
}

/* Чекбоксы */
QCheckBox {
    color: #333333;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 20px;
    height: 20px;
    border-radius: 5px;
    border: 2px solid #D5CCC0;
}
QCheckBox::indicator:checked {
    background-color: #F38BA8;
    border: 2px solid #F38BA8;
}

/* Меню */
QMenuBar {
    background-color: #FFFFFF;
    color: #333333;
    border-bottom: 2px solid #E8E0D5;
}
QMenuBar::item:selected {
    background-color: #F38BA8;
    color: #FFFFFF;
}
QMenu {
    background-color: #FFFFFF;
    color: #333333;
    border: 1px solid #E8E0D5;
}
QMenu::item:selected {
    background-color: #FADADD;
    color: #333333;
}

/* Строка состояния */
QStatusBar {
    background-color: #F38BA8;
    color: #FFFFFF;
    font-weight: bold;
}

/* Прогресс-бар */
QProgressBar {
    border: 2px solid #D5CCC0;
    border-radius: 10px;
    text-align: center;
    background-color: #F9F7F4;
    color: #333333;
}
QProgressBar::chunk {
    background-color: #88C4A3;
    border-radius: 10px;
}

/* Карточки метрик на главной */
.metric-card {
    background-color: #FFFFFF;
    border: 2px solid #E8E0D5;
    border-radius: 16px;
    padding: 18px;
}
.metric-card QLabel {
    font-size: 14px;
    color: #888888;
}
.metric-card QLabel#value {
    font-size: 28px;
    font-weight: bold;
    color: #333333;
}
.metric-card QLabel#icon {
    font-size: 32px;
}

/* Списки */
QListWidget {
    border: 2px solid #E8E0D5;
    border-radius: 8px;
    padding: 5px;
}
QListWidget::item {
    padding: 8px 12px;
    border-radius: 6px;
}
QListWidget::item:selected {
    background-color: #FADADD;
    color: #333333;
}
QListWidget::item:hover {
    background-color: #F9F7F4;
}

/* Сплиттер */
QSplitter::handle {
    background-color: #E8E0D5;
    width: 3px;
}
"""

# --- 4. Модели базы данных ---
Base = declarative_base()

class Store(Base):
    __tablename__ = 'stores'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    address = Column(String(250))
    phone = Column(String(30))
    is_active = Column(Boolean, default=True)
    staff = relationship('Staff', back_populates='store')
    orders = relationship('Order', back_populates='store')
    inventory = relationship('InventoryItem', back_populates='store')
    expenses = relationship('Expense', back_populates='store')
    corporate_clients = relationship('CorporateClient', back_populates='store')

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    password_hash = Column(String(200), nullable=False)
    full_name = Column(String(150))
    role = Column(String(20), default='admin')
    is_active = Column(Boolean, default=True)
    staff_profile = relationship('Staff', back_populates='user', uselist=False, cascade='all, delete-orphan')

class Staff(Base):
    __tablename__ = 'staff'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), unique=True, nullable=True)
    store_id = Column(Integer, ForeignKey('stores.id'), nullable=False)
    full_name = Column(String(150), nullable=False)
    position = Column(String(50))
    phone = Column(String(30))
    salary = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)
    hire_date = Column(Date, default=date.today)
    user = relationship('User', back_populates='staff_profile')
    store = relationship('Store', back_populates='staff')

    @property
    def position_display(self):
        return {'florist': '🌸 Флорист', 'manager': '👔 Менеджер', 'admin': '👑 Директор'}.get(self.position, self.position or '—')

class Customer(Base):
    __tablename__ = 'customers'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    phone = Column(String(30))
    address = Column(String(250))
    birthday = Column(Date, nullable=True)
    notes = Column(Text)
    is_vip = Column(Boolean, default=False)
    discount = Column(Float, default=0.0)
    orders = relationship('Order', back_populates='customer')

    @property
    def total_spent(self):
        return sum(o.amount or 0 for o in self.orders if o.status == 'доставлен')

class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False)
    category = Column(String(50))
    description = Column(Text)
    composition = Column(Text)
    price = Column(Float, nullable=False)
    cost_price = Column(Float, default=0.0)
    supplier_id = Column(Integer, ForeignKey('suppliers.id'), nullable=True)
    unit = Column(String(20), default='шт')
    barcode = Column(String(50), unique=True, nullable=True)
    min_stock = Column(Float, default=0.0)
    stock = Column(Float, default=0.0)
    season = Column(String(20), default='круглый год')
    is_perishable = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    is_popular = Column(Boolean, default=False)
    is_gift_set = Column(Boolean, default=False)
    image_path = Column(String(250), nullable=True)
    supplier = relationship('Supplier')

    @property
    def margin(self):
        return (self.price or 0) - (self.cost_price or 0)

    @property
    def margin_percent(self):
        if self.cost_price and self.cost_price > 0:
            return (self.margin / self.cost_price) * 100
        return 0

class Order(Base):
    __tablename__ = 'orders'
    id = Column(Integer, primary_key=True)
    order_number = Column(String(30), unique=True)
    store_id = Column(Integer, ForeignKey('stores.id'), nullable=False)
    customer_id = Column(Integer, ForeignKey('customers.id'), nullable=True)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=True)
    corporate_client_id = Column(Integer, ForeignKey('corporate_clients.id'), nullable=True)
    order_date = Column(Date, default=date.today)
    delivery_date = Column(Date, nullable=False)
    delivery_time = Column(String(10))
    bouquet = Column(String(150), nullable=False)
    composition = Column(Text)
    quantity = Column(Integer, default=1)
    amount = Column(Float, default=0.0)
    cost_price = Column(Float, default=0.0)
    discount = Column(Float, default=0.0)
    paid = Column(Boolean, default=False)
    address = Column(String(250))
    recipient_phone = Column(String(30))
    recipient_name = Column(String(150))
    status = Column(String(30), default='новый')
    florist_id = Column(Integer, ForeignKey('staff.id'), nullable=True)
    comment = Column(Text)
    occasion = Column(String(50))
    auto_created = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    has_card = Column(Boolean, default=False)
    has_sweets = Column(Boolean, default=False)
    extra_cost = Column(Float, default=0.0)
    is_office_decor = Column(Boolean, default=False)
    photo_path = Column(String(250), nullable=True)

    store = relationship('Store', back_populates='orders')
    customer = relationship('Customer', back_populates='orders')
    product = relationship('Product')
    corporate_client = relationship('CorporateClient', back_populates='orders')
    florist = relationship('Staff', foreign_keys=[florist_id])

    @property
    def profit(self):
        return (self.amount or 0) - (self.cost_price or 0)

    @property
    def client_name(self):
        return self.customer.name if self.customer else 'Без клиента'

Index('idx_orders_store_delivery', Order.store_id, Order.delivery_date)
Index('idx_orders_status', Order.status)
Index('idx_orders_corporate', Order.corporate_client_id)

class InventoryItem(Base):
    __tablename__ = 'inventory_items'
    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, ForeignKey('stores.id'), nullable=False)
    name = Column(String(150), nullable=False)
    category = Column(String(50))
    unit = Column(String(20), default='шт')
    quantity = Column(Float, default=0.0)
    min_quantity = Column(Float, default=0.0)
    purchase_price = Column(Float, default=0.0)
    batch_number = Column(String(50))
    arrival_date = Column(Date)
    supplier_id = Column(Integer, ForeignKey('suppliers.id'), nullable=True)
    store = relationship('Store', back_populates='inventory')
    supplier = relationship('Supplier')

    @property
    def is_low_stock(self):
        return self.quantity <= self.min_quantity and self.min_quantity > 0

    @property
    def days_on_stock(self):
        if self.arrival_date:
            return (date.today() - self.arrival_date).days
        return 0

class Supplier(Base):
    __tablename__ = 'suppliers'
    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False)
    contact_person = Column(String(100))
    phone = Column(String(30))
    address = Column(String(250))
    notes = Column(Text)
    is_active = Column(Boolean, default=True)

class Expense(Base):
    __tablename__ = 'expenses'
    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, ForeignKey('stores.id'), nullable=False)
    category = Column(String(50), nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(String(250))
    supplier_id = Column(Integer, ForeignKey('suppliers.id'), nullable=True)
    date = Column(Date, nullable=False)
    store = relationship('Store', back_populates='expenses')
    supplier = relationship('Supplier')

class Holiday(Base):
    __tablename__ = 'holidays'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    date_month = Column(Integer)
    date_day = Column(Integer)
    days_before = Column(Integer, default=7)
    notes = Column(Text)

class CorporateClient(Base):
    __tablename__ = 'corporate_clients'
    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, ForeignKey('stores.id'), nullable=False)
    company_name = Column(String(200), nullable=False)
    contact_person = Column(String(150))
    phone = Column(String(30))
    address = Column(String(250))
    contract_number = Column(String(50))
    contract_date = Column(Date)
    contract_until = Column(Date)
    discount = Column(Float, default=10.0)
    payment_terms = Column(String(100))
    notes = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    fixed_price = Column(Float, default=0.0)
    manager_id = Column(Integer, ForeignKey('staff.id'), nullable=True)
    store = relationship('Store', back_populates='corporate_clients')
    employees = relationship('CorporateEmployee', back_populates='client', cascade='all, delete-orphan')
    orders = relationship('Order', back_populates='corporate_client')
    invoices = relationship('Invoice', back_populates='corporate_client')
    manager = relationship('Staff', foreign_keys=[manager_id])

    @property
    def total_revenue(self):
        return sum(o.amount or 0 for o in self.orders if o.status == 'доставлен')

    @property
    def debt(self):
        return sum(inv.amount for inv in self.invoices if not inv.paid)

class CorporateEmployee(Base):
    __tablename__ = 'corporate_employees'
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('corporate_clients.id'), nullable=False)
    full_name = Column(String(150), nullable=False)
    position = Column(String(100))
    birthday = Column(Date)
    phone = Column(String(30))
    notes = Column(Text)
    is_active = Column(Boolean, default=True)
    preferred_bouquet = Column(String(150))
    preferred_budget = Column(Float)
    gender = Column(String(10), default='female')
    client = relationship('CorporateClient', back_populates='employees')

class Invoice(Base):
    __tablename__ = 'invoices'
    id = Column(Integer, primary_key=True)
    invoice_number = Column(String(30), unique=True)
    corporate_client_id = Column(Integer, ForeignKey('corporate_clients.id'), nullable=False)
    issue_date = Column(Date, default=date.today)
    due_date = Column(Date, nullable=False)
    amount = Column(Float, default=0.0)
    paid = Column(Boolean, default=False)
    paid_date = Column(Date)
    description = Column(Text)
    corporate_client = relationship('CorporateClient', back_populates='invoices')

class AutoOrdersLog(Base):
    __tablename__ = 'auto_orders_log'
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey('corporate_employees.id'), nullable=False)
    for_date = Column(Date, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    __table_args__ = (UniqueConstraint('employee_id', 'for_date'),)

class Setting(Base):
    __tablename__ = 'settings'
    key = Column(String(50), primary_key=True)
    value = Column(String(200))

# --- 5. Работа с базой данных ---
engine = create_engine(
    f'sqlite:///{DB_PATH}',
    echo=False,
    connect_args={'check_same_thread': False}
)
Base.metadata.create_all(engine)
SessionFactory = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False
)
Session = scoped_session(SessionFactory)

@contextmanager
def session_scope():
    session = Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def get_setting(key, default=None):
    with session_scope() as session:
        s = session.get(Setting, key)
        return s.value if s else default

def set_setting(key, value):
    with session_scope() as session:
        s = session.get(Setting, key)
        if s:
            s.value = str(value)
        else:
            session.add(Setting(key=key, value=str(value)))

def hash_password(password):
    return generate_password_hash(password)

def verify_password(password, hash_):
    return check_password_hash(hash_, password)

def backup_database():
    if not os.path.exists(DB_PATH):
        return None
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(BACKUP_DIR, f'muzflowers_backup_{timestamp}.db')
    try:
        shutil.copy2(DB_PATH, backup_path)
        backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.startswith('muzflowers_backup_')])
        for old in backups[:-10]:
            try:
                os.remove(os.path.join(BACKUP_DIR, old))
            except:
                pass
        return backup_path
    except Exception as e:
        logger.error(f"Ошибка бэкапа: {e}", exc_info=True)
        return None

# --- 6. Вспомогательные функции ---
def get_upcoming_holidays(days=14):
    with session_scope() as session:
        today = date.today()
        result = []
        holidays = session.query(Holiday).all()
        for h in holidays:
            try:
                h_date = date(today.year, h.date_month, h.date_day)
                if h_date < today:
                    h_date = date(today.year + 1, h.date_month, h.date_day)
                delta = (h_date - today).days
                if 0 <= delta <= days:
                    result.append({
                        'date': h_date, 'name': h.name,
                        'days_before': h.days_before, 'delta': delta, 'id': h.id
                    })
            except ValueError:
                continue
        result.sort(key=lambda x: x['delta'])
        return result

def get_upcoming_customer_birthdays(days=30):
    with session_scope() as session:
        today = date.today()
        result = []
        customers = session.query(Customer).filter(Customer.birthday != None).all()
        for c in customers:
            try:
                bd_this = date(today.year, c.birthday.month, c.birthday.day)
            except ValueError:
                if c.birthday.month == 2 and c.birthday.day == 29:
                    bd_this = date(today.year, 2, 28)
                else:
                    continue
            if bd_this < today:
                bd_this = date(today.year + 1, c.birthday.month, c.birthday.day)
            delta = (bd_this - today).days
            if 0 <= delta <= days:
                result.append({
                    'date': bd_this, 'name': c.name,
                    'phone': c.phone or '—', 'delta': delta
                })
        result.sort(key=lambda x: x['delta'])
        return result

def get_upcoming_corporate_birthdays(days=30):
    with session_scope() as session:
        today = date.today()
        result = []
        employees = session.query(CorporateEmployee).filter(
            CorporateEmployee.birthday != None,
            CorporateEmployee.is_active == True
        ).all()
        for e in employees:
            try:
                bd_this = date(today.year, e.birthday.month, e.birthday.day)
            except ValueError:
                if e.birthday.month == 2 and e.birthday.day == 29:
                    bd_this = date(today.year, 2, 28)
                else:
                    continue
            if bd_this < today:
                bd_this = date(today.year + 1, e.birthday.month, e.birthday.day)
            delta = (bd_this - today).days
            if 0 <= delta <= days:
                result.append({
                    'date': bd_this, 'employee_id': e.id,
                    'full_name': e.full_name,
                    'company_name': e.client.company_name if e.client else '',
                    'preferred_bouquet': e.preferred_bouquet or '',
                    'preferred_budget': e.preferred_budget, 'delta': delta
                })
        result.sort(key=lambda x: x['delta'])
        return result

def generate_order_number(session):
    """Генерирует уникальный номер заказа с учётом уже добавленных в сессию записей."""
    today_str = date.today().strftime('%Y%m%d')
    prefix = 'MUZ'
    pattern = f'{prefix}-{today_str}-%'

    # 1. Номера из базы данных
    existing_in_db = session.query(Order.order_number).filter(Order.order_number.like(pattern)).all()
    existing_in_db = {num[0] for num in existing_in_db}

    # 2. Номера из объектов, уже добавленных в сессию, но ещё не сохранённых
    existing_in_session = set()
    for obj in session.new:
        if isinstance(obj, Order) and obj.order_number and obj.order_number.startswith(prefix):
            existing_in_session.add(obj.order_number)

    all_existing = existing_in_db.union(existing_in_session)

    num = 1
    while True:
        candidate = f'{prefix}-{today_str}-{num:03d}'
        if candidate not in all_existing:
            return candidate
        num += 1

def generate_invoice_number(session):
    """Генерирует уникальный номер счета с учётом уже добавленных в сессию записей."""
    today_str = date.today().strftime('%Y%m%d')
    prefix = 'INV'
    pattern = f'{prefix}-{today_str}-%'

    # 1. Номера из базы данных
    existing_in_db = session.query(Invoice.invoice_number).filter(Invoice.invoice_number.like(pattern)).all()
    existing_in_db = {num[0] for num in existing_in_db}

    # 2. Номера из объектов, уже добавленных в сессию, но ещё не сохранённых
    existing_in_session = set()
    for obj in session.new:
        if isinstance(obj, Invoice) and obj.invoice_number and obj.invoice_number.startswith(prefix):
            existing_in_session.add(obj.invoice_number)

    all_existing = existing_in_db.union(existing_in_session)

    num = 1
    while True:
        candidate = f'{prefix}-{today_str}-{num:03d}'
        if candidate not in all_existing:
            return candidate
        num += 1

def safe_date(value):
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except:
            return date.today()
    return date.today()

# --- 7. Автозаказы и массовые заказы ---
def generate_auto_orders(target_date=None):
    if target_date is None:
        target_date = date.today() + timedelta(days=1)
    with session_scope() as session:
        store = session.query(Store).filter_by(is_active=True).first()
        if not store:
            return 0
        employees = session.query(CorporateEmployee).filter(
            CorporateEmployee.is_active == True,
            CorporateEmployee.birthday != None
        ).all()
        created = 0
        for emp in employees:
            if not emp.client or not emp.client.is_active:
                continue
            if (emp.birthday.month == target_date.month and
                    emp.birthday.day == target_date.day):
                existing = session.query(AutoOrdersLog).filter_by(
                    employee_id=emp.id, for_date=target_date
                ).first()
                if existing:
                    continue
                bouquet = emp.preferred_bouquet or "Корпоративный букет"
                default_budget = float(get_setting('default_budget', 3500.0))
                if emp.preferred_budget and emp.preferred_budget > 0:
                    amount = emp.preferred_budget
                elif emp.client.fixed_price and emp.client.fixed_price > 0:
                    amount = emp.client.fixed_price
                else:
                    amount = default_budget
                address = emp.client.address or ''
                order = Order(
                    store_id=store.id, customer_id=None,
                    corporate_client_id=emp.client_id,
                    order_date=date.today(), delivery_date=target_date,
                    bouquet=bouquet, quantity=1, amount=amount,
                    address=address, recipient_name=emp.full_name,
                    recipient_phone=emp.phone or '', status='новый',
                    occasion='День рождения',
                    comment=f"🤖 Автозаказ на ДР {emp.full_name}",
                    auto_created=True
                )
                customer = session.query(Customer).filter_by(name=f"[{emp.client.company_name}]").first()
                if not customer:
                    customer = Customer(name=f"[{emp.client.company_name}]", phone=emp.client.phone or '')
                    session.add(customer)
                    session.flush()
                order.customer_id = customer.id
                order.order_number = generate_order_number(session)
                session.add(order)
                session.add(AutoOrdersLog(employee_id=emp.id, for_date=target_date))
                created += 1
        return created

def create_mass_orders(holiday_id, year, bouquet_name, amount, target_gender):
    with session_scope() as session:
        holiday = session.get(Holiday, holiday_id)
        if not holiday:
            return 0, "Праздник не найден"
        delivery_date = date(year, holiday.date_month, holiday.date_day)
        store = session.query(Store).filter_by(is_active=True).first()
        if not store:
            return 0, "Магазин не найден"
        employees = session.query(CorporateEmployee).filter(
            CorporateEmployee.is_active == True
        ).all()
        if target_gender == 'female':
            employees = [e for e in employees if e.gender == 'female']
        elif target_gender == 'male':
            employees = [e for e in employees if e.gender == 'male']
        created = 0
        for emp in employees:
            if not emp.client or not emp.client.is_active:
                continue
            existing = session.query(Order).filter(
                Order.corporate_client_id == emp.client_id,
                Order.occasion == holiday.name,
                Order.delivery_date == delivery_date,
                Order.recipient_name == emp.full_name
            ).first()
            if existing:
                continue
            order_amount = amount if amount > 0 else (emp.client.fixed_price or float(get_setting('default_budget', 3500.0)))
            order = Order(
                store_id=store.id, customer_id=None,
                corporate_client_id=emp.client_id,
                order_date=date.today(), delivery_date=delivery_date,
                bouquet=bouquet_name or f"Праздничный букет",
                quantity=1, amount=order_amount,
                address=emp.client.address or '',
                recipient_name=emp.full_name,
                recipient_phone=emp.phone or '',
                status='новый', occasion=holiday.name,
                comment=f"Массовый заказ на {holiday.name}",
                auto_created=True
            )
            customer = session.query(Customer).filter_by(name=f"[{emp.client.company_name}]").first()
            if not customer:
                customer = Customer(name=f"[{emp.client.company_name}]", phone=emp.client.phone or '')
                session.add(customer)
                session.flush()
            order.customer_id = customer.id
            order.order_number = generate_order_number(session)
            session.add(order)
            created += 1
        return created, f"Создано {created} заказов на {delivery_date.strftime('%d.%m.%Y')}"

# --- 8. Экспорт/импорт Excel ---
def export_orders_to_excel(orders, filepath):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Заказы"
    headers = ["№", "Номер заказа", "Дата заказа", "Дата выдачи", "Повод",
               "Клиент", "Телефон получателя", "Букет", "Кол-во", "Сумма (₽)",
               "Себестоимость", "Прибыль", "Адрес", "Статус", "Оплачен", "Комментарий",
               "Открытка", "Сладости", "Оформление офиса"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="45475a")
    for i, o in enumerate(orders, 1):
        ws.append([
            i, o.order_number or '',
            o.order_date.isoformat() if o.order_date else '',
            o.delivery_date.isoformat() if o.delivery_date else '',
            o.occasion or '', o.client_name, o.recipient_phone or '',
            o.bouquet, o.quantity, o.amount,
            o.cost_price, o.profit, o.address or '', o.status,
            "Да" if o.paid else "Нет", o.comment or '',
            "Да" if o.has_card else "Нет",
            "Да" if o.has_sweets else "Нет",
            "Да" if o.is_office_decor else "Нет"
        ])
    for col in ws.columns:
        max_len = max((len(str(cell.value or '')) for cell in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 50)
    wb.save(filepath)

def import_orders_from_excel(filepath, store_id):
    wb = openpyxl.load_workbook(filepath, data_only=True)
    ws = wb.active
    imported = 0
    errors = []
    with session_scope() as session:
        store = session.get(Store, store_id)
        if not store:
            raise ValueError("Магазин не найден")
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        for row_num, row in enumerate(rows, start=2):
            try:
                if not row or not row[0]:
                    continue
                customer_name = str(row[5] or '').strip()
                if not customer_name:
                    continue
                customer = session.query(Customer).filter_by(name=customer_name).first()
                if not customer:
                    customer = Customer(name=customer_name, phone=str(row[6] or ''))
                    session.add(customer)
                    session.flush()
                if row[1]:
                    existing = session.query(Order).filter_by(order_number=str(row[1])).first()
                    if existing:
                        continue
                order = Order(
                    store_id=store.id, customer_id=customer.id,
                    order_date=safe_date(row[2]), delivery_date=safe_date(row[3]),
                    occasion=str(row[4] or ''), bouquet=str(row[7] or 'Букет'),
                    quantity=int(row[8]) if row[8] else 1,
                    amount=float(row[9]) if row[9] else 0.0,
                    cost_price=float(row[10]) if row[10] else 0.0,
                    address=str(row[12] or ''), recipient_phone=str(row[6] or ''),
                    recipient_name=str(row[5] or ''),
                    status=str(row[13] or 'новый'),
                    paid=(str(row[14]).lower() == 'да') if row[14] else False,
                    comment=str(row[15] or ''),
                    has_card=(str(row[16]).lower() == 'да') if row[16] else False,
                    has_sweets=(str(row[17]).lower() == 'да') if row[17] else False,
                    is_office_decor=(str(row[18]).lower() == 'да') if row[18] else False
                )
                order.order_number = str(row[1]) if row[1] else generate_order_number(session)
                session.add(order)
                imported += 1
            except Exception as e:
                errors.append(f"Строка {row_num}: {str(e)}")
    return imported, errors

def export_corporate_proposal(client, filepath):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "КП"
    ws.merge_cells('A1:D1')
    title = ws['A1']
    title.value = f"Коммерческое предложение\n{client.company_name}"
    title.font = Font(bold=True, size=16, color="F38BA8")
    title.alignment = Alignment(horizontal='center')
    ws['A3'] = "Клиент:"; ws['B3'] = client.company_name
    ws['A4'] = "Контакт:"; ws['B4'] = client.contact_person or ''
    ws['A5'] = "Телефон:"; ws['B5'] = client.phone or ''
    ws['A6'] = "Скидка:"; ws['B6'] = f"{client.discount}%"
    ws['A7'] = "Фикс. цена букета:"; ws['B7'] = f"{client.fixed_price:,.0f} ₽" if client.fixed_price else "—"
    ws['A8'] = "Менеджер:"; ws['B8'] = client.manager.full_name if client.manager else '—'
    ws['A9'] = "Условия:"; ws['B9'] = client.payment_terms or 'По счету раз в месяц'
    ws['A11'] = "Сотрудники для поздравления:"
    ws['A11'].font = Font(bold=True)
    ws.append(["ФИО", "Должность", "День рождения", "Телефон", "Предпочт. букет", "Бюджет"])
    for e in client.employees:
        ws.append([
            e.full_name, e.position or '',
            e.birthday.strftime('%d.%m') if e.birthday else '',
            e.phone or '', e.preferred_bouquet or '', e.preferred_budget or ''
        ])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 25
    wb.save(filepath)

def export_products_to_excel(products, filepath):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Каталог"
    headers = ["ID", "Название", "Категория", "Поставщик", "Ед.", "Цена", "Себест.", "Маржа",
               "Остаток", "Мин. остаток", "Сезон", "Скоропорт.", "Активен", "Хит", "Подарочный"]
    ws.append(headers)
    for p in products:
        ws.append([
            p.id, p.name, p.category,
            p.supplier.name if p.supplier else '',
            p.unit, p.price, p.cost_price, p.margin,
            p.stock, p.min_stock, p.season,
            "Да" if p.is_perishable else "Нет",
            "Да" if p.is_active else "Нет",
            "Да" if p.is_popular else "Нет",
            "Да" if p.is_gift_set else "Нет"
        ])
    for col in ws.columns:
        max_len = max((len(str(cell.value or '')) for cell in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 30)
    wb.save(filepath)

def import_products_from_excel(filepath):
    wb = openpyxl.load_workbook(filepath, data_only=True)
    ws = wb.active
    header_row_idx = None
    for row_idx, row in enumerate(ws.iter_rows(min_row=1, max_col=10, values_only=True), 1):
        row_text = ' '.join(str(cell or '').lower() for cell in row)
        if any(keyword in row_text for keyword in ['цена', 'размер', 'см', 'стоимость', 'руб']):
            header_row_idx = row_idx
            break
    if not header_row_idx:
        raise ValueError("Не удалось найти строку с заголовками (цена, размер, см...)")
    imported = 0
    updated = 0
    with session_scope() as session:
        for row in ws.iter_rows(min_row=header_row_idx + 1, max_col=10):
            name_cell = row[0].value
            if not name_cell:
                continue
            name = str(name_cell).strip()
            if not name or name.lower() in ['итого', 'всего', 'роза кустовая']:
                continue
            cost_price = None
            for col_idx in range(1, 7):
                val = row[col_idx].value
                if val and isinstance(val, (int, float)) and val > 0:
                    cost_price = val
                    break
            if not cost_price:
                continue
            product = session.query(Product).filter_by(name=name).first()
            if product:
                product.cost_price = cost_price
                markup = float(get_setting('default_markup', 1.7))
                product.price = cost_price * markup
                updated += 1
            else:
                product = Product(
                    name=name,
                    category='букеты',
                    cost_price=cost_price,
                    price=cost_price * float(get_setting('default_markup', 1.7)),
                    unit='шт',
                    is_active=True
                )
                session.add(product)
                imported += 1
    return imported, updated

# --- 9. Диалоги ---

class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🌹 Muzflowers CRM — Вход")
        self.setModal(True)
        self.setFixedSize(500, 350)
        layout = QVBoxLayout(self)
        title = QLabel("🌹 Muzflowers B2B CRM")
        title.setStyleSheet("font-size: 28px; font-weight: bold; color: #F38BA8;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        subtitle = QLabel("Корпоративные поздравления по подписке")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #888888; font-size: 14px;")
        layout.addWidget(subtitle)
        layout.addSpacing(15)
        form = QFormLayout()
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("admin")
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("••••••••")
        form.addRow("Логин:", self.username_edit)
        form.addRow("Пароль:", self.password_edit)
        layout.addLayout(form)
        self.login_btn = QPushButton("🔓 Войти")
        self.login_btn.clicked.connect(self.try_login)
        self.password_edit.returnPressed.connect(self.try_login)
        layout.addWidget(self.login_btn)
        hint = QLabel("admin / admin123  •  sergey / sergey123")
        hint.setStyleSheet("color: #D0C8BE; font-size: 10px;")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)
        self.user_data = None

    def try_login(self):
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        if not username or not password:
            QMessageBox.warning(self, "Ошибка", "Введите логин и пароль")
            return
        with session_scope() as session:
            user = session.query(User).filter_by(username=username, is_active=True).first()
            if user and verify_password(password, user.password_hash):
                self.user_data = {
                    'id': user.id, 'username': user.username,
                    'full_name': user.full_name, 'role': user.role,
                    'is_active': user.is_active
                }
                self.accept()
            else:
                QMessageBox.warning(self, "Ошибка", "Неверный логин или пароль")

class ChangePasswordDialog(QDialog):
    def __init__(self, user_data, parent=None):
        super().__init__(parent)
        self.user_data = user_data
        self.setWindowTitle("Смена пароля")
        self.setMinimumWidth(400)
        layout = QFormLayout(self)
        self.old_password = QLineEdit()
        self.old_password.setEchoMode(QLineEdit.Password)
        self.new_password = QLineEdit()
        self.new_password.setEchoMode(QLineEdit.Password)
        self.confirm_password = QLineEdit()
        self.confirm_password.setEchoMode(QLineEdit.Password)
        layout.addRow("Текущий пароль:", self.old_password)
        layout.addRow("Новый пароль:", self.new_password)
        layout.addRow("Подтвердите пароль:", self.confirm_password)
        btn_box = QHBoxLayout()
        ok_btn = QPushButton("Сменить")
        cancel_btn = QPushButton("Отмена")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(ok_btn)
        btn_box.addWidget(cancel_btn)
        layout.addRow(btn_box)

    def validate_and_save(self):
        old_pwd = self.old_password.text()
        new_pwd = self.new_password.text()
        confirm_pwd = self.confirm_password.text()
        if not old_pwd or not new_pwd or not confirm_pwd:
            QMessageBox.warning(self, "Ошибка", "Заполните все поля")
            return False
        if new_pwd != confirm_pwd:
            QMessageBox.warning(self, "Ошибка", "Пароли не совпадают")
            return False
        if len(new_pwd) < 6:
            QMessageBox.warning(self, "Ошибка", "Пароль должен быть не менее 6 символов")
            return False
        with session_scope() as session:
            user = session.get(User, self.user_data['id'])
            if not user:
                QMessageBox.critical(self, "Ошибка", "Пользователь не найден")
                return False
            if not verify_password(old_pwd, user.password_hash):
                QMessageBox.warning(self, "Ошибка", "Неверный текущий пароль")
                return False
            user.password_hash = hash_password(new_pwd)
        QMessageBox.information(self, "Успех", "Пароль успешно изменён")
        return True

class CustomerDialog(QDialog):
    def __init__(self, customer=None, store_id=None, parent=None):
        super().__init__(parent)
        self.store_id = store_id
        self.customer = customer
        self.setWindowTitle("Клиент" if customer else "Новый клиент")
        self.setMinimumWidth(500)
        layout = QFormLayout(self)
        self.name_edit = QLineEdit()
        self.phone_edit = QLineEdit()
        self.address_edit = QLineEdit()
        self.has_birthday = QCheckBox("Указать день рождения")
        self.birthday = QDateEdit()
        self.birthday.setCalendarPopup(True)
        self.birthday.setDate(QDate(1990, 1, 1))
        self.birthday.setEnabled(False)
        self.has_birthday.stateChanged.connect(lambda state: self.birthday.setEnabled(state == Qt.Checked))
        self.discount_edit = QDoubleSpinBox()
        self.discount_edit.setRange(0, 100)
        self.discount_edit.setSuffix(" %")
        self.vip_check = QCheckBox("VIP-клиент")
        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(80)
        layout.addRow("Имя *:", self.name_edit)
        layout.addRow("Телефон:", self.phone_edit)
        layout.addRow("Адрес:", self.address_edit)
        layout.addRow(self.has_birthday)
        layout.addRow("День рождения:", self.birthday)
        layout.addRow("Скидка:", self.discount_edit)
        layout.addRow(self.vip_check)
        layout.addRow("Заметки:", self.notes_edit)
        if customer:
            self.name_edit.setText(customer.name)
            self.phone_edit.setText(customer.phone or '')
            self.address_edit.setText(customer.address or '')
            if customer.birthday:
                self.has_birthday.setChecked(True)
                self.birthday.setDate(QDate(customer.birthday.year, customer.birthday.month, customer.birthday.day))
            self.discount_edit.setValue(customer.discount or 0)
            self.vip_check.setChecked(customer.is_vip)
            self.notes_edit.setPlainText(customer.notes or '')
        btn_box = QHBoxLayout()
        ok_btn = QPushButton("💾 Сохранить")
        cancel_btn = QPushButton("Отмена")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(ok_btn)
        btn_box.addWidget(cancel_btn)
        layout.addRow(btn_box)

    def get_data(self):
        return {
            'store_id': self.store_id,
            'name': self.name_edit.text().strip(),
            'phone': self.phone_edit.text().strip(),
            'address': self.address_edit.text().strip(),
            'birthday': self.birthday.date().toPyDate() if self.has_birthday.isChecked() else None,
            'discount': self.discount_edit.value(),
            'is_vip': self.vip_check.isChecked(),
            'notes': self.notes_edit.toPlainText()
        }

class ProductDialog(QDialog):
    UNITS = ['шт', 'букет', 'кг', 'м', 'упаковка', 'коробка', 'рулон']
    SEASONS = ['круглый год', 'весна', 'лето', 'осень', 'зима', 'сезонный']

    def __init__(self, product=None, suppliers=None, parent=None):
        super().__init__(parent)
        self.product = product
        self.suppliers = suppliers or []
        self.image_path = None
        self.setWindowTitle("Товар" if product else "Новый товар")
        self.setMinimumWidth(700)
        layout = QFormLayout(self)

        self.name_edit = QLineEdit()
        self.category_combo = QComboBox()
        self.category_combo.addItems(["букеты", "корзины", "композиции", "подарочные наборы", "свадебные", "траурные", "комнатные растения"])

        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(70)
        self.composition_edit = QTextEdit()
        self.composition_edit.setMaximumHeight(70)

        self.price_spin = QDoubleSpinBox()
        self.price_spin.setRange(0, 10000000)
        self.price_spin.setPrefix("₽ ")
        self.price_spin.setDecimals(2)

        self.cost_spin = QDoubleSpinBox()
        self.cost_spin.setRange(0, 10000000)
        self.cost_spin.setPrefix("₽ ")
        self.cost_spin.setDecimals(2)

        self.supplier_combo = QComboBox()
        self.supplier_combo.addItem("—", None)
        for s in self.suppliers:
            self.supplier_combo.addItem(s.name, s.id)

        self.unit_combo = QComboBox()
        self.unit_combo.addItems(self.UNITS)

        self.barcode_edit = QLineEdit()

        self.min_stock_spin = QDoubleSpinBox()
        self.min_stock_spin.setRange(0, 1000000)
        self.min_stock_spin.setDecimals(1)

        self.stock_spin = QDoubleSpinBox()
        self.stock_spin.setRange(0, 1000000)
        self.stock_spin.setDecimals(1)

        self.season_combo = QComboBox()
        self.season_combo.addItems(self.SEASONS)

        self.perishable_check = QCheckBox("Скоропортящийся")
        self.active_check = QCheckBox("Активен")
        self.popular_check = QCheckBox("Хит продаж")
        self.gift_set_check = QCheckBox("🎁 Подарочный набор")

        self.image_label = QLabel("Нет фото")
        self.image_label.setFixedSize(150, 150)
        self.image_label.setStyleSheet("border: 1px solid #E8E0D5; background: #F9F7F4; border-radius: 8px;")
        self.image_label.setAlignment(Qt.AlignCenter)

        self.btn_load_img = QPushButton("📷 Загрузить фото")
        self.btn_load_img.clicked.connect(self.load_image)

        img_layout = QHBoxLayout()
        img_layout.addWidget(self.image_label)
        img_layout.addWidget(self.btn_load_img)

        layout.addRow("Название *:", self.name_edit)
        layout.addRow("Категория:", self.category_combo)
        layout.addRow("Поставщик:", self.supplier_combo)
        layout.addRow("Единица измерения:", self.unit_combo)
        layout.addRow("Штрихкод:", self.barcode_edit)
        layout.addRow("Описание:", self.description_edit)
        layout.addRow("Состав:", self.composition_edit)
        layout.addRow("Цена продажи:", self.price_spin)
        layout.addRow("Себестоимость:", self.cost_spin)
        layout.addRow("Минимальный остаток:", self.min_stock_spin)
        layout.addRow("Текущий остаток:", self.stock_spin)
        layout.addRow("Сезонность:", self.season_combo)
        layout.addRow(self.perishable_check)
        layout.addRow(self.active_check)
        layout.addRow(self.popular_check)
        layout.addRow(self.gift_set_check)
        layout.addRow("Фото товара:", img_layout)

        if product:
            self.name_edit.setText(product.name)
            if product.category:
                idx = self.category_combo.findText(product.category)
                if idx >= 0:
                    self.category_combo.setCurrentIndex(idx)
            if product.supplier_id:
                idx = self.supplier_combo.findData(product.supplier_id)
                if idx >= 0:
                    self.supplier_combo.setCurrentIndex(idx)
            if product.unit:
                idx = self.unit_combo.findText(product.unit)
                if idx >= 0:
                    self.unit_combo.setCurrentIndex(idx)
            self.barcode_edit.setText(product.barcode or '')
            self.description_edit.setPlainText(product.description or '')
            self.composition_edit.setPlainText(product.composition or '')
            self.price_spin.setValue(product.price)
            self.cost_spin.setValue(product.cost_price or 0)
            self.min_stock_spin.setValue(product.min_stock or 0)
            self.stock_spin.setValue(product.stock or 0)
            if product.season:
                idx = self.season_combo.findText(product.season)
                if idx >= 0:
                    self.season_combo.setCurrentIndex(idx)
            self.perishable_check.setChecked(product.is_perishable)
            self.active_check.setChecked(product.is_active)
            self.popular_check.setChecked(product.is_popular)
            self.gift_set_check.setChecked(product.is_gift_set)
            if product.image_path and os.path.exists(product.image_path):
                self._show_image(product.image_path)
        else:
            self.active_check.setChecked(True)

        btn_box = QHBoxLayout()
        ok_btn = QPushButton("💾 Сохранить")
        cancel_btn = QPushButton("Отмена")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(ok_btn)
        btn_box.addWidget(cancel_btn)
        layout.addRow(btn_box)

    def load_image(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Выберите фото", "", "Images (*.png *.jpg *.jpeg)")
        if filepath:
            ext = os.path.splitext(filepath)[1]
            dest_filename = f"{uuid.uuid4().hex}{ext}"
            dest_path = os.path.join(MEDIA_DIR, 'products', dest_filename)
            shutil.copy2(filepath, dest_path)
            self.image_path = dest_path
            self._show_image(dest_path)

    def _show_image(self, path):
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            self.image_label.setPixmap(pixmap.scaled(150, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.image_label.setText("Ошибка загрузки")

    def get_data(self):
        return {
            'name': self.name_edit.text().strip(),
            'category': self.category_combo.currentText(),
            'supplier_id': self.supplier_combo.currentData(),
            'unit': self.unit_combo.currentText(),
            'barcode': self.barcode_edit.text().strip(),
            'description': self.description_edit.toPlainText(),
            'composition': self.composition_edit.toPlainText(),
            'price': self.price_spin.value(),
            'cost_price': self.cost_spin.value(),
            'min_stock': self.min_stock_spin.value(),
            'stock': self.stock_spin.value(),
            'season': self.season_combo.currentText(),
            'is_perishable': self.perishable_check.isChecked(),
            'is_active': self.active_check.isChecked(),
            'is_popular': self.popular_check.isChecked(),
            'is_gift_set': self.gift_set_check.isChecked(),
            'image_path': self.image_path
        }

class OrderDialog(QDialog):
    STATUSES = ['новый', 'принят', 'собирается', 'готов', 'доставлен', 'отменён']
    OCCASIONS = ['День рождения', '8 Марта', 'Новый год', '1 Сентября', '14 Февраля',
                 '23 Февраля', 'День учителя', 'Юбилей', 'Свадьба', 'Профессиональный праздник', 'Другое']

    def __init__(self, order=None, customers=None, products=None, florists=None,
                 corporate_clients=None, store_id=None, parent=None):
        super().__init__(parent)
        self.order = order
        self.store_id = store_id
        self.products_list = products or []
        self._customers = customers or []
        self._corporate_clients = corporate_clients or []
        self.setWindowTitle("Заказ" if order else "Новый заказ")
        self.setMinimumWidth(750)
        self.setMinimumHeight(800)
        layout = QFormLayout(self)

        self._manual_amount_edit = False

        self.customer_combo = QComboBox()
        self.customer_combo.addItem("", None)
        for c in self._customers:
            self.customer_combo.addItem(f"{c.name} ({c.phone or ''})", c.id)

        self.corp_combo = QComboBox()
        self.corp_combo.addItem("— Физ. лицо —", None)
        for cc in self._corporate_clients:
            self.corp_combo.addItem(f"🏢 {cc.company_name}", cc.id)

        self.occasion_combo = QComboBox()
        self.occasion_combo.addItems(self.OCCASIONS)

        self.order_date = QDateEdit()
        self.order_date.setCalendarPopup(True)
        self.order_date.setDate(QDate.currentDate())

        self.delivery_date = QDateEdit()
        self.delivery_date.setCalendarPopup(True)
        self.delivery_date.setDate(QDate.currentDate().addDays(1))
        self.delivery_date.setMinimumDate(QDate.currentDate())

        self.delivery_time = QLineEdit()
        self.delivery_time.setPlaceholderText("14:00")

        self.product_combo = QComboBox()
        self.product_combo.addItem("— Без каталога —", None)
        for p in self.products_list:
            if p.is_active:
                # Добавляем информацию об остатке в название
                stock_info = f" (остаток: {p.stock:.0f})" if p.stock is not None else ""
                self.product_combo.addItem(f"{p.name} ({p.price:,.0f} ₽){stock_info}", p.id)

        # Метка для отображения остатка выбранного товара
        self.stock_label = QLabel("Остаток: —")
        self.stock_label.setStyleSheet("color: #555; font-size: 12px;")

        self.bouquet_edit = QLineEdit()
        self.composition_edit = QTextEdit()
        self.composition_edit.setMaximumHeight(60)

        self.quantity_spin = QSpinBox()
        self.quantity_spin.setRange(1, 9999)
        self.quantity_spin.setValue(1)

        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(0, 10000000)
        self.amount_spin.setPrefix("₽ ")
        self.amount_spin.setDecimals(2)

        self.cost_spin = QDoubleSpinBox()
        self.cost_spin.setRange(0, 10000000)
        self.cost_spin.setPrefix("₽ ")
        self.cost_spin.setDecimals(2)

        self.recipient_name = QLineEdit()
        self.recipient_phone = QLineEdit()
        self.address_edit = QLineEdit()

        self.status_combo = QComboBox()
        self.status_combo.addItems(self.STATUSES)

        self.florist_combo = QComboBox()
        self.florist_combo.addItem("—", None)
        for f in florists or []:
            self.florist_combo.addItem(f"{f.full_name}", f.id)

        self.paid_check = QCheckBox("Оплачен")
        self.card_check = QCheckBox("📨 Открытка")
        self.sweets_check = QCheckBox("🍬 Сладости")
        self.decor_check = QCheckBox("🌿 Оформление офиса")

        if order:
            self._base_amount = (order.amount or 0) - (order.extra_cost or 0)
        else:
            self._base_amount = 0

        def update_extra():
            if not self._manual_amount_edit:
                card_price = float(get_setting('card_price', 100))
                sweets_price = float(get_setting('sweets_price', 200))
                extra = (card_price if self.card_check.isChecked() else 0) + \
                        (sweets_price if self.sweets_check.isChecked() else 0)
                self.amount_spin.setValue(self._base_amount + extra)

        def on_amount_edited():
            self._manual_amount_edit = True
            self._base_amount = self.amount_spin.value() - (
                (float(get_setting('card_price', 100)) if self.card_check.isChecked() else 0) +
                (float(get_setting('sweets_price', 200)) if self.sweets_check.isChecked() else 0)
            )

        self.amount_spin.valueChanged.connect(on_amount_edited)
        self.card_check.stateChanged.connect(update_extra)
        self.sweets_check.stateChanged.connect(update_extra)

        self.comment_edit = QTextEdit()
        self.comment_edit.setMaximumHeight(60)

        # Добавляем виджет для отображения остатка
        stock_layout = QHBoxLayout()
        stock_layout.addWidget(self.stock_label)
        stock_layout.addStretch()

        layout.addRow("Клиент (физ. лицо):", self.customer_combo)
        layout.addRow("Корпоративный клиент:", self.corp_combo)
        layout.addRow("Повод:", self.occasion_combo)
        layout.addRow("Дата заказа:", self.order_date)
        layout.addRow("Дата доставки *:", self.delivery_date)
        layout.addRow("Время доставки:", self.delivery_time)
        layout.addRow("Из каталога:", self.product_combo)
        layout.addRow("", stock_layout)  # Добавляем строку с остатком
        layout.addRow("Букет *:", self.bouquet_edit)
        layout.addRow("Состав:", self.composition_edit)
        layout.addRow("Количество:", self.quantity_spin)
        layout.addRow("Сумма продажи:", self.amount_spin)
        layout.addRow("Себестоимость:", self.cost_spin)
        layout.addRow("Получатель:", self.recipient_name)
        layout.addRow("Телефон получателя:", self.recipient_phone)
        layout.addRow("Адрес доставки:", self.address_edit)
        layout.addRow("Статус:", self.status_combo)
        layout.addRow("Флорист:", self.florist_combo)
        layout.addRow(self.paid_check)
        layout.addRow(self.card_check)
        layout.addRow(self.sweets_check)
        layout.addRow(self.decor_check)
        layout.addRow("Комментарий:", self.comment_edit)

        def update_stock_label():
            """Обновляет метку остатка при выборе товара."""
            pid = self.product_combo.currentData()
            if pid:
                for p in self.products_list:
                    if p.id == pid:
                        stock = p.stock if p.stock is not None else 0
                        self.stock_label.setText(f"Остаток: {stock:.0f} {p.unit}")
                        # Если остаток мал, выделяем красным
                        if stock <= p.min_stock and p.min_stock > 0:
                            self.stock_label.setStyleSheet("color: #E57373; font-weight: bold;")
                        else:
                            self.stock_label.setStyleSheet("color: #555; font-size: 12px;")
                        break
            else:
                self.stock_label.setText("Остаток: —")
                self.stock_label.setStyleSheet("color: #555; font-size: 12px;")

        def on_product_selected(idx):
            pid = self.product_combo.itemData(idx)
            if pid:
                for p in self.products_list:
                    if p.id == pid:
                        self.bouquet_edit.setText(p.name)
                        self.composition_edit.setPlainText(p.composition or '')
                        self.amount_spin.setValue(p.price)
                        self.cost_spin.setValue(p.cost_price or 0)
                        self._base_amount = p.price
                        self._manual_amount_edit = False
                        update_extra()
                        update_stock_label()
                        # Проверка скоропортящегося товара
                        if p.is_perishable:
                            max_date = QDate.currentDate().addDays(PERISHABLE_DAYS)
                            self.delivery_date.setMaximumDate(max_date)
                            self.delivery_date.setDate(min(QDate.currentDate().addDays(1), max_date))
                        else:
                            self.delivery_date.setMaximumDate(QDate(2099, 12, 31))
                        break
            else:
                self.stock_label.setText("Остаток: —")
                self.stock_label.setStyleSheet("color: #555; font-size: 12px;")

        self.product_combo.currentIndexChanged.connect(on_product_selected)

        def on_corp_selected(idx):
            corp_id = self.corp_combo.itemData(idx)
            if corp_id:
                for cc in self._corporate_clients:
                    if cc.id == corp_id:
                        for c in self._customers:
                            if c.name == f"[{cc.company_name}]":
                                c_idx = self.customer_combo.findData(c.id)
                                if c_idx >= 0:
                                    self.customer_combo.setCurrentIndex(c_idx)
                                break
                        if not self.address_edit.text():
                            self.address_edit.setText(cc.address or '')
                        if not self.recipient_phone.text():
                            self.recipient_phone.setText(cc.phone or '')
                        break
        self.corp_combo.currentIndexChanged.connect(on_corp_selected)

        if order:
            if order.customer_id:
                idx = self.customer_combo.findData(order.customer_id)
                if idx >= 0:
                    self.customer_combo.setCurrentIndex(idx)
            if order.corporate_client_id:
                idx = self.corp_combo.findData(order.corporate_client_id)
                if idx >= 0:
                    self.corp_combo.setCurrentIndex(idx)
            if order.occasion and order.occasion in self.OCCASIONS:
                self.occasion_combo.setCurrentText(order.occasion)
            if order.order_date:
                self.order_date.setDate(QDate(order.order_date.year, order.order_date.month, order.order_date.day))
            self.delivery_date.setDate(QDate(order.delivery_date.year, order.delivery_date.month, order.delivery_date.day))
            self.delivery_time.setText(order.delivery_time or '')
            if order.product_id:
                idx = self.product_combo.findData(order.product_id)
                if idx >= 0:
                    self.product_combo.setCurrentIndex(idx)
            self.bouquet_edit.setText(order.bouquet or '')
            self.composition_edit.setPlainText(order.composition or '')
            self.quantity_spin.setValue(order.quantity or 1)
            self.amount_spin.setValue(order.amount or 0)
            self.cost_spin.setValue(order.cost_price or 0)
            self.recipient_name.setText(order.recipient_name or '')
            self.recipient_phone.setText(order.recipient_phone or '')
            self.address_edit.setText(order.address or '')
            idx = self.status_combo.findText(order.status)
            if idx >= 0:
                self.status_combo.setCurrentIndex(idx)
            if order.florist_id:
                idx = self.florist_combo.findData(order.florist_id)
                if idx >= 0:
                    self.florist_combo.setCurrentIndex(idx)
            self.paid_check.setChecked(order.paid)
            self.comment_edit.setPlainText(order.comment or '')
            self.card_check.setChecked(order.has_card or False)
            self.sweets_check.setChecked(order.has_sweets or False)
            self.decor_check.setChecked(order.is_office_decor or False)
            # Обновить метку остатка
            update_stock_label()

        btn_box = QHBoxLayout()
        ok_btn = QPushButton("💾 Сохранить заказ")
        cancel_btn = QPushButton("Отмена")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(ok_btn)
        btn_box.addWidget(cancel_btn)
        layout.addRow(btn_box)

    def get_data(self):
        extra = 0
        if self.card_check.isChecked():
            extra += float(get_setting('card_price', 100))
        if self.sweets_check.isChecked():
            extra += float(get_setting('sweets_price', 200))
        return {
            'store_id': self.store_id,
            'customer_id': self.customer_combo.currentData(),
            'corporate_client_id': self.corp_combo.currentData(),
            'occasion': self.occasion_combo.currentText(),
            'order_date': self.order_date.date().toPyDate(),
            'delivery_date': self.delivery_date.date().toPyDate(),
            'delivery_time': self.delivery_time.text().strip(),
            'product_id': self.product_combo.currentData(),
            'bouquet': self.bouquet_edit.text().strip() or 'Букет',
            'composition': self.composition_edit.toPlainText(),
            'quantity': self.quantity_spin.value(),
            'amount': self.amount_spin.value(),
            'cost_price': self.cost_spin.value(),
            'recipient_name': self.recipient_name.text().strip(),
            'recipient_phone': self.recipient_phone.text().strip(),
            'address': self.address_edit.text().strip(),
            'status': self.status_combo.currentText(),
            'florist_id': self.florist_combo.currentData(),
            'paid': self.paid_check.isChecked(),
            'comment': self.comment_edit.toPlainText(),
            'has_card': self.card_check.isChecked(),
            'has_sweets': self.sweets_check.isChecked(),
            'extra_cost': extra,
            'is_office_decor': self.decor_check.isChecked()
        }

class InventoryDialog(QDialog):
    def __init__(self, item=None, store_id=None, suppliers=None, parent=None):
        super().__init__(parent)
        self.item = item
        self.store_id = store_id
        self.suppliers = suppliers or []
        self.setWindowTitle("Позиция склада" if item else "Новая позиция")
        self.setMinimumWidth(500)
        layout = QFormLayout(self)
        self.name_edit = QLineEdit()
        self.category_combo = QComboBox()
        self.category_combo.addItems(["цветы", "упаковка", "ленты", "корзины", "открытки", "сладости", "другое"])
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["шт", "уп.", "кг", "м"])
        self.quantity_spin = QDoubleSpinBox()
        self.quantity_spin.setRange(0, 1000000)
        self.quantity_spin.setDecimals(1)
        self.min_quantity_spin = QDoubleSpinBox()
        self.min_quantity_spin.setRange(0, 1000000)
        self.min_quantity_spin.setDecimals(1)
        self.purchase_price_spin = QDoubleSpinBox()
        self.purchase_price_spin.setRange(0, 10000000)
        self.purchase_price_spin.setPrefix("₽ ")
        self.purchase_price_spin.setDecimals(2)
        self.batch_edit = QLineEdit()
        self.arrival_date = QDateEdit()
        self.arrival_date.setCalendarPopup(True)
        self.arrival_date.setDate(QDate.currentDate())
        self.supplier_combo = QComboBox()
        self.supplier_combo.addItem("—", None)
        for s in self.suppliers:
            self.supplier_combo.addItem(s.name, s.id)
        layout.addRow("Название *:", self.name_edit)
        layout.addRow("Категория:", self.category_combo)
        layout.addRow("Единица:", self.unit_combo)
        layout.addRow("Количество:", self.quantity_spin)
        layout.addRow("Мин. остаток:", self.min_quantity_spin)
        layout.addRow("Цена закупки:", self.purchase_price_spin)
        layout.addRow("Партия:", self.batch_edit)
        layout.addRow("Дата прихода:", self.arrival_date)
        layout.addRow("Поставщик:", self.supplier_combo)
        if item:
            self.name_edit.setText(item.name)
            idx = self.category_combo.findText(item.category or '')
            if idx >= 0:
                self.category_combo.setCurrentIndex(idx)
            idx = self.unit_combo.findText(item.unit or 'шт')
            if idx >= 0:
                self.unit_combo.setCurrentIndex(idx)
            self.quantity_spin.setValue(item.quantity)
            self.min_quantity_spin.setValue(item.min_quantity)
            self.purchase_price_spin.setValue(item.purchase_price)
            self.batch_edit.setText(item.batch_number or '')
            if item.arrival_date:
                self.arrival_date.setDate(QDate(item.arrival_date.year, item.arrival_date.month, item.arrival_date.day))
            if item.supplier_id:
                idx = self.supplier_combo.findData(item.supplier_id)
                if idx >= 0:
                    self.supplier_combo.setCurrentIndex(idx)
        btn_box = QHBoxLayout()
        ok_btn = QPushButton("💾 Сохранить")
        cancel_btn = QPushButton("Отмена")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(ok_btn)
        btn_box.addWidget(cancel_btn)
        layout.addRow(btn_box)

    def get_data(self):
        return {
            'store_id': self.store_id,
            'name': self.name_edit.text().strip(),
            'category': self.category_combo.currentText(),
            'unit': self.unit_combo.currentText(),
            'quantity': self.quantity_spin.value(),
            'min_quantity': self.min_quantity_spin.value(),
            'purchase_price': self.purchase_price_spin.value(),
            'batch_number': self.batch_edit.text().strip(),
            'arrival_date': self.arrival_date.date().toPyDate(),
            'supplier_id': self.supplier_combo.currentData()
        }

class SupplierDialog(QDialog):
    def __init__(self, supplier=None, parent=None):
        super().__init__(parent)
        self.supplier = supplier
        self.setWindowTitle("Поставщик" if supplier else "Новый поставщик")
        self.setMinimumWidth(500)
        layout = QFormLayout(self)
        self.name_edit = QLineEdit()
        self.contact_edit = QLineEdit()
        self.phone_edit = QLineEdit()
        self.address_edit = QLineEdit()
        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(80)
        layout.addRow("Название *:", self.name_edit)
        layout.addRow("Контактное лицо:", self.contact_edit)
        layout.addRow("Телефон:", self.phone_edit)
        layout.addRow("Адрес:", self.address_edit)
        layout.addRow("Заметки:", self.notes_edit)
        if supplier:
            self.name_edit.setText(supplier.name)
            self.contact_edit.setText(supplier.contact_person or '')
            self.phone_edit.setText(supplier.phone or '')
            self.address_edit.setText(supplier.address or '')
            self.notes_edit.setPlainText(supplier.notes or '')
        btn_box = QHBoxLayout()
        ok_btn = QPushButton("💾 Сохранить")
        cancel_btn = QPushButton("Отмена")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(ok_btn)
        btn_box.addWidget(cancel_btn)
        layout.addRow(btn_box)

    def get_data(self):
        return {
            'name': self.name_edit.text().strip(),
            'contact_person': self.contact_edit.text().strip(),
            'phone': self.phone_edit.text().strip(),
            'address': self.address_edit.text().strip(),
            'notes': self.notes_edit.toPlainText(),
            'is_active': True
        }

class ExpenseDialog(QDialog):
    CATEGORIES = ['аренда', 'закупка цветов', 'транспорт', 'упаковка', 'коммунальные', 'реклама', 'зарплата', 'прочее']

    def __init__(self, expense=None, store_id=None, suppliers=None, parent=None):
        super().__init__(parent)
        self.expense = expense
        self.store_id = store_id
        self.suppliers = suppliers or []
        self.setWindowTitle("Расход" if expense else "Новый расход")
        self.setMinimumWidth(500)
        layout = QFormLayout(self)
        self.category_combo = QComboBox()
        self.category_combo.addItems(self.CATEGORIES)
        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(0, 10000000)
        self.amount_spin.setPrefix("₽ ")
        self.amount_spin.setDecimals(2)
        self.desc_edit = QLineEdit()
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        self.supplier_combo = QComboBox()
        self.supplier_combo.addItem("—", None)
        for s in self.suppliers:
            self.supplier_combo.addItem(s.name, s.id)
        layout.addRow("Категория *:", self.category_combo)
        layout.addRow("Сумма *:", self.amount_spin)
        layout.addRow("Описание:", self.desc_edit)
        layout.addRow("Дата:", self.date_edit)
        layout.addRow("Поставщик:", self.supplier_combo)
        if expense:
            idx = self.category_combo.findText(expense.category)
            if idx >= 0:
                self.category_combo.setCurrentIndex(idx)
            self.amount_spin.setValue(expense.amount)
            self.desc_edit.setText(expense.description or '')
            if expense.date:
                self.date_edit.setDate(QDate(expense.date.year, expense.date.month, expense.date.day))
            if expense.supplier_id:
                idx = self.supplier_combo.findData(expense.supplier_id)
                if idx >= 0:
                    self.supplier_combo.setCurrentIndex(idx)
        btn_box = QHBoxLayout()
        ok_btn = QPushButton("💾 Сохранить")
        cancel_btn = QPushButton("Отмена")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(ok_btn)
        btn_box.addWidget(cancel_btn)
        layout.addRow(btn_box)

    def get_data(self):
        return {
            'store_id': self.store_id,
            'category': self.category_combo.currentText(),
            'amount': self.amount_spin.value(),
            'description': self.desc_edit.text().strip(),
            'date': self.date_edit.date().toPyDate(),
            'supplier_id': self.supplier_combo.currentData()
        }

class StaffDialog(QDialog):
    POSITIONS = ['florist', 'manager', 'admin']

    def __init__(self, staff=None, store_id=None, parent=None):
        super().__init__(parent)
        self.staff = staff
        self.store_id = store_id
        self.setWindowTitle("Сотрудник" if staff else "Новый сотрудник")
        self.setMinimumWidth(500)
        layout = QFormLayout(self)
        self.full_name_edit = QLineEdit()
        self.position_combo = QComboBox()
        self.position_combo.addItems(self.POSITIONS)
        self.phone_edit = QLineEdit()
        self.salary_spin = QDoubleSpinBox()
        self.salary_spin.setRange(0, 10000000)
        self.salary_spin.setPrefix("₽ ")
        self.salary_spin.setDecimals(2)
        self.hire_date = QDateEdit()
        self.hire_date.setCalendarPopup(True)
        self.hire_date.setDate(QDate.currentDate())
        self.active_check = QCheckBox("Активен")
        layout.addRow("ФИО *:", self.full_name_edit)
        layout.addRow("Должность:", self.position_combo)
        layout.addRow("Телефон:", self.phone_edit)
        layout.addRow("Зарплата:", self.salary_spin)
        layout.addRow("Дата найма:", self.hire_date)
        layout.addRow(self.active_check)
        if staff:
            self.full_name_edit.setText(staff.full_name)
            idx = self.position_combo.findText(staff.position or '')
            if idx >= 0:
                self.position_combo.setCurrentIndex(idx)
            self.phone_edit.setText(staff.phone or '')
            self.salary_spin.setValue(staff.salary or 0)
            if staff.hire_date:
                self.hire_date.setDate(QDate(staff.hire_date.year, staff.hire_date.month, staff.hire_date.day))
            self.active_check.setChecked(staff.is_active)
        else:
            self.active_check.setChecked(True)
        btn_box = QHBoxLayout()
        ok_btn = QPushButton("💾 Сохранить")
        cancel_btn = QPushButton("Отмена")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(ok_btn)
        btn_box.addWidget(cancel_btn)
        layout.addRow(btn_box)

    def get_data(self):
        return {
            'store_id': self.store_id,
            'full_name': self.full_name_edit.text().strip(),
            'position': self.position_combo.currentText(),
            'phone': self.phone_edit.text().strip(),
            'salary': self.salary_spin.value(),
            'hire_date': self.hire_date.date().toPyDate(),
            'is_active': self.active_check.isChecked()
        }

class CorporateClientDialog(QDialog):
    def __init__(self, client=None, store_id=None, managers=None, parent=None):
        super().__init__(parent)
        self.client = client
        self.store_id = store_id
        self.managers = managers or []
        self.setWindowTitle("Корпоративный клиент" if client else "Новый корпоративный клиент")
        self.setMinimumWidth(600)
        layout = QFormLayout(self)
        self.company_edit = QLineEdit()
        self.contact_edit = QLineEdit()
        self.phone_edit = QLineEdit()
        self.address_edit = QLineEdit()
        self.contract_number_edit = QLineEdit()
        self.contract_date = QDateEdit()
        self.contract_date.setCalendarPopup(True)
        self.contract_date.setDate(QDate.currentDate())
        self.contract_until = QDateEdit()
        self.contract_until.setCalendarPopup(True)
        self.contract_until.setDate(QDate.currentDate().addYears(1))
        self.discount_spin = QDoubleSpinBox()
        self.discount_spin.setRange(0, 100)
        self.discount_spin.setSuffix(" %")
        self.fixed_price_spin = QDoubleSpinBox()
        self.fixed_price_spin.setRange(0, 10000000)
        self.fixed_price_spin.setPrefix("₽ ")
        self.fixed_price_spin.setDecimals(2)
        self.payment_terms_edit = QLineEdit()
        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(80)
        self.manager_combo = QComboBox()
        self.manager_combo.addItem("—", None)
        for m in self.managers:
            self.manager_combo.addItem(m.full_name, m.id)
        layout.addRow("Название компании *:", self.company_edit)
        layout.addRow("Контактное лицо:", self.contact_edit)
        layout.addRow("Телефон:", self.phone_edit)
        layout.addRow("Адрес:", self.address_edit)
        layout.addRow("№ договора:", self.contract_number_edit)
        layout.addRow("Дата договора:", self.contract_date)
        layout.addRow("Действует до:", self.contract_until)
        layout.addRow("Скидка (%):", self.discount_spin)
        layout.addRow("Фикс. цена букета:", self.fixed_price_spin)
        layout.addRow("Условия оплаты:", self.payment_terms_edit)
        layout.addRow("Персональный менеджер:", self.manager_combo)
        layout.addRow("Заметки:", self.notes_edit)
        if client:
            self.company_edit.setText(client.company_name)
            self.contact_edit.setText(client.contact_person or '')
            self.phone_edit.setText(client.phone or '')
            self.address_edit.setText(client.address or '')
            self.contract_number_edit.setText(client.contract_number or '')
            if client.contract_date:
                self.contract_date.setDate(QDate(client.contract_date.year, client.contract_date.month, client.contract_date.day))
            if client.contract_until:
                self.contract_until.setDate(QDate(client.contract_until.year, client.contract_until.month, client.contract_until.day))
            self.discount_spin.setValue(client.discount or 0)
            self.fixed_price_spin.setValue(client.fixed_price or 0)
            self.payment_terms_edit.setText(client.payment_terms or '')
            self.notes_edit.setPlainText(client.notes or '')
            if client.manager_id:
                idx = self.manager_combo.findData(client.manager_id)
                if idx >= 0:
                    self.manager_combo.setCurrentIndex(idx)
        btn_box = QHBoxLayout()
        ok_btn = QPushButton("💾 Сохранить")
        cancel_btn = QPushButton("Отмена")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(ok_btn)
        btn_box.addWidget(cancel_btn)
        layout.addRow(btn_box)

    def get_data(self):
        return {
            'store_id': self.store_id,
            'company_name': self.company_edit.text().strip(),
            'contact_person': self.contact_edit.text().strip(),
            'phone': self.phone_edit.text().strip(),
            'address': self.address_edit.text().strip(),
            'contract_number': self.contract_number_edit.text().strip(),
            'contract_date': self.contract_date.date().toPyDate(),
            'contract_until': self.contract_until.date().toPyDate(),
            'discount': self.discount_spin.value(),
            'fixed_price': self.fixed_price_spin.value(),
            'payment_terms': self.payment_terms_edit.text().strip(),
            'manager_id': self.manager_combo.currentData(),
            'notes': self.notes_edit.toPlainText(),
            'is_active': True
        }

class CorporateEmployeeDialog(QDialog):
    def __init__(self, employee=None, parent=None):
        super().__init__(parent)
        self.employee = employee
        self.setWindowTitle("Сотрудник компании" if employee else "Новый сотрудник компании")
        self.setMinimumWidth(500)
        layout = QFormLayout(self)
        self.full_name_edit = QLineEdit()
        self.position_edit = QLineEdit()
        self.birthday = QDateEdit()
        self.birthday.setCalendarPopup(True)
        self.birthday.setDate(QDate(1990, 1, 1))
        self.phone_edit = QLineEdit()
        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(80)
        self.preferred_bouquet_edit = QLineEdit()
        self.preferred_budget_spin = QDoubleSpinBox()
        self.preferred_budget_spin.setRange(0, 10000000)
        self.preferred_budget_spin.setPrefix("₽ ")
        self.preferred_budget_spin.setDecimals(2)
        self.gender_combo = QComboBox()
        self.gender_combo.addItems(['female', 'male'])
        layout.addRow("ФИО *:", self.full_name_edit)
        layout.addRow("Должность:", self.position_edit)
        layout.addRow("День рождения:", self.birthday)
        layout.addRow("Телефон:", self.phone_edit)
        layout.addRow("Пол:", self.gender_combo)
        layout.addRow("Предпочт. букет:", self.preferred_bouquet_edit)
        layout.addRow("Бюджет:", self.preferred_budget_spin)
        layout.addRow("Заметки:", self.notes_edit)
        if employee:
            self.full_name_edit.setText(employee.full_name)
            self.position_edit.setText(employee.position or '')
            if employee.birthday:
                self.birthday.setDate(QDate(employee.birthday.year, employee.birthday.month, employee.birthday.day))
            self.phone_edit.setText(employee.phone or '')
            self.notes_edit.setPlainText(employee.notes or '')
            self.preferred_bouquet_edit.setText(employee.preferred_bouquet or '')
            self.preferred_budget_spin.setValue(employee.preferred_budget or 0)
            if employee.gender:
                idx = self.gender_combo.findText(employee.gender)
                if idx >= 0:
                    self.gender_combo.setCurrentIndex(idx)
        btn_box = QHBoxLayout()
        ok_btn = QPushButton("💾 Сохранить")
        cancel_btn = QPushButton("Отмена")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(ok_btn)
        btn_box.addWidget(cancel_btn)
        layout.addRow(btn_box)

    def get_data(self):
        return {
            'full_name': self.full_name_edit.text().strip(),
            'position': self.position_edit.text().strip(),
            'birthday': self.birthday.date().toPyDate(),
            'phone': self.phone_edit.text().strip(),
            'notes': self.notes_edit.toPlainText(),
            'preferred_bouquet': self.preferred_bouquet_edit.text().strip(),
            'preferred_budget': self.preferred_budget_spin.value(),
            'gender': self.gender_combo.currentText(),
            'is_active': True
        }

class InvoiceDialog(QDialog):
    def __init__(self, invoice=None, clients=None, parent=None):
        super().__init__(parent)
        self.invoice = invoice
        self.clients = clients or []
        self.setWindowTitle("Счёт" if invoice else "Новый счёт")
        self.setMinimumWidth(500)
        layout = QFormLayout(self)
        self.client_combo = QComboBox()
        self.client_combo.addItem("—", None)
        for c in self.clients:
            self.client_combo.addItem(c.company_name, c.id)
        self.issue_date = QDateEdit()
        self.issue_date.setCalendarPopup(True)
        self.issue_date.setDate(QDate.currentDate())
        self.due_date = QDateEdit()
        self.due_date.setCalendarPopup(True)
        self.due_date.setDate(QDate.currentDate().addDays(30))
        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(0, 10000000)
        self.amount_spin.setPrefix("₽ ")
        self.amount_spin.setDecimals(2)
        self.desc_edit = QLineEdit()
        self.paid_check = QCheckBox("Оплачен")
        layout.addRow("Клиент *:", self.client_combo)
        layout.addRow("Дата выставления:", self.issue_date)
        layout.addRow("Срок оплаты:", self.due_date)
        layout.addRow("Сумма *:", self.amount_spin)
        layout.addRow("Описание:", self.desc_edit)
        layout.addRow(self.paid_check)
        if invoice:
            idx = self.client_combo.findData(invoice.corporate_client_id)
            if idx >= 0:
                self.client_combo.setCurrentIndex(idx)
            if invoice.issue_date:
                self.issue_date.setDate(QDate(invoice.issue_date.year, invoice.issue_date.month, invoice.issue_date.day))
            if invoice.due_date:
                self.due_date.setDate(QDate(invoice.due_date.year, invoice.due_date.month, invoice.due_date.day))
            self.amount_spin.setValue(invoice.amount)
            self.desc_edit.setText(invoice.description or '')
            self.paid_check.setChecked(invoice.paid)
        btn_box = QHBoxLayout()
        ok_btn = QPushButton("💾 Сохранить")
        cancel_btn = QPushButton("Отмена")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(ok_btn)
        btn_box.addWidget(cancel_btn)
        layout.addRow(btn_box)

    def get_data(self):
        return {
            'corporate_client_id': self.client_combo.currentData(),
            'issue_date': self.issue_date.date().toPyDate(),
            'due_date': self.due_date.date().toPyDate(),
            'amount': self.amount_spin.value(),
            'description': self.desc_edit.text().strip(),
            'paid': self.paid_check.isChecked()
        }

# --- 10. Главное окно ---
class MainWindow(QMainWindow):
    def __init__(self, user_data):
        super().__init__()
        self.user_data = user_data
        self.user_id = user_data['id']
        self.username = user_data['username']
        self.full_name = user_data['full_name']
        self.role = user_data['role']
        self.is_active = user_data['is_active']
        self.store_id = None
        self.setWindowTitle(f"🌹 Muzflowers B2B CRM — {self.full_name or self.username}")
        self.resize(1900, 1050)
        self.setStyleSheet(STYLE)
        self.setup_ui()
        self.setup_shortcuts()
        self.refresh_all()
        self.setup_scheduler()
        self.statusBar().showMessage(f"✅ Готово к работе | Пользователь: {self.full_name or self.username}", 5000)
        QTimer.singleShot(1500, self.show_startup_reminders)

    def setup_ui(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("📁 Файл")
        backup_action = QAction("💾 Создать резервную копию", self)
        backup_action.triggered.connect(self.create_backup)
        file_menu.addAction(backup_action)
        file_menu.addSeparator()
        exit_action = QAction("🚪 Выход", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        profile_menu = menubar.addMenu("👤 Профиль")
        change_pwd_action = QAction("🔑 Сменить пароль", self)
        change_pwd_action.triggered.connect(self.change_password)
        profile_menu.addAction(change_pwd_action)

        settings_menu = menubar.addMenu("⚙️ Настройки")
        if self.role == 'admin':
            users_action = QAction("👥 Пользователи системы", self)
            users_action.triggered.connect(self.show_users)
            settings_menu.addAction(users_action)
            app_settings_action = QAction("🛠 Параметры системы", self)
            app_settings_action.triggered.connect(self.show_app_settings)
            settings_menu.addAction(app_settings_action)
        reminders_action = QAction("🔔 Проверить напоминания", self)
        reminders_action.triggered.connect(self.show_startup_reminders)
        settings_menu.addAction(reminders_action)

        help_menu = menubar.addMenu("❓ Помощь")
        about_action = QAction("ℹ️ О программе", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

        self.central = QWidget()
        self.setCentralWidget(self.central)
        main_layout = QVBoxLayout(self.central)
        main_layout.setContentsMargins(10, 10, 10, 10)

        top_bar = QHBoxLayout()
        welcome = QLabel(f"👤 {self.full_name or self.username} ({self.role})")
        welcome.setStyleSheet("font-size: 16px; font-weight: bold; color: #F38BA8;")
        top_bar.addWidget(welcome)

        with session_scope() as session:
            store = session.query(Store).filter_by(is_active=True).first()
            if not store:
                QMessageBox.critical(self, "Ошибка", "Магазин не найден.")
                QApplication.quit()
                return
            self.store_id = store.id
            store_label = QLabel(f"🛍️ {store.name}")
            store_label.setStyleSheet("color: #88C4A3; font-size: 14px;")
            top_bar.addWidget(store_label)
            top_bar.addStretch()

            low_stock_count = session.query(InventoryItem).filter(
                InventoryItem.store_id == self.store_id,
                InventoryItem.quantity <= InventoryItem.min_quantity,
                InventoryItem.min_quantity > 0
            ).count()
            if low_stock_count > 0:
                warning = QLabel(f"⚠️ {low_stock_count} позиций заканчивается!")
                warning.setStyleSheet("color: #E57373; font-weight: bold; background: #FCE4E4; padding: 5px 15px; border-radius: 20px;")
                top_bar.addWidget(warning)

        refresh_btn = QPushButton("🔄 Обновить")
        refresh_btn.setObjectName("secondary")
        refresh_btn.clicked.connect(self.refresh_all)
        top_bar.addWidget(refresh_btn)
        logout_btn = QPushButton("🚪 Выйти")
        logout_btn.clicked.connect(self.logout)
        top_bar.addWidget(logout_btn)
        main_layout.addLayout(top_bar)

        self.tabs = QTabWidget()
        self.tabs.setUsesScrollButtons(True)
        main_layout.addWidget(self.tabs)

        self.create_dashboard_tab()
        self.create_orders_tab()
        self.create_customers_tab()
        self.create_products_tab()
        self.create_inventory_tab()
        self.create_suppliers_tab()
        self.create_expenses_tab()
        self.create_staff_tab()
        self.create_corporate_tab()
        self.create_invoices_tab()
        self.create_holidays_tab()
        self.create_statistics_tab()

        self.apply_role_permissions()

    def apply_role_permissions(self):
        role = self.role
        if role == 'florist':
            hidden_tabs = [2, 4, 5, 6, 7, 8, 9, 10, 11]
            for idx in sorted(hidden_tabs, reverse=True):
                if idx < self.tabs.count():
                    self.tabs.removeTab(idx)

    def setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+N"), self, self.add_order)
        QShortcut(QKeySequence("Ctrl+E"), self, self.export_orders)
        QShortcut(QKeySequence("Ctrl+R"), self, self.refresh_all)
        QShortcut(QKeySequence("F5"), self, self.refresh_all)

    def setup_scheduler(self):
        self.scheduler = QtScheduler()
        self.scheduler.add_job(func=self.run_reminders_check, trigger='cron', hour=9, minute=0, id='reminders_daily')
        self.scheduler.add_job(func=self.auto_backup, trigger='cron', hour=2, minute=0, id='auto_backup')
        self.scheduler.add_job(func=self.run_auto_orders, trigger='cron', hour=8, minute=0, id='auto_orders_daily')
        self.scheduler.start()

    def run_reminders_check(self):
        QTimer.singleShot(0, self.show_startup_reminders)

    def auto_backup(self):
        backup_database()

    def run_auto_orders(self):
        QTimer.singleShot(0, self._do_auto_orders)

    def _do_auto_orders(self):
        count = generate_auto_orders()
        if count:
            self.refresh_all()
            QMessageBox.information(self, "Автозаказы", f"Создано {count} заказов на завтра")

    def create_backup(self):
        path = backup_database()
        if path:
            QMessageBox.information(self, "Резервная копия", f"✅ Создана: {path}")
        else:
            QMessageBox.warning(self, "Ошибка", "Не удалось создать резервную копию")

    def change_password(self):
        dlg = ChangePasswordDialog(self.user_data, self)
        if dlg.exec_():
            dlg.validate_and_save()

    def show_about(self):
        QMessageBox.about(self, "О программе",
                          "🌹 Muzflowers B2B CRM v2.0\n\n"
                          "Сервис корпоративных поздравлений по подписке.\n"
                          "Управление B2B-клиентами, автозаказы, финансы.\n\n"
                          "Дизайн вдохновлен Muzflower.ru и Posiflora.com\n"
                          "© 2026 Muzflowers")

    def show_app_settings(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Настройки системы")
        dlg.setMinimumWidth(400)
        layout = QFormLayout(dlg)

        card_price = get_setting('card_price', '100')
        sweets_price = get_setting('sweets_price', '200')
        default_budget = get_setting('default_budget', '3500.0')
        default_markup = get_setting('default_markup', '1.7')

        card_edit = QDoubleSpinBox()
        card_edit.setRange(0, 10000)
        card_edit.setPrefix("₽ ")
        card_edit.setValue(float(card_price))

        sweets_edit = QDoubleSpinBox()
        sweets_edit.setRange(0, 10000)
        sweets_edit.setPrefix("₽ ")
        sweets_edit.setValue(float(sweets_price))

        budget_edit = QDoubleSpinBox()
        budget_edit.setRange(0, 100000)
        budget_edit.setPrefix("₽ ")
        budget_edit.setValue(float(default_budget))

        markup_edit = QDoubleSpinBox()
        markup_edit.setRange(1.0, 5.0)
        markup_edit.setSingleStep(0.1)
        markup_edit.setValue(float(default_markup))

        layout.addRow("Цена открытки:", card_edit)
        layout.addRow("Цена сладостей:", sweets_edit)
        layout.addRow("Бюджет по умолчанию (автозаказы):", budget_edit)
        layout.addRow("Наценка (коэффициент):", markup_edit)

        btn_box = QHBoxLayout()
        ok_btn = QPushButton("💾 Сохранить")
        cancel_btn = QPushButton("Отмена")
        ok_btn.clicked.connect(dlg.accept)
        cancel_btn.clicked.connect(dlg.reject)
        btn_box.addWidget(ok_btn)
        btn_box.addWidget(cancel_btn)
        layout.addRow(btn_box)

        if dlg.exec_():
            set_setting('card_price', str(card_edit.value()))
            set_setting('sweets_price', str(sweets_edit.value()))
            set_setting('default_budget', str(budget_edit.value()))
            set_setting('default_markup', str(markup_edit.value()))
            QMessageBox.information(self, "Настройки", "✅ Настройки сохранены")

    def show_startup_reminders(self):
        messages = []
        upcoming_holidays = get_upcoming_holidays(days=14)
        if upcoming_holidays:
            msg = "🎉 БЛИЖАЙШИЕ ПРАЗДНИКИ:\n\n"
            for h in upcoming_holidays:
                msg += f"• {h['date'].strftime('%d.%m')} — {h['name']}"
                if h['delta'] == 0:
                    msg += " (СЕГОДНЯ!)"
                else:
                    msg += f" (через {h['delta']} дн.)"
                msg += f"\n📋 Готовиться за {h['days_before']} дн.\n"
            messages.append(("🎉 Праздники", msg))
        upcoming_bd = get_upcoming_customer_birthdays(days=7)
        if upcoming_bd:
            msg = "🎂 ДНИ РОЖДЕНИЯ КЛИЕНТОВ (7 дней):\n\n"
            for bd in upcoming_bd:
                msg += f"• {bd['date'].strftime('%d.%m')} — {bd['name']} (тел. {bd['phone']})"
                if bd['delta'] == 0:
                    msg += " — СЕГОДНЯ!"
                else:
                    msg += f" (через {bd['delta']} дн.)"
                msg += "\n"
            messages.append(("🎂 Дни рождения клиентов", msg))
        upcoming_corp_bd = get_upcoming_corporate_birthdays(days=14)
        if upcoming_corp_bd:
            msg = "🏢 КОРПОРАТИВНЫЕ ПОЗДРАВЛЕНИЯ (14 дней):\n\n"
            for bd in upcoming_corp_bd:
                msg += f"• {bd['date'].strftime('%d.%m')} — {bd['full_name']}"
                if bd['company_name']:
                    msg += f" ({bd['company_name']})"
                if bd['delta'] == 0:
                    msg += " — СЕГОДНЯ!"
                else:
                    msg += f" (через {bd['delta']} дн.)"
                msg += "\n"
            messages.append(("🏢 Корпоративные поздравления", msg))
        with session_scope() as session:
            overdue = session.query(Invoice).filter(Invoice.paid == False, Invoice.due_date < date.today()).all()
            if overdue:
                msg = "🔴 ПРОСРОЧЕННЫЕ СЧЕТА:\n\n"
                total = 0
                for inv in overdue:
                    days_overdue = (date.today() - inv.due_date).days
                    msg += f"• Счёт {inv.invoice_number} от {inv.corporate_client.company_name}\n"
                    msg += f"   Сумма: {inv.amount:,.2f} ₽, просрочка {days_overdue} дн.\n"
                    total += inv.amount
                msg += f"\n💸 Общая сумма просрочки: {total:,.2f} ₽"
                messages.append(("🔴 Просроченные счета", msg))
        if messages:
            for title, msg in messages:
                QMessageBox.information(self, title, msg)
        else:
            QMessageBox.information(self, "Напоминания", "✅ На ближайшие 14 дней напоминаний нет")

    def refresh_all(self):
        try:
            self.refresh_dashboard()
            self.refresh_orders()
            self.refresh_customers()
            self.refresh_products()
            self.refresh_inventory()
            self.refresh_suppliers()
            self.refresh_expenses()
            self.refresh_staff()
            self.refresh_corporate()
            self.refresh_invoices()
            self.refresh_holidays()
            self.refresh_statistics()
            self.statusBar().showMessage("✅ Данные обновлены", 3000)
        except Exception as e:
            logger.error(f"Ошибка обновления: {e}", exc_info=True)
            QMessageBox.warning(self, "Ошибка обновления", str(e))

    # ---------- Вкладка Главная ----------
    def create_dashboard_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(20)

        title = QLabel("🏠 Главная панель")
        title.setObjectName("title")
        layout.addWidget(title)

        metrics_layout = QHBoxLayout()
        metrics_layout.setSpacing(15)
        self.metric_revenue = self._create_metric_card("💰", "Выручка (мес)", "0 ₽")
        self.metric_profit = self._create_metric_card("📈", "Прибыль (мес)", "0 ₽")
        self.metric_orders = self._create_metric_card("📦", "Всего заказов", "0")
        self.metric_customers = self._create_metric_card("👤", "Клиентов", "0")
        self.metric_corp = self._create_metric_card("🏢", "Корп. клиентов", "0")
        self.metric_low_stock = self._create_metric_card("⚠️", "Заканчивается", "0")
        self.metric_debt = self._create_metric_card("💸", "Дебиторка (корп)", "0 ₽")
        metrics_layout.addWidget(self.metric_revenue)
        metrics_layout.addWidget(self.metric_profit)
        metrics_layout.addWidget(self.metric_orders)
        metrics_layout.addWidget(self.metric_customers)
        metrics_layout.addWidget(self.metric_corp)
        metrics_layout.addWidget(self.metric_low_stock)
        metrics_layout.addWidget(self.metric_debt)
        layout.addLayout(metrics_layout)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background-color: #E8E0D5; width: 3px; }")

        left_box = QGroupBox("📅 Заказы на завтра")
        left_layout = QVBoxLayout(left_box)
        self.tomorrow_orders_table = QTableWidget()
        self.tomorrow_orders_table.setColumnCount(5)
        self.tomorrow_orders_table.setHorizontalHeaderLabels(["Номер", "Клиент", "Букет", "Сумма", "Статус"])
        self.tomorrow_orders_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tomorrow_orders_table.setEditTriggers(QTableWidget.NoEditTriggers)
        left_layout.addWidget(self.tomorrow_orders_table)
        splitter.addWidget(left_box)

        right_box = QGroupBox("🎉 Ближайшие события")
        right_layout = QVBoxLayout(right_box)
        self.events_preview = QListWidget()
        self.events_preview.setStyleSheet("QListWidget { border: none; }")
        right_layout.addWidget(self.events_preview)
        splitter.addWidget(right_box)

        splitter.setSizes([900, 500])
        layout.addWidget(splitter)

        actions_group = QGroupBox("⚡ Быстрые действия")
        actions_layout = QHBoxLayout(actions_group)
        actions_layout.setSpacing(10)
        btn_new_order = QPushButton("➕ Новый заказ (Ctrl+N)")
        btn_new_order.clicked.connect(self.add_order)
        actions_layout.addWidget(btn_new_order)
        btn_export = QPushButton("📤 Экспорт (Ctrl+E)")
        btn_export.clicked.connect(self.export_orders)
        actions_layout.addWidget(btn_export)
        btn_import = QPushButton("📥 Импорт")
        btn_import.clicked.connect(self.import_orders)
        actions_layout.addWidget(btn_import)
        btn_backup = QPushButton("💾 Бэкап")
        btn_backup.setObjectName("secondary")
        btn_backup.clicked.connect(self.create_backup)
        actions_layout.addWidget(btn_backup)
        btn_auto = QPushButton("🤖 Автозаказы")
        btn_auto.clicked.connect(self._do_auto_orders)
        actions_layout.addWidget(btn_auto)
        layout.addWidget(actions_group)

        self.tabs.addTab(tab, "🏠 Главная")

    def _create_metric_card(self, icon, label, value):
        card = QFrame()
        card.setProperty("class", "metric-card")
        card.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 2px solid #E8E0D5;
                border-radius: 16px;
                padding: 18px;
            }
        """)
        layout = QVBoxLayout(card)
        layout.setSpacing(5)

        icon_label = QLabel(icon)
        icon_label.setStyleSheet("font-size: 32px;")
        layout.addWidget(icon_label)

        value_label = QLabel(value)
        value_label.setObjectName("value")
        value_label.setStyleSheet("font-size: 26px; font-weight: bold; color: #333333;")
        layout.addWidget(value_label)

        desc_label = QLabel(label)
        desc_label.setStyleSheet("font-size: 14px; color: #888888;")
        layout.addWidget(desc_label)

        card.value_label = value_label
        return card

    def refresh_dashboard(self):
        today = date.today()
        month_start = date(today.year, today.month, 1)
        next_month = date(today.year + 1, 1, 1) if today.month == 12 else date(today.year, today.month + 1, 1)
        with session_scope() as session:
            orders = session.query(Order).filter(
                Order.store_id == self.store_id,
                Order.delivery_date >= month_start,
                Order.delivery_date < next_month,
                Order.status == 'доставлен'
            ).all()
            revenue = sum(o.amount or 0 for o in orders)
            cost = sum(o.cost_price or 0 for o in orders)
            expenses = session.query(Expense).filter(
                Expense.store_id == self.store_id,
                Expense.date >= month_start,
                Expense.date < next_month
            ).all()
            expenses_total = sum(e.amount for e in expenses)
            profit = revenue - cost - expenses_total
            total_orders = session.query(Order).filter_by(store_id=self.store_id).count()
            total_customers = session.query(Customer).count()
            corp_clients = session.query(CorporateClient).filter_by(store_id=self.store_id, is_active=True).count()
            low_stock = session.query(InventoryItem).filter(
                InventoryItem.store_id == self.store_id,
                InventoryItem.quantity <= InventoryItem.min_quantity,
                InventoryItem.min_quantity > 0
            ).count()
            total_debt = session.query(func.sum(Invoice.amount)).filter(
                Invoice.paid == False,
                Invoice.corporate_client.has(store_id=self.store_id)
            ).scalar() or 0

            self.metric_revenue.value_label.setText(f"{revenue:,.0f} ₽")
            self.metric_profit.value_label.setText(f"{profit:,.0f} ₽")
            self.metric_orders.value_label.setText(f"{total_orders}")
            self.metric_customers.value_label.setText(f"{total_customers}")
            self.metric_corp.value_label.setText(f"{corp_clients}")
            self.metric_low_stock.value_label.setText(f"{low_stock}")
            self.metric_debt.value_label.setText(f"{total_debt:,.0f} ₽")

            tomorrow = today + timedelta(days=1)
            tomorrow_orders = session.query(Order).filter(
                Order.store_id == self.store_id,
                Order.delivery_date == tomorrow
            ).all()
            self.tomorrow_orders_table.setRowCount(len(tomorrow_orders))
            for i, o in enumerate(tomorrow_orders):
                self.tomorrow_orders_table.setItem(i, 0, QTableWidgetItem(o.order_number or ''))
                self.tomorrow_orders_table.setItem(i, 1, QTableWidgetItem(o.client_name))
                self.tomorrow_orders_table.setItem(i, 2, QTableWidgetItem(o.bouquet))
                self.tomorrow_orders_table.setItem(i, 3, QTableWidgetItem(f"{o.amount:,.0f} ₽"))
                self.tomorrow_orders_table.setItem(i, 4, QTableWidgetItem(o.status))

            self.events_preview.clear()
            upcoming_holidays = get_upcoming_holidays(days=30)
            for h in upcoming_holidays:
                text = f"🎉 {h['date'].strftime('%d.%m')} — {h['name']}"
                if h['delta'] == 0:
                    text += " (СЕГОДНЯ!)"
                else:
                    text += f" (через {h['delta']} дн.)"
                self.events_preview.addItem(QListWidgetItem(text))

            upcoming_bd = get_upcoming_customer_birthdays(days=30)
            for bd in upcoming_bd:
                text = f"🎂 {bd['date'].strftime('%d.%m')} — {bd['name']}"
                if bd['delta'] == 0:
                    text += " (СЕГОДНЯ!)"
                else:
                    text += f" (через {bd['delta']} дн.)"
                self.events_preview.addItem(QListWidgetItem(text))

            upcoming_corp = get_upcoming_corporate_birthdays(days=30)
            for bd in upcoming_corp:
                text = f"🏢 {bd['date'].strftime('%d.%m')} — {bd['full_name']} ({bd['company_name']})"
                if bd['delta'] == 0:
                    text += " (СЕГОДНЯ!)"
                else:
                    text += f" (через {bd['delta']} дн.)"
                self.events_preview.addItem(QListWidgetItem(text))

    # ---------- Вкладка Заказы ----------
    def create_orders_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        title = QLabel("🛍️ Заказы")
        title.setObjectName("section-title")
        layout.addWidget(title)
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Статус:"))
        self.status_combo = QComboBox()
        self.status_combo.addItems(["Все"] + OrderDialog.STATUSES)
        filter_layout.addWidget(self.status_combo)
        filter_layout.addWidget(QLabel("Повод:"))
        self.occasion_combo = QComboBox()
        self.occasion_combo.addItems(["Все"] + OrderDialog.OCCASIONS)
        filter_layout.addWidget(self.occasion_combo)
        filter_layout.addWidget(QLabel("Поиск:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Клиент, букет, адрес, номер...")
        self.search_edit.setMaximumWidth(300)
        filter_layout.addWidget(self.search_edit)
        apply_btn = QPushButton("🔍")
        apply_btn.setMaximumWidth(70)
        reset_btn = QPushButton("Сброс")
        reset_btn.setMaximumWidth(140)
        reset_btn.setObjectName("secondary")
        filter_layout.addWidget(apply_btn)
        filter_layout.addWidget(reset_btn)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        self.orders_table = QTableWidget()
        self.orders_table.setColumnCount(13)
        self.orders_table.setHorizontalHeaderLabels([
            "Номер", "Дата дост.", "Время", "Клиент", "Получатель",
            "Повод", "Букет", "К-во", "Сумма", "Статус", "Опл.",
            "Открытка", "Сладости"
        ])
        self.orders_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.orders_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.orders_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.orders_table.setAlternatingRowColors(True)
        self.orders_table.doubleClicked.connect(self.edit_order)
        layout.addWidget(self.orders_table)

        btn_layout = QHBoxLayout()
        self.btn_add_order = QPushButton("➕ Новый (Ctrl+N)")
        self.btn_edit_order = QPushButton("✏️ Редактировать")
        self.btn_del_order = QPushButton("🗑️ Удалить")
        refresh_btn = QPushButton("🔄 Обновить")
        export_btn = QPushButton("📤 Excel")
        self.btn_add_order.clicked.connect(self.add_order)
        self.btn_edit_order.clicked.connect(self.edit_order)
        self.btn_del_order.clicked.connect(self.del_order)
        refresh_btn.clicked.connect(self.refresh_orders)
        export_btn.clicked.connect(self.export_orders)
        btn_layout.addWidget(self.btn_add_order)
        btn_layout.addWidget(self.btn_edit_order)
        btn_layout.addWidget(self.btn_del_order)
        btn_layout.addWidget(refresh_btn)
        btn_layout.addWidget(export_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        apply_btn.clicked.connect(self.refresh_orders)
        reset_btn.clicked.connect(self._reset_filters)
        self.tabs.addTab(tab, "🛍️ Заказы")

    def _reset_filters(self):
        self.status_combo.setCurrentIndex(0)
        self.occasion_combo.setCurrentIndex(0)
        self.search_edit.clear()
        self.refresh_orders()

    def refresh_orders(self):
        table = self.orders_table
        status = self.status_combo.currentText()
        occasion = self.occasion_combo.currentText()
        search = self.search_edit.text().strip()
        with session_scope() as session:
            query = session.query(Order).filter(Order.store_id == self.store_id)
            if status != "Все":
                query = query.filter(Order.status == status)
            if occasion != "Все":
                query = query.filter(Order.occasion == occasion)
            if search:
                like = f"%{search}%"
                query = query.filter(
                    (Order.bouquet.like(like)) |
                    (Order.address.like(like)) |
                    (Order.comment.like(like)) |
                    (Order.order_number.like(like)) |
                    (Order.recipient_name.like(like)) |
                    (Order.customer.has(Customer.name.like(like)))
                )
            orders = query.order_by(Order.delivery_date.desc(), Order.id.desc()).all()
            table.setRowCount(len(orders))
            status_colors = {
                'новый': '#89b4fa', 'принят': '#89dceb', 'собирается': '#f9e2af',
                'готов': '#a6e3a1', 'доставлен': '#94e2d5', 'отменён': '#f38ba8'
            }
            for i, o in enumerate(orders):
                table.setItem(i, 0, QTableWidgetItem(o.order_number or str(o.id)))
                table.setItem(i, 1, QTableWidgetItem(o.delivery_date.strftime('%d.%m') if o.delivery_date else ''))
                table.setItem(i, 2, QTableWidgetItem(o.delivery_time or ''))
                table.setItem(i, 3, QTableWidgetItem(o.client_name))
                table.setItem(i, 4, QTableWidgetItem(o.recipient_name or ''))
                table.setItem(i, 5, QTableWidgetItem(o.occasion or ''))
                table.setItem(i, 6, QTableWidgetItem(o.bouquet))
                table.setItem(i, 7, QTableWidgetItem(str(o.quantity)))
                table.setItem(i, 8, QTableWidgetItem(f"{o.amount:,.0f} ₽"))
                status_item = QTableWidgetItem(o.status)
                color = status_colors.get(o.status, '#cdd6f4')
                status_item.setForeground(QColor(color))
                table.setItem(i, 9, status_item)
                table.setItem(i, 10, QTableWidgetItem("✅" if o.paid else "❌"))
                table.setItem(i, 11, QTableWidgetItem("📨" if o.has_card else ""))
                table.setItem(i, 12, QTableWidgetItem("🍬" if o.has_sweets else ""))

    def add_order(self):
        if self.role == 'florist':
            QMessageBox.warning(self, "Доступ запрещён", "Флорист не может создавать заказы.")
            return
        with session_scope() as session:
            customers = session.query(Customer).all()
            products = session.query(Product).filter_by(is_active=True).all()
            florists = session.query(Staff).filter(
                Staff.position.in_(['florist', 'manager', 'admin']),
                Staff.is_active == True,
                Staff.store_id == self.store_id
            ).all()
            corporate_clients = session.query(CorporateClient).filter_by(
                store_id=self.store_id, is_active=True
            ).all()
            dlg = OrderDialog(
                customers=customers, products=products, florists=florists,
                corporate_clients=corporate_clients, store_id=self.store_id, parent=self
            )
            if dlg.exec_():
                data = dlg.get_data()
                if not data['customer_id'] and not data['corporate_client_id']:
                    QMessageBox.warning(self, "Ошибка", "Выберите клиента")
                    return
                if not data['customer_id'] and data['corporate_client_id']:
                    corp = session.get(CorporateClient, data['corporate_client_id'])
                    customer = session.query(Customer).filter_by(name=f"[{corp.company_name}]").first()
                    if not customer:
                        customer = Customer(name=f"[{corp.company_name}]", phone=corp.phone or '')
                        session.add(customer)
                        session.flush()
                    data['customer_id'] = customer.id

                # Проверка остатка товара
                if data.get('product_id'):
                    product = session.get(Product, data['product_id'])
                    if product and product.stock is not None:
                        if product.stock < data['quantity']:
                            QMessageBox.warning(self, "Ошибка",
                                f"Недостаточно товара '{product.name}'. Доступно: {product.stock}, запрошено: {data['quantity']}")
                            return
                        # Списание остатка
                        product.stock -= data['quantity']

                # Проверка скоропортящегося товара
                if data.get('product_id'):
                    product = session.get(Product, data['product_id'])
                    if product and product.is_perishable:
                        max_delivery = date.today() + timedelta(days=PERISHABLE_DAYS)
                        if data['delivery_date'] > max_delivery:
                            QMessageBox.warning(self, "Ошибка",
                                f"Скоропортящийся товар нельзя доставлять позже чем через {PERISHABLE_DAYS} дней от сегодня.")
                            return

                # Проверка: статус "доставлен" требует оплаты
                if data['status'] == 'доставлен' and not data['paid']:
                    reply = QMessageBox.question(self, "Предупреждение",
                        "Заказ не оплачен. Установить статус 'доставлен'?",
                        QMessageBox.Yes | QMessageBox.No)
                    if reply == QMessageBox.No:
                        return

                order = Order(**data)
                order.order_number = generate_order_number(session)
                session.add(order)
                self.refresh_orders()
                self.refresh_dashboard()
                self.statusBar().showMessage(f"✅ Заказ {order.order_number} создан", 3000)

    def edit_order(self):
        row = self.orders_table.currentRow()
        if row < 0:
            return
        order_number = self.orders_table.item(row, 0).text()
        with session_scope() as session:
            if order_number.startswith('MUZ-'):
                order = session.query(Order).filter_by(order_number=order_number).first()
            else:
                try:
                    order = session.get(Order, int(order_number))
                except ValueError:
                    QMessageBox.warning(self, "Ошибка", "Неверный номер заказа")
                    return
            if not order:
                QMessageBox.warning(self, "Ошибка", "Заказ не найден")
                return
            if self.role == 'florist':
                staff_id = session.query(Staff).filter_by(user_id=self.user_id).first()
                if not staff_id or order.florist_id != staff_id.id:
                    QMessageBox.warning(self, "Доступ запрещён", "Флорист может редактировать только свои заказы.")
                    return

            old_product_id = order.product_id
            old_quantity = order.quantity
            old_status = order.status

            customers = session.query(Customer).all()
            products = session.query(Product).filter_by(is_active=True).all()
            florists = session.query(Staff).filter(
                Staff.position.in_(['florist', 'manager', 'admin']),
                Staff.is_active == True,
                Staff.store_id == self.store_id
            ).all()
            corporate_clients = session.query(CorporateClient).filter_by(
                store_id=self.store_id, is_active=True
            ).all()
            dlg = OrderDialog(order, customers, products, florists, corporate_clients, self.store_id, self)
            if dlg.exec_():
                data = dlg.get_data()

                # Восстанавливаем старый остаток (если был товар)
                if old_product_id:
                    old_prod = session.get(Product, old_product_id)
                    if old_prod:
                        old_prod.stock = (old_prod.stock or 0) + old_quantity

                # Проверяем новый товар
                if data.get('product_id'):
                    new_prod = session.get(Product, data['product_id'])
                    if new_prod and new_prod.stock is not None:
                        if new_prod.stock < data['quantity']:
                            # Откатываем восстановление старого остатка (возвращаем обратно)
                            if old_product_id:
                                old_prod = session.get(Product, old_product_id)
                                if old_prod:
                                    old_prod.stock = (old_prod.stock or 0) - old_quantity
                            QMessageBox.warning(self, "Ошибка",
                                f"Недостаточно товара '{new_prod.name}'. Доступно: {new_prod.stock}, запрошено: {data['quantity']}")
                            return
                        # Списание нового остатка
                        new_prod.stock -= data['quantity']

                # Проверка скоропортящегося товара
                if data.get('product_id'):
                    product = session.get(Product, data['product_id'])
                    if product and product.is_perishable:
                        max_delivery = date.today() + timedelta(days=PERISHABLE_DAYS)
                        if data['delivery_date'] > max_delivery:
                            QMessageBox.warning(self, "Ошибка",
                                f"Скоропортящийся товар нельзя доставлять позже чем через {PERISHABLE_DAYS} дней от сегодня.")
                            # Откат списания
                            if data.get('product_id'):
                                new_prod = session.get(Product, data['product_id'])
                                if new_prod:
                                    new_prod.stock = (new_prod.stock or 0) + data['quantity']
                            if old_product_id:
                                old_prod = session.get(Product, old_product_id)
                                if old_prod:
                                    old_prod.stock = (old_prod.stock or 0) - old_quantity
                            return

                # Проверка: статус "доставлен" требует оплаты
                if data['status'] == 'доставлен' and not data['paid']:
                    reply = QMessageBox.question(self, "Предупреждение",
                        "Заказ не оплачен. Установить статус 'доставлен'?",
                        QMessageBox.Yes | QMessageBox.No)
                    if reply == QMessageBox.No:
                        # Откат изменений
                        if data.get('product_id'):
                            new_prod = session.get(Product, data['product_id'])
                            if new_prod:
                                new_prod.stock = (new_prod.stock or 0) + data['quantity']
                        if old_product_id:
                            old_prod = session.get(Product, old_product_id)
                            if old_prod:
                                old_prod.stock = (old_prod.stock or 0) - old_quantity
                        return

                # Если статус меняется на "отменён" и есть товар, возвращаем его на склад
                if data['status'] == 'отменён' and data['status'] != old_status and order.product_id:
                    prod = session.get(Product, order.product_id)
                    if prod:
                        prod.stock = (prod.stock or 0) + order.quantity
                        order.product_id = None  # Чтобы повторно не вернуть

                # Обновляем остальные поля заказа
                for k, v in data.items():
                    setattr(order, k, v)
                order.paid = data['paid']
                session.add(order)
                session.flush()
                self.refresh_orders()
                self.refresh_dashboard()
                self.statusBar().showMessage(f"✅ Заказ {order_number} обновлён", 3000)

    def del_order(self):
        row = self.orders_table.currentRow()
        if row < 0:
            return
        order_number = self.orders_table.item(row, 0).text()
        reply = QMessageBox.question(self, "Удаление", f"Удалить заказ {order_number}?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            with session_scope() as session:
                if order_number.startswith('MUZ-'):
                    order = session.query(Order).filter_by(order_number=order_number).first()
                else:
                    try:
                        order = session.get(Order, int(order_number))
                    except ValueError:
                        order = None
                if order:
                    if self.role == 'florist':
                        staff_id = session.query(Staff).filter_by(user_id=self.user_id).first()
                        if not staff_id or order.florist_id != staff_id.id:
                            QMessageBox.warning(self, "Доступ запрещён", "Флорист может удалять только свои заказы.")
                            return
                    if order.product_id:
                        prod = session.get(Product, order.product_id)
                        if prod:
                            prod.stock = (prod.stock or 0) + order.quantity
                    session.delete(order)
                    self.refresh_orders()
                    self.refresh_dashboard()

    def export_orders(self):
        with session_scope() as session:
            orders = session.query(Order).filter(Order.store_id == self.store_id).all()
            filepath, _ = QFileDialog.getSaveFileName(self, "Экспорт заказов", f"orders_{date.today().isoformat()}.xlsx", "Excel (*.xlsx)")
            if filepath:
                try:
                    export_orders_to_excel(orders, filepath)
                    QMessageBox.information(self, "Экспорт", f"✅ Сохранено {len(orders)} заказов")
                except Exception as e:
                    QMessageBox.critical(self, "Ошибка", f"Не удалось экспортировать:\n{str(e)}")

    def import_orders(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Импорт заказов", "", "Excel (*.xlsx)")
        if not filepath:
            return
        try:
            count, errors = import_orders_from_excel(filepath, self.store_id)
            msg = f"✅ Успешно импортировано {count} заказов"
            if errors:
                msg += f"\nОшибок: {len(errors)}"
            QMessageBox.information(self, "Импорт", msg)
            self.refresh_orders()
            self.refresh_dashboard()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка импорта", f"Не удалось импортировать:\n{str(e)}")

    # ---------- Вкладка Клиенты ----------
    def create_customers_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        title = QLabel("👤 Клиенты (физ. лица)")
        title.setObjectName("section-title")
        layout.addWidget(title)
        search_layout = QHBoxLayout()
        self.customer_search = QLineEdit()
        self.customer_search.setPlaceholderText("🔍 Поиск по имени или телефону...")
        self.customer_search.setMaximumWidth(350)
        self.customer_search.textChanged.connect(self.refresh_customers)
        search_layout.addWidget(self.customer_search)
        search_layout.addStretch()
        layout.addLayout(search_layout)
        self.customers_table = QTableWidget()
        self.customers_table.setColumnCount(7)
        self.customers_table.setHorizontalHeaderLabels(["ID", "Имя", "Телефон", "Скидка", "VIP", "Заказов", "Потрачено"])
        self.customers_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.customers_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.customers_table.setAlternatingRowColors(True)
        self.customers_table.doubleClicked.connect(self.edit_customer)
        layout.addWidget(self.customers_table)
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Добавить")
        edit_btn = QPushButton("✏️ Редактировать")
        del_btn = QPushButton("🗑️ Удалить")
        add_btn.clicked.connect(self.add_customer)
        edit_btn.clicked.connect(self.edit_customer)
        del_btn.clicked.connect(self.del_customer)
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(del_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        self.tabs.addTab(tab, "👤 Клиенты")

    def refresh_customers(self):
        search = self.customer_search.text().strip() if hasattr(self, 'customer_search') else ''
        with session_scope() as session:
            query = session.query(Customer)
            if search:
                query = query.filter((Customer.name.like(f"%{search}%")) | (Customer.phone.like(f"%{search}%")))
            customers = query.all()
            self.customers_table.setRowCount(len(customers))
            for i, c in enumerate(customers):
                self.customers_table.setItem(i, 0, QTableWidgetItem(str(c.id)))
                self.customers_table.setItem(i, 1, QTableWidgetItem(c.name))
                self.customers_table.setItem(i, 2, QTableWidgetItem(c.phone or ''))
                self.customers_table.setItem(i, 3, QTableWidgetItem(f"{c.discount}%"))
                vip_item = QTableWidgetItem("⭐" if c.is_vip else "")
                if c.is_vip:
                    vip_item.setForeground(QColor('#f9e2af'))
                self.customers_table.setItem(i, 4, vip_item)
                orders_count = session.query(Order).filter_by(customer_id=c.id).count()
                self.customers_table.setItem(i, 5, QTableWidgetItem(str(orders_count)))
                total_spent = sum(o.amount or 0 for o in c.orders if o.status == 'доставлен')
                self.customers_table.setItem(i, 6, QTableWidgetItem(f"{total_spent:,.0f} ₽"))

    def add_customer(self):
        dlg = CustomerDialog(store_id=self.store_id, parent=self)
        if dlg.exec_():
            data = dlg.get_data()
            if not data['name']:
                QMessageBox.warning(self, "Ошибка", "Введите имя клиента")
                return
            with session_scope() as session:
                new_cust = Customer(**data)
                session.add(new_cust)
                self.refresh_customers()

    def edit_customer(self, row=None, col=None):
        row_idx = row if isinstance(row, int) else self.customers_table.currentRow()
        if row_idx < 0:
            return
        cid = int(self.customers_table.item(row_idx, 0).text())
        with session_scope() as session:
            cust = session.get(Customer, cid)
            if not cust:
                return
            dlg = CustomerDialog(cust, self.store_id, self)
            if dlg.exec_():
                data = dlg.get_data()
                if not data['name']:
                    return
                for k, v in data.items():
                    setattr(cust, k, v)
                self.refresh_customers()

    def del_customer(self):
        row = self.customers_table.currentRow()
        if row < 0:
            return
        cid = int(self.customers_table.item(row, 0).text())
        reply = QMessageBox.question(self, "Удаление", "Удалить клиента?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            with session_scope() as session:
                cust = session.get(Customer, cid)
                if cust:
                    session.delete(cust)
                    self.refresh_customers()

    # ---------- Вкладка Каталог ----------
    def create_products_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        title = QLabel("🌹 Каталог товаров")
        title.setObjectName("section-title")
        layout.addWidget(title)

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Категория:"))
        self.prod_category_combo = QComboBox()
        self.prod_category_combo.addItems(["Все"] + ["букеты", "корзины", "композиции", "подарочные наборы", "свадебные", "траурные", "комнатные растения"])
        self.prod_category_combo.currentTextChanged.connect(self.refresh_products)
        filter_layout.addWidget(self.prod_category_combo)

        filter_layout.addSpacing(20)
        filter_layout.addWidget(QLabel("Поставщик:"))
        self.prod_supplier_combo = QComboBox()
        self.prod_supplier_combo.addItem("Все", None)
        self.prod_supplier_combo.currentIndexChanged.connect(self.refresh_products)
        filter_layout.addWidget(self.prod_supplier_combo)

        filter_layout.addSpacing(20)
        filter_layout.addWidget(QLabel("Сезон:"))
        self.prod_season_combo = QComboBox()
        self.prod_season_combo.addItems(["Все", "круглый год", "весна", "лето", "осень", "зима", "сезонный"])
        self.prod_season_combo.currentTextChanged.connect(self.refresh_products)
        filter_layout.addWidget(self.prod_season_combo)

        filter_layout.addSpacing(20)
        filter_layout.addWidget(QLabel("Поиск:"))
        self.prod_search_edit = QLineEdit()
        self.prod_search_edit.setPlaceholderText("Название, штрихкод...")
        self.prod_search_edit.setMinimumWidth(200)
        self.prod_search_edit.textChanged.connect(self.refresh_products)
        filter_layout.addWidget(self.prod_search_edit)

        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        self.products_table = QTableWidget()
        self.products_table.setColumnCount(13)
        self.products_table.setHorizontalHeaderLabels([
            "ID", "Название", "Категория", "Поставщик", "Ед.", "Цена (₽)",
            "Себест.", "Маржа", "Остаток", "Мин.", "Сезон", "Хит", "Фото"
        ])
        self.products_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.products_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.products_table.setAlternatingRowColors(True)
        self.products_table.doubleClicked.connect(self.edit_product)
        layout.addWidget(self.products_table)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Добавить")
        edit_btn = QPushButton("✏️ Редактировать")
        del_btn = QPushButton("🗑️ Удалить")
        import_btn = QPushButton("📥 Импорт из Excel")
        export_btn = QPushButton("📤 Экспорт в Excel")
        refresh_btn = QPushButton("🔄 Обновить")

        add_btn.clicked.connect(self.add_product)
        edit_btn.clicked.connect(self.edit_product)
        del_btn.clicked.connect(self.del_product)
        import_btn.clicked.connect(self.import_products_from_excel)
        export_btn.clicked.connect(self.export_products_to_excel)
        refresh_btn.clicked.connect(self.refresh_products)

        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(del_btn)
        btn_layout.addWidget(import_btn)
        btn_layout.addWidget(export_btn)
        btn_layout.addWidget(refresh_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.tabs.addTab(tab, "🌹 Каталог")
        self.refresh_product_suppliers()

    def refresh_product_suppliers(self):
        with session_scope() as session:
            suppliers = session.query(Supplier).filter_by(is_active=True).all()
            suppliers_data = [(s.id, s.name) for s in suppliers]
        self.prod_supplier_combo.clear()
        self.prod_supplier_combo.addItem("Все", None)
        for sid, sname in suppliers_data:
            self.prod_supplier_combo.addItem(sname, sid)

    def refresh_products(self):
        category = self.prod_category_combo.currentText()
        supplier_id = self.prod_supplier_combo.currentData()
        season = self.prod_season_combo.currentText()
        search = self.prod_search_edit.text().strip().lower()

        with session_scope() as session:
            query = session.query(Product)
            if category != "Все":
                query = query.filter(Product.category == category)
            if supplier_id:
                query = query.filter(Product.supplier_id == supplier_id)
            if season != "Все":
                query = query.filter(Product.season == season)
            if search:
                query = query.filter(
                    (Product.name.ilike(f"%{search}%")) |
                    (Product.barcode.ilike(f"%{search}%"))
                )
            products = query.order_by(Product.name).all()

            self.products_table.setRowCount(len(products))
            for i, p in enumerate(products):
                self.products_table.setItem(i, 0, QTableWidgetItem(str(p.id)))
                self.products_table.setItem(i, 1, QTableWidgetItem(p.name))
                self.products_table.setItem(i, 2, QTableWidgetItem(p.category or ''))
                supplier_name = p.supplier.name if p.supplier else ''
                self.products_table.setItem(i, 3, QTableWidgetItem(supplier_name))
                self.products_table.setItem(i, 4, QTableWidgetItem(p.unit or 'шт'))
                self.products_table.setItem(i, 5, QTableWidgetItem(f"{p.price:,.2f}"))
                self.products_table.setItem(i, 6, QTableWidgetItem(f"{p.cost_price:,.2f}"))
                margin = p.margin
                margin_item = QTableWidgetItem(f"{margin:,.2f} ({p.margin_percent:.1f}%)")
                margin_item.setForeground(QColor('#a6e3a1') if margin > 0 else QColor('#f38ba8'))
                self.products_table.setItem(i, 7, margin_item)
                # Остаток
                stock_item = QTableWidgetItem(f"{p.stock:,.1f}")
                if p.stock is not None and p.stock <= p.min_stock and p.min_stock > 0:
                    stock_item.setForeground(QColor('#E57373'))  # красный
                elif p.stock is not None and p.stock <= 0:
                    stock_item.setForeground(QColor('#999999'))  # серый
                self.products_table.setItem(i, 8, stock_item)
                self.products_table.setItem(i, 9, QTableWidgetItem(f"{p.min_stock:,.1f}"))
                self.products_table.setItem(i, 10, QTableWidgetItem(p.season or ''))
                pop_item = QTableWidgetItem("⭐" if p.is_popular else "")
                if p.is_popular:
                    pop_item.setForeground(QColor('#f9e2af'))
                self.products_table.setItem(i, 11, pop_item)
                img_item = QTableWidgetItem()
                if p.image_path and os.path.exists(p.image_path):
                    pix = QPixmap(p.image_path)
                    if not pix.isNull():
                        img_item.setData(Qt.DecorationRole, pix.scaled(50, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.products_table.setItem(i, 12, img_item)

    def add_product(self):
        with session_scope() as session:
            suppliers = session.query(Supplier).filter_by(is_active=True).all()
            dlg = ProductDialog(suppliers=suppliers, parent=self)
            if dlg.exec_():
                data = dlg.get_data()
                if not data['name'] or data['price'] <= 0:
                    QMessageBox.warning(self, "Ошибка", "Введите название и цену > 0")
                    return
                if data['barcode']:
                    with session_scope() as sess:
                        existing = sess.query(Product).filter_by(barcode=data['barcode']).first()
                        if existing:
                            QMessageBox.warning(self, "Ошибка", "Товар с таким штрихкодом уже существует")
                            return
                with session_scope() as session:
                    p = Product(**data)
                    session.add(p)
                    self.refresh_products()
                    self.refresh_product_suppliers()

    def edit_product(self):
        row = self.products_table.currentRow()
        if row < 0:
            return
        pid = int(self.products_table.item(row, 0).text())
        with session_scope() as session:
            p = session.get(Product, pid)
            if not p:
                return
            suppliers = session.query(Supplier).filter_by(is_active=True).all()
            dlg = ProductDialog(p, suppliers, self)
            if dlg.exec_():
                data = dlg.get_data()
                if data['barcode']:
                    with session_scope() as sess:
                        existing = sess.query(Product).filter(
                            Product.barcode == data['barcode'],
                            Product.id != pid
                        ).first()
                        if existing:
                            QMessageBox.warning(self, "Ошибка", "Товар с таким штрихкодом уже существует")
                            return
                for k, v in data.items():
                    setattr(p, k, v)
                self.refresh_products()
                self.refresh_product_suppliers()

    def del_product(self):
        row = self.products_table.currentRow()
        if row < 0:
            return
        pid = int(self.products_table.item(row, 0).text())
        reply = QMessageBox.question(self, "Удаление", "Удалить товар?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            with session_scope() as session:
                p = session.get(Product, pid)
                if p:
                    orders = session.query(Order).filter_by(product_id=pid).count()
                    if orders > 0:
                        QMessageBox.warning(self, "Невозможно удалить", f"Товар используется в {orders} заказах")
                        return
                    if p.image_path and os.path.exists(p.image_path):
                        try:
                            os.remove(p.image_path)
                        except:
                            pass
                    session.delete(p)
                    self.refresh_products()
                    self.refresh_product_suppliers()

    def import_products_from_excel(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Выберите файл прайс-листа", "", "Excel (*.xlsx *.xls)")
        if not filepath:
            return
        try:
            imported, updated = import_products_from_excel(filepath)
            QMessageBox.information(self, "Импорт завершён",
                                    f"✅ Добавлено новых товаров: {imported}\n"
                                    f"🔄 Обновлено существующих: {updated}")
            self.refresh_products()
            self.refresh_product_suppliers()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка импорта", f"Не удалось импортировать:\n{str(e)}")

    def export_products_to_excel(self):
        filepath, _ = QFileDialog.getSaveFileName(self, "Сохранить каталог", f"catalog_{date.today().isoformat()}.xlsx", "Excel (*.xlsx)")
        if not filepath:
            return
        try:
            with session_scope() as session:
                products = session.query(Product).all()
                export_products_to_excel(products, filepath)
                QMessageBox.information(self, "Экспорт", f"✅ Сохранено {len(products)} товаров")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось экспортировать:\n{str(e)}")

    # ---------- Вкладка Склад ----------
    def create_inventory_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        title = QLabel("📦 Склад")
        title.setObjectName("section-title")
        layout.addWidget(title)
        self.inventory_table = QTableWidget()
        self.inventory_table.setColumnCount(9)
        self.inventory_table.setHorizontalHeaderLabels([
            "ID", "Название", "Категория", "Остаток", "Ед.", "Мин.", "Партия", "Дней на складе", "Статус"
        ])
        self.inventory_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.inventory_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.inventory_table.setAlternatingRowColors(True)
        self.inventory_table.doubleClicked.connect(self.edit_inventory)
        layout.addWidget(self.inventory_table)
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Добавить")
        edit_btn = QPushButton("✏️ Редактировать")
        del_btn = QPushButton("🗑️ Удалить")
        add_btn.clicked.connect(self.add_inventory)
        edit_btn.clicked.connect(self.edit_inventory)
        del_btn.clicked.connect(self.del_inventory)
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(del_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        self.tabs.addTab(tab, "📦 Склад")

    def refresh_inventory(self):
        with session_scope() as session:
            items = session.query(InventoryItem).filter_by(store_id=self.store_id).all()
            self.inventory_table.setRowCount(len(items))
            for i, item in enumerate(items):
                self.inventory_table.setItem(i, 0, QTableWidgetItem(str(item.id)))
                self.inventory_table.setItem(i, 1, QTableWidgetItem(item.name))
                self.inventory_table.setItem(i, 2, QTableWidgetItem(item.category or ''))
                self.inventory_table.setItem(i, 3, QTableWidgetItem(f"{item.quantity:,.1f}"))
                self.inventory_table.setItem(i, 4, QTableWidgetItem(item.unit))
                self.inventory_table.setItem(i, 5, QTableWidgetItem(f"{item.min_quantity:,.1f}"))
                self.inventory_table.setItem(i, 6, QTableWidgetItem(item.batch_number or '—'))
                self.inventory_table.setItem(i, 7, QTableWidgetItem(str(item.days_on_stock)))
                if item.is_low_stock:
                    status, color = "⚠️ МАЛО", '#f38ba8'
                elif item.days_on_stock > 14 and item.category == 'цветы':
                    status, color = "🟡 Старое", '#f9e2af'
                else:
                    status, color = "✅ ОК", '#a6e3a1'
                status_item = QTableWidgetItem(status)
                status_item.setForeground(QColor(color))
                self.inventory_table.setItem(i, 8, status_item)

    def add_inventory(self):
        with session_scope() as session:
            suppliers = session.query(Supplier).all()
            dlg = InventoryDialog(store_id=self.store_id, suppliers=suppliers, parent=self)
            if dlg.exec_():
                data = dlg.get_data()
                if not data['name']:
                    QMessageBox.warning(self, "Ошибка", "Введите название")
                    return
                item = InventoryItem(**data)
                session.add(item)
                self.refresh_inventory()
                self.refresh_dashboard()

    def edit_inventory(self, row=None, col=None):
        row_idx = row if isinstance(row, int) else self.inventory_table.currentRow()
        if row_idx < 0:
            return
        iid = int(self.inventory_table.item(row_idx, 0).text())
        with session_scope() as session:
            item = session.get(InventoryItem, iid)
            if not item:
                return
            suppliers = session.query(Supplier).all()
            dlg = InventoryDialog(item, self.store_id, suppliers, self)
            if dlg.exec_():
                data = dlg.get_data()
                for k, v in data.items():
                    setattr(item, k, v)
                self.refresh_inventory()
                self.refresh_dashboard()

    def del_inventory(self):
        row = self.inventory_table.currentRow()
        if row < 0:
            return
        iid = int(self.inventory_table.item(row, 0).text())
        reply = QMessageBox.question(self, "Удаление", "Удалить позицию?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            with session_scope() as session:
                item = session.get(InventoryItem, iid)
                if item:
                    session.delete(item)
                    self.refresh_inventory()
                    self.refresh_dashboard()

    # ---------- Вкладка Поставщики ----------
    def create_suppliers_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        title = QLabel("🚚 Поставщики")
        title.setObjectName("section-title")
        layout.addWidget(title)
        self.suppliers_table = QTableWidget()
        self.suppliers_table.setColumnCount(5)
        self.suppliers_table.setHorizontalHeaderLabels(["ID", "Название", "Контакт", "Телефон", "Адрес"])
        self.suppliers_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.suppliers_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.suppliers_table.setAlternatingRowColors(True)
        self.suppliers_table.doubleClicked.connect(self.edit_supplier)
        layout.addWidget(self.suppliers_table)
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Добавить")
        edit_btn = QPushButton("✏️ Редактировать")
        del_btn = QPushButton("🗑️ Удалить")
        add_btn.clicked.connect(self.add_supplier)
        edit_btn.clicked.connect(self.edit_supplier)
        del_btn.clicked.connect(self.del_supplier)
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(del_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        self.tabs.addTab(tab, "🚚 Поставщики")

    def refresh_suppliers(self):
        with session_scope() as session:
            suppliers = session.query(Supplier).all()
            self.suppliers_table.setRowCount(len(suppliers))
            for i, s in enumerate(suppliers):
                self.suppliers_table.setItem(i, 0, QTableWidgetItem(str(s.id)))
                self.suppliers_table.setItem(i, 1, QTableWidgetItem(s.name))
                self.suppliers_table.setItem(i, 2, QTableWidgetItem(s.contact_person or ''))
                self.suppliers_table.setItem(i, 3, QTableWidgetItem(s.phone or ''))
                self.suppliers_table.setItem(i, 4, QTableWidgetItem(s.address or ''))

    def add_supplier(self):
        dlg = SupplierDialog(parent=self)
        if dlg.exec_():
            data = dlg.get_data()
            if not data['name']:
                QMessageBox.warning(self, "Ошибка", "Введите название")
                return
            with session_scope() as session:
                s = Supplier(**data)
                session.add(s)
                self.refresh_suppliers()

    def edit_supplier(self, row=None, col=None):
        row_idx = row if isinstance(row, int) else self.suppliers_table.currentRow()
        if row_idx < 0:
            return
        sid = int(self.suppliers_table.item(row_idx, 0).text())
        with session_scope() as session:
            s = session.get(Supplier, sid)
            if not s:
                return
            dlg = SupplierDialog(s, self)
            if dlg.exec_():
                data = dlg.get_data()
                for k, v in data.items():
                    setattr(s, k, v)
                self.refresh_suppliers()

    def del_supplier(self):
        row = self.suppliers_table.currentRow()
        if row < 0:
            return
        sid = int(self.suppliers_table.item(row, 0).text())
        reply = QMessageBox.question(self, "Удаление", "Удалить поставщика?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            with session_scope() as session:
                s = session.get(Supplier, sid)
                if s:
                    session.delete(s)
                    self.refresh_suppliers()

    # ---------- Вкладка Расходы ----------
    def create_expenses_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        title = QLabel("💸 Расходы")
        title.setObjectName("section-title")
        layout.addWidget(title)
        self.expenses_table = QTableWidget()
        self.expenses_table.setColumnCount(6)
        self.expenses_table.setHorizontalHeaderLabels(["ID", "Дата", "Категория", "Сумма", "Описание", "Поставщик"])
        self.expenses_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.expenses_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.expenses_table.setAlternatingRowColors(True)
        self.expenses_table.doubleClicked.connect(self.edit_expense)
        layout.addWidget(self.expenses_table)
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Добавить")
        edit_btn = QPushButton("✏️ Редактировать")
        del_btn = QPushButton("🗑️ Удалить")
        add_btn.clicked.connect(self.add_expense)
        edit_btn.clicked.connect(self.edit_expense)
        del_btn.clicked.connect(self.del_expense)
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(del_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        self.tabs.addTab(tab, "💸 Расходы")

    def refresh_expenses(self):
        with session_scope() as session:
            expenses = session.query(Expense).filter_by(store_id=self.store_id).order_by(Expense.date.desc()).all()
            self.expenses_table.setRowCount(len(expenses))
            for i, e in enumerate(expenses):
                self.expenses_table.setItem(i, 0, QTableWidgetItem(str(e.id)))
                self.expenses_table.setItem(i, 1, QTableWidgetItem(e.date.strftime('%d.%m.%Y') if e.date else ''))
                self.expenses_table.setItem(i, 2, QTableWidgetItem(e.category))
                amount_item = QTableWidgetItem(f"{e.amount:,.2f} ₽")
                amount_item.setForeground(QColor('#f38ba8'))
                self.expenses_table.setItem(i, 3, amount_item)
                self.expenses_table.setItem(i, 4, QTableWidgetItem(e.description or ''))
                self.expenses_table.setItem(i, 5, QTableWidgetItem(e.supplier.name if e.supplier else ''))

    def add_expense(self):
        with session_scope() as session:
            suppliers = session.query(Supplier).all()
            dlg = ExpenseDialog(store_id=self.store_id, suppliers=suppliers, parent=self)
            if dlg.exec_():
                data = dlg.get_data()
                if not data['amount']:
                    QMessageBox.warning(self, "Ошибка", "Введите сумму")
                    return
                e = Expense(**data)
                session.add(e)
                self.refresh_expenses()
                self.refresh_dashboard()

    def edit_expense(self, row=None, col=None):
        row_idx = row if isinstance(row, int) else self.expenses_table.currentRow()
        if row_idx < 0:
            return
        eid = int(self.expenses_table.item(row_idx, 0).text())
        with session_scope() as session:
            e = session.get(Expense, eid)
            if not e:
                return
            suppliers = session.query(Supplier).all()
            dlg = ExpenseDialog(e, self.store_id, suppliers, self)
            if dlg.exec_():
                data = dlg.get_data()
                for k, v in data.items():
                    setattr(e, k, v)
                self.refresh_expenses()
                self.refresh_dashboard()

    def del_expense(self):
        row = self.expenses_table.currentRow()
        if row < 0:
            return
        eid = int(self.expenses_table.item(row, 0).text())
        reply = QMessageBox.question(self, "Удаление", "Удалить расход?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            with session_scope() as session:
                e = session.get(Expense, eid)
                if e:
                    session.delete(e)
                    self.refresh_expenses()
                    self.refresh_dashboard()

    # ---------- Вкладка Сотрудники ----------
    def create_staff_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        title = QLabel("👥 Сотрудники магазина")
        title.setObjectName("section-title")
        layout.addWidget(title)
        self.staff_table = QTableWidget()
        self.staff_table.setColumnCount(7)
        self.staff_table.setHorizontalHeaderLabels(["ID", "ФИО", "Должность", "Телефон", "Зарплата", "Дата найма", "Активен"])
        self.staff_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.staff_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.staff_table.setAlternatingRowColors(True)
        self.staff_table.doubleClicked.connect(self.edit_staff)
        layout.addWidget(self.staff_table)
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Добавить")
        edit_btn = QPushButton("✏️ Редактировать")
        del_btn = QPushButton("🗑️ Удалить")
        add_btn.clicked.connect(self.add_staff)
        edit_btn.clicked.connect(self.edit_staff)
        del_btn.clicked.connect(self.del_staff)
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(del_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        self.tabs.addTab(tab, "👥 Сотрудники")

    def refresh_staff(self):
        with session_scope() as session:
            staff_list = session.query(Staff).filter_by(store_id=self.store_id).order_by(Staff.full_name).all()
            self.staff_table.setRowCount(len(staff_list))
            for i, s in enumerate(staff_list):
                self.staff_table.setItem(i, 0, QTableWidgetItem(str(s.id)))
                self.staff_table.setItem(i, 1, QTableWidgetItem(s.full_name))
                self.staff_table.setItem(i, 2, QTableWidgetItem(s.position_display))
                self.staff_table.setItem(i, 3, QTableWidgetItem(s.phone or ''))
                self.staff_table.setItem(i, 4, QTableWidgetItem(f"{s.salary:,.0f} ₽" if s.salary else '—'))
                self.staff_table.setItem(i, 5, QTableWidgetItem(s.hire_date.strftime('%d.%m.%Y') if s.hire_date else ''))
                active_item = QTableWidgetItem("✅" if s.is_active else "❌")
                if s.is_active:
                    active_item.setForeground(QColor('#a6e3a1'))
                else:
                    active_item.setForeground(QColor('#f38ba8'))
                self.staff_table.setItem(i, 6, active_item)

    def add_staff(self):
        dlg = StaffDialog(store_id=self.store_id, parent=self)
        if dlg.exec_():
            data = dlg.get_data()
            if not data['full_name']:
                QMessageBox.warning(self, "Ошибка", "Введите ФИО")
                return
            with session_scope() as session:
                staff = Staff(**data)
                session.add(staff)
                self.refresh_staff()

    def edit_staff(self, row=None, col=None):
        row_idx = row if isinstance(row, int) else self.staff_table.currentRow()
        if row_idx < 0:
            return
        sid = int(self.staff_table.item(row_idx, 0).text())
        with session_scope() as session:
            staff = session.get(Staff, sid)
            if not staff:
                return
            dlg = StaffDialog(staff, self.store_id, self)
            if dlg.exec_():
                data = dlg.get_data()
                for k, v in data.items():
                    setattr(staff, k, v)
                self.refresh_staff()

    def del_staff(self):
        row = self.staff_table.currentRow()
        if row < 0:
            return
        sid = int(self.staff_table.item(row, 0).text())
        reply = QMessageBox.question(self, "Удаление", "Удалить сотрудника?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            with session_scope() as session:
                staff = session.get(Staff, sid)
                if staff:
                    session.delete(staff)
                    self.refresh_staff()

    # ---------- Вкладка B2B ----------
    def create_corporate_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        title = QLabel("🏢 Корпоративные клиенты (B2B)")
        title.setObjectName("section-title")
        layout.addWidget(title)
        info = QLabel(
            "💡 Сервис корпоративных поздравлений по подписке: ведём календарь ДР сотрудников, готовим букеты, доставляем. "
            "Доход стабилен и предсказуем."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #88C4A3; padding: 10px; background: #F0F7F3; border-radius: 8px;")
        layout.addWidget(info)
        splitter = QSplitter(Qt.Vertical)
        companies_box = QGroupBox("Компании-клиенты")
        companies_layout = QVBoxLayout(companies_box)
        self.corp_table = QTableWidget()
        self.corp_table.setColumnCount(8)
        self.corp_table.setHorizontalHeaderLabels(["ID", "Компания", "Контакт", "Телефон", "Скидка", "Договор до", "Сотрудников", "Долг"])
        self.corp_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.corp_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.corp_table.setAlternatingRowColors(True)
        self.corp_table.doubleClicked.connect(self.edit_corporate_client)
        companies_layout.addWidget(self.corp_table)
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Добавить компанию")
        edit_btn = QPushButton("✏️ Редактировать")
        del_btn = QPushButton("🗑️ Удалить")
        export_btn = QPushButton("📤 Экспорт КП")
        add_btn.clicked.connect(self.add_corporate_client)
        edit_btn.clicked.connect(self.edit_corporate_client)
        del_btn.clicked.connect(self.del_corporate_client)
        export_btn.clicked.connect(self.export_corporate_proposal)
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(del_btn)
        btn_layout.addWidget(export_btn)
        btn_layout.addStretch()
        companies_layout.addLayout(btn_layout)
        splitter.addWidget(companies_box)

        employees_box = QGroupBox("Сотрудники компании (для автопоздравлений)")
        employees_layout = QVBoxLayout(employees_box)
        self.corp_emp_table = QTableWidget()
        self.corp_emp_table.setColumnCount(6)
        self.corp_emp_table.setHorizontalHeaderLabels(["ID", "ФИО", "Должность", "День рождения", "Телефон", "Букет/Бюджет"])
        self.corp_emp_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.corp_emp_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.corp_emp_table.setAlternatingRowColors(True)
        self.corp_emp_table.doubleClicked.connect(self.edit_corporate_employee)
        employees_layout.addWidget(self.corp_emp_table)
        emp_btn_layout = QHBoxLayout()
        add_emp_btn = QPushButton("➕ Добавить сотрудника")
        edit_emp_btn = QPushButton("✏️ Редактировать")
        del_emp_btn = QPushButton("🗑️ Удалить")
        add_emp_btn.clicked.connect(self.add_corporate_employee)
        edit_emp_btn.clicked.connect(self.edit_corporate_employee)
        del_emp_btn.clicked.connect(self.del_corporate_employee)
        emp_btn_layout.addWidget(add_emp_btn)
        emp_btn_layout.addWidget(edit_emp_btn)
        emp_btn_layout.addWidget(del_emp_btn)
        emp_btn_layout.addStretch()
        employees_layout.addLayout(emp_btn_layout)
        splitter.addWidget(employees_box)

        splitter.setSizes([400, 300])
        layout.addWidget(splitter)
        self.corp_table.itemSelectionChanged.connect(self.on_corp_selected)
        self.tabs.addTab(tab, "🏢 B2B")

    def on_corp_selected(self):
        row = self.corp_table.currentRow()
        if row < 0:
            self.corp_emp_table.setRowCount(0)
            return
        cid = int(self.corp_table.item(row, 0).text())
        with session_scope() as session:
            client = session.get(CorporateClient, cid)
            if not client:
                return
            employees = session.query(CorporateEmployee).filter_by(client_id=cid).all()
            self.corp_emp_table.setRowCount(len(employees))
            for i, emp in enumerate(employees):
                self.corp_emp_table.setItem(i, 0, QTableWidgetItem(str(emp.id)))
                self.corp_emp_table.setItem(i, 1, QTableWidgetItem(emp.full_name))
                self.corp_emp_table.setItem(i, 2, QTableWidgetItem(emp.position or ''))
                self.corp_emp_table.setItem(i, 3, QTableWidgetItem(emp.birthday.strftime('%d.%m') if emp.birthday else ''))
                self.corp_emp_table.setItem(i, 4, QTableWidgetItem(emp.phone or ''))
                pref = f"{emp.preferred_bouquet or ''} {emp.preferred_budget or ''}".strip()
                self.corp_emp_table.setItem(i, 5, QTableWidgetItem(pref or '—'))

    def refresh_corporate(self):
        with session_scope() as session:
            clients = session.query(CorporateClient).filter_by(store_id=self.store_id).all()
            self.corp_table.setRowCount(len(clients))
            for i, c in enumerate(clients):
                self.corp_table.setItem(i, 0, QTableWidgetItem(str(c.id)))
                self.corp_table.setItem(i, 1, QTableWidgetItem(c.company_name))
                self.corp_table.setItem(i, 2, QTableWidgetItem(c.contact_person or ''))
                self.corp_table.setItem(i, 3, QTableWidgetItem(c.phone or ''))
                self.corp_table.setItem(i, 4, QTableWidgetItem(f"{c.discount}%"))
                self.corp_table.setItem(i, 5, QTableWidgetItem(c.contract_until.strftime('%d.%m.%Y') if c.contract_until else ''))
                emp_count = session.query(CorporateEmployee).filter_by(client_id=c.id, is_active=True).count()
                self.corp_table.setItem(i, 6, QTableWidgetItem(str(emp_count)))
                debt = sum(inv.amount for inv in c.invoices if not inv.paid)
                self.corp_table.setItem(i, 7, QTableWidgetItem(f"{debt:,.0f} ₽"))
            self.on_corp_selected()

    def _get_selected_corp_client_id(self):
        row = self.corp_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Ошибка", "Выберите компанию")
            return None
        return int(self.corp_table.item(row, 0).text())

    def add_corporate_client(self):
        with session_scope() as session:
            managers = session.query(Staff).filter_by(position='manager', is_active=True).all()
            dlg = CorporateClientDialog(store_id=self.store_id, managers=managers, parent=self)
            if dlg.exec_():
                data = dlg.get_data()
                if not data['company_name']:
                    QMessageBox.warning(self, "Ошибка", "Введите название компании")
                    return
                client = CorporateClient(**data)
                session.add(client)
                self.refresh_corporate()

    def edit_corporate_client(self):
        cid = self._get_selected_corp_client_id()
        if cid is None:
            return
        with session_scope() as session:
            client = session.get(CorporateClient, cid)
            if not client:
                return
            managers = session.query(Staff).filter_by(position='manager', is_active=True).all()
            dlg = CorporateClientDialog(client, self.store_id, managers, self)
            if dlg.exec_():
                data = dlg.get_data()
                for k, v in data.items():
                    setattr(client, k, v)
                self.refresh_corporate()

    def del_corporate_client(self):
        cid = self._get_selected_corp_client_id()
        if cid is None:
            return
        reply = QMessageBox.question(self, "Удаление", "Удалить корпоративного клиента и всех его сотрудников?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            with session_scope() as session:
                client = session.get(CorporateClient, cid)
                if client:
                    session.delete(client)
                    self.refresh_corporate()

    def export_corporate_proposal(self):
        cid = self._get_selected_corp_client_id()
        if cid is None:
            return
        with session_scope() as session:
            client = session.get(CorporateClient, cid)
            if not client:
                return
            filepath, _ = QFileDialog.getSaveFileName(self, "Экспорт КП", f"КП_{client.company_name}.xlsx", "Excel (*.xlsx)")
            if filepath:
                try:
                    export_corporate_proposal(client, filepath)
                    QMessageBox.information(self, "Экспорт", f"✅ КП сохранено в {filepath}")
                except Exception as e:
                    QMessageBox.critical(self, "Ошибка", str(e))

    def add_corporate_employee(self):
        cid = self._get_selected_corp_client_id()
        if cid is None:
            return
        dlg = CorporateEmployeeDialog(parent=self)
        if dlg.exec_():
            data = dlg.get_data()
            if not data['full_name']:
                QMessageBox.warning(self, "Ошибка", "Введите ФИО")
                return
            with session_scope() as session:
                emp = CorporateEmployee(client_id=cid, **data)
                session.add(emp)
                self.on_corp_selected()
                self.refresh_corporate()

    def edit_corporate_employee(self):
        cid = self._get_selected_corp_client_id()
        if cid is None:
            return
        row = self.corp_emp_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Ошибка", "Выберите сотрудника")
            return
        eid = int(self.corp_emp_table.item(row, 0).text())
        with session_scope() as session:
            emp = session.get(CorporateEmployee, eid)
            if not emp:
                return
            dlg = CorporateEmployeeDialog(emp, self)
            if dlg.exec_():
                data = dlg.get_data()
                for k, v in data.items():
                    setattr(emp, k, v)
                self.on_corp_selected()

    def del_corporate_employee(self):
        row = self.corp_emp_table.currentRow()
        if row < 0:
            return
        eid = int(self.corp_emp_table.item(row, 0).text())
        reply = QMessageBox.question(self, "Удаление", "Удалить сотрудника?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            with session_scope() as session:
                emp = session.get(CorporateEmployee, eid)
                if emp:
                    session.delete(emp)
                    self.on_corp_selected()
                    self.refresh_corporate()

    # ---------- Вкладка Счета ----------
    def create_invoices_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        title = QLabel("💳 Счета для корпоративных клиентов")
        title.setObjectName("section-title")
        layout.addWidget(title)
        self.invoices_table = QTableWidget()
        self.invoices_table.setColumnCount(7)
        self.invoices_table.setHorizontalHeaderLabels(["Номер", "Дата", "Срок", "Компания", "Сумма", "Статус", "Описание"])
        self.invoices_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.invoices_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.invoices_table.setAlternatingRowColors(True)
        self.invoices_table.doubleClicked.connect(self.edit_invoice)
        layout.addWidget(self.invoices_table)
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Выставить счёт")
        edit_btn = QPushButton("✏️ Редактировать")
        toggle_btn = QPushButton("💰 Отметить оплату")
        del_btn = QPushButton("🗑️ Удалить")
        add_btn.clicked.connect(self.add_invoice)
        edit_btn.clicked.connect(self.edit_invoice)
        toggle_btn.clicked.connect(self.toggle_invoice_paid)
        del_btn.clicked.connect(self.del_invoice)
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(toggle_btn)
        btn_layout.addWidget(del_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        self.tabs.addTab(tab, "💳 Счета")

    def refresh_invoices(self):
        with session_scope() as session:
            invoices = session.query(Invoice).join(CorporateClient).filter(
                CorporateClient.store_id == self.store_id
            ).order_by(Invoice.issue_date.desc()).all()
            self.invoices_table.setRowCount(len(invoices))
            today = date.today()
            for i, inv in enumerate(invoices):
                self.invoices_table.setItem(i, 0, QTableWidgetItem(inv.invoice_number or ''))
                self.invoices_table.setItem(i, 1, QTableWidgetItem(inv.issue_date.strftime('%d.%m.%Y') if inv.issue_date else ''))
                self.invoices_table.setItem(i, 2, QTableWidgetItem(inv.due_date.strftime('%d.%m.%Y') if inv.due_date else ''))
                self.invoices_table.setItem(i, 3, QTableWidgetItem(inv.corporate_client.company_name if inv.corporate_client else ''))
                self.invoices_table.setItem(i, 4, QTableWidgetItem(f"{inv.amount:,.2f} ₽"))
                if inv.paid:
                    status, color = "✅ Оплачен", '#a6e3a1'
                elif inv.due_date and inv.due_date < today:
                    status, color = "🔴 Просрочен", '#f38ba8'
                else:
                    status, color = "⏳ Ожидает", '#f9e2af'
                status_item = QTableWidgetItem(status)
                status_item.setForeground(QColor(color))
                self.invoices_table.setItem(i, 5, status_item)
                self.invoices_table.setItem(i, 6, QTableWidgetItem(inv.description or ''))

    def add_invoice(self):
        with session_scope() as session:
            clients = session.query(CorporateClient).filter_by(store_id=self.store_id, is_active=True).all()
            dlg = InvoiceDialog(clients=clients, parent=self)
            if dlg.exec_():
                data = dlg.get_data()
                if not data['corporate_client_id']:
                    return
                invoice = Invoice(**data)
                invoice.invoice_number = generate_invoice_number(session)
                session.add(invoice)
                self.refresh_invoices()
                self.refresh_dashboard()

    def edit_invoice(self, row=None, col=None):
        row_idx = row if isinstance(row, int) else self.invoices_table.currentRow()
        if row_idx < 0:
            return
        inv_number = self.invoices_table.item(row_idx, 0).text()
        with session_scope() as session:
            invoice = session.query(Invoice).filter_by(invoice_number=inv_number).first()
            if not invoice:
                return
            clients = session.query(CorporateClient).filter_by(store_id=self.store_id, is_active=True).all()
            dlg = InvoiceDialog(invoice, clients, self)
            if dlg.exec_():
                data = dlg.get_data()
                for k, v in data.items():
                    setattr(invoice, k, v)
                self.refresh_invoices()
                self.refresh_dashboard()

    def toggle_invoice_paid(self):
        row = self.invoices_table.currentRow()
        if row < 0:
            return
        inv_number = self.invoices_table.item(row, 0).text()
        with session_scope() as session:
            invoice = session.query(Invoice).filter_by(invoice_number=inv_number).first()
            if invoice:
                invoice.paid = not invoice.paid
                invoice.paid_date = date.today() if invoice.paid else None
                self.refresh_invoices()
                self.refresh_dashboard()

    def del_invoice(self):
        row = self.invoices_table.currentRow()
        if row < 0:
            return
        inv_number = self.invoices_table.item(row, 0).text()
        reply = QMessageBox.question(self, "Удаление", "Удалить счёт?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            with session_scope() as session:
                invoice = session.query(Invoice).filter_by(invoice_number=inv_number).first()
                if invoice:
                    session.delete(invoice)
                    self.refresh_invoices()
                    self.refresh_dashboard()

    # ---------- Вкладка Праздники ----------
    def create_holidays_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        title = QLabel("🎉 Праздники и массовые заказы")
        title.setObjectName("section-title")
        layout.addWidget(title)
        info = QLabel("Здесь вы можете управлять праздниками и создавать массовые заказы для всех сотрудников корпоративных клиентов.")
        info.setWordWrap(True)
        info.setStyleSheet("color: #88C4A3; padding: 10px; background: #F0F7F3; border-radius: 8px;")
        layout.addWidget(info)
        self.holidays_table = QTableWidget()
        self.holidays_table.setColumnCount(5)
        self.holidays_table.setHorizontalHeaderLabels(["ID", "Название", "Дата", "Дней подготовки", "Заметки"])
        self.holidays_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.holidays_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.holidays_table.setAlternatingRowColors(True)
        layout.addWidget(self.holidays_table)
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Добавить праздник")
        edit_btn = QPushButton("✏️ Редактировать")
        del_btn = QPushButton("🗑️ Удалить")
        mass_btn = QPushButton("🎁 Создать массовые заказы")
        mass_btn.setStyleSheet("background-color: #88C4A3; color: #FFFFFF; font-weight: bold;")
        add_btn.clicked.connect(self.add_holiday)
        edit_btn.clicked.connect(self.edit_holiday)
        del_btn.clicked.connect(self.del_holiday)
        mass_btn.clicked.connect(self.create_mass_orders_dialog)
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(del_btn)
        btn_layout.addWidget(mass_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        self.tabs.addTab(tab, "🎉 Праздники")

    def refresh_holidays(self):
        with session_scope() as session:
            holidays = session.query(Holiday).order_by(Holiday.date_month, Holiday.date_day).all()
            self.holidays_table.setRowCount(len(holidays))
            months = ['', 'Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']
            for i, h in enumerate(holidays):
                self.holidays_table.setItem(i, 0, QTableWidgetItem(str(h.id)))
                self.holidays_table.setItem(i, 1, QTableWidgetItem(h.name))
                self.holidays_table.setItem(i, 2, QTableWidgetItem(f"{h.date_day} {months[h.date_month]}"))
                self.holidays_table.setItem(i, 3, QTableWidgetItem(str(h.days_before)))
                self.holidays_table.setItem(i, 4, QTableWidgetItem(h.notes or ''))

    def add_holiday(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Новый праздник")
        dlg.setMinimumWidth(400)
        layout = QFormLayout(dlg)
        name_edit = QLineEdit()
        month_combo = QComboBox()
        months = ['', 'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
                  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
        for i, m in enumerate(months[1:], 1):
            month_combo.addItem(m, i)
        day_spin = QSpinBox()
        day_spin.setRange(1, 31)
        days_before = QSpinBox()
        days_before.setRange(1, 60)
        days_before.setValue(7)
        notes_edit = QTextEdit()
        notes_edit.setMaximumHeight(80)
        layout.addRow("Название:", name_edit)
        layout.addRow("Месяц:", month_combo)
        layout.addRow("День:", day_spin)
        layout.addRow("За сколько дней готовить:", days_before)
        layout.addRow("Заметки:", notes_edit)
        btn_box = QHBoxLayout()
        ok_btn = QPushButton("💾 Сохранить")
        cancel_btn = QPushButton("Отмена")
        ok_btn.clicked.connect(dlg.accept)
        cancel_btn.clicked.connect(dlg.reject)
        btn_box.addWidget(ok_btn)
        btn_box.addWidget(cancel_btn)
        layout.addRow(btn_box)
        if dlg.exec_():
            if not name_edit.text():
                return
            with session_scope() as session:
                h = Holiday(
                    name=name_edit.text(),
                    date_month=month_combo.currentData(),
                    date_day=day_spin.value(),
                    days_before=days_before.value(),
                    notes=notes_edit.toPlainText()
                )
                session.add(h)
                self.refresh_holidays()

    def edit_holiday(self):
        row = self.holidays_table.currentRow()
        if row < 0:
            return
        hid = int(self.holidays_table.item(row, 0).text())
        with session_scope() as session:
            h = session.get(Holiday, hid)
            if not h:
                return
            dlg = QDialog(self)
            dlg.setWindowTitle("Редактировать праздник")
            dlg.setMinimumWidth(400)
            layout = QFormLayout(dlg)
            name_edit = QLineEdit(h.name)
            month_combo = QComboBox()
            months = ['', 'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
                      'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
            for i, m in enumerate(months[1:], 1):
                month_combo.addItem(m, i)
            month_combo.setCurrentIndex(h.date_month - 1)
            day_spin = QSpinBox()
            day_spin.setRange(1, 31)
            day_spin.setValue(h.date_day)
            days_before = QSpinBox()
            days_before.setRange(1, 60)
            days_before.setValue(h.days_before)
            notes_edit = QTextEdit()
            notes_edit.setPlainText(h.notes or '')
            notes_edit.setMaximumHeight(80)
            layout.addRow("Название:", name_edit)
            layout.addRow("Месяц:", month_combo)
            layout.addRow("День:", day_spin)
            layout.addRow("За сколько дней:", days_before)
            layout.addRow("Заметки:", notes_edit)
            btn_box = QHBoxLayout()
            ok_btn = QPushButton("💾 Сохранить")
            cancel_btn = QPushButton("Отмена")
            ok_btn.clicked.connect(dlg.accept)
            cancel_btn.clicked.connect(dlg.reject)
            btn_box.addWidget(ok_btn)
            btn_box.addWidget(cancel_btn)
            layout.addRow(btn_box)
            if dlg.exec_():
                h.name = name_edit.text()
                h.date_month = month_combo.currentData()
                h.date_day = day_spin.value()
                h.days_before = days_before.value()
                h.notes = notes_edit.toPlainText()
                self.refresh_holidays()

    def del_holiday(self):
        row = self.holidays_table.currentRow()
        if row < 0:
            return
        hid = int(self.holidays_table.item(row, 0).text())
        reply = QMessageBox.question(self, "Удаление", "Удалить праздник?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            with session_scope() as session:
                h = session.get(Holiday, hid)
                if h:
                    session.delete(h)
                    self.refresh_holidays()

    def create_mass_orders_dialog(self):
        with session_scope() as session:
            holidays = session.query(Holiday).all()
            if not holidays:
                QMessageBox.warning(self, "Внимание", "Сначала добавьте праздники")
                return
            dlg = QDialog(self)
            dlg.setWindowTitle("Массовые заказы на праздник")
            dlg.setMinimumWidth(500)
            layout = QFormLayout(dlg)
            holiday_combo = QComboBox()
            months = ['', 'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
                      'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
            for h in holidays:
                holiday_combo.addItem(f"{h.name} ({h.date_day} {months[h.date_month]})", h.id)
            year_spin = QSpinBox()
            year_spin.setRange(2024, 2030)
            year_spin.setValue(date.today().year)
            bouquet_edit = QLineEdit()
            bouquet_edit.setPlaceholderText("Например: Весенний букет")
            amount_spin = QDoubleSpinBox()
            amount_spin.setRange(0, 100000)
            amount_spin.setPrefix("₽ ")
            amount_spin.setValue(0)
            target_combo = QComboBox()
            target_combo.addItems(["Все сотрудники", "Только женщины (8 марта)", "Только мужчины (23 февраля)"])
            layout.addRow("Праздник:", holiday_combo)
            layout.addRow("Год:", year_spin)
            layout.addRow("Букет (название):", bouquet_edit)
            layout.addRow("Сумма (0 - использовать цену компании):", amount_spin)
            layout.addRow("Получатели:", target_combo)
            btn_box = QHBoxLayout()
            ok_btn = QPushButton("🎁 Создать заказы")
            cancel_btn = QPushButton("Отмена")
            ok_btn.clicked.connect(dlg.accept)
            cancel_btn.clicked.connect(dlg.reject)
            btn_box.addWidget(ok_btn)
            btn_box.addWidget(cancel_btn)
            layout.addRow(btn_box)
            if dlg.exec_():
                holiday_id = holiday_combo.currentData()
                year = year_spin.value()
                bouquet = bouquet_edit.text().strip()
                amount = amount_spin.value()
                target_text = target_combo.currentText()
                target_gender = 'all'
                if "Только женщины" in target_text:
                    target_gender = 'female'
                elif "Только мужчины" in target_text:
                    target_gender = 'male'
                count, msg = create_mass_orders(holiday_id, year, bouquet, amount, target_gender)
                QMessageBox.information(self, "Результат", msg)
                self.refresh_all()

    # ---------- Вкладка Статистика ----------
    def create_statistics_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        title = QLabel("📊 Аналитика и отчёты")
        title.setObjectName("section-title")
        layout.addWidget(title)

        monthly_group = QGroupBox("📈 Месячная динамика (за последние 6 месяцев)")
        monthly_layout = QVBoxLayout(monthly_group)
        self.monthly_table = QTableWidget()
        self.monthly_table.setColumnCount(5)
        self.monthly_table.setHorizontalHeaderLabels(["Месяц", "Выручка (₽)", "Прибыль (₽)", "Расходы (₽)", "Корп. доход (₽)"])
        self.monthly_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.monthly_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.monthly_table.setAlternatingRowColors(True)
        self.monthly_table.setMaximumHeight(200)
        monthly_layout.addWidget(self.monthly_table)
        layout.addWidget(monthly_group)

        abc_group = QGroupBox("📈 ABC-анализ товаров (какие приносят 80% прибыли)")
        abc_layout = QVBoxLayout(abc_group)
        self.abc_table = QTableWidget()
        self.abc_table.setColumnCount(6)
        self.abc_table.setHorizontalHeaderLabels(["Класс", "Товар", "Продано шт.", "Выручка (₽)", "Прибыль (₽)", "Доля прибыли"])
        self.abc_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.abc_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.abc_table.setMaximumHeight(200)
        abc_layout.addWidget(self.abc_table)
        layout.addWidget(abc_group)

        status_group = QGroupBox("📊 Статусы заказов")
        status_layout = QVBoxLayout(status_group)
        self.status_table = QTableWidget()
        self.status_table.setColumnCount(2)
        self.status_table.setHorizontalHeaderLabels(["Статус", "Количество"])
        self.status_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.status_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.status_table.setMaximumHeight(150)
        status_layout.addWidget(self.status_table)
        layout.addWidget(status_group)

        refresh_btn = QPushButton("🔄 Обновить аналитику")
        refresh_btn.clicked.connect(self.refresh_statistics)
        layout.addWidget(refresh_btn)

        self.tabs.addTab(tab, "📊 Статистика")

    def refresh_statistics(self):
        self.statusBar().showMessage("⏳ Загрузка аналитики...")
        try:
            self._compute_stats()
            self.statusBar().showMessage("✅ Аналитика обновлена", 3000)
        except Exception as e:
            logger.error(f"Ошибка в статистике: {e}", exc_info=True)
            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить аналитику: {str(e)}")
            self.statusBar().showMessage("❌ Ошибка загрузки аналитики")

    def _compute_stats(self):
        with session_scope() as session:
            today = date.today()
            months_data = []
            for i in range(5, -1, -1):
                m = today.month - i
                y = today.year
                while m <= 0:
                    m += 12
                    y -= 1
                start = date(y, m, 1)
                end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
                orders = session.query(Order).filter(
                    Order.store_id == self.store_id,
                    Order.delivery_date >= start,
                    Order.delivery_date < end,
                    Order.status == 'доставлен'
                ).all()
                rev = sum(o.amount or 0 for o in orders)
                cost = sum(o.cost_price or 0 for o in orders)
                exp = sum(e.amount for e in session.query(Expense).filter(
                    Expense.store_id == self.store_id,
                    Expense.date >= start, Expense.date < end
                ).all())
                corp_rev = sum(o.amount or 0 for o in orders if o.corporate_client_id is not None)
                months_data.append((start.strftime('%b %Y'), rev, rev - cost - exp, exp, corp_rev))

            self.monthly_table.setRowCount(len(months_data))
            for i, (month, rev, profit, exp, corp_rev) in enumerate(months_data):
                self.monthly_table.setItem(i, 0, QTableWidgetItem(month))
                self.monthly_table.setItem(i, 1, QTableWidgetItem(f"{rev:,.0f}"))
                self.monthly_table.setItem(i, 2, QTableWidgetItem(f"{profit:,.0f}"))
                self.monthly_table.setItem(i, 3, QTableWidgetItem(f"{exp:,.0f}"))
                self.monthly_table.setItem(i, 4, QTableWidgetItem(f"{corp_rev:,.0f}"))

            # ABC-анализ
            products = session.query(Product).all()
            product_stats = []
            for p in products:
                orders_p = session.query(Order).filter(
                    Order.product_id == p.id,
                    Order.status == 'доставлен'
                ).all()
                qty = sum(o.quantity or 0 for o in orders_p)
                revenue = sum(o.amount or 0 for o in orders_p)
                profit = sum(o.profit for o in orders_p)
                if qty > 0 or revenue > 0:
                    product_stats.append((p, qty, revenue, profit))
            product_stats.sort(key=lambda x: x[3], reverse=True)
            total_profit = sum(x[3] for x in product_stats)
            abc_data = []
            if total_profit > 0:
                cum = 0
                for p, qty, rev, prof in product_stats:
                    cum += prof
                    pct = cum / total_profit * 100
                    if pct <= 80:
                        cls = 'A'
                    elif pct <= 95:
                        cls = 'B'
                    else:
                        cls = 'C'
                    abc_data.append((cls, p.name, qty, rev, prof, prof / total_profit * 100))
            else:
                abc_data = [('—', 'Нет данных', 0, 0, 0, 0)]

            self.abc_table.setRowCount(len(abc_data))
            for i, (cls, name, qty, rev, prof, pct) in enumerate(abc_data):
                cls_item = QTableWidgetItem(cls)
                if cls == 'A':
                    cls_item.setForeground(QColor('#a6e3a1'))
                elif cls == 'B':
                    cls_item.setForeground(QColor('#f9e2af'))
                else:
                    cls_item.setForeground(QColor('#f38ba8'))
                self.abc_table.setItem(i, 0, cls_item)
                self.abc_table.setItem(i, 1, QTableWidgetItem(name))
                self.abc_table.setItem(i, 2, QTableWidgetItem(str(qty)))
                self.abc_table.setItem(i, 3, QTableWidgetItem(f"{rev:,.0f}"))
                self.abc_table.setItem(i, 4, QTableWidgetItem(f"{prof:,.0f}"))
                self.abc_table.setItem(i, 5, QTableWidgetItem(f"{pct:.1f}%"))

            # Статусы заказов
            status_counts = {}
            for st in OrderDialog.STATUSES:
                status_counts[st] = session.query(Order).filter_by(store_id=self.store_id, status=st).count()
            self.status_table.setRowCount(len(status_counts))
            for i, (st, cnt) in enumerate(status_counts.items()):
                self.status_table.setItem(i, 0, QTableWidgetItem(st))
                self.status_table.setItem(i, 1, QTableWidgetItem(str(cnt)))

    # ---------- Управление пользователями ----------
    def show_users(self):
        if self.role != 'admin':
            QMessageBox.warning(self, "Доступ запрещён", "Только администратор может управлять пользователями")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("👥 Управление пользователями")
        dlg.setMinimumSize(700, 500)
        layout = QVBoxLayout(dlg)
        table = QTableWidget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["ID", "Логин", "ФИО", "Роль", "Активен"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(table)

        def refresh():
            with session_scope() as session:
                users = session.query(User).all()
                table.setRowCount(len(users))
                for i, u in enumerate(users):
                    table.setItem(i, 0, QTableWidgetItem(str(u.id)))
                    table.setItem(i, 1, QTableWidgetItem(u.username))
                    table.setItem(i, 2, QTableWidgetItem(u.full_name or ''))
                    table.setItem(i, 3, QTableWidgetItem(u.role))
                    table.setItem(i, 4, QTableWidgetItem("✅" if u.is_active else "❌"))
        refresh()
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Добавить")
        toggle_btn = QPushButton("🔒 Вкл/Выкл")
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(toggle_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        def add_user():
            new_dlg = QDialog(dlg)
            new_dlg.setWindowTitle("Новый пользователь")
            new_dlg.setMinimumWidth(400)
            fl = QFormLayout(new_dlg)
            username_edit = QLineEdit()
            fullname_edit = QLineEdit()
            password_edit = QLineEdit()
            password_edit.setEchoMode(QLineEdit.Password)
            role_combo = QComboBox()
            role_combo.addItems(["admin", "manager", "florist"])
            fl.addRow("Логин:", username_edit)
            fl.addRow("ФИО:", fullname_edit)
            fl.addRow("Пароль:", password_edit)
            fl.addRow("Роль:", role_combo)
            bb = QHBoxLayout()
            ok = QPushButton("Создать")
            cancel = QPushButton("Отмена")
            ok.clicked.connect(new_dlg.accept)
            cancel.clicked.connect(new_dlg.reject)
            bb.addWidget(ok)
            bb.addWidget(cancel)
            fl.addRow(bb)
            if new_dlg.exec_():
                if not username_edit.text() or not password_edit.text():
                    QMessageBox.warning(new_dlg, "Ошибка", "Заполните логин и пароль")
                    return
                with session_scope() as session:
                    u = User(
                        username=username_edit.text(),
                        full_name=fullname_edit.text(),
                        password_hash=hash_password(password_edit.text()),
                        role=role_combo.currentText()
                    )
                    session.add(u)
                    refresh()

        def toggle_user():
            row = table.currentRow()
            if row < 0:
                return
            uid = int(table.item(row, 0).text())
            with session_scope() as session:
                u = session.get(User, uid)
                if u.id == self.user_id:
                    QMessageBox.warning(dlg, "Ошибка", "Нельзя деактивировать самого себя")
                    return
                u.is_active = not u.is_active
                refresh()

        add_btn.clicked.connect(add_user)
        toggle_btn.clicked.connect(toggle_user)
        dlg.exec_()

    # ---------- Выход ----------
    def logout(self):
        reply = QMessageBox.question(self, "Выход", "Выйти из системы?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            if hasattr(self, 'scheduler'):
                try:
                    self.scheduler.shutdown()
                except:
                    pass
            Session.remove()
            self.close()
            login = LoginDialog()
            if login.exec_() == QDialog.Accepted:
                new_window = MainWindow(login.user_data)
                new_window.show()
                self._next_window = new_window
            else:
                QApplication.quit()

    def closeEvent(self, event):
        if hasattr(self, 'scheduler'):
            try:
                self.scheduler.shutdown()
            except:
                pass
        Session.remove()
        event.accept()

# --- 11. Точка входа ---
def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    with session_scope() as session:
        if session.query(Store).count() == 0:
            store = Store(
                name="Muzflowers",
                address="г. Москва, ул. Земляной Вал, 39/1с1",
                phone="+7 (995) 152-21-31"
            )
            session.add(store)
            logger.info("✅ Создан магазин Muzflowers")

        if session.query(User).count() == 0:
            admin = User(username='admin', password_hash=hash_password('admin123'), full_name='Администратор', role='admin')
            sergey = User(username='sergey', password_hash=hash_password('sergey123'), full_name='Сергей', role='admin')
            nikolay = User(username='nikolay', password_hash=hash_password('nikolay123'), full_name='Николай', role='admin')
            mikhail = User(username='mikhail', password_hash=hash_password('mikhail123'), full_name='Михаил', role='manager')
            klim = User(username='klim', password_hash=hash_password('klim123'), full_name='Клим', role='manager')
            natalia_bobrova = User(username='natalia_bobrova', password_hash=hash_password('natalia123'), full_name='Наталья Боброва', role='florist')
            natalia = User(username='natalia', password_hash=hash_password('natalia123'), full_name='Наталья', role='florist')
            session.add_all([admin, sergey, nikolay, mikhail, klim, natalia_bobrova, natalia])
            logger.info("✅ Созданы пользователи")

        store = session.query(Store).first()
        if store and session.query(Staff).count() == 0:
            admin_user = session.query(User).filter_by(username='admin').first()
            sergey_user = session.query(User).filter_by(username='sergey').first()
            nikolay_user = session.query(User).filter_by(username='nikolay').first()
            mikhail_user = session.query(User).filter_by(username='mikhail').first()
            klim_user = session.query(User).filter_by(username='klim').first()
            natalia_bobrova_user = session.query(User).filter_by(username='natalia_bobrova').first()
            natalia_user = session.query(User).filter_by(username='natalia').first()

            staff_admin = Staff(user_id=admin_user.id, store_id=store.id, full_name='Администратор', position='admin', phone='+7 (900) 111-11-11', salary=100000)
            staff_sergey = Staff(user_id=sergey_user.id, store_id=store.id, full_name='Сергей', position='admin', phone='+7 (916) 162-21-31', salary=100000)
            staff_nikolay = Staff(user_id=nikolay_user.id, store_id=store.id, full_name='Николай', position='admin', phone='+7 (916) 255-86-84', salary=100000)
            staff_mikhail = Staff(user_id=mikhail_user.id, store_id=store.id, full_name='Михаил', position='manager', phone='+7 (961) 352-89-10', salary=80000)
            staff_klim = Staff(user_id=klim_user.id, store_id=store.id, full_name='Клим', position='manager', phone='+7 (916) 198-51-56', salary=80000)
            staff_natalia_bobrova = Staff(user_id=natalia_bobrova_user.id, store_id=store.id, full_name='Наталья Боброва', position='florist', phone='+7 (917) 549-49-41', salary=60000)
            staff_natalia = Staff(user_id=natalia_user.id, store_id=store.id, full_name='Наталья', position='florist', phone='+7 (995) 152-21-31', salary=60000)
            session.add_all([staff_admin, staff_sergey, staff_nikolay, staff_mikhail, staff_klim, staff_natalia_bobrova, staff_natalia])
            logger.info("✅ Созданы сотрудники")

        if session.query(Holiday).count() == 0:
            holidays = [
                Holiday(name="8 Марта", date_month=3, date_day=8, days_before=14, notes="Международный женский день"),
                Holiday(name="14 Февраля", date_month=2, date_day=14, days_before=7, notes="День всех влюблённых"),
                Holiday(name="23 Февраля", date_month=2, date_day=23, days_before=7, notes="День защитника Отечества"),
                Holiday(name="9 Мая", date_month=5, date_day=9, days_before=10, notes="День Победы"),
                Holiday(name="1 Сентября", date_month=9, date_day=1, days_before=14, notes="День знаний"),
                Holiday(name="Новый год", date_month=12, date_day=31, days_before=14, notes="Главный праздник года"),
            ]
            session.add_all(holidays)
            logger.info("✅ Созданы праздники")

        if session.query(Setting).count() == 0:
            defaults = [
                ('card_price', '100'),
                ('sweets_price', '200'),
                ('default_budget', '3500.0'),
                ('default_markup', '1.7')
            ]
            for key, value in defaults:
                session.add(Setting(key=key, value=value))
            logger.info("✅ Созданы настройки по умолчанию")

    login = LoginDialog()
    if login.exec_() == QDialog.Accepted:
        window = MainWindow(login.user_data)
        window.show()
        sys.exit(app.exec_())
    else:
        sys.exit()

if __name__ == '__main__':
    main()