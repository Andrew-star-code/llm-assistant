from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from openai.types.chat import ChatCompletionChunk

from app.core.config import REPO_ROOT, ModelEndpoint, load_settings
from app.core.errors import AppError
from app.modules.completions.generation import clean_title, fallback_title
from app.modules.completions.prompt import (
    PromptRenderer,
    PromptUser,
    Turn,
    build_messages,
    system_prompt,
)
from app.modules.completions.streaming import format_sse
from app.modules.llm.registry import ModelRegistry
from app.modules.llm.stream import Delta, Finish, Usage, parse_stream
from app.modules.llm.tokens import TokenCounter

RENDERER = PromptRenderer(REPO_ROOT / "config" / "prompts")


def _user(address: str | None = "Иван Петрович") -> PromptUser:
    return PromptUser("Иванов Иван Петрович", "Руководитель ИТ-отдела", "ИТ-отдел", address)


def test_system_prompt_personalization() -> None:
    settings = load_settings()
    now = datetime(2026, 10, 31, 9, 30, tzinfo=UTC)
    text = system_prompt(RENDERER, settings, _user(), now)
    assert "ФИО: Иванов Иван Петрович" in text
    assert "Должность: Руководитель ИТ-отдела" in text
    assert "Отдел: ИТ-отдел" in text
    assert "Обращение к пользователю: Иван Петрович." in text
    assert "31.10.2026 12:30 (Europe/Moscow)" in text  # время компании, а не UTC
    assert settings.chat.company_name in text

    formal = system_prompt(RENDERER, settings, _user(None), now)
    assert "Обращение к пользователю: на «вы», без имени." in formal


def _endpoint(context: int, reserve: int) -> ModelEndpoint:
    return ModelEndpoint(
        base_url="http://x/v1", model="m", context_length=context, max_output_tokens=reserve
    )


def test_budget_truncates_oldest_history_first() -> None:
    counter = TokenCounter(None)
    history = [
        Turn("user" if i % 2 == 0 else "assistant", f"сообщение {i} " * 20) for i in range(10)
    ]
    built = build_messages(
        system="система",
        history=history,
        message="новый вопрос",
        endpoint=_endpoint(context=600, reserve=100),
        counter=counter,
    )
    roles = [m["role"] for m in built.messages]
    assert roles[0] == "system" and built.messages[-1] == {
        "role": "user",
        "content": "новый вопрос",
    }
    assert 0 < built.history_used < built.history_total
    # Сохранена самая свежая история и она начинается с вопроса пользователя.
    assert built.messages[1]["role"] == "user"
    assert built.messages[-2]["content"] == history[-1].content
    assert built.prompt_tokens <= 500


def test_budget_rejects_too_long_message() -> None:
    with pytest.raises(AppError, match="слишком длинное"):
        build_messages(
            system="система",
            history=[],
            message="слово " * 1000,
            endpoint=_endpoint(context=500, reserve=100),
            counter=TokenCounter(None),
        )


def _registry(**chat: Any) -> ModelRegistry:
    settings = load_settings(
        models={
            "chat": {"base_url": "http://x/v1", "model": "m", **chat},
            "chat-thinking": {"base_url": "http://y/v1", "model": "big"},
        }
    )
    return ModelRegistry(settings)


def test_thinking_modes() -> None:
    plan = _registry().plan("chat", thinking=True)  # из config/models.yaml: chat_template_kwarg
    assert plan.thinking is True
    assert plan.params["extra_body"]["chat_template_kwargs"] == {"enable_thinking": True}
    assert plan.params["temperature"] == 1.0 and plan.params["extra_body"]["top_k"] == 20
    off = _registry().plan("chat", thinking=False)
    assert off.params["extra_body"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert off.params["presence_penalty"] == 1.5

    effort = _registry(thinking={"mode": "reasoning_effort", "effort": "high"}).plan(
        "chat", thinking=True
    )
    assert effort.params["reasoning_effort"] == "high"

    separate = _registry(thinking={"mode": "separate_model", "model_role": "chat-thinking"})
    plan = separate.plan("chat", thinking=True)
    assert (plan.role, plan.endpoint.model) == ("chat-thinking", "big")
    assert separate.plan("chat", thinking=False).endpoint.model == "m"

    none = _registry(thinking={"mode": "none"})
    assert not none.thinking_available("chat")
    assert none.plan("chat", thinking=True).thinking is False


def _chunk(
    delta: dict[str, Any], finish: str | None = None, usage: dict[str, Any] | None = None
) -> ChatCompletionChunk:
    choices = [] if usage else [{"index": 0, "delta": delta, "finish_reason": finish}]
    return ChatCompletionChunk.model_validate(
        {
            "id": "c",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "m",
            "choices": choices,
            "usage": usage,
        }
    )


async def test_parse_stream_understands_both_reasoning_fields() -> None:
    async def chunks() -> Any:
        yield _chunk({"role": "assistant", "content": ""})
        yield _chunk({"reasoning": "думаю "})
        yield _chunk({"reasoning_content": "ещё"})
        yield _chunk({"content": "ответ"})
        yield _chunk({}, finish="stop")
        yield _chunk(
            {},
            usage={
                "prompt_tokens": 5,
                "completion_tokens": 3,
                "total_tokens": 8,
                "completion_tokens_details": {"reasoning_tokens": 2},
            },
        )

    items = [item async for item in parse_stream(chunks())]
    assert items == [
        Delta("reasoning", "думаю "),
        Delta("reasoning", "ещё"),
        Delta("content", "ответ"),
        Finish("stop"),
        Usage(prompt_tokens=5, completion_tokens=3, reasoning_tokens=2),
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Оформление отпуска", "Оформление отпуска"),
        ("«Оформление отпуска в декабре»", "Оформление отпуска в декабре"),
        ("Заголовок: Командировка в Казань.", "Командировка в Казань"),
        (
            "**Очень длинный заголовок из восьми слов про всё на свете**",
            "Очень длинный заголовок из восьми слов",
        ),
        ("\n\n  Сводка продаж\nпояснение", "Сводка продаж"),
        ("  ", None),
    ],
)
def test_clean_title(raw: str, expected: str | None) -> None:
    assert clean_title(raw) == expected


def test_fallback_title() -> None:
    assert (
        fallback_title("Как оформить отпуск в декабре этого года")
        == "Как оформить отпуск в декабре этого…"
    )
    assert fallback_title("Коротко") == "Коротко"


def test_format_sse() -> None:
    assert format_sse(3, "content.delta", {"text": "При\nвет"}) == (
        'id: 3\nevent: content.delta\ndata: {"text":"При\\nвет"}\n\n'
    )
