"""``python -m app.cli kb …`` — базы знаний из командной строки (§10.3).

* ``kb list`` — общие и ролевые базы с числом документов по статусам;
* ``kb import --kb <код> <папка>`` — массовый импорт из папки внутри ``kb.import_root``: создаёт
  задачу и ставит её в очередь воркера ``kb``; прогресс — в админке или ``kb imports --kb <код>``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import select

from app.core.config import Settings
from app.core.db import create_engine, create_session_factory
from app.modules.kb import service
from app.modules.kb.models import LEVEL_PERSONAL, KbImport, KnowledgeBase
from app.workers.dispatch import Dispatcher
from app.workers.kb_jobs import scan_folder


async def _list(settings: Settings) -> int:
    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as db:
            bases = (
                await db.scalars(
                    select(KnowledgeBase)
                    .where(
                        KnowledgeBase.deleted_at.is_(None), KnowledgeBase.level != LEVEL_PERSONAL
                    )
                    .order_by(KnowledgeBase.code)
                )
            ).all()
            counts = await service.status_counts(db, kb_ids=[b.id for b in bases])
            for kb in bases:
                c = counts.get(kb.id)
                stats = (
                    f"готово {c.ready}, в очереди {c.queued}, в обработке {c.processing}, "
                    f"ошибок {c.error}"
                    if c
                    else "документов нет"
                )
                print(f"{kb.code:<24} {kb.level:<7} {kb.name} — {stats}")
    finally:
        await engine.dispose()
    return 0


async def _import(settings: Settings, code: str, folder: str) -> int:
    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as db:
            kb = await db.scalar(
                select(KnowledgeBase).where(
                    KnowledgeBase.code == code, KnowledgeBase.deleted_at.is_(None)
                )
            )
            if kb is None or kb.level == LEVEL_PERSONAL:
                print(f"База «{code}» не найдена (личные базы не импортируются)")
                return 1
            root = settings.kb.import_root
            path = Path(folder)
            target = path if path.is_absolute() else root / path
            files = await asyncio.to_thread(scan_folder, target, root)
            if files is None:
                print(f"Папка {target} не найдена внутри каталога импорта {root}")
                return 1
            imp = KbImport(
                kb_id=kb.id, path=str(target), status="scanning", total=len(files),
                created_by=kb.created_by,
            )  # fmt: skip
            db.add(imp)
            await db.commit()
            import_id = imp.id
    finally:
        await engine.dispose()
    await Dispatcher(settings).import_folder(str(import_id))
    print(f"Импорт {import_id}: {len(files)} файлов из {target} в «{code}» поставлен в очередь")
    return 0


def cmd_kb_list(settings: Settings) -> int:
    return asyncio.run(_list(settings))


def cmd_kb_import(settings: Settings, code: str, folder: str) -> int:
    return asyncio.run(_import(settings, code, folder))
