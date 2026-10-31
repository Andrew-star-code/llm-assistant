"""Совместимость fake-llm с официальным SDK openai — тем же клиентом, что использует api."""

from __future__ import annotations

import json
from typing import Any

import httpx
import openai
import pytest
from openai import AsyncOpenAI


def _msg(text: str) -> list[Any]:
    return [{"role": "user", "content": text}]


async def _collect(client: AsyncOpenAI, text: str, **kwargs: Any) -> dict[str, Any]:
    stream = await client.chat.completions.create(
        model="fake-chat",
        messages=_msg(text),
        stream=True,
        stream_options={"include_usage": True},
        **kwargs,
    )
    out: dict[str, Any] = {"content": "", "reasoning": "", "tool_calls": {}, "finish": None}
    async for chunk in stream:
        if chunk.usage:
            out["usage"] = chunk.usage
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        delta = choice.delta
        out["content"] += delta.content or ""
        out["reasoning"] += (delta.model_extra or {}).get("reasoning") or ""
        for tc in delta.tool_calls or []:
            entry = out["tool_calls"].setdefault(tc.index, {"name": "", "arguments": ""})
            if tc.function and tc.function.name:
                entry["name"] = tc.function.name
            if tc.function and tc.function.arguments:
                entry["arguments"] += tc.function.arguments
        if choice.finish_reason:
            out["finish"] = choice.finish_reason
    return out


async def test_default_stream(client: AsyncOpenAI) -> None:
    result = await _collect(client, "Привет")
    assert result["content"] == "Это ответ fake-llm на запрос: «Привет»."
    assert result["reasoning"] == ""
    assert result["finish"] == "stop"
    assert result["usage"].completion_tokens > 0


async def test_thinking_by_flag(client: AsyncOpenAI) -> None:
    result = await _collect(
        client, "Сколько будет 2+2?", extra_body={"chat_template_kwargs": {"enable_thinking": True}}
    )
    assert result["reasoning"].startswith("Пользователь спрашивает")
    assert result["content"].startswith("Обдуманный ответ")
    assert result["usage"].completion_tokens_details.reasoning_tokens > 0


async def test_thinking_by_marker(client: AsyncOpenAI) -> None:
    result = await _collect(client, "[[scenario:thinking]] вопрос")
    assert result["reasoning"]
    assert "«вопрос»" in result["content"]


