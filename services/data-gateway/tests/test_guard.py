"""Проверка SQL модели (§9.5) — обязательные тесты безопасности §18.2: изменения данных и схемы,
несколько выражений, запрещённые таблицы и колонки отклоняются; RLS подставляется."""

from __future__ import annotations

from pathlib import Path

import pytest
from data_gateway.catalog import Catalog, Dataset, load
from data_gateway.guard import Rejected, prepare_function, prepare_query
from data_gateway.identity import Identity

PETROV = Identity(user_id="u1", login="petrov", roles=frozenset({"dept:Бухгалтерия"}),
                  department="Бухгалтерия")  # fmt: skip


@pytest.fixture
def catalog() -> Catalog:
    cat = load(Path(__file__).resolve().parents[1] / "catalog")
    cat.datasets["salaries"] = Dataset.model_validate(
        {
            "name": "salaries", "title": "Зарплаты", "description": "Фонд оплаты труда",
            "source": "mssql_main", "view": "hr.v_salaries", "roles": ["hr"],
            "columns": [{"name": "department"}, {"name": "amount", "type": "number"}],
            "rls": [{"column": "department", "equals": "{user.department}",
                     "unless_roles": ["hr_director"]}],
        }
    )  # fmt: skip
    return cat


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("UPDATE dbo.v_phonebook SET phone = '1'", "только SELECT"),
        ("DELETE FROM dbo.v_phonebook", "только SELECT"),
        ("INSERT INTO dbo.v_phonebook (full_name) VALUES ('x')", "только SELECT"),
        ("DROP VIEW dbo.v_phonebook", "только SELECT"),
        ("TRUNCATE TABLE dbo.v_phonebook", "только SELECT"),
        ("CREATE TABLE t (a int)", "только SELECT"),
        ("SELECT full_name FROM dbo.v_phonebook; DROP TABLE x", "ровно одно выражение"),
        ("SELECT full_name FROM dbo.v_phonebook; SELECT 1", "ровно одно выражение"),
        ("EXEC xp_cmdshell 'dir'", "только SELECT"),
        ("EXEC sp_executesql N'select 1'", "только SELECT"),
        ("SELECT full_name INTO #t FROM dbo.v_phonebook", "INTO"),
        ("DECLARE @a int; SELECT @a", "ровно одно выражение"),
        ("SELECT full_name FROM dbo.v_phonebook WHERE department = @dep", "переменные"),
        ("SELECT full_name FROM dbo.v_phonebook WHERE department = :dep", "переменные"),
        ("SELECT a FROM OPENROWSET('SQLNCLI', 'srv', 'select 1')", "запрещен"),
        (
            "SELECT full_name FROM dbo.v_phonebook WHERE 1 = (SELECT COUNT(*) FROM "
            "OPENQUERY(srv, 'select 1'))",
            "OPENQUERY",
        ),
        ("SELECT xp_msver()", "XP_MSVER"),
        ("SELECT name FROM sys.tables", "не описана в каталоге"),
        ("SELECT login FROM dbo.users", "не описана в каталоге"),
        ("SELECT full_name FROM otherdb.dbo.v_phonebook", "другой базе"),
        ("SELECT salary FROM dbo.v_phonebook", "salary не описана"),
        ("SELECT p.salary FROM dbo.v_phonebook p", "нет в наборе"),
        ("SELECT * FROM dbo.v_phonebook", "вместо *"),
        ("SELECT p.* FROM dbo.v_phonebook p", "вместо *"),
        ("SELECT department, amount FROM hr.v_salaries", "нет доступа"),
        ("SELECT 1", "ни одного представления"),
        ("SELEKT full_name FROM dbo.v_phonebook", "разобрать"),
    ],
)
def test_rejected(catalog: Catalog, sql: str, reason: str) -> None:
    with pytest.raises(Rejected) as error:
        prepare_query(sql, catalog, PETROV)
    assert reason in error.value.message


