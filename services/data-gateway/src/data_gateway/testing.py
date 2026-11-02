"""Тестовый каталог шлюза: источник SQLite с тем же справочником, что у mock-MSSQL дев-стенда.

Используют тесты шлюза и интеграционные тесты ``api`` (шлюз в процессе, без MS SQL).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import yaml

EMPLOYEES = [
    ("Иванов Иван Петрович", "Руководитель ИТ-отдела", "ИТ-отдел", "+7 (495) 100-10-01", "1001",
     "ivanov@corp.local", "Москва, офис 1, каб. 101"),
    ("Ким Александр", "Инженер технической поддержки", "ИТ-отдел", "+7 (495) 100-10-02", "1002",
     "kim@corp.local", "Москва, офис 1, каб. 102"),
    ("Смирнова Анна Викторовна", "Главный бухгалтер", "Бухгалтерия", "+7 (495) 100-20-01", "2001",
     "smirnova@corp.local", "Москва, офис 1, каб. 214"),
    ("Петров Сергей Алексеевич", "Бухгалтер", "Бухгалтерия", "+7 (495) 100-20-02", "2002",
     "petrov@corp.local", "Москва, офис 1, каб. 215"),
    ("Петрова Ольга Игоревна", "Менеджер по продажам", "Отдел продаж", "+7 (495) 100-40-07",
     "4007", "o.petrova@corp.local", "Москва, офис 2, каб. 12"),
    ("Сидорова Елена Николаевна", "Юрисконсульт", "Юридический отдел", "+7 (495) 100-30-01",
     "3001", "sidorova@corp.local", "Москва, офис 1, каб. 301"),
]  # fmt: skip

CATALOG = Path(__file__).resolve().parents[2] / "catalog"


def make_db(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE v_phonebook (full_name TEXT, position TEXT, department TEXT, "
            "phone TEXT, internal_phone TEXT, email TEXT, office TEXT, salary INTEGER)"
        )
        db.executemany("INSERT INTO v_phonebook VALUES (?, ?, ?, ?, ?, ?, ?, 100000)", EMPLOYEES)
        db.execute("CREATE VIEW v_dept_staff AS SELECT full_name, department FROM v_phonebook")


def make_catalog(root: Path, *, extra_datasets: list[dict[str, object]] | None = None) -> Path:
    """Копия каталога репозитория, где источник ``mssql_main`` — файл SQLite."""
    catalog = root / "catalog"
    (catalog / "datasets").mkdir(parents=True)
    (catalog / "functions").mkdir()
    make_db(root / "corp.db")
    (catalog / "sources.yaml").write_text(
        yaml.safe_dump(
            {
                "sources": [
                    {"name": "mssql_main", "dialect": "sqlite",
                     "url": f"sqlite:///{root / 'corp.db'}",
                     "timeout_s": 5, "max_rows": 1000},
                ]
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )  # fmt: skip
    for folder in ("datasets", "functions"):
        for src in (CATALOG / folder).glob("*.yaml"):
            (catalog / folder / src.name).write_text(src.read_text(encoding="utf-8"), "utf-8")
    for extra in extra_datasets or []:
        name = str(extra["name"])
        (catalog / "datasets" / f"{name}.yaml").write_text(
            yaml.safe_dump(extra, allow_unicode=True), encoding="utf-8"
        )
    return catalog
