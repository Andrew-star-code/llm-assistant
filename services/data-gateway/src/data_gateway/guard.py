"""Проверка и подготовка SQL модели (§9.5, тесты безопасности §18.2).

1. Разбор sqlglot в диалекте T-SQL: ровно одно выражение — SELECT, WITH … SELECT или
   UNION/INTERSECT/EXCEPT из них.
2. Отказ: изменения данных и схемы, ``EXEC``, ``SELECT … INTO``, переменные и параметры,
   опасные и системные функции (``OPENROWSET``, ``OPENQUERY``, ``OPENDATASOURCE``, ``xp_*``,
   ``sp_*``), другие базы, таблицы вне наборов, доступных ролям пользователя, колонки вне
   описанных в каталоге, ``*`` (кроме ``COUNT(*)``).
3. RLS: представление набора заменяется подзапросом с условием по атрибутам пользователя
   (значения — параметрами, не текстом SQL).
4. Ограничение строк ``TOP max_rows`` (меньший TOP модели сохраняется).
5. Итог — T-SQL для аудита и тот же запрос в диалекте источника для выполнения.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from data_gateway.catalog import SQLGLOT_DIALECT, Catalog, Dataset, Function, visible
from data_gateway.identity import Identity

MAX_SQL_CHARS = 20_000
BANNED_FUNCTIONS = frozenset({"OPENROWSET", "OPENQUERY", "OPENDATASOURCE", "OPENXML"})
BANNED_PREFIXES = ("XP_", "SP_")
# Узлы, которых не может быть в запросе на чтение (имена — по версиям sqlglot).
_FORBIDDEN = tuple(
    cls
    for name in (
        "Insert",
        "Update",
        "Delete",
        "Merge",
        "Create",
        "Drop",
        "Alter",
        "Command",
        "Transaction",
        "Commit",
        "Rollback",
        "Use",
        "Set",
        "Execute",
        "Declare",
        "Grant",
        "TruncateTable",
        "Into",
        "Parameter",
        "Placeholder",
        "SessionParameter",
    )
    if isinstance(cls := getattr(exp, name, None), type)
)
_TEMPLATE = re.compile(r"^\{user\.(department|login)\}$")


class Rejected(Exception):  # noqa: N818 — «запрос отклонён», не ошибка шлюза
    """Запрос отклонён; текст уходит модели, чтобы она исправила запрос."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class Prepared:
    source: str
    tsql: str  # итоговый запрос в T-SQL — для аудита
    sql: str  # в диалекте источника — для выполнения
    params: dict[str, Any] = field(default_factory=dict)
    datasets: list[str] = field(default_factory=list)
    rls: list[str] = field(default_factory=list)  # наборы, к которым применён RLS
    max_rows: int = 1000


def _parse(sql: str) -> exp.Expr:
    if len(sql) > MAX_SQL_CHARS:
        raise Rejected(f"запрос длиннее {MAX_SQL_CHARS} символов")
    try:
        trees = [t for t in sqlglot.parse(sql, read="tsql") if t is not None]
    except ParseError as exc:
        raise Rejected(
            f"не удалось разобрать SQL (T-SQL): {str(exc).splitlines()[0][:300]}"
        ) from exc
    if len(trees) != 1:
        raise Rejected("разрешено ровно одно выражение SELECT")
    return trees[0]


def _check_root(root: exp.Expr) -> None:
    if not isinstance(root, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise Rejected("разрешён только SELECT (или WITH … SELECT); изменения данных запрещены")
    for node in root.walk():
        if isinstance(node, _FORBIDDEN):
            kind = type(node).__name__
            if kind == "Into":
                raise Rejected("SELECT … INTO запрещён")
            if kind in ("Parameter", "Placeholder", "SessionParameter"):
                raise Rejected("переменные и параметры в запросе запрещены — подставьте значения")
            raise Rejected(f"запрещённая конструкция: {kind}")
        if isinstance(node, exp.Func):
            name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).upper()
            if name in BANNED_FUNCTIONS or name.startswith(BANNED_PREFIXES):
                raise Rejected(f"функция {name} запрещена")
    for star in root.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            raise Rejected("перечислите нужные колонки вместо *")


