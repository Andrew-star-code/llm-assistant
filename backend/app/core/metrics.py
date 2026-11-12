"""Метрики приложения для Prometheus (§16.6): генерация, очередь исполнителя, инструменты, SSE.

Метрики HTTP — в ``core/request_context.py``. Здесь — то, что пишет код генерации: в режиме
очереди (ADR-0013) он работает в сервисе ``generator``, поэтому у того свой эндпоинт метрик
(``generation.metrics_port``), а ``api`` отдаёт длину очереди, число исполнителей и SSE.

Метки — только из закрытых наборов (роль модели, статус, имя зарегистрированного инструмента):
значения от пользователя или модели в метки не попадают.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

GENERATIONS = Counter("app_generations_total", "Завершённые ответы ассистента", ["role", "status"])
GENERATION_DURATION = Histogram(
    "app_generation_duration_seconds",
    "Длительность ответа от запуска генерации до сохранения",
    ["role"],
    buckets=(1, 2, 5, 10, 20, 30, 60, 120, 300, 600),
)
GENERATION_TTFT = Histogram(
    "app_generation_ttft_seconds",
    "Время до первого токена ответа (§18.4)",
    ["role"],
    buckets=(0.25, 0.5, 1, 2, 4, 8, 15, 30, 60),
)
GENERATIONS_ACTIVE = Gauge("app_generations_active", "Ответы, которые ведёт этот процесс")
GENERATION_TOKENS = Counter(
    "app_generation_tokens_total", "Токены ответов", ["role", "kind"]
)  # kind: prompt | completion | reasoning
MODEL_RETRIES = Counter(
    "app_model_retries_total", "Автоповторы запроса к модели при кратком сбое", ["role"]
)
TOOL_CALLS = Counter("app_tool_calls_total", "Вызовы инструментов", ["tool", "status"])
TOOL_DURATION = Histogram(
    "app_tool_duration_seconds",
    "Длительность вызова инструмента",
    ["tool"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120),
)
CONTEXT_TRIMS = Counter(
    "app_context_trims_total", "Ответы, где цикл инструментов усекал контекст", ["kind"]
)  # kind: history | tool_results_dropped | tool_results_truncated

QUEUE_WAIT = Histogram(
    "app_generation_queue_wait_seconds",
    "Сколько задание ждало исполнителя в очереди",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)
JOBS_EXPIRED = Counter(
    "app_generation_jobs_expired_total", "Задания, не дождавшиеся исполнителя (ответ прерван)"
)
QUEUE_LENGTH = Gauge("app_generation_queue_length", "Заданий в очереди генерации")
EXECUTORS = Gauge("app_generation_executors", "Работающих исполнителей генерации")

SSE_CONNECTIONS = Gauge("app_sse_connections", "Открытые SSE-потоки ответов")

UNKNOWN_TOOL = "unknown"
