# Новый набор данных или функция SQL

Семантический слой — [services/data-gateway](../../services/data-gateway/README.md), требования —
SPEC §9.5. Модель видит только то, что описано в каталоге `services/data-gateway/catalog/`; каталог
перечитывается без перезапуска шлюза.

## 1. Права в БД

У источника — свой логин **только на чтение** с `SELECT` на нужные представления (не на таблицы):

```sql
GRANT SELECT ON dbo.v_sales_by_month TO dg_reader;
```

Представление отдаёт только то, что можно показать ассистенту: без паролей, зарплат и служебных
колонок, которые не нужны для ответов.

## 2. Источник (если новый)

`catalog/sources.yaml`: `name`, `dialect: mssql`, `url` с секретами `${ИМЯ}` (значения — в
`/run/secrets/<имя>` или переменных окружения шлюза), `timeout_s`, `max_rows`.

## 3. Набор данных

`catalog/datasets/<имя>.yaml`:

```yaml
name: sales
title: Продажи по месяцам
description: Выручка и число сделок по месяцам и регионам. Одна строка — месяц × регион.
source: mssql_main
view: dbo.v_sales_by_month
columns:
  - {name: month, type: date, description: "Первый день месяца", examples: ["2026-01-01"]}
  - {name: region, type: string, description: Регион продаж, synonyms: [филиал]}
  - {name: revenue, type: number, description: "Выручка, руб. без НДС"}
  - {name: manager, type: string, description: Менеджер, pii: true}
metrics:
  - "Выручка за период: SUM(revenue)"
roles: [sales, management]          # пусто — всем
rls:
  - {column: region, equals: "{user.department}", unless_roles: [management]}
examples:
  - question: Выручка по регионам за прошлый месяц
    sql: "SELECT region, SUM(revenue) AS revenue FROM dbo.v_sales_by_month WHERE month = DATEFROMPARTS(YEAR(DATEADD(month, -1, GETDATE())), MONTH(DATEADD(month, -1, GETDATE())), 1) GROUP BY region"
```

* Колонки — все, что модель может использовать; остальные колонки представления шлюз не пропустит.
* Синонимы и примеры значений помогают модели понять вопрос; `pii` — пометка персональных данных.
* RLS — строки только «своего» значения атрибута пользователя (`{user.department}` или
  `{user.login}`); у пользователя без атрибута — ни одной строки; `unless_roles` — роли без ограничения.
* 5–15 примеров «вопрос → SQL» на T-SQL: `describe_dataset` отдаёт модели до 5 самых похожих.

## 4. Функция

Если вопрос типовой, функция надёжнее произвольного SQL. `catalog/functions/<имя>.yaml`:

```yaml
name: sales_for_region
description: Выручка региона по месяцам за год
source: mssql_main
roles: [sales, management]
params:
  region: {type: string, max_length: 100}
  year: {type: integer, min: 2015, max: 2100}
sql: |
  SELECT month, revenue FROM dbo.v_sales_by_month
  WHERE region = :region AND YEAR(month) = :year ORDER BY month
```

Параметры — только `:имя`; строки склеивайте `CONCAT(…)`, а не `+`. Функции не проходят RLS —
ограничивайте их ролями и самим SQL.

## 5. Проверить

* Админка «Источники данных»: набор и функция видны, ошибок каталога нет; тестовый вызов функции.
* `uv run pytest services/data-gateway/tests` — проверка SQL не сломана.
* В чате: вопрос по набору → в аудите запись `data.query` с итоговым SQL и числом строк.
