"""Общие настройки тестов: путь к проекту, headless-режим Qt, временная база."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

import database  # noqa: E402


@pytest.fixture
def session(tmp_path):
    """Чистая база во временной папке; сессия фиксируется в конце теста."""
    database.init_db(tmp_path / "test.db")
    with database.session_scope() as s:
        yield s
