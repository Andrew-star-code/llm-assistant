# Как добавить инструмент для модели

Инструмент — класс в `backend/app/modules/tools/builtin/`, который модель вызывает в цикле §8.4.
Права, тайм-аут, обрезку результата, события SSE и запись в `tool_calls` обеспечивает фреймворк.

1. **Аргументы.** Pydantic-модель: из неё строится JSON Schema для модели, поэтому у каждого поля —
   `Field(description=…)` на русском и ограничения (`min_length`, `ge`, `Literal`). Без аргументов —
   `NoArgs`. Идентификатор пользователя, чат и права **не** бывают аргументами — они в `ToolContext`.
2. **Класс.**

   ```python
   @register_tool
   class FindEmployee(Tool):
       name = "find_employee"                      # snake_case, уникально
       description = "Найти сотрудника по ФИО … Не используй для …"  # когда звать и когда нет
       args_model = FindEmployeeArgs
       status_label = "tools.find_employee"        # i18n-ключ строки статуса
       timeout_s = 10
       required_permissions = frozenset({Perm.…})  # пусто — доступен всем
       needs_attachments = False                   # True — только в чатах с вложениями
       visibility = "visible"                      # "hidden" — без событий SSE и без показа (§9.6)

       def label_params(self, args): return {"name": args.query}

       async def run(self, ctx: ToolContext, args: FindEmployeeArgs) -> ToolResult:
           ...
           return ToolResult("текст для модели", data={"для": "трассировки"})
   ```

   Ожидаемую ошибку («файл не найден», «нет доступа») бросайте `ToolError("…")` — текст уйдёт модели,
   генерация продолжится. Любое другое исключение тоже не роняет ответ, но модель увидит только тип
   ошибки, а подробности — в логе.
3. **Регистрация.** Импорт модуля в `tools/builtin/__init__.py` (декоратор регистрирует класс).
   Глобально включённые инструменты — `tools.enabled` в `config/app.yaml` (`null` — все).
4. **Данные пользователя.** Только через сервисы модулей с проверкой владельца (`ctx.user_id`), файлы —
   только из `ctx.attachments`. Тяжёлая работа (конвертация, OCR) — в воркере через
   `ctx.services.dispatcher`; файл для пользователя — `ToolResult(files=[…])`, фреймворк отправит
   событие `file` и покажет карточку.
5. **Строка статуса.** Ключ `tools.<name>` в `frontend/src/i18n/locales/ru.json` и `en.json`
   (параметры — `{{name}}`).
6. **fake-llm.** Типовые аргументы в `services/fake-llm/src/fake_llm/scenarios.py::tool_arguments`,
   чтобы инструмент вызывался сценарием `[[scenario:tool:<name>]]`.
7. **Тесты.** Unit — `run` с подставным `ToolContext` (`backend/tests/unit/test_tools.py`);
   интеграционный — через чат и fake-llm (`backend/tests/integration/test_files.py`): события
   `tool.start`/`tool.end`, шаг в `tools` сообщения, запись в `tool_calls`.
8. **Документация.** Таблица в `backend/app/modules/tools/README.md`, CHANGELOG.
