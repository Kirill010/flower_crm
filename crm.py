#!/usr/bin/env python3
"""CRM корпоративных поздравлений.

Запуск:
    python crm.py              рабочая база flower.db (рядом с программой)
    python crm.py --demo       демо-режим: вымышленные данные в отдельной базе demo.db
    python crm.py --db ПУТЬ    своя база данных
"""
from __future__ import annotations

import argparse
import logging
import sys
import traceback

from database import APP_DIR


def _setup_logging() -> None:
    logging.basicConfig(filename=APP_DIR / "crm.log", level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _install_excepthook(QMessageBox) -> None:
    """Ошибка в обработчике кнопки не должна закрывать программу молча."""
    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        logging.error("Необработанная ошибка:\n%s", text)
        try:
            QMessageBox.critical(None, "Ошибка", f"Произошла ошибка:\n{exc}\n\nПодробности записаны в crm.log")
        except Exception:
            pass
    sys.excepthook = hook


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CRM корпоративных поздравлений")
    parser.add_argument("--demo", action="store_true", help="демо-данные в отдельной базе demo.db")
    parser.add_argument("--db", help="путь к файлу базы данных")
    args = parser.parse_args(argv)
    _setup_logging()

    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication, QMessageBox

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)    # чёткий текст при масштабе Windows 125–150%
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    if sys.platform == "win32":                    # свой значок в панели задач, а не значок Python
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Dianthus.CRM.Greetings")
        except Exception:
            pass
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    import theme
    theme.apply(app)                               # фирменный стиль «Диантус»: шрифты, иконка, оформление
    _install_excepthook(QMessageBox)

    import database
    db_file = args.db or (APP_DIR / "demo.db" if args.demo else None)
    try:
        database.init_db(db_file)
        if args.demo:
            from demo_data import seed_demo
            from models import CorporateClient
            with database.session_scope() as s:
                if s.query(CorporateClient).count() == 0:
                    seed_demo(s)
    except Exception as exc:
        logging.exception("Не удалось открыть базу данных")
        QMessageBox.critical(None, "База данных", f"Не удалось открыть базу данных:\n{exc}\n\n"
                                                  "Закройте другие программы, которые используют файл базы, "
                                                  "и запустите снова. Подробности в crm.log")
        return 1
    if not args.demo:
        try:
            database.daily_backup()
        except Exception:
            logging.exception("Не удалось создать резервную копию")

    from ui import MainWindow
    window = MainWindow(demo=args.demo)
    window.showMaximized()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