def _datasets_for(
    root: exp.Expr, catalog: Catalog, identity: Identity
) -> tuple[dict[str, Dataset], list[tuple[exp.Table, Dataset]]]:
    ctes = {cte.alias_or_name.lower() for cte in root.find_all(exp.CTE)}
    by_view = {d.view_key: d for d in catalog.datasets.values()}
    aliases: dict[str, Dataset] = {}
    refs: list[tuple[exp.Table, Dataset]] = []
    for table in root.find_all(exp.Table):
        if isinstance(table.this, exp.Func):
            raise Rejected("табличные функции запрещены")
        if table.catalog:
            raise Rejected("обращение к другой базе данных запрещено")
        name = table.name.lower()
        if not table.db and name in ctes:
            continue
        dataset = by_view.get(((table.db or "dbo").lower(), name))
        if dataset is None:
            raise Rejected(
                f"таблица {table.sql('tsql')} не описана в каталоге — используйте "
                "представления из describe_dataset"
            )
        if not visible(dataset.roles, identity.roles):
            raise Rejected(f"нет доступа к набору «{dataset.title}»")
        aliases[table.alias_or_name.lower()] = dataset
        refs.append((table, dataset))
    if not refs:
        raise Rejected("в запросе нет ни одного представления из каталога")
    return aliases, refs


def _check_columns(root: exp.Expr, aliases: dict[str, Dataset]) -> None:
    derived = {cte.alias_or_name.lower() for cte in root.find_all(exp.CTE)}
    derived |= {s.alias.lower() for s in root.find_all(exp.Subquery) if s.alias}
    known = {c.name.lower() for d in aliases.values() for c in d.columns}
    output = {a.alias.lower() for a in root.find_all(exp.Alias) if a.alias}
    output |= {
        i.name.lower() for t in root.find_all(exp.TableAlias) for i in t.args.get("columns") or []
    }
    for column in root.find_all(exp.Column):
        name = column.name.lower()
        qualifier = column.table.lower()
        if qualifier:
            if qualifier in aliases:
                if name not in {c.name.lower() for c in aliases[qualifier].columns}:
                    raise Rejected(
                        f"колонки {column.name} нет в наборе «{aliases[qualifier].title}»"
                    )
            elif qualifier not in derived:
                raise Rejected(f"неизвестный псевдоним {column.table}")
        elif name not in known and name not in output:
            raise Rejected(f"колонка {column.name} не описана в каталоге")


def _rls_value(template: str, identity: Identity) -> str | None:
    match = _TEMPLATE.match(template.strip())
    if match is None:
        return template  # константа
    attr = match.group(1)
    return identity.department if attr == "department" else identity.login


def _apply_rls(
    refs: list[tuple[exp.Table, Dataset]], identity: Identity, params: dict[str, Any]
) -> list[str]:
    applied: list[str] = []
    for table, dataset in refs:
        rules = [r for r in dataset.rls if not set(r.unless_roles) & identity.roles]
        if not rules:
            continue
        conditions: list[exp.Expr] = []
        for rule in rules:
            value = _rls_value(rule.equals, identity)
            if value is None:
                conditions.append(
                    exp.EQ(this=exp.Literal.number(1), expression=exp.Literal.number(0))
                )
                continue
            key = f"rls_{len(params)}"
            params[key] = value
            conditions.append(
                exp.EQ(this=exp.column(rule.column), expression=exp.Placeholder(this=key))
            )
        inner = exp.select("*").from_(exp.table_(dataset.view_key[1], db=table.db or "dbo"))
        inner = inner.where(exp.and_(*conditions))
        alias = table.alias_or_name
        table.replace(exp.Subquery(this=inner, alias=exp.TableAlias(this=exp.to_identifier(alias))))
        applied.append(dataset.name)
    return applied


def render(tree: exp.Expr, dialect: str) -> str:
    """Запрос в диалекте источника. У SQLite (тесты) нет схем — префикс ``dbo.`` убирается."""
    if dialect == "sqlite":
        tree = tree.copy()
        for table in tree.find_all(exp.Table):
            table.set("db", None)
    return tree.sql(SQLGLOT_DIALECT[dialect])


