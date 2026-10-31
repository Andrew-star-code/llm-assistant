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

SCENARIO_MARKER = re.compile(r"\[\[scenario:([a-z0-9_:\-]+)\]\]")


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


def resolve(body: dict[str, Any], slow_delay_s: float) -> Scenario:
    messages: list[dict[str, Any]] = body.get("messages") or []
    user_text = last_user_text(messages)
    match = SCENARIO_MARKER.search(user_text)
    thinking = bool((body.get("chat_template_kwargs") or {}).get("enable_thinking"))
    name = match.group(1) if match else ("thinking" if thinking else "default")
    clean = SCENARIO_MARKER.sub("", user_text).strip()
    last = messages[-1] if messages else {}
    if not match and TITLE_REQUEST in user_text:
        return Scenario("title", [Step("content", title_from(user_text))])
    address = address_of(messages)

    def greet(text: str) -> str:
        return f"{address}, {text[:1].lower()}{text[1:]}" if address else text

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
    "error_500",
    "disconnect",
    "slow",
    "title",
)