def test_select_gets_row_limit_and_keeps_smaller_top(catalog: Catalog) -> None:
    plain = prepare_query("SELECT full_name FROM dbo.v_phonebook", catalog, PETROV)
    assert plain.tsql == "SELECT TOP 1000 full_name FROM dbo.v_phonebook"
    assert plain.sql == plain.tsql  # источник каталога — MS SQL: выполняется тот же T-SQL
    small = prepare_query("SELECT TOP 5 full_name FROM dbo.v_phonebook", catalog, PETROV)
    assert small.tsql.startswith("SELECT TOP 5 ")
    huge = prepare_query("SELECT TOP 100000 full_name FROM dbo.v_phonebook", catalog, PETROV)
    assert huge.tsql.startswith("SELECT TOP 1000 ")
    paged = prepare_query(
        "SELECT full_name FROM dbo.v_phonebook ORDER BY full_name "
        "OFFSET 0 ROWS FETCH NEXT 5000 ROWS ONLY",
        catalog, PETROV,
    )  # fmt: skip
    assert paged.tsql.endswith("ROWS FETCH FIRST 1000 ROWS ONLY")  # FIRST и NEXT — синонимы
    union = prepare_query(
        "SELECT full_name FROM dbo.v_phonebook UNION SELECT email FROM dbo.v_phonebook",
        catalog, PETROV,
    )  # fmt: skip
    assert union.tsql.startswith("SELECT TOP 1000 * FROM (SELECT full_name")


def test_allowed_constructs(catalog: Catalog) -> None:
    for sql in (
        "SELECT department, COUNT(*) AS n FROM dbo.v_phonebook GROUP BY department ORDER BY n DESC",
        "WITH b AS (SELECT full_name, department FROM dbo.v_phonebook WHERE department = "
        "N'Бухгалтерия') SELECT full_name FROM b",
        "SELECT p.full_name, q.email FROM dbo.v_phonebook p JOIN dbo.v_phonebook q "
        "ON q.full_name = p.full_name",
        "SELECT UPPER(full_name) AS name FROM v_phonebook WHERE full_name LIKE N'Петров%'",
    ):
        prepared = prepare_query(sql, catalog, PETROV)
        assert prepared.datasets == ["phonebook"]


def test_rls_is_substituted_with_parameters(catalog: Catalog) -> None:
    hr = Identity(user_id="u2", login="hr1", roles=frozenset({"hr"}), department="Бухгалтерия")
    prepared = prepare_query(
        "SELECT s.department, SUM(s.amount) AS total FROM hr.v_salaries AS s GROUP BY s.department",
        catalog, hr,
    )  # fmt: skip
    assert prepared.rls == ["salaries"]
    assert prepared.params == {"rls_0": "Бухгалтерия"}
    assert "FROM (SELECT * FROM hr.v_salaries WHERE department = :rls_0) AS s" in prepared.tsql
    # Значение — параметр, а не текст: кавычки в атрибуте пользователя не ломают запрос.
    tricky = Identity(user_id="u3", login="x", roles=frozenset({"hr"}),
                      department="x' OR 1=1 --")  # fmt: skip
    attack = prepare_query("SELECT amount FROM hr.v_salaries", catalog, tricky)
    assert "OR 1=1" not in attack.tsql and attack.params == {"rls_0": "x' OR 1=1 --"}
    # Без отдела — ни одной строки; роль-исключение — без фильтра.
    nobody = Identity(user_id="u4", login="y", roles=frozenset({"hr"}), department=None)
    assert "WHERE 1 = 0" in prepare_query("SELECT amount FROM hr.v_salaries", catalog, nobody).tsql
    director = Identity(user_id="u5", login="z", roles=frozenset({"hr", "hr_director"}))
    free = prepare_query("SELECT amount FROM hr.v_salaries", catalog, director)
    assert free.rls == [] and "WHERE" not in free.tsql


def test_function_parameters_are_typed_and_checked(catalog: Catalog) -> None:
    function = catalog.functions["search_employees"]
    prepared = prepare_function(function, {"query": "Петров", "limit": 500}, catalog)
    assert prepared.params == {"query": "Петров", "department": None, "limit": 50}
    assert "TOP (:limit)" in prepared.sql and prepared.sql == prepared.tsql
    for bad, reason in (
        ({}, "query обязателен"),
        ({"query": "П"}, "не короче 2"),
        ({"query": "Петров", "limit": "много"}, "ожидается integer"),
        ({"query": "Петров", "drop": 1}, "неизвестные параметры"),
    ):
        with pytest.raises(Rejected) as error:
            prepare_function(function, bad, catalog)
        assert reason in error.value.message
