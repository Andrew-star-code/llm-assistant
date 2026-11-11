# Как проходит одно сообщение

Реализация §2.2 (инструменты и RAG встраиваются в шаг генерации). Исполнитель — сервис
`generator` ([ADR-0013](../adr/0013-generation-executor.md)); в режиме `generation.mode: inline`
его роль играет сам `api`.

```mermaid
sequenceDiagram
  participant B as Браузер
  participant A as api (любой процесс)
  participant G as generator (исполнитель)
  participant R as Redis
  participant M as Модель (vLLM / fake-llm)
  participant P as PostgreSQL
  B->>A: POST /api/chats/{id}/messages
  A->>P: вопрос + ответ status=streaming, active_leaf_id
  A->>R: gen:alive:{msg} (TTL ожидания), RPUSH gen:queue
  A-->>B: 202 {user_message, assistant_message}
  R-->>G: BLPOP gen:queue → задача, gen:alive:{msg} (TTL 30 с, продлевается)
  B->>A: GET /api/messages/{msg}/stream (SSE)
  G->>P: история активной ветки, пользователь
  G->>M: chat.completions stream
  loop чанки
    M-->>G: дельты reasoning / content
    G->>R: XADD gen:{msg} 0-N (пачки раз в 50 мс)
    A-->>B: id: N, event: content.delta
    G->>R: gen:cancel:{msg}? (раз в 200 мс)
  end
  G->>P: ответ, токены, время, трассировка; заголовок (utility)
  G->>R: usage, title, message.end; EXPIRE gen:{msg}
  A-->>B: message.end
  B->>A: GET /api/chats/{id} (финальное состояние)
```

- **Обрыв или перезагрузка.** Браузер открывает поток заново (с `Last-Event-ID` или с начала) — события
  лежат в Redis Stream ещё 10 минут после конца.
- **«Стоп».** `POST /api/messages/{id}/stop` может попасть в любой процесс: он ставит флаг в Redis,
  исполнитель закрывает запрос к модели и сохраняет частичный ответ `stopped`.
- **Перезапуск api.** Ответы не затрагивает: браузер переподключается к новому процессу и
  дочитывает поток из Redis.
- **Остановка исполнителя.** По SIGTERM он не берёт новые задания и дорабатывает идущие; новые
  сообщения ждут в очереди следующего исполнителя.
- **Падение исполнителя.** Ключ живости истекает; читатель SSE или проверка в api помечают
  ответ `interrupted`, пользователь видит «Повторить». Так же — задание, не дождавшееся
  исполнителя.
- **Ветки.** Перегенерация создаёт сестринский ответ; переключатель «‹ 2/3 ›» меняет
  `active_leaf_id` (свежий лист выбранной версии).
