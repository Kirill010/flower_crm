"""Тесты базы: миграция старой flower.db без потери данных, копии, повторный запуск."""
import shutil
import sqlite3
from datetime import date
from pathlib import Path

import pytest

import database
from models import CorporateClient, Holiday, Order
from services import generate_birthday_orders

LEGACY_DDL = """
CREATE TABLE corporate_clients (id INTEGER NOT NULL, company_name VARCHAR(200) NOT NULL,
    contact_person VARCHAR(150), phone VARCHAR(30), address VARCHAR(250), fixed_price FLOAT,
    discount FLOAT, is_active BOOLEAN, PRIMARY KEY (id));
CREATE TABLE corporate_employees (id INTEGER NOT NULL, client_id INTEGER, full_name VARCHAR(150) NOT NULL,
    position VARCHAR(100), birthday DATE, phone VARCHAR(30), preferred_bouquet VARCHAR(150),
    preferred_budget FLOAT, PRIMARY KEY (id), FOREIGN KEY(client_id) REFERENCES corporate_clients (id));
CREATE TABLE orders (id INTEGER NOT NULL, client_id INTEGER, employee_id INTEGER, order_date DATE,
    delivery_date DATE NOT NULL, occasion VARCHAR(100), bouquet VARCHAR(150), amount FLOAT,
    status VARCHAR(50), PRIMARY KEY (id), FOREIGN KEY(client_id) REFERENCES corporate_clients (id),
    FOREIGN KEY(employee_id) REFERENCES corporate_employees (id));
CREATE TABLE invoices (id INTEGER NOT NULL, client_id INTEGER, issue_date DATE, amount FLOAT, paid BOOLEAN,
    PRIMARY KEY (id), FOREIGN KEY(client_id) REFERENCES corporate_clients (id));
CREATE TABLE holidays (id INTEGER NOT NULL, name VARCHAR(100) NOT NULL, month INTEGER, day INTEGER,
    PRIMARY KEY (id));
INSERT INTO corporate_clients VALUES (1, 'Старая Ромашка', 'Иван', '+7 999', 'ул. Цветочная, 1', 40.0, 5.0, 1);
INSERT INTO corporate_employees VALUES (1, 1, 'Алексей Иванов', 'Менеджер', '1985-11-05', '+7 111', 'Розы', 45.0);
INSERT INTO orders VALUES (1, 1, 1, '2026-07-02', '2026-07-03', 'День рождения', 'Розы', 45.0, 'Доставлен');
INSERT INTO invoices VALUES (1, 1, '2026-06-27', 200.0, 1);
INSERT INTO invoices VALUES (2, 1, '2026-06-30', 50.0, 0);
INSERT INTO holidays VALUES (1, '8 Марта', 3, 8);
INSERT INTO holidays VALUES (2, '23 Февраля', 2, 23);
INSERT INTO holidays VALUES (3, 'Новый год', 12, 31);
"""


