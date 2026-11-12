"""Smoke-проверка стенда после запуска или обновления (runbook первого запуска, раздел 11.2).

Проходит тем же путём, что браузер, главное из чек-листа приёмки:

1. вход и профиль из AD;
2. ответ на сообщение идёт потоком, у чата появляется заголовок (служебная модель);
3. вопрос по приложенному файлу — ответ по его содержимому (воркер, вложения);
4. «сделай документ Word» — карточка файла, файл скачивается;
5. переподключение к потоку посреди ответа — ответ дочитывается без пропусков;
6. админ: все развёрнутые модели отвечают, есть исполнитель генерации, открытые инциденты.

    uv run python scripts/smoke.py --base-url https://ai.corp.local --provider ldap \\
        --login <сотрудник> --admin <админ> --ask-password

Не автоматизировано (проверить в браузере): распознавание скана, база знаний с цитатами,
внешний вид печати ответа. Против дев-стенда с fake-llm — флаг ``--fake`` (make smoke).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.load.run import User

CODE_WORD = "Сириус-4821"
ATTACHMENT = f"Служебная записка.\n\nКодовое слово проверки: {CODE_WORD}.\n".encode()


@dataclass
class Answer:
    status: str
    text: str = ""
    deltas: int = 0
    spread_s: float = 0.0  # между первой и последней дельтой: «постепенно», а не одним куском
    events: list[tuple[int, str, dict[str, Any]]] = field(default_factory=list)

    def first(self, event: str) -> dict[str, Any] | None:
        return next((data for _, name, data in self.events if name == event), None)


class CheckError(Exception):
    """Проверка не пройдена; текст — что именно не так."""


def expect(condition: object, message: str) -> None:
    if not condition:
        raise CheckError(message)


async def read_events(
    user: User, message_id: str, *, after: int = 0, limit: int | None = None
) -> list[tuple[int, str, dict[str, Any], float]]:
    """События потока с позиции ``after``; ``limit`` — оборвать чтение (как закрытая вкладка)."""
    events: list[tuple[int, str, dict[str, Any], float]] = []
    seq, event = after, ""
    path = f"/api/messages/{message_id}/stream"
    async with user.http.stream("GET", path, params={"after": after}) as response:
        expect(response.status_code == 200, f"поток ответил {response.status_code}")
        async for line in response.aiter_lines():
            if line.startswith("id: "):
                seq = int(line[4:])
            elif line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and event != "ping":
                events.append((seq, event, json.loads(line[6:]), time.monotonic()))
                if event == "message.end" or (limit is not None and len(events) >= limit):
                    break
    return events


def to_answer(events: list[tuple[int, str, dict[str, Any], float]]) -> Answer:
    deltas = [(data["text"], at) for _, name, data, at in events if name == "content.delta"]
    end = next((data for _, name, data, _ in events if name == "message.end"), None)
    return Answer(
        status=str(end["status"]) if end else "нет message.end",
        text="".join(text for text, _ in deltas),
        deltas=len(deltas),
        spread_s=deltas[-1][1] - deltas[0][1] if deltas else 0.0,
        events=[(seq, name, data) for seq, name, data, _ in events],
    )


async def send(user: User, chat_id: str, text: str, **body: Any) -> str:
    response = await user.post(f"/api/chats/{chat_id}/messages", {"content": text, **body})
    expect(response.status_code == 202, f"сообщение не принято: {response.status_code}")
    return str(response.json()["assistant_message"]["id"])


async def new_chat(user: User) -> str:
    response = await user.post("/api/chats", {})
    expect(response.status_code == 201, f"чат не создан: {response.status_code}")
    return str(response.json()["id"])


async def ask(user: User, text: str, **body: Any) -> tuple[str, Answer]:
    chat_id = await new_chat(user)
    answer = to_answer(await read_events(user, await send(user, chat_id, text, **body)))
    error = answer.first("error")
    expect(answer.status == "completed", f"ответ не завершён: {answer.status} {error or ''}")
    return chat_id, answer


# ------------------------------------------------------------------ проверки


async def check_profile(user: User, args: argparse.Namespace) -> str:
    me = (await user.http.get("/api/auth/me")).json()
    expect(me.get("full_name"), "в профиле нет ФИО")
    if args.provider == "ldap":
        expect(me.get("department") or me.get("title"), "в профиле нет ни отдела, ни должности")
    return f"{me['full_name']}, {me.get('department') or 'отдел не заполнен'}"


async def check_streaming(user: User, args: argparse.Namespace) -> str:
    prompt = "[[scenario:stream:60:30]] привет" if args.fake else "Привет! Расскажи о себе."
    chat_id, answer = await ask(user, prompt)
    expect(answer.deltas >= 2, f"ответ пришёл одним куском ({answer.deltas} дельта) — см. Е1")
    expect(answer.spread_s > 0.2, "все дельты пришли разом: nginx буферизует поток (Е1)")
    title = answer.first("title")
    if title is None:  # заголовок мог не успеть в поток — он сохраняется в чате
        title = (await user.http.get(f"/api/chats/{chat_id}")).json()
    expect(title.get("title"), "у чата нет заголовка — служебная модель utility")
    return f"{answer.deltas} частей за {answer.spread_s:.1f} с, заголовок «{title['title']}»"


async def check_attachment(user: User, args: argparse.Namespace) -> str:
    upload = await user.http.post(
        "/api/files",
        files={"file": ("Служебная записка.txt", ATTACHMENT, "text/plain")},
        headers={"X-CSRF-Token": user.csrf},
    )
    expect(upload.status_code == 201, f"файл не принят: {upload.status_code} {upload.text[:200]}")
    file = upload.json()
    for _ in range(60):  # разбор — задача воркера
        if file["parse_status"] not in ("pending", "processing"):
            break
        await asyncio.sleep(1)
        file = (await user.http.get(f"/api/files/{file['id']}")).json()
    expect(file["parse_status"] == "ready", f"файл не разобран: {file['parse_status']} — воркер")
    prompt = (
        "[[scenario:find]] «Кодовое слово проверки»"
        if args.fake
        else "Какое кодовое слово проверки указано в приложенном файле? Назови его точно."
    )
    _, answer = await ask(user, prompt, attachment_ids=[file["id"]])
    expect(CODE_WORD in answer.text, f"в ответе нет кодового слова: «{answer.text[:200]}»")
    return "ответ по содержимому файла"


async def check_document(user: User, args: argparse.Namespace) -> str:
    prompt = (
        "[[scenario:tool:create_document]] Word"
        if args.fake
        else "Сделай документ Word на полстраницы: три пункта о пользе документации."
    )
    _, answer = await ask(user, prompt)
    card = answer.first("file")
    if card is None:
        raise CheckError("нет карточки файла — модель не вызвала инструмент или сбой воркера")
    download = await user.http.get(f"/api/files/{card['file_id']}/content")
    expect(download.status_code == 200, f"файл не скачивается: {download.status_code}")
    expect(len(download.content) > 1000, "скачанный файл подозрительно мал")
    return f"«{card['name']}», {len(download.content) // 1024} КБ"


async def check_reconnect(user: User, args: argparse.Namespace) -> str:
    prompt = "[[scenario:stream:120:30]] длинно" if args.fake else "Напиши рассказ на 200 слов."
    message_id = await send(user, await new_chat(user), prompt)
    head = await read_events(user, message_id, limit=4)  # «закрыли вкладку» посреди ответа
    expect(head and head[-1][1] != "message.end", "ответ слишком короткий для проверки")
    tail = await read_events(user, message_id, after=head[-1][0])
    ids = [seq for seq, *_ in head + tail]
    expect(ids == list(range(1, len(ids) + 1)), f"пропуски или повторы событий: {ids[:12]}…")
    answer = to_answer(head + tail)
    expect(answer.status == "completed", f"после переподключения: {answer.status}")
    return f"{len(head)} + {len(tail)} событий без пропусков"


async def check_admin(admin: User, args: argparse.Namespace) -> str:
    health = await admin.http.get("/api/admin/models/health")
    expect(health.status_code == 200, f"нет доступа к админке: {health.status_code}")
    down = [f"{m['role']} ({m['detail']})" for m in health.json() if not m["ok"]]
    expect(not down, "модели не отвечают: " + ", ".join(down))
    queues = (await admin.http.get("/api/admin/dashboard")).json()["queues"]
    executors = queues.get("generation_executors")
    expect(executors is None or executors > 0, "нет исполнителя генерации (generator) — Г10")
    summary = (await admin.http.get("/api/admin/incidents/summary")).json()
    note = f"моделей: {len(health.json())}, исполнителей: {executors if executors else '—'}"
    return f"{note}, новых инцидентов высокого уровня: {summary.get('new_high', 0)}"


Check = Callable[[User, argparse.Namespace], Awaitable[str]]
USER_CHECKS: list[tuple[str, Check]] = [
    ("Вход и профиль", check_profile),
    ("Ответ потоком и заголовок чата", check_streaming),
    ("Вопрос по приложенному файлу", check_attachment),
    ("Документ Word", check_document),
    ("Переподключение к потоку", check_reconnect),
]
MANUAL = (
    "Вручную в браузере: скан (PDF-картинка) распознаётся; база знаний — документы «готово», "
    "ответ с цитатами, клик открывает документ; ответ печатается постепенно."
)


async def run(args: argparse.Namespace) -> int:
    failures = 0

    async def step(name: str, check: Check, who: User) -> None:
        nonlocal failures
        try:
            print(f"  ✓ {name}: {await check(who, args)}")
        except CheckError as exc:
            failures += 1
            print(f"  ✗ {name}: {exc}")
        except Exception as exc:  # сетевой сбой и т. п. — тоже провал проверки, а не скрипта
            failures += 1
            print(f"  ✗ {name}: {type(exc).__name__}: {exc}")

    print(f"Smoke-проверка {args.base_url}")
    user = User(args.base_url, args.login, args.timeout, args.ca_file)
    try:
        await user.sign_in(args.provider, args.password)
        for name, check in USER_CHECKS:
            await step(name, check, user)
    finally:
        await user.http.aclose()
    if args.admin:
        admin = User(args.base_url, args.admin, args.timeout, args.ca_file)
        try:
            await admin.sign_in(args.provider, args.admin_password or args.password)
            await step("Админка: модели, исполнитель, инциденты", check_admin, admin)
        finally:
            await admin.http.aclose()
    else:
        print("  – Админка не проверялась: не задан --admin")
    print(MANUAL)
    print("Итог: " + ("всё в порядке" if not failures else f"не пройдено проверок: {failures}"))
    return 1 if failures else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--base-url", default="http://localhost:8000", help="Адрес портала")
    parser.add_argument("--login", default="petrov", help="Обычный сотрудник")
    parser.add_argument("--admin", help="Администратор (из bootstrap_admins)")
    parser.add_argument("--provider", default="dev", help="Провайдер входа: dev или ldap")
    parser.add_argument("--password", default="", help="Пароль (лучше --ask-password)")
    parser.add_argument("--admin-password", default="", help="Пароль администратора, если другой")
    parser.add_argument("--ask-password", action="store_true", help="Спросить пароли с клавиатуры")
    parser.add_argument("--ca-file", type=Path, help="Сертификат CA портала (https)")
    parser.add_argument("--timeout", type=float, default=300, help="Тайм-аут запроса, с")
    parser.add_argument(
        "--fake", action="store_true", help="Стенд с fake-llm: сценарии вместо фраз"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.ask_password:
        args.password = getpass.getpass(f"Пароль {args.login}: ")
        if args.admin:
            args.admin_password = getpass.getpass(f"Пароль {args.admin} (Enter — тот же): ")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
