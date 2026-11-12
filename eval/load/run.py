"""Нагрузочный тест чата (§18.4, этап 10): N одновременных диалогов против работающего стенда.

Каждый виртуальный пользователь входит, создаёт чат, отправляет сообщение и читает SSE до
``message.end`` — тот же путь, что у браузера. Замеряются приём сообщения (``POST``), время до
первого токена, длительность ответа и скорость генерации; итог сравнивается с целями §18.4.

Против fake-llm (дев-стенд) цифры показывают накладные расходы приложения: api, очередь и
исполнитель генерации, Redis Streams, SSE, PostgreSQL. Против настоящей модели — то, что увидят
пользователи; полный тест самой модели — ``vllm bench serve`` (runbook первого запуска).

    uv run python eval/load/run.py --concurrency 10 --messages 100 --check

Лимиты: по умолчанию у пользователя 2 одновременных ответа и 200 сообщений в сутки, поэтому на
10 одновременных диалогов нужно 5 логинов; ``--admin`` временно поднимает лимиты тестовым
пользователям через админ-API (политики со сроком 2 часа, запись в аудите).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import ssl
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

DEV_LOGINS = "ivanov,kim,smirnova,petrov,sidorova"
# Цели §18.4 для 10 одновременных генераций.
TARGET_TTFT_P95_S = 2.0
TARGET_TOKENS_PER_S = 20.0
RAISED_LIMITS = (("concurrent_generations", None, 1000), ("messages", "day", 1_000_000))


@dataclass
class Sample:
    status: str  # completed | error | … | http_<код> | limited | failed
    accept_s: float = 0.0  # POST /messages → 202
    ttft_s: float | None = None  # отправка → первая дельта
    total_s: float = 0.0
    tokens: int = 0
    tokens_per_s: float | None = None
    error: str | None = None


@dataclass
class Report:
    base_url: str
    concurrency: int
    messages: int
    prompt: str
    duration_s: float
    statuses: dict[str, int]
    errors: dict[str, int]
    accept_s: dict[str, float]
    ttft_s: dict[str, float]
    total_s: dict[str, float]
    tokens_per_s: dict[str, float]
    answers_per_s: float
    checks: dict[str, bool] = field(default_factory=dict)


def percentile(values: list[float], q: float) -> float:
    """Перцентиль методом ближайшего ранга: p95 из 20 замеров — 19-й по возрастанию."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    return {
        "p50": round(percentile(values, 0.5), 3),
        "p95": round(percentile(values, 0.95), 3),
        "max": round(max(values), 3),
    }


def build_report(
    samples: list[Sample], *, base_url: str, concurrency: int, prompt: str, duration_s: float
) -> Report:
    done = [s for s in samples if s.status == "completed"]
    statuses: dict[str, int] = {}
    errors: dict[str, int] = {}
    for sample in samples:
        statuses[sample.status] = statuses.get(sample.status, 0) + 1
        if sample.error:
            errors[sample.error] = errors.get(sample.error, 0) + 1
    report = Report(
        base_url=base_url,
        concurrency=concurrency,
        messages=len(samples),
        prompt=prompt,
        duration_s=round(duration_s, 2),
        statuses=statuses,
        errors=errors,
        accept_s=summary([s.accept_s for s in samples if s.accept_s]),
        ttft_s=summary([s.ttft_s for s in done if s.ttft_s is not None]),
        total_s=summary([s.total_s for s in done]),
        tokens_per_s=summary([s.tokens_per_s for s in done if s.tokens_per_s is not None]),
        answers_per_s=round(len(done) / duration_s, 2) if duration_s else 0.0,
    )
    speeds = [s.tokens_per_s for s in done if s.tokens_per_s is not None]
    report.checks = {
        "all_completed": len(done) == len(samples) and bool(samples),
        "ttft_p95": bool(report.ttft_s) and report.ttft_s["p95"] <= TARGET_TTFT_P95_S,
        # Скорость на пользователя: медленнейшая половина не должна быть ниже цели.
        "tokens_per_s": bool(speeds) and percentile(speeds, 0.5) >= TARGET_TOKENS_PER_S,
    }
    return report


