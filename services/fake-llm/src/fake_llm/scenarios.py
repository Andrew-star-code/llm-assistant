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


def resolve(body: dict[str, Any], slow_delay_s: float) -> Scenario:
    messages: list[dict[str, Any]] = body.get("messages") or []
    user_text = last_user_text(messages)
    match = SCENARIO_MARKER.search(user_text)
    thinking = bool((body.get("chat_template_kwargs") or {}).get("enable_thinking"))
    name = match.group(1) if match else ("thinking" if thinking else "default")
    clean = SCENARIO_MARKER.sub("", user_text).strip()
    last = messages[-1] if messages else {}

    if name == "default":
        return Scenario(name, [Step("content", f"Это ответ fake-llm на запрос: «{clean}».")])
    if name == "thinking":
        return Scenario(
            name,
            [
                Step(
                    "reasoning",
                    "Пользователь спрашивает. Подумаю шаг за шагом: "
                    "сначала разберу вопрос, затем сформулирую ответ.",
                ),
                Step("content", f"Обдуманный ответ fake-llm на запрос: «{clean}»."),
            ],
        )
    if name == "markdown":
        return Scenario(name, [Step("content", MARKDOWN_SAMPLE)])
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
    "tool_call_search",
    "error_500",
    "disconnect",
    "slow",
    "title",
)