async def test_tool_call_then_final_answer(client: AsyncOpenAI) -> None:
    first = await _collect(client, "[[scenario:tool_call_search]] отпуск")
    assert first["finish"] == "tool_calls"
    call = first["tool_calls"][0]
    assert call["name"] == "search_knowledge_base"
    assert json.loads(call["arguments"]) == {"query": "отпуск"}

    messages: list[Any] = [
        {"role": "user", "content": "[[scenario:tool_call_search]] отпуск"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": call["name"], "arguments": call["arguments"]},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "Отпуск — 28 дней."},
    ]
    response = await client.chat.completions.create(model="fake-chat", messages=messages)
    assert response.choices[0].message.content == "По данным базы знаний [1]: Отпуск — 28 дней."


async def test_non_stream_response(client: AsyncOpenAI) -> None:
    response = await client.chat.completions.create(
        model="fake-utility", messages=_msg("[[scenario:title]]")
    )
    assert response.model == "fake-utility"
    assert response.choices[0].message.content == "Тестовый заголовок чата"


async def test_error_500(client: AsyncOpenAI) -> None:
    with pytest.raises(openai.InternalServerError):
        await client.chat.completions.create(
            model="fake-chat", messages=_msg("[[scenario:error_500]]"), stream=True
        )


async def test_disconnect_mid_stream(client: AsyncOpenAI) -> None:
    received = ""
    with pytest.raises((openai.APIConnectionError, httpx.RemoteProtocolError, httpx.ReadError)):
        stream = await client.chat.completions.create(
            model="fake-chat", messages=_msg("[[scenario:disconnect]]"), stream=True
        )
        async for chunk in stream:
            if chunk.choices:
                received += chunk.choices[0].delta.content or ""
    assert received.startswith("Начинаю отвечать")


async def test_slow_stream_has_many_chunks(client: AsyncOpenAI) -> None:
    result = await _collect(client, "[[scenario:slow]]")
    assert result["content"].startswith("Слово1 Слово2")
    assert result["content"].endswith("Слово40.")


async def test_markdown_scenario(client: AsyncOpenAI) -> None:
    result = await _collect(client, "[[scenario:markdown]]")
    assert r"\(E = mc^2\)" in result["content"]
    assert "```python" in result["content"]


async def test_embeddings_are_deterministic_and_normalized(client: AsyncOpenAI) -> None:
    response = await client.embeddings.create(
        model="fake-embed", input=["договор поставки", "договор поставки", "отпуск"]
    )
    a, b, c = (d.embedding for d in response.data)
    assert len(a) == 64
    assert a == b
    assert abs(sum(x * x for x in a) - 1) < 1e-9
    assert sum(x * y for x, y in zip(a, c, strict=True)) < 0.9


async def test_rerank(base_url: str) -> None:
    async with httpx.AsyncClient(base_url=base_url) as http:
        response = await http.post(
            "/v1/rerank",
            json={
                "model": "fake-rerank",
                "query": "договор поставки",
                "documents": ["про отпуск", "типовой договор поставки"],
                "top_n": 1,
            },
        )
    body = response.json()
    assert body["results"] == [
        {"index": 1, "document": {"text": "типовой договор поставки"}, "relevance_score": 1.0}
    ]


async def test_models(client: AsyncOpenAI) -> None:
    models = [m.id async for m in client.models.list()]
    assert "fake-chat" in models


async def test_first_answer_uses_address_from_system_prompt(client: AsyncOpenAI) -> None:
    system = "Правила.\n\nОбращение к пользователю: Иван Петрович.\nОбращайся так."
    messages: list[Any] = [
        {"role": "system", "content": system},
        {"role": "user", "content": "Привет"},
    ]
    first = await client.chat.completions.create(model="fake-chat", messages=messages)
    assert (
        first.choices[0].message.content == "Иван Петрович, это ответ fake-llm на запрос: «Привет»."
    )

    later = [*messages, {"role": "assistant", "content": "…"}, {"role": "user", "content": "Ещё"}]
    second = await client.chat.completions.create(model="fake-chat", messages=later)
    assert second.choices[0].message.content == "Это ответ fake-llm на запрос: «Ещё»."

    formal: list[Any] = [
        {"role": "system", "content": "Обращение к пользователю: на «вы», без имени."},
        {"role": "user", "content": "Привет"},
    ]
    third = await client.chat.completions.create(model="fake-chat", messages=formal)
    assert third.choices[0].message.content == "Это ответ fake-llm на запрос: «Привет»."


async def test_title_request(client: AsyncOpenAI) -> None:
    prompt = (
        "Придумай короткий заголовок (3–6 слов)…\n"
        "<<<\nкак оформить отпуск в декабре этого года\n>>>"
    )
    response = await client.chat.completions.create(
        model="fake-utility", messages=[{"role": "user", "content": prompt}]
    )
    assert response.choices[0].message.content == "Как оформить отпуск в декабре"


async def test_parallel_tool_calls(client: AsyncOpenAI) -> None:
    result = await _collect(
        client, "[[scenario:tool:list_attachments+search_in_documents]] «отпуск»"
    )
    assert result["finish"] == "tool_calls"
    calls = result["tool_calls"]
    assert [calls[0]["name"], calls[1]["name"]] == ["list_attachments", "search_in_documents"]
    assert json.loads(calls[1]["arguments"]) == {"query": "отпуск"}


def test_tool_scenario_arguments_and_final_answer() -> None:
    from fake_llm.scenarios import resolve

    system = {"role": "system", "content": "=== Файл «отчёт.docx» (docx, страниц: 30) ==="}
    user = {"role": "user", "content": "[[scenario:tool:read_document]] прочитай стр. 25"}
    first = resolve({"messages": [system, user]}, 0)
    [step] = first.steps
    assert step.tool_name == "read_document"
    assert step.tool_arguments == {"file": "отчёт.docx", "page_from": 25, "page_to": 25}

    pdf = resolve({"messages": [system, {**user, "content": "[[scenario:tool:create_pdf]]"}]}, 0)
    assert pdf.steps[0].tool_name == "create_document"
    assert pdf.steps[0].tool_arguments["format"] == "pdf"

    question = {"role": "user", "content": "[[scenario:tool:read_document]] где «код проекта»?"}
    tool = {"role": "tool", "tool_call_id": "c1", "content": "[стр. 25]\nКод проекта: ZX-42\n"}
    final = resolve({"messages": [system, question, {"role": "assistant"}, tool]}, 0)
    assert final.steps[0].text == "Готово. Результат инструмента: Код проекта: ZX-42"


def test_tool_loop_never_finishes() -> None:
    from fake_llm.scenarios import resolve

    tool = {"role": "tool", "tool_call_id": "c1", "content": "файлов нет"}
    user = {"role": "user", "content": "[[scenario:tool_loop]]"}
    assert resolve({"messages": [user, tool]}, 0).finish_reason == "tool_calls"


def test_find_in_system_prompt() -> None:
    from fake_llm.scenarios import resolve

    system = {"role": "system", "content": "Документ:\n[стр. 12]\nКодовое слово: ЛАЗУРЬ-7\n"}
    user = {"role": "user", "content": "[[scenario:find]] «кодовое слово»"}
    assert resolve({"messages": [system, user]}, 0).steps[0].text == (
        "Нашёл в документе: Кодовое слово: ЛАЗУРЬ-7"
    )
    missing = resolve({"messages": [user]}, 0).steps[0].text
    assert missing == "В документах нет «кодовое слово»."


def test_rewrite_request_returns_question_without_marker() -> None:
    from fake_llm.scenarios import resolve

    prompt = (
        "Переформулируй запрос пользователя…\n<<<\n[[scenario:tool:read_document]] Где  договор?"
        "\n>>>"
    )
    scenario = resolve({"messages": [{"role": "user", "content": prompt}]}, 0)
    assert scenario.name == "rewrite" and scenario.steps[0].text == "Где договор?"


def test_find_cites_knowledge_fragment() -> None:
    from fake_llm.scenarios import resolve

    system = (
        "Фрагменты из баз знаний…\n[1] «Регламент» (Общая), стр. 2\nПро отпуск.\n"
        "[2] «Договоры», стр. 5\nДоговор № 17-42/Б подписан.\n"
        "=== Файл «a.txt» (txt, страниц: 1) ===\nСтрока вложения про договор."
    )
    user = {"role": "user", "content": "[[scenario:find]] «17-42/Б»"}
    text = resolve({"messages": [{"role": "system", "content": system}, user]}, 0).steps[0].text
    assert text == "Нашёл в документе: Договор № 17-42/Б подписан. [2]"
    attachment = {"role": "user", "content": "[[scenario:find]] «Строка вложения»"}
    text = resolve({"messages": [{"role": "system", "content": system}, attachment]}, 0)
    assert text.steps[0].text == "Нашёл в документе: Строка вложения про договор."


def test_rerank_matches_word_forms() -> None:
    from fake_llm.app import overlap_score

    assert overlap_score("договорам поставки", "Типовой договор поставок") == 1.0
