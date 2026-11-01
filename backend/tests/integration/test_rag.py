"""RAG (этап 4): базы трёх уровней, изоляция, гибридный поиск с реранкером, деградация,
цитаты и источники, удаление, массовый импорт с продолжением после перезапуска.

Модели — fake-llm (эмбеддинги «мешок слов», реранк по основам слов), Qdrant — настоящий
(testcontainers) с серверным BM25, воркер — в режиме eager.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.modules.audit.models import AuditLog
from app.modules.incidents.models import Incident
from app.modules.ingestion.parsers import ParsedDocument
from app.modules.kb.models import KbDocument, KbImport
from app.modules.rag import search as search_module
from app.modules.rag.search import Scope, search
from app.modules.rag.service import SearchContext, build_scope, run_search
from app.modules.rag.store import qdrant_client
from app.modules.rbac.models import Role
from app.modules.users.models import User
from app.workers import kb_jobs
from tests import samples
from tests.integration.conftest import (
    ApiClient,
    Infra,
    SseEvent,
    chat_settings,
    new_chat,
    read_stream,
    send,
)

ACCOUNTING = "dept:Бухгалтерия"  # роль petrov из DEV_USERS; у kim её нет


def text_of(events: list[SseEvent]) -> str:
    return "".join(e.data["text"] for e in events if e.event == "content.delta")


async def ask(client: ApiClient, text: str) -> tuple[list[SseEvent], dict[str, Any]]:
    chat_id = await new_chat(client)
    sent = await send(client, chat_id, text)
    events = await read_stream(client, sent["assistant_message"]["id"])
    detail = (await client.get(f"/api/chats/{chat_id}")).json()
    return events, detail["messages"][-1]


async def create_kb(admin: ApiClient, code: str, level: str = "global", roles: Any = ()) -> str:
    body = {"code": code, "name": code.title(), "level": level, "role_ids": list(roles)}
    response = await admin.post("/api/admin/kb", json=body)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def upload(admin: ApiClient, kb_id: str, name: str, data: bytes) -> dict[str, Any]:
    response = await admin.post(
        f"/api/admin/kb/{kb_id}/documents", files={"file": (name, data, "application/octet-stream")}
    )
    assert response.status_code == 201, response.text
    doc: dict[str, Any] = response.json()
    assert doc["status"] == "ready", doc  # eager-воркер: проиндексирован к ответу
    return doc


async def role_id(app: Any, code: str) -> str:
    async with app.state.db_sessions() as db:
        return str(await db.scalar(select(Role.id).where(Role.code == code)))


async def user_scope(app: Any, login: str) -> Scope:
    from app.modules.rbac import service as rbac

    async with app.state.db_sessions() as db:
        user = await db.scalar(select(User).where(User.login == login))
        assert user is not None
        roles = await rbac.user_roles(db, user.id)
        return await build_scope(db, user.id, [r.role.id for r in roles])


async def run(
    settings: Settings, app: Any, scope: Scope, query: str, **kwargs: Any
) -> search_module.SearchResult:
    client = qdrant_client(settings)
    try:
        return await search(
            client, app.state.models, settings.rag.search, query=query, scope=scope, **kwargs
        )
    finally:
        await client.close()


@pytest.fixture
async def stand(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str, qdrant_url: str
) -> Any:
    async def factory(**overrides: Any) -> tuple[Settings, Any, ApiClient, ApiClient, ApiClient]:
        settings = chat_settings(infra, tmp_path, fake_llm_url, qdrant_url=qdrant_url, **overrides)
        app, admin = await make_client(settings)
        _, petrov = await make_client(settings)
        _, kim = await make_client(settings)
        for client, login in ((admin, "ivanov"), (petrov, "petrov"), (kim, "kim")):
            assert (await client.login(login)).status_code == 200
        return settings, app, admin, petrov, kim

    return factory


def uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


# ------------------------------------------------------------------ цитаты и источники


async def test_answer_cites_global_kb_with_card_and_page(stand: Any) -> None:
    _settings, _app, admin, petrov, _ = await stand()
    kb_id = await create_kb(admin, uniq("regulations"))
    code = uniq("ORION").upper()  # латиница: у шрифта helv в PDF нет кириллицы
    pdf = samples.text_pdf(["Vvedenie general text", f"Kodovoe slovo {code} zdes", "Konec"])
    doc = await upload(admin, kb_id, "Регламент.pdf", pdf)

    events, answer = await ask(petrov, f"[[scenario:find]] «{code}»")
    assert text_of(events) == f"Нашёл в документе: Kodovoe slovo {code} zdes [1]"
    [sources] = [e for e in events if e.event == "sources"]
    card = sources.data["items"][0]
    assert card["index"] == 1 and card["kind"] == "kb" and card["document_id"] == doc["id"]
    assert card["title"] == "Регламент" and card["page"] == 2  # страница, где найден код
    # Шаг «Ищу в базах знаний» в ленте и источники в истории.
    assert [s["tool"] for s in answer["tools"]] == ["search_knowledge_base"]
    [src] = [s for s in answer["sources"] if s["cited"]]
    assert src["document_id"] == doc["id"] and src["page"] == 2
    # Просмотр источника: права проверяются заново.
    preview = await petrov.get(f"/api/kb/documents/{doc['id']}/preview")
    assert preview.status_code == 200 and preview.content.startswith(b"%PDF-")


async def test_nothing_found_note_without_cards(stand: Any) -> None:
    _, _, admin, petrov, _ = await stand()
    await create_kb(admin, uniq("faq"))
    events, answer = await ask(petrov, "[[scenario:find]] «Совершенно нет такого»")
    assert "sources" not in {e.event for e in events}
    assert answer["sources"] == []


# ------------------------------------------------------------------ изоляция


async def test_role_kb_is_invisible_without_role(stand: Any) -> None:
    settings, app, admin, petrov, kim = await stand()
    kb_id = await create_kb(admin, uniq("accounting"), "role", [await role_id(app, ACCOUNTING)])
    secret = uniq("ЛИСА").upper()
    doc = await upload(admin, kb_id, "Учёт.md", f"# Учёт\n\nСекрет бухгалтерии {secret}.".encode())

    events, _ = await ask(petrov, f"[[scenario:find]] «{secret}»")
    assert text_of(events).startswith(f"Нашёл в документе: Секрет бухгалтерии {secret}")

    events, answer = await ask(kim, f"[[scenario:find]] «{secret}»")
    assert text_of(events) == f"В документах нет «{secret}»."
    assert answer["sources"] == []
    scope = await user_scope(app, "kim")
    assert uuid.UUID(kb_id) not in scope.kb_ids
    for kwargs in ({"use_bm25": False}, {"use_dense": False}):
        result = await run(settings, app, scope, f"Секрет бухгалтерии {secret}", **kwargs)
        assert all(c["document_id"] != doc["id"] for c in result.trace["candidates"])
    assert (await kim.get(f"/api/kb/documents/{doc['id']}")).status_code == 404
    assert (await kim.get(f"/api/kb/documents/{doc['id']}/content")).status_code == 404


async def test_personal_kb_never_leaks_dense_or_bm25(stand: Any) -> None:
    settings, app, _, petrov, kim = await stand()
    marker = uniq("ЛИЧНОЕ").upper()
    text = f"Мой личный план отпуска {marker} на лето"
    response = await petrov.post(
        "/api/kb/personal/documents", files={"file": ("план.txt", text.encode(), "text/plain")}
    )
    assert response.status_code == 201 and response.json()["status"] == "ready"
    doc_id = response.json()["id"]

    owner, other = await user_scope(app, "petrov"), await user_scope(app, "kim")
    for kwargs in ({"use_bm25": False}, {"use_dense": False}):
        mine = await run(settings, app, owner, text, use_rerank=False, **kwargs)
        assert any(f.document_id == doc_id for f in mine.fragments), kwargs
        theirs = await run(settings, app, other, text, use_rerank=False, **kwargs)
        assert all(c["document_id"] != doc_id for c in theirs.trace["candidates"]), kwargs

    events, _ = await ask(kim, f"[[scenario:find]] «{marker}»")
    assert text_of(events) == f"В документах нет «{marker}»."
    assert (await kim.get(f"/api/kb/documents/{doc_id}")).status_code == 404

    # Квота и список в «Моей базе знаний».
    personal = (await petrov.get("/api/kb/personal")).json()
    assert [d["id"] for d in personal["documents"]] == [doc_id]
    assert personal["quota"]["used_documents"] == 1 and personal["quota"]["max_documents"] == 100
    again = await petrov.post(
        "/api/kb/personal/documents", files={"file": ("копия.txt", text.encode(), "text/plain")}
    )
    assert again.status_code == 409 and again.json()["error"]["code"] == "duplicate"


# ------------------------------------------------------------------ качество поиска


async def test_exact_code_and_word_forms_when_dense_is_blind(
    stand: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, app, admin, _, _ = await stand()
    kb_id = await create_kb(admin, uniq("contracts"))
    number = f"{uuid.uuid4().int % 90 + 10}-{uuid.uuid4().int % 900 + 100}/Б"
    target = await upload(
        admin, kb_id, "Договор.md",
        f"# Договор\n\nДоговор поставки № {number} заключён с ООО «Ромашка».".encode(),
    )  # fmt: skip
    for i in range(12):
        await upload(
            admin, kb_id, f"Шум {i}.md",
            f"# Справка {i}\n\nОбщие сведения о компании, отпусках и командировках {i}.".encode(),
        )  # fmt: skip
    scope = await user_scope(app, "petrov")

    # «Слепой» векторный поиск: эмбеддинг запроса не связан с текстом документов.
    from app.modules.rag.store import embed as original

    async def blind(registry: Any, texts: list[str]) -> list[list[float]]:
        return await original(registry, ["совершенно посторонние слова"] * len(texts))

    monkeypatch.setattr(search_module, "embed", blind)
    dense_only = await run(settings, app, scope, f"№ {number}", use_bm25=False, use_rerank=False)
    assert target["id"] not in [f.document_id for f in dense_only.fragments[:5]]

    for query in (f"№ {number}", "договорам поставок с Ромашкой"):
        result = await run(settings, app, scope, query)
        top5 = [f.document_id for f in result.fragments[:5]]
        assert target["id"] in top5, (query, result.trace["candidates"][:5])


async def test_all_candidates_reranked_and_traced(stand: Any) -> None:
    _, app, admin, petrov, _ = await stand()
    kb_id = await create_kb(admin, uniq("it"))
    for i in range(3):
        await upload(
            admin, kb_id, f"ИТ {i}.md", f"# ИТ {i}\n\nПароль от Wi-Fi меняется {i}.".encode()
        )
    _, answer = await ask(petrov, "Как поменять пароль от Wi-Fi?")
    async with app.state.db_sessions() as db:
        from app.modules.chats.models import Message

        row = await db.get(Message, uuid.UUID(answer["id"]))
        assert row is not None and row.trace is not None
    rag = row.trace["rag"]
    assert rag["stages"] == {"dense": "ok", "bm25": "ok", "rerank": "ok"}
    pool = [c for c in rag["candidates"] if c["status"] != "beyond_rerank_pool"]
    assert pool and all(c["rerank"] is not None and c["rrf"] is not None for c in pool)
    assert all(c["dense_rank"] or c["bm25_rank"] for c in pool)
    assert {"selected"} <= {c["status"] for c in pool}


async def test_reranker_down_rrf_order_and_incident(stand: Any, fake_llm_url: str) -> None:
    models = {"rerank": {"base_url": "http://127.0.0.1:9/v1", "model": "fake-rerank"}}
    _, app, admin, petrov, _ = await stand(models=models)
    kb_id = await create_kb(admin, uniq("hr"))
    marker = uniq("ОТПУСК").upper()
    await upload(admin, kb_id, "Отпуск.md", f"# Отпуск\n\nПравила отпуска {marker}.".encode())

    for _ in range(2):
        events, answer = await ask(petrov, f"[[scenario:find]] «{marker}»")
        assert text_of(events) == f"Нашёл в документе: Правила отпуска {marker}. [1]"
    async with app.state.db_sessions() as db:
        from app.modules.chats.models import Message

        row = await db.get(Message, uuid.UUID(answer["id"]))
        assert row is not None and row.trace is not None
        assert row.trace["rag"]["stages"]["rerank"].startswith("skipped")
        selected = [c for c in row.trace["rag"]["candidates"] if c["status"] == "selected"]
        assert len(selected) <= 6 and all(c["rerank"] is None for c in selected)

    page = (await admin.get("/api/admin/incidents", params={"type": "rag_degraded"})).json()
    cards = [(await admin.get(f"/api/admin/incidents/{i['id']}")).json() for i in page["items"]]
    [incident] = [i for i in cards if i["payload"]["stage"] == "rerank"]
    assert incident["occurrences"] == 1  # второй отказ в течение 10 минут — без новой записи
    assert (await petrov.get("/api/admin/incidents")).status_code == 403


async def test_deleted_document_disappears_from_search(stand: Any) -> None:
    settings, app, admin, petrov, _ = await stand()
    kb_id = await create_kb(admin, uniq("tmp"))
    marker = uniq("УДАЛИ").upper()
    doc = await upload(admin, kb_id, "Временный.md", f"# Временный\n\nТекст {marker}.".encode())
    scope = await user_scope(app, "petrov")
    assert (await run(settings, app, scope, marker)).fragments
    response = await admin.request("DELETE", f"/api/admin/kb/{kb_id}/documents/{doc['id']}")
    assert response.status_code == 204
    # Сразу после ответа на удаление — точек в Qdrant нет.
    result = await run(settings, app, scope, marker, use_rerank=False)
    assert all(c["document_id"] != doc["id"] for c in result.trace["candidates"])
    assert (await petrov.get(f"/api/kb/documents/{doc['id']}")).status_code == 404


# ------------------------------------------------------------------ порог реранкера в админке


async def test_rerank_threshold_from_admin_applies_without_restart(stand: Any) -> None:
    settings, app, admin, petrov, _ = await stand()
    kb_id = await create_kb(admin, uniq("threshold"))
    marker = uniq("PORTAL").upper()
    await upload(admin, kb_id, "Порог.md", f"# Порог\n\nКодовое слово {marker}.".encode())
    scope = await user_scope(app, "petrov")
    ctx = SearchContext(settings, app.state.models, app.state.db_sessions, None)
    # Половина слов запроса есть в документе: балл заглушки-реранкера 0,5.
    query = f"{marker} отсутствующееслово"

    async def found() -> bool:
        result = await run_search(ctx, scope, query=query)
        return any(f.title == "Порог" for f in result.fragments)

    current = (await admin.get("/api/admin/kb/search-settings")).json()
    default = settings.rag.search.rerank.score_threshold
    assert current == {
        "score_threshold": default, "default_threshold": default, "overridden": False,
        "updated_at": None,
    }  # fmt: skip
    assert await found()

    response = await admin.request(
        "PUT", "/api/admin/kb/search-settings", json={"score_threshold": 0.9}
    )
    assert response.status_code == 200, response.text
    assert response.json()["score_threshold"] == 0.9 and response.json()["overridden"] is True
    assert not await found()  # тот же процесс, без перезапуска

    bad = await admin.request("PUT", "/api/admin/kb/search-settings", json={"score_threshold": 1.5})
    assert bad.status_code == 422
    # Менять порог может только admin.kb.manage.
    denied = await petrov.request(
        "PUT", "/api/admin/kb/search-settings", json={"score_threshold": 0.1}
    )
    assert denied.status_code == 403

    reset = await admin.request(
        "PUT", "/api/admin/kb/search-settings", json={"score_threshold": None}
    )
    assert reset.json() == current
    assert await found()
    async with app.state.db_sessions() as db:
        actions = (
            await db.scalars(
                select(AuditLog.details).where(AuditLog.action == "kb.search_settings")
            )
        ).all()
    assert {"before": default, "after": 0.9} in actions and {
        "before": 0.9,
        "after": None,
    } in actions


# ------------------------------------------------------------------ импорт


async def test_folder_import_resumes_after_restart(stand: Any, tmp_path: Path) -> None:
    root = tmp_path / "import"
    folder = root / "batch"
    (folder / "sub").mkdir(parents=True)
    for i in range(5):
        (folder / f"doc{i}.md").write_text(f"# Документ {i}\n\nИмпорт текст {i}.", "utf-8")
    (folder / "sub" / "copy.md").write_text("# Документ 0\n\nИмпорт текст 0.", "utf-8")  # дубль
    (folder / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n")  # не поддерживается
    settings, app, admin, _, _ = await stand(kb={"import_root": str(root)})
    kb_id = await create_kb(admin, uniq("import"))

    folders = (await admin.get("/api/admin/kb/import-folders")).json()
    assert {"path": "batch", "files": 7} in folders
    bad = await admin.post(f"/api/admin/kb/{kb_id}/imports", json={"path": "../../etc"})
    assert bad.status_code == 422

    # «Падение воркера»: импорт создан, сканирование оборвалось после двух файлов.
    async with app.state.db_sessions() as db:
        imp = KbImport(kb_id=uuid.UUID(kb_id), path=str(folder), status="scanning", total=0)
        db.add(imp)
        await db.commit()
        import_id = str(imp.id)
    queued: list[str] = []

    class WorkerKilled(BaseException):
        """Процесс убит: код задачи не успевает ничего записать (в отличие от Exception)."""

    async def crash_after_two(document_id: str) -> None:
        queued.append(document_id)
        if len(queued) == 2:
            raise WorkerKilled

    with pytest.raises(WorkerKilled):
        await kb_jobs.import_job(import_id, settings, crash_after_two)

    # Перезапуск воркера: незавершённое возвращается в очередь и доделывается без дублей.
    async def index(document_id: str) -> None:
        await kb_jobs.index_document_job(document_id, settings)

    async def resume(imp_id: str) -> None:
        await kb_jobs.import_job(imp_id, settings, index)

    counts = await kb_jobs.requeue_job(settings, index, resume)
    assert counts == {"imports": 1, "documents": 2}

    imports = (await admin.get(f"/api/admin/kb/{kb_id}/imports")).json()
    [progress] = imports
    assert progress["status"] == "done" and progress["total"] == 7
    assert progress["skipped"] == 2  # дубль и PNG
    assert progress["documents"]["ready"] == 5
    async with app.state.db_sessions() as db:
        total = await db.scalar(
            select(func.count()).select_from(KbDocument).where(KbDocument.kb_id == uuid.UUID(kb_id))
        )
    assert total == 5


async def test_unexpected_worker_errors_mark_import_and_document_failed(
    stand: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "import3"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "a.md").write_text("# A\n\nТекст.", "utf-8")
    _, app, admin, _, _ = await stand(kb={"import_root": str(root)})
    kb_id = await create_kb(admin, uniq("crash"))

    # Сбой посреди сканирования (не ParseError): импорт — «ошибка», а не вечное «сканирование».
    def broken_scan(folder: Path, root: Path) -> list[Path] | None:
        raise OSError("диск отвалился")

    monkeypatch.setattr(kb_jobs, "scan_folder", broken_scan)
    response = await admin.post(f"/api/admin/kb/{kb_id}/imports", json={"path": "docs"})
    assert response.status_code == 202, response.text
    [progress] = (await admin.get(f"/api/admin/kb/{kb_id}/imports")).json()
    assert progress["status"] == "error" and "OSError" in progress["error"]
    monkeypatch.undo()

    # Сбой вне разбора (запись результата): документ — «ошибка» с причиной, а не «в обработке».
    def broken_markdown(self: Any) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(ParsedDocument, "markdown", broken_markdown)
    response = await admin.post(
        f"/api/admin/kb/{kb_id}/documents",
        files={"file": ("Сбой.md", "# Сбой\n\nТекст.".encode(), "text/markdown")},
    )
    assert response.status_code == 201, response.text
    doc = (await admin.get(f"/api/admin/kb/{kb_id}/documents")).json()[0]
    assert doc["status"] == "error" and "RuntimeError" in doc["error"], doc
    async with app.state.db_sessions() as db:
        found = (
            await db.scalars(
                select(Incident).where(Incident.type.in_(("kb_index", "worker_failed")))
            )
        ).all()
    assert any(i.payload and i.payload.get("document_id") == doc["id"] for i in found)
    assert any(i.payload and i.payload.get("import_id") == progress["id"] for i in found)


async def test_admin_import_api_runs_in_background(stand: Any, tmp_path: Path) -> None:
    root = tmp_path / "import2"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "a.md").write_text("# A\n\nТекст для импорта.", "utf-8")
    _, _, admin, _, _ = await stand(kb={"import_root": str(root)})
    kb_id = await create_kb(admin, uniq("bulk"))
    response = await admin.post(f"/api/admin/kb/{kb_id}/imports", json={"path": "docs"})
    assert response.status_code == 202, response.text
    progress = (await admin.get(f"/api/admin/kb/{kb_id}/imports")).json()[0]
    assert progress["status"] == "done" and progress["documents"]["ready"] == 1
    docs = (await admin.get(f"/api/admin/kb/{kb_id}/documents")).json()
    assert [d["title"] for d in docs] == ["a"]


async def test_kb_manager_sees_only_own_role_bases(stand: Any) -> None:
    _, app, admin, petrov, _ = await stand()
    accounting = await create_kb(admin, uniq("acc"), "role", [await role_id(app, ACCOUNTING)])
    other = await create_kb(admin, uniq("oth"), "role", [await role_id(app, "dept:ИТ-отдел")])
    # petrov — менеджер БЗ: роль kb_manager выдаёт суперадмин.
    async with app.state.db_sessions() as db:
        petrov_id = await db.scalar(select(User.id).where(User.login == "petrov"))
    manager_role = await role_id(app, "kb_manager")
    response = await admin.request(
        "PUT", f"/api/admin/users/{petrov_id}/roles", json={"role_ids": [manager_role]}
    )
    assert response.status_code in (200, 204), response.text
    assert (await petrov.login("petrov")).status_code == 200

    listed = {kb["id"] for kb in (await petrov.get("/api/admin/kb")).json()}
    assert accounting in listed and other not in listed
    assert (await petrov.get(f"/api/admin/kb/{other}/documents")).status_code == 403
    created = await petrov.post(
        "/api/admin/kb", json={"code": "nope", "name": "x", "level": "global"}
    )
    assert created.status_code == 403
    await upload(petrov, accounting, "Акт.md", "# Акт\n\nАкт сверки.".encode())


async def test_tei_reranker_format_in_batches(
    stand: Any, fake_llm_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Реранкер text-embeddings-inference: `/rerank` без /v1, поле texts, пакеты по TEI_BATCH."""
    models = {
        "rerank": {"base_url": fake_llm_url, "model": "BAAI/bge-reranker-v2-m3", "api": "tei"}
    }
    settings, app, admin, _, _ = await stand(models=models)
    monkeypatch.setattr(search_module, "TEI_BATCH", 2)  # 5 кандидатов → 3 запроса
    kb_id = await create_kb(admin, uniq("tei"))
    marker = uniq("ТЕИ").upper()
    for i in range(5):
        await upload(
            admin, kb_id, f"Док {i}.md", f"# Док {i}\n\nОбщий текст {i} {marker}.".encode()
        )
    scope = await user_scope(app, "petrov")
    result = await run(settings, app, scope, f"текст 3 {marker}")
    assert result.trace["stages"]["rerank"] == "ok"
    pool = [c for c in result.trace["candidates"] if c["status"] != "beyond_rerank_pool"]
    assert len(pool) == 5 and all(c["rerank"] is not None for c in pool)
    assert result.fragments[0].title == "Док 3"  # лучший балл реранкера — на своём месте