class User:
    """Сессия одного пользователя: cookie и CSRF, как у браузера."""

    def __init__(
        self, base_url: str, login: str, timeout: float, ca_file: Path | None = None
    ) -> None:
        self.login = login
        # Корпоративный CA портала: системное хранилище рабочей станции его может не знать.
        verify = ssl.create_default_context(cafile=str(ca_file)) if ca_file else True
        self.http = httpx.AsyncClient(base_url=base_url, timeout=timeout, verify=verify)
        self.csrf = ""
        self.id = ""

    async def sign_in(self, provider: str, password: str) -> None:
        self.csrf = (await self.http.get("/api/auth/csrf")).json()["csrf_token"]
        response = await self.post(
            "/api/auth/login", {"login": self.login, "password": password, "provider": provider}
        )
        if response.status_code != 200:
            raise SystemExit(f"Вход {self.login} не удался: {response.status_code} {response.text}")
        self.id = response.json()["id"]
        # После входа CSRF-токен привязан к сессии.
        self.csrf = (await self.http.get("/api/auth/csrf")).json()["csrf_token"]
        # Уведомление о хранении переписки при первом входе — как кнопка «Понятно».
        await self.post("/api/auth/notice/accept", {})

    async def post(self, path: str, body: dict[str, Any]) -> httpx.Response:
        return await self.http.post(path, json=body, headers={"X-CSRF-Token": self.csrf})

    async def ask(self, prompt: str, thinking: bool) -> Sample:
        started = time.monotonic()
        try:
            chat = await self.post("/api/chats", {})
            if chat.status_code != 201:
                return Sample(f"http_{chat.status_code}", error="chat_create")
            sent = await self.post(
                f"/api/chats/{chat.json()['id']}/messages",
                {"content": prompt, "thinking": thinking or None},
            )
            accept = time.monotonic() - started
            if sent.status_code == 429:
                return Sample("limited", accept_s=accept, error=_code(sent))
            if sent.status_code != 202:
                return Sample(f"http_{sent.status_code}", accept_s=accept, error=_code(sent))
            message_id = sent.json()["assistant_message"]["id"]
            return await self._read(message_id, started, accept)
        except httpx.HTTPError as exc:
            return Sample("failed", total_s=time.monotonic() - started, error=type(exc).__name__)

    async def _read(self, message_id: str, started: float, accept: float) -> Sample:
        sample = Sample("failed", accept_s=accept)
        first: float | None = None
        event = ""
        async with self.http.stream("GET", f"/api/messages/{message_id}/stream") as response:
            if response.status_code != 200:
                return Sample(f"http_{response.status_code}", accept_s=accept, error="stream")
            async for line in response.aiter_lines():
                if line.startswith("event: "):
                    event = line[7:]
                    continue
                if not line.startswith("data: "):
                    continue
                now = time.monotonic()
                data = json.loads(line[6:])
                if event in ("content.delta", "reasoning.delta") and first is None:
                    first = now
                    sample.ttft_s = now - started
                elif event == "usage":
                    sample.tokens = int(data.get("completion_tokens") or 0)
                elif event == "error":
                    sample.error = str(data.get("code"))
                elif event == "message.end":
                    sample.status = str(data.get("status"))
                    sample.total_s = now - started
                    if first is not None and sample.tokens and now > first:
                        sample.tokens_per_s = sample.tokens / (now - first)
                    return sample
        sample.total_s = time.monotonic() - started
        sample.error = sample.error or "stream_closed"
        return sample


def _code(response: httpx.Response) -> str:
    try:
        return str(response.json()["error"]["code"])
    except (ValueError, KeyError, TypeError):
        return f"http_{response.status_code}"


async def raise_limits(args: argparse.Namespace, users: list[User]) -> None:
    """Временные персональные политики тестовым пользователям — от имени администратора."""
    admin = User(args.base_url, args.admin, args.timeout, args.ca_file)
    try:
        await admin.sign_in(args.provider, args.password)
        expires = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
        for user_id in sorted({u.id for u in users}):
            for metric, window, limit in RAISED_LIMITS:
                body = {
                    "scope": "user", "target_id": user_id, "metric": metric, "window": window,
                    "limit": limit, "expires_at": expires, "note": "нагрузочный тест eval/load",
                }  # fmt: skip
                response = await admin.post("/api/admin/limits/policies", body)
                if response.status_code not in (201, 409):  # 409 — уже поднят прошлым прогоном
                    raise SystemExit(
                        f"Не удалось поднять лимит {metric}: {response.status_code} {response.text}"
                    )
    finally:
        await admin.http.aclose()


