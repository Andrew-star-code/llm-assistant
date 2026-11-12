# deploy/monitoring

Сбор метрик и алерты для Prometheus (§16.6 SPEC). Compose мониторинга, экспортёры (node, DCGM,
postgres, redis), Alertmanager и дашборды Grafana — этап 10; здесь то, что можно проверить до
приезда сервера.

| Файл | Что это |
| --- | --- |
| `prometheus.yml` | Цели сбора: `api`, `generator`, модели vLLM, Qdrant, экспортёры |
| `alerts.yml` | Правила: группа `app` (метрики приложения) и `platform` (модели, диск, цели) |
| `alerts.test.yml` | Тесты правил группы `app` |

Проверка: `make test-monitoring` (promtool из образа Prometheus; входит в `make check`).

## Метрики приложения

Определены в `backend/app/core/metrics.py` и `core/request_context.py`.

| Метрика | Кто отдаёт | Что показывает |
| --- | --- | --- |
| `app_http_requests_total`, `app_http_request_duration_seconds` | api | запросы и их длительность по маршрутам |
| `app_sse_connections` | api | открытые потоки ответов |
| `app_generation_queue_length`, `app_generation_executors` | api | задания в очереди и работающие исполнители |
| `app_generations_total{role,status}` | generator | ответы по статусам (`completed`, `stopped`, `error`, `interrupted`) |
| `app_generation_duration_seconds`, `app_generation_ttft_seconds` | generator | длительность ответа и время до первого токена (§18.4) |
| `app_generations_active` | generator | ответы в работе у исполнителя |
| `app_generation_tokens_total{role,kind}` | generator | токены: `prompt`, `completion`, `reasoning` |
| `app_generation_queue_wait_seconds`, `app_generation_jobs_expired_total` | generator | ожидание в очереди; задания, не дождавшиеся исполнителя |
| `app_model_retries_total` | generator | автоповторы запроса к модели |
| `app_tool_calls_total{tool,status}`, `app_tool_duration_seconds` | generator | вызовы инструментов |
| `app_context_trims_total{kind}` | generator | ответы, где усекался контекст в цикле инструментов |

`api` отдаёт метрики на `/metrics/` (порт 8000), `generator` — на порту
`generation.metrics_port` (9100). В режиме `generation.mode: inline` метрики генерации пишет сам
`api`. Воркеры Celery метрик не отдают: их очереди видны на дашборде админки.

Без Prometheus главный сбой — «нет исполнителя» — виден и так: планировщик заводит инцидент
`generator_health`, а дашборд админки показывает очередь генерации и число исполнителей.

## Что сверить на сервере (этап 10)

- Имена метрик vLLM в `alerts.yml` (`vllm:num_requests_waiting`, `vllm:gpu_cache_usage_perc`)
  зависят от версии — проверить `curl llm-chat:8000/metrics`.
- Пороги алертов — после нагрузочного теста.
- Маршрутизация алертов (Alertmanager → почта или мессенджер) не настроена.
