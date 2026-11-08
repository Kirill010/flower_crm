"""База данных: подключение, миграция схемы, резервные копии.

Старая версия приложения хранила данные в flower.db без версии схемы.
migrate() создаёт недостающие таблицы и ДОБАВЛЯЕТ недостающие колонки,
ничего не удаляя и не переименовывая. Перед первой миграцией старой базы
делается резервная копия в папке backups/.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker

from models import Base

log = logging.getLogger("crm.db")

APP_DIR = Path(__file__).resolve().parent
DEFAULT_DB = APP_DIR / "flower.db"
SCHEMA_VERSION = 2   # 0 — база старой версии (до перехода на ТЗ), 2 — текущая

# Значение по умолчанию для старых строк при добавлении колонки.
# Все компании из старой базы уже работали как клиенты.
LEGACY_DEFAULTS = {("corporate_clients", "stage"): "Клиент"}

# Праздники для новой (пустой) базы. День — это день ДОСТАВКИ; можно править во вкладке «Праздники».
DEFAULT_HOLIDAYS = [
    ("23 Февраля", 2, 23, 7, "male"),
    ("8 Марта", 3, 8, 7, "female"),
    ("Новый год", 12, 28, 10, "all"),
]

_engine = None
_factory = None
_db_path: Path | None = None


# ------------------------------------------------------------------ подключение
def db_path() -> Path:
    if _db_path is None:
        raise RuntimeError("База не инициализирована: вызовите init_db()")
    return _db_path


def init_db(path: str | os.PathLike | None = None, *, backup: bool = True) -> Path:
    """Открывает (и при необходимости мигрирует) базу. Можно вызывать повторно."""
    global _engine, _factory, _db_path
    if _engine is not None:
        _engine.dispose()
    _db_path = Path(path or os.environ.get("CRM_DB") or DEFAULT_DB).resolve()
    _db_path.parent.mkdir(parents=True, exist_ok=True)

    if backup and _db_path.exists() and _has_tables(_db_path) and _schema_version(_db_path) < SCHEMA_VERSION:
        dest = backup_database("before-migration")
        log.info("Резервная копия перед обновлением схемы: %s", dest)

    engine = create_engine(f"sqlite:///{_db_path}", future=True)
    event.listen(engine, "connect", _on_connect)
    migrate(engine)
    _engine = engine
    _factory = sessionmaker(bind=engine, expire_on_commit=False)
    return _db_path


def _on_connect(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


@contextmanager
def session_scope():
    """Сессия с commit/rollback. Объекты остаются читаемыми после commit."""
    if _factory is None:
        raise RuntimeError("База не инициализирована: вызовите init_db()")
    session = _factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ------------------------------------------------------------------- миграция
def _schema_version(path: Path) -> int:
    con = sqlite3.connect(str(path))
    try:
        return con.execute("PRAGMA user_version").fetchone()[0]
    finally:
        con.close()


def _has_tables(path: Path) -> bool:
    con = sqlite3.connect(str(path))
    try:
        return con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0] > 0
    finally:
        con.close()


def _literal(value) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def _add_column_ddl(engine, table: str, col) -> str:
    ddl = f'ALTER TABLE "{table}" ADD COLUMN "{col.name}" {col.type.compile(dialect=engine.dialect)}'
    default = LEGACY_DEFAULTS.get((table, col.name))
    if default is None and col.default is not None and getattr(col.default, "is_scalar", False):
        default = col.default.arg
    if default is not None:
        ddl += " DEFAULT " + _literal(default)
    for fk in col.foreign_keys:
        ddl += f' REFERENCES "{fk.column.table.name}" ("{fk.column.name}")'
    return ddl


def migrate(engine) -> None:
    """Приводит схему к текущей версии. Безопасно запускать сколько угодно раз."""
    legacy = inspect(engine).has_table("corporate_clients")
    with engine.connect() as conn:
        version = conn.execute(text("PRAGMA user_version")).scalar() or 0

    Base.metadata.create_all(engine)
    insp = inspect(engine)          # свежий инспектор: кэш прежнего устарел
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    conn.execute(text(_add_column_ddl(engine, table.name, col)))
                    log.info("Добавлена колонка %s.%s", table.name, col.name)
        # create_all не добавляет индексы к уже существующим таблицам
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_orders_source_key ON orders(source_key)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_invoices_number ON invoices(number)"))
        if version < SCHEMA_VERSION:
            if legacy:
                _fix_legacy_data(conn)
            else:
                _seed_holidays(conn)
            conn.execute(text(f"PRAGMA user_version = {SCHEMA_VERSION}"))


def _fix_legacy_data(conn) -> None:
    """Разовое заполнение новых полей у записей из старой версии."""
    conn.execute(text(
        "UPDATE orders SET recipient_name = (SELECT e.full_name FROM corporate_employees e "
        "WHERE e.id = orders.employee_id) WHERE recipient_name IS NULL AND employee_id IS NOT NULL"))
    conn.execute(text(
        "UPDATE orders SET recipient_phone = (SELECT e.phone FROM corporate_employees e "
        "WHERE e.id = orders.employee_id) WHERE recipient_phone IS NULL AND employee_id IS NOT NULL"))
    conn.execute(text(
        "UPDATE orders SET address = (SELECT c.address FROM corporate_clients c "
        "WHERE c.id = orders.client_id) WHERE address IS NULL AND client_id IS NOT NULL"))
    conn.execute(text("UPDATE orders SET event_date = delivery_date WHERE event_date IS NULL"))
    conn.execute(text(
        "UPDATE invoices SET due_date = date(issue_date, '+14 day') "
        "WHERE due_date IS NULL AND issue_date IS NOT NULL"))
    rows = conn.execute(text(
        "SELECT id, issue_date FROM invoices WHERE number IS NULL ORDER BY issue_date, id")).fetchall()
    counters: dict[str, int] = {}
    for inv_id, issue in rows:
        ym = (str(issue) if issue else "0000-00")[:7].replace("-", "")
        counters[ym] = counters.get(ym, 0) + 1
        conn.execute(text("UPDATE invoices SET number = :n WHERE id = :i"),
                     {"n": f"СЧ-{ym}-{counters[ym]:03d}", "i": inv_id})
    conn.execute(text("UPDATE holidays SET audience = 'female' WHERE name = '8 Марта'"))
    conn.execute(text("UPDATE holidays SET audience = 'male' WHERE name = '23 Февраля'"))


def _seed_holidays(conn) -> None:
    if conn.execute(text("SELECT COUNT(*) FROM holidays")).scalar():
        return
    for name, month, day, lead, audience in DEFAULT_HOLIDAYS:
        conn.execute(text(
            "INSERT INTO holidays (name, month, day, lead_days, audience, is_active) "
            "VALUES (:n, :m, :d, :l, :a, 1)"),
            {"n": name, "m": month, "d": day, "l": lead, "a": audience})


# ---------------------------------------------------------- резервные копии
def backup_dir() -> Path:
    return db_path().parent / "backups"


def backup_database(tag: str = "auto", keep: int = 20) -> Path:
    """Копия базы средствами SQLite (корректна, даже если база открыта)."""
    src_path = db_path()
    bdir = backup_dir()
    bdir.mkdir(exist_ok=True)
    dest = bdir / f"{src_path.stem}-{datetime.now():%Y%m%d-%H%M%S}-{tag}.db"
    src = sqlite3.connect(str(src_path))
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    if tag == "auto":
        old = sorted(bdir.glob(f"{src_path.stem}-*-auto.db"))
        for f in old[:-keep]:
            try:
                f.unlink()
            except OSError:
                log.warning("Не удалось удалить старую копию %s", f)
    return dest


def daily_backup() -> Path | None:
    """Одна автоматическая копия в сутки при запуске программы."""
    today = datetime.now()
    exists = any(backup_dir().glob(f"{db_path().stem}-{today:%Y%m%d}-*-auto.db")) if backup_dir().exists() else False
    return None if exists else backup_database("auto")