async def run(args: argparse.Namespace) -> Report:
    logins = [x.strip() for x in args.logins.split(",") if x.strip()]
    users = [
        User(args.base_url, logins[i % len(logins)], args.timeout, args.ca_file)
        for i in range(args.concurrency)
    ]
    try:
        # Входы — по очереди: десятки одновременных входов с одного адреса — это перебор паролей.
        for user in users:
            await user.sign_in(args.provider, args.password)
        if args.admin:
            await raise_limits(args, users)
        queue: asyncio.Queue[int] = asyncio.Queue()
        for number in range(args.messages):
            queue.put_nowait(number)
        samples: list[Sample] = []

        async def worker(user: User) -> None:
            while True:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                samples.append(await user.ask(args.prompt, args.thinking))

        started = time.monotonic()
        await asyncio.gather(*(worker(user) for user in users))
        duration = time.monotonic() - started
    finally:
        for user in users:
            await user.http.aclose()
    return build_report(
        samples,
        base_url=args.base_url,
        concurrency=args.concurrency,
        prompt=args.prompt,
        duration_s=duration,
    )


def render(report: Report) -> str:
    def row(name: str, values: dict[str, float], unit: str) -> str:
        if not values:
            return f"  {name:<28} нет данных"
        return (
            f"  {name:<28} p50 {values['p50']:>8.3f}  p95 {values['p95']:>8.3f}  "
            f"max {values['max']:>8.3f}  {unit}"
        )

    marks = {True: "да", False: "НЕТ"}
    lines = [
        f"Стенд {report.base_url}: {report.messages} сообщений, одновременно {report.concurrency}, "
        f"{report.duration_s} с ({report.answers_per_s} ответа/с)",
        f"  статусы: {report.statuses}" + (f", ошибки: {report.errors}" if report.errors else ""),
        row("приём сообщения (POST)", report.accept_s, "с"),
        row("время до первого токена", report.ttft_s, "с"),
        row("длительность ответа", report.total_s, "с"),
        row("скорость генерации", report.tokens_per_s, "токенов/с"),
        "Цели §18.4:",
        f"  все ответы завершены: {marks[report.checks['all_completed']]}",
        f"  TTFT p95 ≤ {TARGET_TTFT_P95_S} с: {marks[report.checks['ttft_p95']]}",
        f"  скорость ≥ {TARGET_TOKENS_PER_S} токенов/с (медиана): "
        f"{marks[report.checks['tokens_per_s']]}",
    ]
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--base-url", default="http://localhost:8000", help="Адрес api или nginx")
    parser.add_argument("--concurrency", type=int, default=10, help="Одновременных диалогов")
    parser.add_argument("--messages", type=int, default=50, help="Сообщений всего")
    parser.add_argument(
        "--prompt",
        default="[[scenario:stream:300:30]] нагрузочный тест",
        help="Текст сообщения; по умолчанию — ровный поток fake-llm (300 слов, 33 слова/с)",
    )
    parser.add_argument("--thinking", action="store_true", help="Режим размышлений")
    parser.add_argument("--logins", default=DEV_LOGINS, help="Логины через запятую")
    parser.add_argument("--provider", default="dev", help="Провайдер входа: dev или ldap")
    parser.add_argument("--password", default="", help="Пароль тестовых пользователей (ldap)")
    parser.add_argument("--admin", help="Логин администратора: временно поднять лимиты")
    parser.add_argument("--ca-file", type=Path, help="Сертификат CA портала (https)")
    parser.add_argument("--timeout", type=float, default=600, help="Тайм-аут запроса, с")
    parser.add_argument("--json", type=Path, help="Сохранить отчёт в файл")
    parser.add_argument("--check", action="store_true", help="Код 1, если цели §18.4 не достигнуты")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = asyncio.run(run(args))
    print(render(report))
    if args.json:
        args.json.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n")
    return 1 if args.check and not all(report.checks.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
