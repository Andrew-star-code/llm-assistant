"""Сценарии ответа fake-llm.

Сценарий выбирается маркером ``[[scenario:<имя>]]`` в последнем сообщении пользователя
(§16.1 SPEC), поэтому e2e-тесты детерминированы. Без маркера — ``default``; если в запросе
``chat_template_kwargs.enable_thinking: true`` — ``thinking``.

Сценарий — это список шагов (``Step``); сервер превращает их в чанки OpenAI-стрима
или в один ответ без стрима.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

SCENARIO_MARKER = re.compile(r"\[\[scenario:([a-z0-9_:+\-]+)\]\]")


@dataclass
class Step:
    kind: Literal["reasoning", "content", "tool_call", "disconnect"]
    text: str = ""
    tool_name: str = ""
    tool_arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class Scenario:
    name: str
    steps: list[Step]
    finish_reason: str = "stop"
    http_error: int | None = None
    delay_s: float = 0.0  # пауза перед каждым чанком


def _text_of(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def last_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return _text_of(message)
    return ""


def split_words(text: str) -> list[str]:
    """Режет текст на куски по словам с сохранением пробелов — похоже на токены модели."""
    return re.findall(r"\S+\s*|\s+", text)


MARKDOWN_SAMPLE = r"""## Пример форматирования

Строчные формулы: \(E = mc^2\) и $a^2 + b^2 = c^2$.

Блочная формула со слэшами:

\[
\int_0^1 x^2\,dx = \frac{1}{3}
\]

И с долларами:

$$\sum_{n=1}^{\infty} \frac{1}{n^2} = \frac{\pi^2}{6}$$

| Показатель | Значение |
| --- | --- |
| Выручка | 1 000 |

```python
def hello(name: str) -> str:
    return f"Привет, {name}!"
```
"""


# Строки из шаблонов config/prompts (см. config/prompts/README.md): по ним fake-llm ведёт себя
# как настоящая модель, которая следует системному промпту.
ADDRESS_LINE = re.compile(r"Обращение к пользователю: ([^\n]+?)\.(?:\n|$)")
TITLE_REQUEST = "Придумай короткий заголовок"
REWRITE_REQUEST = "Переформулируй запрос"
# Заголовки фрагментов RAG (system/knowledge.md.j2, результаты search_*): «[3] «Регламент»…».
FRAGMENT_HEADER = re.compile(r"^\[(\d+)\] «")
ATTACHMENT_START = "=== Файл «"
TITLE_SOURCE = re.compile(r"<<<\s*(.*?)\s*>>>", re.DOTALL)


def address_of(messages: list[dict[str, Any]]) -> str | None:
    """Обращение из системного промпта — только для первого ответа диалога (§11.1)."""
    if any(m.get("role") == "assistant" for m in messages):
        return None
    system = next((_text_of(m) for m in messages if m.get("role") == "system"), "")
    match = ADDRESS_LINE.search(system)
    if not match or match.group(1).startswith("на «вы»"):
        return None
    return match.group(1).strip()


def title_from(text: str) -> str:
    source = TITLE_SOURCE.search(text)
    words = SCENARIO_MARKER.sub("", source.group(1) if source else text).split()[:5]
    title = " ".join(words).strip(" .,!?:;«»\"'")
    return (title[:1].upper() + title[1:]) if title else "Новый диалог"


# Заголовок вложения в системном промпте (config/prompts/system/attachments.md.j2).
ATTACHMENT_HEADER = re.compile(r"=== Файл «(.+?)»")
QUOTED = re.compile(r"«([^»]+)»")
PAGE_REF = re.compile(r"стр\w*\.?\s*(\d+)", re.IGNORECASE)

SPREADSHEET_ARGS: dict[str, Any] = {
    "format": "xlsx",
    "title": "Продажи по кварталам",
    "sheets": [
        {
            "name": "Продажи",
            "columns": [
                {"header": "Квартал", "type": "text"},
                {"header": "Выручка", "type": "currency"},
                {"header": "Доля", "type": "percent"},
            ],
            "rows": [
                ["I кв.", 1200000, 0.2],
                ["II кв.", 1500000, 0.25],
                ["III кв.", 1800000, 0.3],
                ["IV кв.", 1500000, 0.25],
                ["Итого", "=SUM(B2:B5)", "=SUM(C2:C5)"],
            ],
        }
    ],
}
DOCUMENT_MARKDOWN = r"""# Формулы

