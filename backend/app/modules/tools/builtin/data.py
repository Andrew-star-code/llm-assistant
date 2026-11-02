"""Инструменты данных (§9.2, §9.5): каталог, функции и контролируемый text-to-SQL через
``data-gateway``. Предлагаются, только если шлюз настроен (``data_gateway.url``).

Каждый SQL-запрос и вызов функции — запись в аудит (пользователь, итоговый SQL после RLS, время,
число строк, результат), включая отклонённые. Модель видит до ``preview_rows`` строк; больший
результат пользователь получает CSV-карточкой. Неудачных SQL-запросов на ответ — не больше
``max_failed_attempts``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.modules.audit import service as audit
from app.modules.data.client import DataGateway, GatewayError, Identity, identity_of
from app.modules.files.generate import ColumnSpec, SheetSpec, SpreadsheetSpec
from app.modules.tools.base import Tool, ToolContext, ToolError, ToolResult
from app.modules.tools.registry import register_tool
from app.workers.dispatch import TaskTimeout

FAILS_TTL_S = 3600


async def _identity(ctx: ToolContext) -> Identity:
    async with ctx.services.sessions() as db:
        return await identity_of(db, ctx.user_id)


def _gateway(ctx: ToolContext) -> DataGateway:
    try:
        return DataGateway(ctx.services.settings)
    except GatewayError as exc:
        raise ToolError(exc.message) from exc


async def _audit(
    ctx: ToolContext, action: str, target_type: str, target: str, details: dict[str, Any]
) -> None:
    """Аудит запроса к данным (§9.5 п. 6): от имени пользователя, в его чате."""
    async with ctx.services.sessions() as db:
        await audit.record(
            db,
            actor_id=ctx.user_id,
            action=action,
            target_type=target_type,
            target_id=target[:200],
            details={**details, "chat_id": str(ctx.chat_id), "message_id": str(ctx.message_id)},
        )
        await db.commit()


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")[:300]


def _table(columns: list[str], rows: list[list[Any]], limit: int) -> str:
    head = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = ["| " + " | ".join(_cell(v) for v in row) + " |" for row in rows[:limit]]
    return "\n".join([head, sep, *body])


async def _csv(ctx: ToolContext, title: str, result: dict[str, Any]) -> dict[str, Any] | None:
    """Полный результат — CSV-файлом в чат (§9.5 п. 4); сбой создания не ломает ответ."""
    spec = SpreadsheetSpec(
        format="csv",
        title=title[:200],
        sheets=[
            SheetSpec(
                name="data",
                columns=[ColumnSpec(header=c[:200] or "?") for c in result["columns"]],
                rows=result["rows"],
            )
        ],
    )
    payload = {
        "kind": "spreadsheet",
        "args": spec.model_dump(mode="json"),
        "owner_id": str(ctx.user_id),
        "chat_id": str(ctx.chat_id),
        "message_id": str(ctx.message_id),
    }
    try:
        file = await ctx.services.dispatcher.generate(payload)
    except TaskTimeout:
        return None
    return None if "error" in file else file


async def _result(
    ctx: ToolContext, title: str, result: dict[str, Any], *, note: str = ""
) -> ToolResult:
    preview = ctx.services.settings.data_gateway.preview_rows
    rows: list[list[Any]] = result["rows"]
    shown = min(len(rows), preview)
    more = " (есть ещё — результат обрезан)" if result.get("truncated") else ""
    parts = [f"Найдено строк: {len(rows)}{more}."]
    if note:
        parts.append(note)
    if rows:
        parts.append(_table(result["columns"], rows, preview))
    files: list[dict[str, Any]] = []
    if len(rows) > shown:
        file = await _csv(ctx, title, result)
        if file is not None:
            files.append(file)
            parts.append(
                f"Показаны первые {shown}; весь результат ({len(rows)} строк) — в файле "
                f"«{file['filename']}», он показан пользователю карточкой. Не вставляй ссылку."
            )
        else:
            parts.append(f"Показаны первые {shown} строк.")
    if not rows:
        parts.append("Ничего не найдено — скажи об этом пользователю, не придумывай данные.")
    return ToolResult(
        "\n\n".join(parts),
        files=files,
        data={"rows": len(rows), "sql": result.get("sql")},
    )


async def _function(ctx: ToolContext, name: str, params: dict[str, Any]) -> ToolResult:
    gateway = _gateway(ctx)
    identity = await _identity(ctx)
    try:
        result = await gateway.call(identity, name, params)
    except GatewayError as exc:
        await _audit(
            ctx, "data.function", "data_function", name,
            {"params": params, "status": exc.code, "error": exc.message},
        )  # fmt: skip
        raise ToolError(exc.message) from exc
    await _audit(
        ctx, "data.function", "data_function", name,
        {
            "params": result.get("params", params), "sql": result.get("sql"), "status": "ok",
            "rows": result.get("row_count"), "duration_ms": result.get("duration_ms"),
        },
    )  # fmt: skip
    return await _result(ctx, name, result)


@register_tool
class ListDatasets(Tool):
    name = "list_datasets"
    description = (
        "Каталог данных компании: наборы данных (представления корпоративных БД) и типовые "
        "функции, доступные пользователю. Вызывай первым, когда вопрос требует цифр или записей "
        "из учётных систем."
    )
    status_label = "tools.list_datasets"
    timeout_s = 30
    needs_data = True

    async def run(self, ctx: ToolContext, args: Any) -> ToolResult:
        try:
            catalog = await _gateway(ctx).catalog(await _identity(ctx))
        except GatewayError as exc:
            raise ToolError(exc.message) from exc
        lines = ["Наборы данных (подробности — describe_dataset):"]
        lines += [f"- {d['name']} — {d['title']}: {d['description']}" for d in catalog["datasets"]]
        if catalog["functions"]:
            lines.append("\nФункции (вызов — call_data_function):")
            for f in catalog["functions"]:
                params = ", ".join(
                    f"{n}{'' if p.get('required', True) else '?'}: {p.get('type', 'string')}"
                    for n, p in f["params"].items()
                )
                lines.append(f"- {f['name']}({params}) — {f['description']}")
        if len(lines) == 1:
            return ToolResult("Доступных наборов данных нет.")
        return ToolResult("\n".join(lines))


class DescribeArgs(BaseModel):
    name: str = Field(description="Имя набора из list_datasets")
    question: str | None = Field(
        None, description="Вопрос пользователя — для подбора похожих примеров SQL"
    )


@register_tool
class DescribeDataset(Tool):
    name = "describe_dataset"
    description = (
        "Описание набора данных: представление, колонки (тип, смысл, примеры), связи, метрики, "
        "ограничения строк и до 5 похожих примеров «вопрос → SQL». Вызывай перед run_sql_query."
    )
    args_model = DescribeArgs
    status_label = "tools.describe_dataset"
    timeout_s = 30
    needs_data = True

    def label_params(self, args: Any) -> dict[str, str]:
        return {"name": args.name}

    async def run(self, ctx: ToolContext, args: Any) -> ToolResult:
        try:
            d = await _gateway(ctx).describe(await _identity(ctx), args.name, args.question)
        except GatewayError as exc:
            raise ToolError(exc.message) from exc
        lines = [f"{d['title']} — представление {d['view']} (T-SQL, MS SQL).", d["description"], ""]
        lines.append("Колонки:")
        for c in d["columns"]:
            extra = []
            if c.get("synonyms"):
                extra.append("синонимы: " + ", ".join(c["synonyms"]))
            if c.get("examples"):
                extra.append("примеры: " + ", ".join(map(str, c["examples"])))
            if c.get("pii"):
                extra.append("персональные данные")
            tail = f" ({'; '.join(extra)})" if extra else ""
            lines.append(f"- {c['name']}: {c['type']} — {c['description']}{tail}")
        if d.get("relations"):
            lines += ["", "Связи:", *(f"- {r}" for r in d["relations"])]
        if d.get("metrics"):
            lines += ["", "Метрики:", *(f"- {m}" for m in d["metrics"])]
        if d.get("row_filter"):
            lines += ["", "Строки ограничены правами пользователя: " + "; ".join(d["row_filter"])]
        if d.get("examples"):
            lines += ["", "Примеры:"]
            lines += [f"- {e['question']}\n  {e['sql']}" for e in d["examples"]]
        lines += [
            "",
            "Пиши один SELECT в T-SQL по этому представлению; только колонки из списка; без *; "
            "строки — N'…'. Ограничение строк, права и тайм-аут шлюз добавит сам.",
        ]
        return ToolResult("\n".join(lines))


class CallFunctionArgs(BaseModel):
    name: str = Field(description="Имя функции из list_datasets")
    params: dict[str, Any] = Field(default_factory=dict, description="Параметры функции")


@register_tool
class CallDataFunction(Tool):
    name = "call_data_function"
    description = (
        "Вызвать типовую функцию данных из каталога (list_datasets) с параметрами. Предпочитай "
        "функцию произвольному SQL, если она отвечает на вопрос."
    )
    args_model = CallFunctionArgs
    status_label = "tools.call_data_function"
    timeout_s = 60
    needs_data = True

    def label_params(self, args: Any) -> dict[str, str]:
        return {"name": args.name}

    async def run(self, ctx: ToolContext, args: Any) -> ToolResult:
        return await _function(ctx, args.name, args.params)


class SqlArgs(BaseModel):
    sql: str = Field(
        min_length=1,
        max_length=20_000,
        description="Один SELECT в T-SQL по представлениям из describe_dataset",
    )


@register_tool
class RunSqlQuery(Tool):
    name = "run_sql_query"
    description = (
        "Выполнить один SELECT (T-SQL) по наборам данных каталога. Сначала describe_dataset. "
        "Изменения данных запрещены. При ошибке исправь запрос по её тексту — не больше трёх "
        "неудачных попыток."
    )
    args_model = SqlArgs
    status_label = "tools.run_sql_query"
    timeout_s = 60
    needs_data = True

    async def run(self, ctx: ToolContext, args: Any) -> ToolResult:
        settings = ctx.services.settings.data_gateway
        redis = ctx.services.redis
        key = f"data:sqlfail:{ctx.message_id}"
        attempt = 0
        if redis is not None:
            # Попытка резервируется атомарно (параллельные вызовы в одном ответе), успех её
            # возвращает: в счётчике остаются только неудачные.
            attempt = int(await redis.incr(key))
            await redis.expire(key, FAILS_TTL_S)
            if attempt > settings.max_failed_attempts:
                raise ToolError(
                    "лимит неудачных попыток исчерпан — объясни пользователю, что запрос "
                    "не удался, и предложи уточнить вопрос"
                )
        gateway = _gateway(ctx)
        identity = await _identity(ctx)
        try:
            result = await gateway.query(identity, args.sql)
        except GatewayError as exc:
            counted = exc.code in ("rejected", "query_failed")
            if redis is not None and not counted:
                await redis.decr(key)  # шлюз недоступен — не вина запроса
            await _audit(
                ctx, "data.query", "dataset", "sql",
                {"sql": args.sql, "status": exc.code, "error": exc.message},
            )  # fmt: skip
            left = max(0, settings.max_failed_attempts - attempt)
            hint = f" Осталось попыток: {left}." if counted and redis is not None else ""
            raise ToolError(f"{exc.message}.{hint}") from exc
        if redis is not None:
            await redis.decr(key)
        datasets = ",".join(result.get("datasets") or []) or "sql"
        await _audit(
            ctx, "data.query", "dataset", datasets,
            {
                "sql": result.get("sql"), "params": result.get("params"), "status": "ok",
                "rows": result.get("row_count"), "truncated": result.get("truncated"),
                "duration_ms": result.get("duration_ms"), "rls": result.get("rls"),
            },
        )  # fmt: skip
        note = (
            "Строки ограничены правами пользователя (" + ", ".join(result["rls"]) + ")."
            if result.get("rls")
            else ""
        )
        return await _result(ctx, f"Запрос {datasets}", result, note=note)


class EmployeesArgs(BaseModel):
    query: str = Field(
        min_length=2, max_length=100, description="ФИО или его часть, телефон или должность"
    )
    department: str | None = Field(None, max_length=100, description="Отдел, например Бухгалтерия")
    limit: int = Field(20, ge=1, le=50, description="Сколько строк вернуть")


@register_tool
class SearchEmployees(Tool):
    name = "search_employees"
    description = (
        "Найти сотрудников в телефонном справочнике по ФИО (или фамилии без падежного окончания), "
        "телефону или должности, при необходимости — в отделе. Возвращает ФИО, должность, "
        "отдел, телефоны, почту и офис."
    )
    args_model = EmployeesArgs
    status_label = "tools.search_employees"
    timeout_s = 30
    needs_data = True

    def label_params(self, args: Any) -> dict[str, str]:
        return {"query": args.query}

    async def run(self, ctx: ToolContext, args: Any) -> ToolResult:
        return await _function(ctx, "search_employees", args.model_dump(exclude_none=True))
