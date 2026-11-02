# Новая метрика лимитов

Лимиты описаны в SPEC §12 и в [README модуля](../../backend/app/modules/limits/README.md). Метрика —
это имя, правило формы политики и место, где её проверяют.

## 1. Объявить метрику

`backend/app/core/config.py`:

* добавить имя в `LimitMetric`;
* метрика со счётчиком в окне (как `uploads`) — в `WINDOWED_METRICS`; с уточнением по роли модели и
  thinking — ещё и в `QUALIFIED_METRICS`;
* значение по умолчанию — строка в `_default_limits()` и в `config/app.yaml` → `limits.defaults`
  (и в `config/app.dev.yaml`, если там свой список).

Порядок в выдаче — `METRIC_ORDER` в `modules/limits/policies.py`.

## 2. Проверять и списывать

* **Счётчик в окне** — по образцу `Limits.reserve_upload`: `spread(...)` даёт ключи расхода во всех
  окнах, `Check(...)` — проверку каждой применимой политики, `Counters.reserve` — атомарно (Lua). Если
  операция может сорваться после резерва, верните его `Limits.cancel` (или оберните контекстом, как
  `Limits.upload`).
* **Величина из БД** (как квота личной базы) — сравните текущее значение с эффективным лимитом
  (`effective(...)`) и посчитайте «занято» в `Limits.status`.
* Превышение — `exceeded(key, limit, used, now, tz)`: HTTP 429 с `details`, которые фронтенд
  превращает в текст.

## 3. Показать

* `frontend/src/i18n/locales/*.json`: `limits.metric.<имя>` (название), `limits.genitive.<имя>`
  («исчерпан лимит …»);
* список метрик формы — `METRICS`, `WINDOWED`, `QUALIFIED` в `frontend/src/admin/pages/LimitsPage.tsx`;
  быстрое повышение в карточке — `RAISABLE` в `admin/components/UserLimits.tsx`.

## 4. Проверить

* unit — форма политики и разрешение (`tests/unit/test_limits_units.py`);
* интеграционный — превышение даёт 429 и не тратит лимит при отказе (`tests/integration/test_limits.py`);
* `make docs-config` — справочник конфигурации.