def _literal_int(node: exp.Expr | None) -> int | None:
    if isinstance(node, exp.Paren):
        node = node.this
    if isinstance(node, exp.Literal) and not node.is_string and node.this.isdigit():
        return int(node.this)
    return None


def _limit(root: exp.Expr, max_rows: int) -> exp.Expr:
    if not isinstance(root, exp.Select):
        # UNION и т. п.: TOP — на весь результат.
        return (
            exp.select("*")
            .from_(exp.Subquery(this=root, alias=exp.TableAlias(this=exp.to_identifier("q"))))
            .limit(max_rows)
        )
    fetch = root.args.get("fetch")
    if fetch is not None:
        count = _literal_int(fetch.args.get("count"))
        if count is None or count > max_rows:
            fetch.set("count", exp.Literal.number(max_rows))
        return root
    limit = root.args.get("limit")
    current = _literal_int(limit.args.get("expression")) if limit is not None else None
    if current is None or current > max_rows:
        root.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))
    return root


def prepare_query(sql: str, catalog: Catalog, identity: Identity) -> Prepared:
    root = _parse(sql)
    _check_root(root)
    aliases, refs = _datasets_for(root, catalog, identity)
    sources = {d.source for _, d in refs}
    if len(sources) != 1:
        raise Rejected("в одном запросе — наборы только одного источника")
    source = catalog.sources[sources.pop()]
    _check_columns(root, aliases)
    params: dict[str, Any] = {}
    rls = _apply_rls(refs, identity, params)
    root = _limit(root, source.max_rows)
    return Prepared(
        source=source.name,
        tsql=root.sql("tsql"),
        sql=render(root, source.dialect),
        params=params,
        datasets=sorted({d.name for _, d in refs}),
        rls=sorted(set(rls)),
        max_rows=source.max_rows,
    )


# --------------------------------------------------------------------------- функции


def _coerce(name: str, spec: Any, value: Any) -> Any:
    if value is None:
        return None
    try:
        if spec.type == "integer":
            if isinstance(value, bool):
                raise ValueError
            value = int(value)
        elif spec.type == "number":
            value = float(value)
        elif spec.type == "boolean":
            if not isinstance(value, bool):
                raise ValueError
        elif spec.type == "date":
            value = date.fromisoformat(str(value)).isoformat()
        else:
            value = str(value).strip()
    except ValueError as exc:
        raise Rejected(f"параметр {name}: ожидается {spec.type}") from exc
    if isinstance(value, str):
        if spec.min_length is not None and len(value) < spec.min_length:
            raise Rejected(f"параметр {name}: не короче {spec.min_length} символов")
        if spec.max_length is not None and len(value) > spec.max_length:
            raise Rejected(f"параметр {name}: не длиннее {spec.max_length} символов")
        if spec.enum is not None and value not in spec.enum:
            raise Rejected(f"параметр {name}: одно из {', '.join(spec.enum)}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if spec.min is not None and value < spec.min:
            raise Rejected(f"параметр {name}: не меньше {spec.min:g}")
        if spec.max is not None and value > spec.max:
            value = type(value)(spec.max)  # «limit: 500» при max 50 — просто 50
    return value


def prepare_function(function: Function, arguments: dict[str, Any], catalog: Catalog) -> Prepared:
    unknown = set(arguments) - set(function.params)
    if unknown:
        raise Rejected(f"неизвестные параметры: {', '.join(sorted(unknown))}")
    params: dict[str, Any] = {}
    for name, spec in function.params.items():
        value = arguments.get(name, spec.default)
        if value in (None, "") and spec.required and spec.default is None:
            raise Rejected(f"параметр {name} обязателен")
        params[name] = _coerce(name, spec, value if value != "" else None)
    source = catalog.sources[function.source]
    tree = sqlglot.parse_one(function.sql, read="tsql")
    return Prepared(
        source=source.name,
        tsql=tree.sql("tsql"),
        sql=render(tree, source.dialect),
        params=params,
        max_rows=source.max_rows,
    )
