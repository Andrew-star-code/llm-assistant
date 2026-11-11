from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from openai.types.chat import ChatCompletionChunk

from app.core.config import REPO_ROOT, ModelEndpoint, load_settings
from app.core.errors import AppError
from app.modules.completions.context import DROPPED_NOTE, TRUNCATED_NOTE, LoopContext
from app.modules.completions.generation import (
    HISTORY_CUT_NOTE,
    _error_payload,
    clean_title,
    fallback_title,
    history_steps,
)
from app.modules.completions.prompt import (
    PromptRenderer,
    PromptUser,
    ToolStep,
    Turn,
    build_messages,
    system_prompt,
)
from app.modules.completions.streaming import format_sse
from app.modules.llm.registry import ModelRegistry
from app.modules.llm.stream import Delta, Finish, Usage, parse_stream
from app.modules.llm.tokens import TokenCounter
from app.modules.tools.models import ToolCall

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


# ------------------------------------------------------------------ бюджет цикла инструментов


def _tool_turn() -> Turn:
    return Turn(
        "assistant",
        "В отделе 12 человек.",
        (
            ToolStep(1, "c1", "describe_dataset", '{"name": "phonebook"}', "поля: фио, отдел"),
            ToolStep(2, "c2", "run_sql_query", '{"sql": "SELECT 1"}', "12"),
            ToolStep(2, "c3", "run_sql_query", '{"sql": "SELECT 2"}', "7"),
        ),
    )


def test_turn_with_tool_steps_becomes_api_messages() -> None:
    items = _tool_turn().messages()
    roles = [m["role"] for m in items]
    assert roles == ["assistant", "tool", "assistant", "tool", "tool", "assistant"]
    assert [c["id"] for c in items[2]["tool_calls"]] == ["c2", "c3"]
    assert items[2]["content"] is None and items[1]["tool_call_id"] == "c1"
    assert items[-1] == {"role": "assistant", "content": "В отделе 12 человек."}


def test_token_counter_counts_tool_calls() -> None:
    counter = TokenCounter(None)
    plain = {"role": "assistant", "content": None}
    call = {"id": "c", "type": "function", "function": {"name": "f", "arguments": "x" * 280}}
    assert counter.count_messages([{**plain, "tool_calls": [call]}]) >= (
        counter.count_messages([plain]) + 100
    )


def test_history_keeps_tool_turn_whole_and_leaves_reserve() -> None:
    counter = TokenCounter(None)
    history = [Turn("user", "Сколько людей в отделе?"), _tool_turn()]
    kwargs: dict[str, Any] = {
        "system": "система",
        "history": history,
        "message": "а в соседнем?",
        "counter": counter,
    }
    built = build_messages(**kwargs, endpoint=_endpoint(context=1000, reserve=100), overhead=50)
    assert built.history_used == 2 and built.history_messages == 7
    assert len(built.costs) == len(built.messages) == 9
    assert built.prompt_tokens == 50 + sum(built.costs) and built.budget == 900
    assert built.trace()["history_tool_steps"] == 3
    # Резерв под результаты инструментов вытесняет историю, но не сам вопрос.
    tight = build_messages(
        **kwargs, endpoint=_endpoint(context=1000, reserve=100), history_reserve=880
    )
    assert tight.history_used == 0 and [m["role"] for m in tight.messages] == ["system", "user"]
    # Описания инструментов занимают контекст: с ними вопрос может не поместиться.
    with pytest.raises(AppError, match="слишком длинное"):
        build_messages(**kwargs, endpoint=_endpoint(context=1000, reserve=100), overhead=890)


def _loop(budget: int, history: list[Turn] | None = None) -> LoopContext:
    counter = TokenCounter(None)
    built = build_messages(
        system="система",
        history=history or [],
        message="вопрос",
        endpoint=_endpoint(context=budget + 100, reserve=100),
        counter=counter,
    )
    return LoopContext.start(built, counter)


def _calls(*ids: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": i, "type": "function", "function": {"name": "read", "arguments": "{}"}}
            for i in ids
        ],
    }


def test_loop_context_within_budget_changes_nothing() -> None:
    loop = _loop(1000)
    loop.add_calls(_calls("a"))
    loop.add_result("a", "короткий результат")
    before = [dict(m) for m in loop.messages]
    loop.fit()
    assert loop.messages == before
    assert loop.stats.trace() == {"budget": 1000, "peak_tokens": loop.used}