def make_legacy(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.executescript(LEGACY_DDL)
    con.commit()
    con.close()
    return path


def test_legacy_database_is_migrated_without_losing_data(tmp_path):
    path = make_legacy(tmp_path / "flower.db")
    database.init_db(path)

    with database.session_scope() as s:
        client = s.query(CorporateClient).one()
        assert (client.company_name, client.stage, client.fixed_price, client.discount) == \
               ("Старая Ромашка", "Клиент", 40.0, 5.0)          # прежние компании продолжают обслуживаться
        assert client.payment_terms == "Раз в месяц по счёту" and client.is_active is True
        order = s.query(Order).one()
        assert (order.recipient_name, order.address, order.event_date, order.service) == \
               ("Алексей Иванов", "ул. Цветочная, 1", date(2026, 7, 3), "Букет")
        assert order.status == "Доставлен" and order.amount == 45.0

    con = sqlite3.connect(path)
    assert con.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION
    invoices = con.execute("SELECT number, due_date, amount FROM invoices ORDER BY id").fetchall()
    assert invoices == [("СЧ-202606-001", "2026-07-11", 200.0), ("СЧ-202606-002", "2026-07-14", 50.0)]
    holidays = dict(con.execute("SELECT name, audience FROM holidays").fetchall())
    assert holidays == {"8 Марта": "female", "23 Февраля": "male", "Новый год": "all"}
    con.close()


def test_backup_before_migration_and_no_repeat(tmp_path):
    path = make_legacy(tmp_path / "flower.db")
    database.init_db(path)
    backups = list((tmp_path / "backups").glob("flower-*-before-migration.db"))
    assert len(backups) == 1
    old = sqlite3.connect(backups[0])
    assert old.execute("SELECT COUNT(*) FROM corporate_clients").fetchone()[0] == 1
    assert "stage" not in [r[1] for r in old.execute("PRAGMA table_info(corporate_clients)")]  # копия — до миграции
    old.close()

    database.init_db(path)                                     # повторное открытие
    assert len(list((tmp_path / "backups").glob("*-before-migration.db"))) == 1


def test_fresh_database_gets_default_holidays_and_no_backup(tmp_path):
    database.init_db(tmp_path / "new.db")
    with database.session_scope() as s:
        names = {h.name: (h.audience, h.day) for h in s.query(Holiday)}
    assert names["8 Марта"] == ("female", 8) and names["23 Февраля"][0] == "male"
    assert not (tmp_path / "backups").exists()
    database.init_db(tmp_path / "new.db")                      # повторный запуск не дублирует праздники
    with database.session_scope() as s:
        assert s.query(Holiday).count() == 3


def test_foreign_keys_are_enforced(tmp_path):
    database.init_db(tmp_path / "fk.db")
    with pytest.raises(Exception):
        with database.session_scope() as s:
            s.add(Order(client_id=999, delivery_date=date(2026, 1, 1)))


def test_generation_on_migrated_legacy_data(tmp_path):
    database.init_db(make_legacy(tmp_path / "flower.db"))
    with database.session_scope() as s:
        res = generate_birthday_orders(s, date(2026, 11, 3), lead_days=3)   # ДР Алексея — 5 ноября
        assert [(o.recipient_name, o.amount, o.occasion) for o in res.created] == \
               [("Алексей Иванов", 45.0, "День рождения")]


def test_backup_rotation_and_daily_backup(tmp_path):
    database.init_db(tmp_path / "rot.db")
    bdir = tmp_path / "backups"
    bdir.mkdir()
    for day in range(1, 5):
        (bdir / f"rot-2026010{day}-000000-auto.db").write_bytes(b"old")
    database.backup_database("auto", keep=2)
    left = sorted(p.name for p in bdir.glob("rot-*-auto.db"))
    assert len(left) == 2 and "rot-20260104-000000-auto.db" in left   # старые удалены, свежие остались


def test_daily_backup_is_made_once_a_day(tmp_path):
    database.init_db(tmp_path / "daily.db")
    first = database.daily_backup()
    assert first is not None and first.exists()
    assert database.daily_backup() is None          # повторно в тот же день — не создаёт


ARCHIVE_DB = Path(__file__).resolve().parents[1] / "_archive" / "v1-2026-07" / "flower.db"


@pytest.mark.skipif(not ARCHIVE_DB.exists(), reason="архивная копия flower.db не найдена")
def test_real_archived_database_migrates(tmp_path):
    path = tmp_path / "flower.db"
    shutil.copy2(ARCHIVE_DB, path)
    before = sqlite3.connect(path)
    counts = {t: before.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("corporate_clients", "corporate_employees", "orders", "invoices", "holidays")}
    before.close()
    database.init_db(path)
    after = sqlite3.connect(path)
    for table, n in counts.items():
        assert after.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == n
    after.close()
    with database.session_scope() as s:
        assert all(o.client is not None for o in s.query(Order))
