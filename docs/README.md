# Документация

| Раздел | Что внутри |
| --- | --- |
| [SPEC.md](SPEC.md) | ТЗ и план разработки — единственный источник требований |
| [status.md](status.md) | Прогресс этапов, кто чем занят, открытые вопросы, демо-сценарии |
| [architecture/](architecture/overview.md) | [Обзор](architecture/overview.md), [SSE-протокол](architecture/sse-protocol.md); дальше — поток запроса, модель данных, безопасность |
| [adr/](adr/0000-template.md) | Архитектурные решения: [шаблон](adr/0000-template.md), 0001–0010 |
| [guides/](guides/README.md) | Пошаговые инструкции «как добавить…» |
| [reference/](reference/config.md) | Генерируемые справочники: [config.md](reference/config.md), [api.md](reference/api.md) |
| [runbooks/](runbooks/README.md) | Эксплуатация: модели, бэкапы, инциденты, секреты |

## ADR

| № | Решение |
| --- | --- |
| [0001](adr/0001-own-product.md) | Собственный продукт, а не форк готового чата |
| [0002](adr/0002-thin-orchestrator.md) | Тонкий собственный оркестратор LLM |
| [0003](adr/0003-sse-redis-streams.md) | Стриминг: SSE + Redis Streams |
| [0004](adr/0004-server-sessions.md) | Серверные сессии: cookie HttpOnly + Redis |
| [0005](adr/0005-qdrant-multitenancy.md) | Qdrant: коллекция на тип данных, права через payload |
| [0006](adr/0006-hybrid-search-rerank.md) | Гибридный поиск BM25 + dense с реранкером |
| [0007](adr/0007-vllm-inference.md) | vLLM для всех моделей |
| [0008](adr/0008-litellm-dev-gateway.md) | LiteLLM Proxy только для разработчиков |
| [0009](adr/0009-file-storage-volume.md) | Файлы — том на диске за интерфейсом Storage |
| [0010](adr/0010-dev-stand-mocks.md) | Дев-стенд: fake-llm, Samba AD DC, bge-m3 на CPU, uv workspace |

Документация — часть Definition of Done (§17): задача без обновлённых документов не закрыта.
`make docs-check` проверяет README модулей, актуальность сгенерированных справочников и ссылки.