def test_loop_context_drops_old_history_first() -> None:
    history = [
        Turn("user", "первый вопрос " * 10),
        _tool_turn(),
        Turn("user", "второй вопрос " * 10),
        Turn("assistant", "второй ответ " * 10),
    ]
    loop = _loop(400, history)
    assert loop.history == 9
    loop.add_calls(_calls("a"))
    loop.add_result("a", "результат " * 60)
    loop.fit()
    assert loop.used <= 400
    # Ушёл первый ход целиком — вместе с вызовами инструментов; результат не тронут.
    assert [m["role"] for m in loop.messages[:3]] == ["system", "user", "assistant"]
    assert loop.messages[1]["content"].startswith("второй вопрос")
    assert loop.messages[-1]["content"] == "результат " * 60
    assert loop.stats.trace()["history_dropped"] == 7
    assert "tool_results_truncated" not in loop.stats.trace()


def test_loop_context_drops_stale_results_before_fresh() -> None:
    loop = _loop(500)
    loop.add_calls(_calls("a"))
    loop.add_result("a", "старый результат " * 60)
    loop.fit()
    loop.add_calls(_calls("b"))
    loop.add_result("b", "свежий результат " * 60)
    loop.fit()
    assert loop.used <= 500
    stale, fresh = (m for m in loop.messages if m["role"] == "tool")
    assert stale["content"] == DROPPED_NOTE and stale["tool_call_id"] == "a"
    assert fresh["content"] == "свежий результат " * 60
    assert loop.stats.results_dropped == 1 and loop.stats.results_truncated == 0


def test_loop_context_truncates_fresh_results_fairly() -> None:
    loop = _loop(1200)
    loop.add_calls(_calls("a", "b", "c"))
    loop.add_result("a", "короткий")
    loop.add_result("b", "длинный результат " * 200)
    loop.add_result("c", "ещё длиннее результат " * 300)
    loop.fit()
    assert loop.used <= 1200
    short, long_b, long_c = (m["content"] for m in loop.messages if m["role"] == "tool")
    assert short == "короткий"
    assert long_b.endswith(TRUNCATED_NOTE) and long_c.endswith(TRUNCATED_NOTE)
    assert long_b.startswith("длинный результат ")
    # Длинные делят остаток поровну и используют бюджет почти целиком.
    assert abs(len(long_b) - len(long_c)) < 200 and loop.used > 1000
    assert loop.stats.results_truncated == 2 and loop.stats.peak_tokens == loop.used


def test_loop_context_reports_overflow_when_nothing_helps() -> None:
    loop = _loop(100)
    loop.add_calls(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "a",
                    "type": "function",
                    "function": {"name": "create_document", "arguments": "текст " * 200},
                }
            ],
        }
    )
    loop.add_result("a", "готово")
    with pytest.raises(AppError) as error:
        loop.fit()
    assert error.value.code == "context_overflow"


def test_history_steps_skip_hidden_and_auto_search() -> None:
    def call(tool: str, iteration: int, result: str, visibility: str = "visible") -> ToolCall:
        return ToolCall(
            call_id=f"{tool}-{iteration}",
            tool=tool,
            arguments={"query": "отпуск"},
            result_preview=result,
            status="ok",
            duration_ms=1,
            visibility=visibility,
            iteration=iteration,
            label="tools.x",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    steps = history_steps(
        [
            call("read_document", 2, "я" * 50),
            call("search_knowledge_base", 0, "фрагментов: 3"),
            call("report_incident", 1, "принято", "hidden"),
            call("run_sql_query", 1, "12"),
        ],
        limit=20,
    )
    assert [(s.name, s.iteration) for s in steps] == [("run_sql_query", 1), ("read_document", 2)]
    assert steps[0].result == "12" and steps[0].arguments == '{"query": "отпуск"}'
    assert steps[1].result == "я" * 20 + HISTORY_CUT_NOTE


def test_expected_errors_are_not_internal() -> None:
    payload = _error_payload(AppError("Не помещается", code="context_overflow", status_code=413))
    assert payload == {"code": "context_overflow", "message": "Не помещается", "retryable": False}
    assert _error_payload(RuntimeError("x"))["code"] == "internal_error"