Энергия покоя: $E = mc^2$.

$$\int_0^1 x^2\,dx = \frac{1}{3}$$

| Величина | Значение |
| --- | --- |
| Скорость света | 299 792 458 м/с |
"""
PRESENTATION_ARGS: dict[str, Any] = {
    "title": "План проекта",
    "slides": [
        {"layout": "title", "title": "План проекта", "bullets": ["Отдел разработки"]},
        {"layout": "content", "title": "Этапы", "bullets": ["Анализ", "Разработка", "Запуск"]},
    ],
}


def citation_for(haystack: str, line: str) -> str:
    """« [n]», если строка взята из пронумерованного фрагмента (ближайший заголовок выше)."""
    lines = haystack.splitlines()
    for i, current in enumerate(lines):
        if current.strip() != line:
            continue
        for previous in reversed(lines[:i]):
            if previous.startswith(ATTACHMENT_START):
                return ""
            header = FRAGMENT_HEADER.match(previous)
            if header:
                return f" [{header.group(1)}]"
        return ""
    return ""


def find_line(haystack: str, needle: str) -> str | None:
    """Строка текста, где встречается ``needle`` (без учёта регистра)."""
    lowered = needle.casefold().strip()
    if not lowered:
        return None
    for line in haystack.splitlines():
        if lowered in line.casefold():
            return line.strip()
    return None


def needle_of(text: str) -> str:
    quoted = QUOTED.search(text)
    return quoted.group(1) if quoted else text


def tool_arguments(name: str, messages: list[dict[str, Any]], clean: str) -> dict[str, Any]:
    """Типовые аргументы инструментов этапа 3 — как их сформировала бы модель."""
    system = next((_text_of(m) for m in messages if m.get("role") == "system"), "")
    attachment = ATTACHMENT_HEADER.search(system)
    file = attachment.group(1) if attachment else "документ"
    if name == "create_spreadsheet":
        return SPREADSHEET_ARGS
    if name == "create_csv":
        return {**SPREADSHEET_ARGS, "format": "csv"}
    if name in ("create_document", "create_pdf"):
        fmt = "pdf" if name == "create_pdf" else "docx"
        return {"format": fmt, "title": "Формулы", "markdown": DOCUMENT_MARKDOWN}
    if name == "create_presentation":
        return PRESENTATION_ARGS
    if name == "read_document":
        page = PAGE_REF.search(clean)
        start = int(page.group(1)) if page else 1
        return {"file": file, "page_from": start, "page_to": start}
    if name in ("get_document_outline", "read_spreadsheet"):
        return {"file": file}
    if name == "search_in_documents":
        return {"query": needle_of(clean) or "документ"}
    if name == "search_employees":
        return person_query(clean) or {"query": clean[:100] or "сотрудник"}
    if name == "run_sql_query":
        return {"sql": clean}
    if name == "describe_dataset":
        return {"name": "phonebook", "question": clean}
    if name == "call_data_function":
        return {"name": "search_employees", "params": person_query(clean) or {"query": clean}}
    return {}


# «Найди телефон Петрова из бухгалтерии», «почта Смирновой», «кто такой Ким».
PERSON_QUESTION = re.compile(
    r"(?:телефон\w*|номер\w*|почт\w*|контакт\w*|найди|кто так\w*)\s+"
    r"(?:(?:телефон\w*|номер\w*|почт\w*)\s+)?([А-ЯЁ][а-яё]+)(?:\s+из\s+([\w-]+))?",
)


def _stem(surname: str) -> str:
    # «Петрова», «Смирновой», «Иванову» → «Петров», «Смирнов», «Иванов»: поиск идёт по LIKE.
    for ending in ("ой", "ым", "ому", "а", "у", "е"):
        if surname.endswith(ending) and len(surname) - len(ending) >= 3:
            return surname[: -len(ending)]
    return surname


def _department(word: str) -> str:
    # «бухгалтерии» → «Бухгалтерия», «ИТ-отдела» → «ИТ-отдел».
    base = word[:-2] + "ия" if word.endswith("ии") else word[:-1] if word.endswith("а") else word
    return base[:1].upper() + base[1:]


def person_query(text: str) -> dict[str, Any] | None:
    match = PERSON_QUESTION.search(text)
    if match is None:
        return None
    args: dict[str, Any] = {"query": _stem(match.group(1))}
    if match.group(2):
        args["department"] = _department(match.group(2))
    return args


def phonebook_answer(result: str) -> str:
    """Ответ по таблице результата ``search_employees``: первая найденная строка."""
    if result.startswith("Ошибка"):
        # Инструмент не сработал (шлюз недоступен и т. п.) — не выдаём это за «никого нет».
        reason = result.removeprefix("Ошибка:").strip()
        return f"Не удалось обратиться к телефонному справочнику: {reason}"
    rows = [line for line in result.splitlines() if line.startswith("|")]
    if len(rows) < 3:
        return "В телефонном справочнике никого не нашёл."
    header = [c.strip() for c in rows[0].strip("|").split("|")]
    first = [c.strip() for c in rows[2].strip("|").split("|")]
    row = dict(zip(header, first, strict=False))
    phone = row.get("phone") or "—"
    internal = row.get("internal_phone")
    extra = f", внутренний {internal}" if internal else ""
    return f"Телефон {row.get('full_name', '?')} ({row.get('department', '?')}): {phone}{extra}."


# Псевдонимы сценариев: имя инструмента и формат файла.
TOOL_ALIASES = {"create_csv": "create_spreadsheet", "create_pdf": "create_document"}


REFUSAL = "Извините, с этим запросом я помочь не могу."
GUARD_MARKER = "[[guard:unsafe]]"
GUARD_WORDS = ("взорвать", "отравить")


def tool_scenario(
    name: str, tools: list[str], messages: list[dict[str, Any]], clean: str, *, loop: bool = False
) -> Scenario:
    """Вызов инструментов; после ответа инструмента (``role: tool``) — финальный текст."""
    last = messages[-1] if messages else {}
    if last.get("role") == "tool" and not loop:
        results: list[str] = []
        for message in reversed(messages):
            if message.get("role") != "tool":
                break
            results.insert(0, _text_of(message))
        joined = "\n".join(results)
        found = find_line(joined, needle_of(clean)) if QUOTED.search(clean) else None
        summary = f"{found}{citation_for(joined, found)}" if found else joined[:300]
        return Scenario(name, [Step("content", f"Готово. Результат инструмента: {summary}")])
    steps = [
        Step(
            "tool_call",
            tool_name=TOOL_ALIASES.get(tool, tool),
            tool_arguments=tool_arguments(tool, messages, clean),
        )
        for tool in tools
    ]
    return Scenario(name, steps, finish_reason="tool_calls")


def guard_verdict(text: str) -> str:
    """Ответ в формате Qwen3Guard: маркер [[guard:unsafe]] или «опасные» слова — Unsafe."""
    if GUARD_MARKER in text or any(word in text.casefold() for word in GUARD_WORDS):
        return "Safety: Unsafe\nCategories: Violent"
    return "Safety: Safe\nCategories: None"


def resolve(body: dict[str, Any], slow_delay_s: float) -> Scenario:
    messages: list[dict[str, Any]] = body.get("messages") or []
    user_text = last_user_text(messages)
    if str(body.get("model", "")).startswith("fake-guard"):
        return Scenario("guard", [Step("content", guard_verdict(user_text))])
    if TITLE_REQUEST in user_text and "[[scenario:title]]" not in user_text:
        # Служебный запрос заголовка: первые слова сообщения без маркера сценария.
        return Scenario("title", [Step("content", title_from(user_text))])
    if REWRITE_REQUEST in user_text:
        # Переформулировка для RAG: сообщение пользователя без маркера сценария, как есть.
        source = TITLE_SOURCE.search(user_text)
        query = SCENARIO_MARKER.sub("", source.group(1) if source else user_text)
        return Scenario("rewrite", [Step("content", " ".join(query.split()) or "запрос")])
    match = SCENARIO_MARKER.search(user_text)
    thinking = bool((body.get("chat_template_kwargs") or {}).get("enable_thinking"))
    name = match.group(1) if match else ("thinking" if thinking else "default")
    clean = SCENARIO_MARKER.sub("", user_text).strip()
    last = messages[-1] if messages else {}
    address = address_of(messages)

    def greet(text: str) -> str:
        return f"{address}, {text[:1].lower()}{text[1:]}" if address else text

    offered = {t.get("function", {}).get("name") for t in body.get("tools") or []}
    if name == "default" and "search_employees" in offered and person_query(clean):
        name = "phonebook"  # «Кадровый бот»: вопрос о сотруднике — поиск в справочнике (§9.5)
    if name == "phonebook":
        if last.get("role") == "tool":
            return Scenario(name, [Step("content", phonebook_answer(_text_of(last)))])
        return Scenario(
            name,
            [
                Step(
                    "tool_call",
                    tool_name="search_employees",
                    tool_arguments=person_query(clean) or {"query": clean[:100]},
                )
            ],
            finish_reason="tool_calls",
        )
    if name == "default":
        return Scenario(name, [Step("content", greet(f"Это ответ fake-llm на запрос: «{clean}»."))])
    if name == "thinking":
        return Scenario(
            name,
            [
                Step(
                    "reasoning",
                    "Пользователь спрашивает. Подумаю шаг за шагом: "
                    "сначала разберу вопрос, затем сформулирую ответ.",
                ),
                Step("content", greet(f"Обдуманный ответ fake-llm на запрос: «{clean}».")),
            ],
        )
    if name == "markdown":
        return Scenario(name, [Step("content", MARKDOWN_SAMPLE)])
    if name == "markdown_slow":
        # То же форматирование по словам с паузой — для проверки рендера во время стрима.
        return Scenario(name, [Step("content", MARKDOWN_SAMPLE)], delay_s=slow_delay_s / 3)
    if name == "tool_call_search":
        if last.get("role") == "tool":
            result = _text_of(last)
            return Scenario(name, [Step("content", f"По данным базы знаний [1]: {result[:200]}")])
        return Scenario(
            name,
            [
                Step(
                    "tool_call",
                    tool_name="search_knowledge_base",
                    tool_arguments={"query": clean or "поиск"},
                )
            ],
            finish_reason="tool_calls",
        )
    if name == "find":
        # Ответ «по документу»: строка из системного промпта или результатов инструментов.
        haystack = "\n".join(_text_of(m) for m in messages if m.get("role") in ("system", "tool"))
        needle = needle_of(clean)
        line = find_line(haystack, needle)
        text = (
            f"Нашёл в документе: {line}{citation_for(haystack, line)}"
            if line
            else f"В документах нет «{needle}»."
        )
        return Scenario(name, [Step("content", text)])
    if name == "moderation":
        # Явное нарушение: скрытый репорт, затем нейтральный отказ (§9.6).
        if last.get("role") == "tool":
            return Scenario(name, [Step("content", REFUSAL)])
        arguments = {
            "category": "illegal",
            "severity": "high",
            "summary": "Просьба помочь с противоправным действием",
            "evidence": clean[:200],
        }
        return Scenario(
            name,
            [Step("tool_call", tool_name="report_incident", tool_arguments=arguments)],
            finish_reason="tool_calls",
        )
    if name.startswith("tool:"):
        return tool_scenario(name, name.removeprefix("tool:").split("+"), messages, clean)
    if name == "tool_loop":
        return tool_scenario(name, ["list_attachments"], messages, clean, loop=True)
    if name == "error_500":
        return Scenario(name, [], http_error=500)
    if name == "disconnect":
        return Scenario(
            name,
            [
                Step("content", "Начинаю отвечать, но соединение сейчас оборвётся"),
                Step("disconnect"),
            ],
        )
    if name == "slow":
        text = " ".join(f"Слово{i}" for i in range(1, 41)) + "."
        return Scenario(name, [Step("content", text)], delay_s=slow_delay_s)
    if name == "title":
        return Scenario(name, [Step("content", "Тестовый заголовок чата")])
    return Scenario("unknown", [Step("content", f"fake-llm: неизвестный сценарий {name!r}.")])


def tool_call_payload(step: Step, call_id: str) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": step.tool_name,
            "arguments": json.dumps(step.tool_arguments, ensure_ascii=False),
        },
    }


SCENARIO_NAMES = (
    "default",
    "thinking",
    "markdown",
    "markdown_slow",
    "tool_call_search",
    "find",
    "tool:<имя>[+<имя>…]",
    "tool_loop",
    "error_500",
    "disconnect",
    "slow",
    "title",
)
