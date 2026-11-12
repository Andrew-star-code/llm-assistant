# Первый запуск на GPU-сервере

Пошаговое руководство для администратора: от пустого сервера до первых пользователей — и типовые
проблемы во время и после запуска с шагами решения. Объём первого запуска упрощён по сравнению
с §16 SPEC: только то, без чего сотрудники не начнут работать; остальное — доводка в первые недели
(раздел 12).

**Что уже есть и чего ещё нет.** Приложение, его образы, конфиг и CLI готовы (этапы 0–9). Файлы
прод-развёртывания есть в репозитории: `deploy/compose/compose.prod.yml`, `deploy/nginx/`,
`deploy/backup/backup.sh`, `config/models.prod.yaml`, образец `config/app.prod.yaml.example`. Без
сервера проверено то, что можно: синтаксис compose, конфигурация nginx и стрим через него, бэкап
и восстановление на контейнерах данных. **На сервере впервые** запускаются модели (флаги vLLM и
TEI, GPU), настоящий TLS и AD.

| Пометка | Значение |
| --- | --- |
| ✅ | Есть в репозитории, команда работает уже сейчас |
| 🔜 | Ещё нет в репозитории; делается вручную по этому документу |

## Содержание

1. [Состав первого запуска](#1-состав-первого-запуска)
2. [За 1–2 недели до сервера: что запросить](#2-за-12-недели-до-сервера-что-запросить)
3. [Генеральная репетиция](#3-генеральная-репетиция)
4. [Шаг 1. Подготовка хоста](#4-шаг-1-подготовка-хоста)
5. [Шаг 2. Код, секреты, конфиг](#5-шаг-2-код-секреты-конфиг)
6. [Шаг 3. Веса моделей](#6-шаг-3-веса-моделей)
7. [Шаг 4. Модели](#7-шаг-4-модели)
8. [Шаг 5. Приложение](#8-шаг-5-приложение)
9. [Шаг 6. nginx и TLS](#9-шаг-6-nginx-и-tls)
10. [Шаг 7. Бэкапы и проверка восстановления](#10-шаг-7-бэкапы-и-проверка-восстановления)
11. [Шаг 8. Приёмка, первые админы, пилот](#11-шаг-8-приёмка-первые-админы-пилот)
12. [После запуска: доводка](#12-после-запуска-доводка)
13. [Обновление и откат](#13-обновление-и-откат)
14. [Проблемы и решения](#14-проблемы-и-решения)

## 1. Состав первого запуска

| Входит | Откладывается на доводку |
| --- | --- |
| PostgreSQL, Redis, Qdrant | Модель для разработчиков `llm-coder` и `dev-gateway` (GPU 2) |
| api, generator, worker, worker-kb, scheduler, frontend | guard-модель (`moderation.guard_enabled: false`) |
| `llm-chat` (GPU 0–1, TP = 2) | Prometheus, Grafana, алерты |
| `llm-utility`, `embed`, `rerank` (GPU 3) | Офлайн-бандл — нужен только к отключению интернета |
| nginx с TLS | data-gateway — пока не известно представление справочника |
| Вход через AD | Нагрузочный тест целиком (в день запуска — короткий бенчмарк) |
| Ночные бэкапы и одна проверка восстановления | gVisor, docling на GPU, MIG, FIM, MTP |

Ориентировочное время при подготовленных данных из раздела 2:

| Шаг | Время |
| --- | --- |
| 1. Хост: драйвер, Docker, NVIDIA Container Toolkit | 1–2 ч |
| 2. Код, секреты, конфиг | 30 мин |
| 3. Веса моделей (~100 ГБ) | от 30 мин до нескольких часов — зависит от канала; можно заранее |
| 4. Модели и короткий бенчмарк | 1 ч |
| 5. Приложение | 30 мин |
| 6. nginx и TLS | 30 мин |
| 7. Бэкапы и проверка восстановления | 1 ч |
| 8. Приёмка и первые админы | 1 ч |

Кто нужен в день запуска: администратор Linux (sudo на сервере), администратор AD (на связи —
для учётки и групп), сетевой инженер или ИБ (на связи — для фаервола и сертификата).

## 2. За 1–2 недели до сервера: что запросить

Большинство задержек в день запуска — это ожидание чужих ответов. Соберите всё заранее и запишите
в защищённое место (не в git).

**У администраторов AD** (подробно — [guides/ad-setup.md](../guides/ad-setup.md)):

- [ ] FQDN контроллеров домена — **как в их сертификатах** — и порт LDAPS (обычно 636)
- [ ] Сертификат корпоративного CA в PEM: корневой и промежуточные, если они есть
- [ ] Сервисная учётка только на чтение, **с паролем без срока действия**
- [ ] Base DN, UPN-суффикс, NetBIOS-имя домена
- [ ] Порог блокировки учёток в политике AD (наш `per_login.max_failures` = 5 должен быть ниже)
- [ ] Логин тестового пользователя для `ad check` и логины первых администраторов портала

**У сети и ИБ:**

- [ ] IP сервера, DNS-имя портала (например, `ai.corp.local`) и A-запись в DNS
- [ ] TLS-сертификат портала от корпоративного CA: SAN = DNS-имя портала, полная цепочка (fullchain)
      и ключ. Корпоративный CA должен быть в доверенных на рабочих местах (обычно через GPO)
- [ ] Фаервол: от пользователей к серверу — 443 (и 80 для редиректа); от сервера к контроллерам — 636
- [ ] Исходящий интернет на время установки: есть ли и через какой прокси. Нужные хосты — раздел 6
      и 8.1
- [ ] **Подсети, которые использует компания.** Docker по умолчанию берёт сети из `172.17.0.0/16` и
      соседних — если они пересекаются с корпоративными, часть пользователей и AD станут недоступны
      (проблема Б1). Выберите заранее свободный диапазон, например `10.250.0.0/16`
- [ ] NTP-сервер компании
- [ ] Куда класть бэкапы: отдельный диск, NAS или другой сервер (не тот же диск, что данные)

**О сервере:**

- [ ] Ubuntu 24.04 LTS установлена, есть sudo и SSH
- [ ] Диски: системный; быстрый NVMe ≥ 1 ТБ под Docker и веса моделей; отдельный том под бэкапы
- [ ] Модель платы GPU: 4× A100 SXM на плате HGX или PCIe с мостами NVLink (от этого зависит
      fabric manager — проблема А5)
- [ ] Secure Boot включён или нет (проблема А2)

**Решения, которые нужно принять до запуска:**

- [ ] Название компании для промпта (`chat.company_name`)
- [ ] Логины первых администраторов (`auth.bootstrap_admins`)
- [ ] Группа доступа (`ldap.access_group`) — или пускать всех включённых пользователей домена
- [ ] Первые базы знаний: какие документы, для каких ролей; документы сложены в папки

## 3. Генеральная репетиция

До приезда сервера прогоните шаги 2, 5–8 на рабочей станции или чистой виртуалке с Ubuntu 24.04
и Docker. Вместо vLLM — fake-llm и TEI на CPU из дев-стенда (или маленькая модель, если на станции
есть GPU), вместо AD — mock-AD.

Цель — поймать всё, что не зависит от видеокарт и реального AD: пути, права на файлы, порядок старта,
nginx и стрим, TLS с тестовым сертификатом, бэкап и восстановление. В день запуска останутся только
GPU, реальный AD и реальный сертификат.

Критерий: на чистой машине по этому документу, без правок «на ходу», проходит приёмка из раздела 11.
Всё, что пришлось поправить, — исправить в документе и в файлах этапа 10а.

## 4. Шаг 1. Подготовка хоста

### 4.1 Система

```bash
sudo apt update && sudo apt full-upgrade -y
sudo timedatectl set-timezone Europe/Moscow
```

NTP — на сервер компании в `/etc/systemd/timesyncd.conf` (`NTP=<адрес>`), затем:

```bash
sudo systemctl restart systemd-timesyncd
```

```bash
timedatectl status
```

Должно быть `System clock synchronized: yes`.

Автообновления не должны трогать драйвер NVIDIA и Docker без вас (проблема А4):

```bash
sudo apt-mark hold 'nvidia-*' 'libnvidia-*' docker-ce docker-ce-cli containerd.io
```

Выполните это **после** установки драйвера и Docker (4.2, 4.3).

### 4.2 Драйвер NVIDIA

Версия драйвера — по требованиям выбранного образа vLLM: образ на CUDA 12.8 требует драйвер ≥ 570.
Серверная ветка драйвера (`-server`) — для дата-центровых GPU.

```bash
sudo ubuntu-drivers list --gpgpu
```

```bash
sudo ubuntu-drivers install --gpgpu nvidia:570-server
```

```bash
sudo apt install -y nvidia-utils-570-server
```

Если GPU на плате HGX с NVSwitch — та же версия `nvidia-fabricmanager-570` и
`sudo systemctl enable --now nvidia-fabricmanager` (проблема А5).

```bash
sudo reboot
```

После перезагрузки:

```bash
nvidia-smi
```

```bash
nvidia-smi topo -m
```

```bash
sudo nvidia-smi -pm 1
```

Ожидается: 4 GPU A100 80 ГБ, без ошибок ECC; в `topo -m` между GPU 0 и GPU 1 — `NV#`
(NVLink), а не `SYS` или `PHB`. Если NVLink только между другой парой, чат ставится на неё
(проблема А6). Persistence mode держит драйвер загруженным — без него первый запуск CUDA медленный.
Чтобы режим переживал перезагрузку:

```bash
sudo systemctl enable --now nvidia-persistenced
```

### 4.3 Docker

Docker Engine и плагин Compose — из официального репозитория Docker (не `docker.io` из Ubuntu, там
старый Compose).

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt update && sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

`/etc/docker/daemon.json` — **до** первого запуска контейнеров:

```json
{
  "data-root": "/data/docker",
  "default-address-pools": [{"base": "10.250.0.0/16", "size": 24}],
  "bip": "10.251.0.1/24",
  "log-driver": "json-file",
  "log-opts": {"max-size": "20m", "max-file": "5"}
}
```

- `data-root` — на быстрый NVMe (образы и тома займут сотни гигабайт).
- `default-address-pools` и `bip` — свободный диапазон из раздела 2 (проблема Б1).
- Если исходящий трафик идёт через корпоративный прокси, Docker нужен свой drop-in для `docker pull`
  (проблема Б3).

```bash
sudo systemctl restart docker
```

### 4.4 NVIDIA Container Toolkit

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update && sudo apt install -y nvidia-container-toolkit
```

```bash
sudo nvidia-ctk runtime configure --runtime=docker
```

```bash
sudo systemctl restart docker
```

`nvidia-ctk` дописывает `runtimes` в `daemon.json` — проверьте, что ваши настройки из 4.3 остались.

### 4.5 Проверка шага

```bash
docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi
```

Видны 4 GPU — шаг пройден. Затем:

```bash
sudo apt-mark hold 'nvidia-*' 'libnvidia-*' docker-ce docker-ce-cli containerd.io
```

### 4.6 Каталоги

```text
/srv/ai-assistant/           код (git checkout)
/srv/ai-assistant-secrets/   секреты, вне репозитория: chmod 700
/srv/models/                 веса моделей
/srv/import/                 документы для импорта в базы знаний
/backup/ai-assistant/        бэкапы — отдельный диск или сетевой том
```

```bash
sudo mkdir -p /srv/ai-assistant /srv/ai-assistant-secrets /srv/models /srv/import /backup/ai-assistant
```

```bash
sudo chmod 700 /srv/ai-assistant-secrets
```

## 5. Шаг 2. Код, секреты, конфиг

### 5.1 Код

```bash
sudo git clone <адрес репозитория> /srv/ai-assistant
```

```bash
cd /srv/ai-assistant && sudo git checkout <тег или коммит релиза>
```

Без доступа к git — архив `git archive` с рабочей станции.

### 5.2 Секреты

**Важно:** секреты на хосте храните в `/srv/ai-assistant-secrets/`, а не в `/run/secrets/` хоста —
`/run` очищается при перезагрузке (проблема Г4). В контейнеры они попадают через `secrets:` compose
по пути `/run/secrets/<имя>`, его и ждёт приложение.

Внутренние пароли генерируйте, вручную вводятся только данные от AD и сертификаты:

```bash
cd /srv/ai-assistant/deploy/compose
sudo install -m 600 /dev/null .env
{
  echo "APP_ENV=prod"
  echo "APP_VERSION=$(git -C /srv/ai-assistant rev-parse --short HEAD)"
  echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)"
  echo "REDIS_PASSWORD=$(openssl rand -hex 24)"
  echo "QDRANT_API_KEY=$(openssl rand -hex 24)"
  echo "DATA_GATEWAY_SECRET=$(openssl rand -hex 24)"
  echo "KB_IMPORT_DIR=/srv/import"
  echo "PORTAL_HOST=ai.corp.local"
  echo "VLLM_IMAGE=vllm/vllm-openai:<версия>@sha256:<digest>"
  echo "TEI_IMAGE=ghcr.io/huggingface/text-embeddings-inference:<версия для Ampere 80>@sha256:<digest>"
} | sudo tee .env >/dev/null
```

`PORTAL_HOST` — имя портала, как в сертификате. Образы моделей задаются по digest
(`docker buildx imagetools inspect <образ>:<тег>`): версию vLLM выбирают под модель, TEI — сборка
для Ampere 80 (A100). Без этих трёх переменных `compose.prod.yml` не стартует и говорит, какой
не хватает. Каталоги и номера GPU, если они не как в руководстве, — см. раздел «Прод» в
`deploy/compose/.env.example`.

Пароли используют только hex-символы: спецсимволы в пароле PostgreSQL ломают DSN (проблема Г3).

```bash
cd /srv/ai-assistant-secrets
sudo install -m 640 -o root -g 10001 /dev/null ldap_bind_password
sudoedit ldap_bind_password
```

Пароль сервисной учётки — одной строкой. Группа `10001` — пользователь `app` в образах api и
воркера: без права чтения приложение не прочтёт секрет (проблема Г5).

```bash
sudo install -m 644 corp-ca.pem /srv/ai-assistant-secrets/corp_ca.pem
```

```bash
sudo install -m 644 fullchain.pem /srv/ai-assistant-secrets/tls_fullchain.pem
```

```bash
sudo install -m 600 privkey.pem /srv/ai-assistant-secrets/tls_privkey.pem
```

`corp_ca.pem` — корневой и промежуточные сертификаты CA контроллеров подряд в одном файле.
`tls_fullchain.pem` — сертификат портала **и** промежуточные (проблема Е4).

### 5.3 Конфиг прода

Поведение — в `config/app.prod.yaml` и `config/models.prod.yaml` поверх базовых (§16.4). Секретов
в них нет, их можно коммитить.

- `config/models.prod.yaml` (✅) — отличия реестра моделей: эмбеддинги и реранкер на TEI,
  `coder` и `guard` помечены `deployed: false` — монитор здоровья не заводит по ним инциденты,
  пока модели не развёрнуты (доводка, раздел 12).
- `config/app.prod.yaml` — из образца (✅ `config/app.prod.yaml.example`): заполните `<…>`.

```bash
cp config/app.prod.yaml.example config/app.prod.yaml
```

Что в нём: вход только через `ldap`, первые админы, контроллеры и сервисная учётка AD, название
компании, `trusted_proxies` (сеть Docker из 4.3 — проблема Д7), выключенные guard-модель и шлюз
данных.

Имя `model` в `models.yaml` должно совпадать с `--served-model-name` у vLLM (проблема В6).

Проверка конфига до старта (✅, после сборки образа в шаге 5):

```bash
docker compose -f docker-compose.yml -f compose.prod.yml run --rm --no-deps api python -m app.cli config check
```

## 6. Шаг 3. Веса моделей

Можно начать заранее, сразу после установки Docker — это самый долгий шаг.

| Роль | Репозиторий | Примерный объём |
| --- | --- | --- |
| chat | `Qwen/Qwen3.8-27B` | ~56 ГБ |
| utility | `Qwen/Qwen3.5-4B` (FP8) | ~5 ГБ |
| embed | `BAAI/bge-m3` | ~2,3 ГБ |
| rerank | `BAAI/bge-reranker-v2-m3` | ~2,3 ГБ |
| coder, guard — на доводке | `Qwen/Qwen3.8-27B-FP8`, `Qwen/Qwen3Guard-Gen-4B` | ~28 ГБ, ~8 ГБ |

Финальный выбор моделей — §3.3 SPEC. Хосты для исходящего доступа: `huggingface.co` и его CDN
(`cdn-lfs.huggingface.co`, `cas-bridge.xethub.hf.co` и другие `*.hf.co`).

```bash
docker run --rm -v /srv/models:/models -e HF_HUB_DISABLE_TELEMETRY=1 python:3.12-slim \
  sh -c "pip install -q 'huggingface_hub[cli]' && hf download Qwen/Qwen3.8-27B --local-dir /models/Qwen3.8-27B"
```

Повторите для каждой модели. Прерванная загрузка продолжается тем же вызовом.

Проверка целостности: `hf download` сверяет хэши LFS-файлов; дополнительно сохраните список
контрольных сумм — он понадобится для офлайн-бандла и для поиска повреждённых файлов (проблема В9):

```bash
cd /srv/models && find . -type f -name '*.safetensors' -exec sha256sum {} + | sudo tee SHA256SUMS
```

## 7. Шаг 4. Модели

Модели поднимаются **до** приложения: им нужно несколько минут на загрузку, и порядок важен —
сначала крупная модель, потом мелкие (§3.2).

### 7.1 Сервисы моделей (✅ `deploy/compose/compose.prod.yml`)

В файле — `llm-chat` (GPU 0–1, TP = 2), `llm-utility`, `embed`, `rerank` (GPU 3). Перед запуском
сверьте с сервером:

- **Флаги vLLM** — стартовые из §3.2 SPEC; финальные — по рецепту vLLM для выбранной версии
  (парсеры размышлений и инструментов, `--max-model-len`).
- **Пути весов** — `/srv/models/Qwen3.8-27B`, `Qwen3.5-4B`, `bge-m3`, `bge-reranker-v2-m3`
  (шаг 3); `--served-model-name` совпадает с `model` в `config/models.yaml` (проблема В6).
- **Образы** — `VLLM_IMAGE` и `TEI_IMAGE` в `.env`, по digest.
- `ipc: host` — общая память для TP = 2 (проблема В3); `start_period` у `llm-chat` — 20 минут:
  первая загрузка весов и компиляция долгие.

Номера GPU надёжнее задавать UUID из `nvidia-smi -L` (`GPU_CHAT_A`, `GPU_CHAT_B`, `GPU_AUX` в
`.env`): порядковые номера могут поменяться после замены карты или обновления прошивки
(проблема А6).

### 7.2 Запуск и проверка

```bash
cd /srv/ai-assistant/deploy/compose
```

```bash
docker compose -f docker-compose.yml -f compose.prod.yml up -d llm-chat
```

```bash
docker compose -f docker-compose.yml -f compose.prod.yml logs -f llm-chat
```

Ждите в логе `Application startup complete`. Затем остальные модели:

```bash
docker compose -f docker-compose.yml -f compose.prod.yml up -d embed rerank llm-utility
```

```bash
nvidia-smi
```

Память: GPU 0 и 1 — около 0,9 от 80 ГБ; GPU 3 — несколько процессов, суммарно меньше половины.

Проверка ответа и вызова инструмента — временным контейнером с curl в сети стенда (порты моделей
наружу не публикуются):

```bash
docker run --rm --network ai-assistant_default curlimages/curl -s http://llm-chat:8000/v1/models
```

```bash
docker run --rm --network ai-assistant_default curlimages/curl -s http://llm-chat:8000/v1/chat/completions -H 'Content-Type: application/json' -d '{"model":"Qwen/Qwen3.8-27B","messages":[{"role":"user","content":"Какая погода в Москве?"}],"tools":[{"type":"function","function":{"name":"get_weather","parameters":{"type":"object","properties":{"city":{"type":"string"}}}}}]}'
```

В ответе — `tool_calls` с `get_weather`, а не текст с JSON внутри `content` (проблема В5).

Короткий бенчмарк (полный нагрузочный тест — на доводке):

```bash
docker compose -f docker-compose.yml -f compose.prod.yml exec llm-chat vllm bench serve --model Qwen/Qwen3.8-27B --dataset-name random --random-input-len 2000 --random-output-len 500 --num-prompts 50 --max-concurrency 10
```

Запишите время до первого токена и скорость генерации в `docs/status.md`.

Когда поднято приложение (шаг 5) — тот же замер глазами пользователя, через api, очередь
генерации и SSE: `eval/load/run.py` (см. `eval/README.md`, раздел «Нагрузочный тест») с
тестовыми учётками AD и обычным вопросом вместо сценария fake-llm.

## 8. Шаг 5. Приложение

### 8.1 Образы

Вариант A — сборка на сервере, если есть интернет. Нужны хосты: `registry-1.docker.io` и
`production.cloudflare.docker.com`, `ghcr.io`, `pypi.org` и `files.pythonhosted.org`,
`registry.npmjs.org`, `deb.debian.org`, `packages.microsoft.com` (ODBC для data-gateway).

```bash
cd /srv/ai-assistant/deploy/compose
```

```bash
docker compose -f docker-compose.yml -f compose.prod.yml build
```

Вариант B — сборка на рабочей станции (там же, где `make check`) и перенос: меньше исключений в
фаерволе и тот же образ, что прошёл тесты.

```bash
docker save ai-assistant/api:<версия> ai-assistant/worker:<версия> ai-assistant/frontend:<версия> | zstd -T0 > images.tar.zst
```

```bash
zstd -dc images.tar.zst | docker load
```

### 8.2 Сервисы приложения (✅ `deploy/compose/compose.prod.yml`)

Отличия прода от базового `docker-compose.yml`, уже записанные в файле:

- `APP_ENV: prod` и каталог `config/` томом только для чтения у `api`, `generator`, `worker`,
  `worker-kb`, `scheduler`, `migrate` — конфиг меняется без пересборки образа;
- секреты `ldap_bind_password` и `corp_ca.pem` у `api` и `worker` (из `/srv/ai-assistant-secrets`);
- `api` и `generator` ждут готовности `llm-chat`; `generator` — исполнитель генерации
  (ADR-0013), без него ответы не начинаются (проблема Г10);
- `data-gateway` — только с `--profile data`; шлюз данных у `api` и `generator` выключен;
- снапшоты Qdrant — сразу в `/backup/ai-assistant/qdrant-snapshots`;
- `frontend` (статика SPA) и `nginx` (раздел 9).

Ни один сервис приложения и моделей не публикует порты наружу: снаружи доступен только nginx
(проблема Б4).

### 8.3 Запуск

```bash
docker compose -f docker-compose.yml -f compose.prod.yml run --rm --no-deps api python -m app.cli config check
```

```bash
docker compose -f docker-compose.yml -f compose.prod.yml up -d
```

Сервис `migrate` применяет миграции до старта api и воркеров (✅). Проверки:

```bash
docker compose -f docker-compose.yml -f compose.prod.yml ps
```

```bash
docker compose -f docker-compose.yml -f compose.prod.yml exec api curl -s http://127.0.0.1:8000/ready
```

```bash
docker compose -f docker-compose.yml -f compose.prod.yml exec worker python -m app.cli worker check
```

```bash
docker compose -f docker-compose.yml -f compose.prod.yml exec api python -m app.cli ad check --user <тестовый логин>
```

Ожидается: все сервисы `running` или `healthy`, `migrate` — `exited (0)`; `/ready` — все проверки
`ok`; `worker check` — pandoc, LibreOffice и Tesseract на месте; `ad check` — «вход возможен», верные
ФИО и роли. Пароль конкретного пользователя: добавьте `--password-prompt`. То же для любого
логина — в админке «Диагностика AD».

## 9. Шаг 6. nginx и TLS

### 9.1 Конфигурация (✅ `deploy/nginx/`, сервис `nginx` в `compose.prod.yml`)

nginx — единственный сервис с портами наружу (80 → редирект, 443). Статику отдаёт контейнер
`frontend`, `/api` — `api`. Конфигурация — шаблон `deploy/nginx/templates/default.conf.template`:
при старте контейнера в него подставляется `PORTAL_HOST` из `.env`. Что в нём важно:

- `/api/` — без буферизации и с чтением до часа: иначе ответ приходит одним куском в конце
  (проблема Е1) или обрывается через минуту (Е2);
- `client_max_body_size 60m` — лимит загрузки 50 МБ с запасом (проблема Е3);
- `/metrics` наружу закрыт (§16.6);
- сертификат и ключ — секреты `tls_fullchain.pem` и `tls_privkey.pem` (раздел 5.2).

Шаблон проверяется без сервера: `make test-nginx` (`nginx -t` в том же образе). Стрим через
nginx с TLS проверен нагрузочным тестом на стенде — время до первого токена не выросло.

### 9.2 Проверка

```bash
docker compose -f docker-compose.yml -f compose.prod.yml exec nginx nginx -t
```

С рабочего места пользователя:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://ai.corp.local/
```

Ожидается `200` без ошибок сертификата. Стрим — главная проверка nginx: в браузере ответ модели
должен печататься постепенно, а не появляться целиком в конце.

## 10. Шаг 7. Бэкапы и проверка восстановления

Минимум с первого дня: данные пользователей появляются с первого часа. Полная схема с WAL-архивом —
§16.7 SPEC, на доводке.

### 10.1 Скрипт ночного бэкапа (✅ `deploy/backup/backup.sh`)

Скрипт пишет в `/backup/ai-assistant/<дата>/`:

- `postgres.dump` — логический дамп PostgreSQL (формат custom);
- `qdrant-snapshot.txt` — имя полного снапшота Qdrant; сам файл — в
  `/backup/ai-assistant/qdrant-snapshots/` (том из `compose.prod.yml`);
- `storage.tar` — файлы пользователей и баз знаний;
- `config.tar` — конфиг без секретов.

Хранит 30 дней (`KEEP_DAYS`). При пустом дампе или отсутствии снапшота завершается с ошибкой —
следите за журналом. Первый запуск вручную:

```bash
sudo /srv/ai-assistant/deploy/backup/backup.sh
```

Скрипт проверен без сервера (`make test-backup`): бэкап и восстановление PostgreSQL на
контейнерах, снапшот Qdrant, архивы, удаление старых бэкапов.

Секреты (`/srv/ai-assistant-secrets`, `deploy/compose/.env`) бэкапятся **отдельно**, в защищённое
хранилище: без пароля PostgreSQL дамп всё равно восстановится, но без `.env` придётся перевыпускать
внутренние пароли.

```bash
echo '30 2 * * * root /srv/ai-assistant/deploy/backup/backup.sh >> /var/log/ai-assistant-backup.log 2>&1' | sudo tee /etc/cron.d/ai-assistant-backup
```

### 10.2 Проверка восстановления (до пуска пользователей)

Восстанавливайте во **временные** контейнеры, не в прод:

```bash
docker run -d --name restore-pg -e POSTGRES_PASSWORD=restore postgres:17
```

```bash
docker exec -i restore-pg pg_restore -U postgres -d postgres --create --no-owner --no-acl < /backup/ai-assistant/<дата>/postgres.dump
```

```bash
docker exec restore-pg psql -U postgres -d assistant -c 'select count(*) from users; select count(*) from chats;'
```

Числа совпадают с продом — дамп рабочий. Для Qdrant — временный контейнер Qdrant, запущенный с
полным снапшотом (`--storage-snapshot <файл>`), и сверка числа точек в коллекциях
(`GET /collections/<имя>`) с продом; точную команду зафиксировать на генеральной репетиции. Для
файлов — распаковать `storage.tar` во временный каталог и открыть пару файлов.

```bash
docker rm -f restore-pg
```

Результат и время восстановления запишите в `docs/status.md`. Полное восстановление после аварии —
✅ [backup-restore.md](backup-restore.md).

## 11. Шаг 8. Приёмка, первые админы, пилот

### 11.1 Чек-лист приёмки

- [ ] Хост: 4 GPU, NVLink в паре чата, контейнеры видят GPU (4.5)
- [ ] Секреты и конфиг: `config check` без ошибок
- [ ] `ad check` — «вход возможен», верные ФИО и роли
- [ ] Smoke-проверка ниже пройдена (скрипт и ручная часть)
- [ ] Бэкап снят, восстановление проверено (10.2)

### 11.2 Smoke-проверка (✅ `scripts/smoke.py` — пункты 1, 2, 5, 7, 8 и вопрос по файлу)

Автоматическая часть — с рабочего места, где есть репозиторий и `uv` (или из контейнера api):

```bash
uv run python scripts/smoke.py --base-url https://ai.corp.local --provider ldap --login <сотрудник> --admin <админ> --ask-password
```

Скрипт входит под обеими учётками и проверяет: профиль из AD; ответ идёт частями и у чата
появляется заголовок; ответ по приложенному текстовому файлу; документ Word создаётся и
скачивается; переподключение к потоку посреди ответа; в админке — все развёрнутые модели
отвечают, есть исполнитель генерации. Код возврата 1 — что-то не прошло, строка с ✗ говорит что.
Если портал подписан корпоративным CA, которого нет на рабочем месте, — `--ca-file corp_ca.pem`.
С настоящей моделью пункты «файл» и «документ» зависят от её ответа: при сбое повторите.

Вручную — то, что скрипт не видит (PDF и DOCX, скан, база знаний, внешний вид печати). Весь
список под учётками из `bootstrap_admins` и одного обычного сотрудника:

1. Вход доменным логином; в профиле — ФИО и отдел из AD.
2. Сообщение «Привет» — ответ печатается **постепенно**; через несколько секунд у чата появляется
   заголовок (работает `utility`).
3. Прикрепить PDF и DOCX, спросить о содержимом — ответ по файлам.
4. Скан (PDF-картинка) — текст распознан (Tesseract в воркере).
5. «Сделай документ Word с итогами» — карточка файла, скачивается с русским именем.
6. Админка: база знаний, загрузить 2–3 документа, статус «готово»; вопрос по ним — ответ с цитатами,
   клик по цитате открывает документ.
7. Перезагрузить страницу во время ответа — ответ дописывается (переподключение стрима).
8. Админка → «Модели»: все модели доступны; «Инциденты» — без неожиданных записей.

### 11.3 Первые админы и наполнение

- Логины из `auth.bootstrap_admins` получают суперадмина при первом входе. Без этого (✅):

```bash
docker compose -f docker-compose.yml -f compose.prod.yml exec api python -m app.cli create-admin --login <логин>
```

- Админка → «Настройки»: название, компания, текст уведомления для пользователей.
- «Лимиты» — проверить значения по умолчанию из `config/app.yaml`.
- «Роли» — отдел из AD у заказчика не заполнен (решение 57): назначить роли списком логинов.
- «Базы знаний» — создать базы и импортировать документы из `/srv/import` (✅ импорт папкой в
  админке или `python -m app.cli kb import --kb <код> <подпапка>`).

### 11.4 Пилот

Первые 2–3 дня — 10–20 сотрудников из разных отделов, затем все. Каждый день пилота смотреть:
«Инциденты», «Модели», «Дашборд», «Обратная связь», свободное место на дисках.

## 12. После запуска: доводка

Порядок — по пользе; каждый пункт — отдельная задача этапа 10б.

1. **Мониторинг и алерты** — Prometheus, DCGM, Grafana, алерты §16.6. Адрес Prometheus — в
   `monitoring.prometheus_url`, тогда в админке появятся метрики GPU.
2. **Разработчики** — `llm-coder` на GPU 2 и `dev-gateway` с персональными ключами (§3.4).
3. **guard-модель** — `llm-guard` на GPU 3, затем `moderation.guard_enabled: true`.
4. **Нагрузочный тест** по целям §18.4.
5. **Полные бэкапы** — WAL-архив PostgreSQL, копия на другой сервер, runbook восстановления.
6. **Порог реранкера** на реальных документах: `make eval-rag KB=… QUESTIONS=…` (✅).
7. **Офлайн-бандл** — к дате отключения интернета (§16.3).
8. **data-gateway** — когда заказчик назовёт представление справочника (`--profile data`).

## 13. Обновление и откат

### 13.1 Обновление

1. Бэкап вручную перед обновлением: `/srv/ai-assistant/deploy/backup/backup.sh`.
2. Новый код: `git fetch && git checkout <новый тег>`; в `.env` — новая `APP_VERSION`.
3. Образы: сборка (8.1, вариант A) или `docker load` (вариант B). Старые образы **не удалять** до
   конца проверки — по ним идёт откат.
4. `config check`, затем `up -d`: `migrate` применит миграции, сервисы перезапустятся. Идущие ответы
   не прерываются: их ведёт `generator`, который при остановке дорабатывает свои ответы (до
   `generation.shutdown_grace_seconds`, 180 с — столько может длиться его перезапуск). Сообщения,
   отправленные в это время, ждут в очереди нового исполнителя. Чат у пользователей
   переподключится сам.
5. Smoke-проверка 11.2 (пункты 1, 2, 6).

Перезапуск моделей не нужен, если не менялись они сами.

### 13.2 Откат

- **Без миграций БД** в новой версии: вернуть прежние `APP_VERSION` и коммит, `up -d`.
- **С миграциями**: откат кода не откатывает схему. Либо `alembic downgrade <ревизия>` (только если
  миграция обратима, проверяйте заранее на репетиции), либо восстановление БД из бэкапа шага 1
  (10.2, но в прод) — с потерей данных после бэкапа. Поэтому релизы с миграциями — в нерабочее время.

## 14. Проблемы и решения

Формат: **симптом** → причина → что делать. Сначала всегда смотрите логи сервиса:

```bash
docker compose -f docker-compose.yml -f compose.prod.yml logs --tail=200 <сервис>
```

Ошибки приложения уже собираются в «Инцидентах» админки со стеком и логом запроса (`system_error`).

### А. Хост и видеокарты

**А1. `nvidia-smi`: «No devices were found» или «couldn't communicate with the NVIDIA driver».**
Драйвер не загружен.
- `lsmod | grep nvidia` пусто → `dmesg | grep -i -E 'nvrm|nvidia'`.
- Загружен `nouveau` → удалить его: драйвер из `ubuntu-drivers` обычно блокирует его сам; иначе
  `blacklist nouveau` в `/etc/modprobe.d/`, `sudo update-initramfs -u`, перезагрузка.
- Видно не 4 GPU → проверить карты в `lspci | grep -i nvidia`; если и там меньше — железо или BIOS
  (Above 4G Decoding, режим слотов), к поставщику.

**А2. Модуль не загружается, в `dmesg` «Lockdown» или «module verification failed» при Secure Boot.**
Неподписанный модуль ядра.
Варианты: подписать через MOK — при установке задаётся пароль, при перезагрузке в синем экране
MokManager выбрать «Enroll MOK» и ввести его (нужен доступ к консоли сервера, iDRAC/iLO); либо
отключить Secure Boot в BIOS по согласованию с ИБ.

**А3. В контейнере vLLM: «CUDA driver version is insufficient for CUDA runtime version».**
Драйвер старше, чем требует образ vLLM. Поставить драйвер новее (4.2) или взять образ vLLM на
более старой CUDA. Проверка: `nvidia-smi` показывает «CUDA Version» — максимально поддерживаемую;
она должна быть не ниже версии CUDA образа.

**А4. После обновления системы: «Failed to initialize NVML: Driver/library version mismatch».**
Пакеты драйвера обновились, а в ядре загружен старый модуль. Перезагрузить сервер. Чтобы не
повторялось — `apt-mark hold` (4.1), обновлять драйвер только вручную по runbook.

**А5. CUDA: «system not yet initialized» (ошибка 802), `nvidia-smi` при этом работает.**
Плата HGX с NVSwitch без fabric manager.
`sudo apt install nvidia-fabricmanager-<та же ветка, что драйвер>`, затем
`sudo systemctl enable --now nvidia-fabricmanager`. Версии драйвера и fabric manager должны
совпадать **точно** — после обновления драйвера обновить и его.

**А6. Чат медленный, в `nvidia-smi topo -m` между GPU 0 и 1 — `SYS` или `PHB`; или модели
«переехали» на другие карты.**
NVLink есть не между теми картами, или порядковые номера GPU поменялись.
Выбрать пару с `NV#` и поставить чат на неё. В `device_ids` указывать UUID (`nvidia-smi -L`), а не
номера. Для процессов внутри контейнера — `CUDA_DEVICE_ORDER=PCI_BUS_ID`.

**А7. В `dmesg` ошибки Xid (79 — «GPU has fallen off the bus», 48 — двойная ошибка ECC), модель
падает.**
Аппаратная проблема: питание, перегрев, карта.
`nvidia-smi -q -d ECC,TEMPERATURE,POWER`; перезагрузка; если повторяется на той же карте —
к поставщику. На время — перенести модели с карты по §3.5 (например, чат на одну GPU в FP8).

**А8. Docker: «could not select device driver "" with capabilities: [[gpu]]».**
Не настроен NVIDIA Container Toolkit. `sudo nvidia-ctk runtime configure --runtime=docker`,
`sudo systemctl restart docker`, проверка из 4.5.

### Б. Сеть и Docker

**Б1. После запуска контейнеров часть пользователей, контроллеры AD или сам сервер по SSH стали
недоступны.**
Сеть Docker пересеклась с корпоративной подсетью.
`ip route` — найти мосты `br-…` и `docker0` с адресами из корпоративного диапазона. Остановить
стенд (`down`), задать `default-address-pools` и `bip` (4.3), `sudo systemctl restart docker`,
удалить старые сети (`docker network prune`) и поднять заново. Не забыть `trusted_proxies` —
он должен совпадать с новым диапазоном (Д7).

**Б2. Из контейнера не резолвится имя контроллера (`ad check`: «Name or service not known»), а с хоста
резолвится.**
Docker не видит корпоративный DNS (типично, когда на хосте `systemd-resolved` со stub 127.0.0.53).
Проверка: `docker compose … exec api getent hosts <dc-fqdn>`. Решение: в `daemon.json` —
`"dns": ["<DNS1>", "<DNS2>"]`, `"dns-search": ["corp.local"]`, перезапуск Docker.

**Б3. `docker pull`, сборка или скачивание весов висят или падают с таймаутом, хотя `curl` с хоста
работает.**
Корпоративный прокси.
- Для `docker pull`: `/etc/systemd/system/docker.service.d/proxy.conf` с `HTTP_PROXY`, `HTTPS_PROXY`,
  `NO_PROXY`, затем `systemctl daemon-reload && systemctl restart docker`.
- Для сборки: `docker compose build --build-arg HTTP_PROXY=… --build-arg HTTPS_PROXY=…`.
- Прокси с подменой TLS (MITM) → корпоративный CA нужен и внутри сборки; проще вариант B
  из 8.1 (сборка на рабочей станции).

**Б4. Сервис отвечает снаружи на порту, который должен быть внутренним (Postgres, Qdrant, vLLM).**
Docker публикует порты в обход `ufw`.
В `compose.prod.yml` порты наружу — только у nginx; для отладки публиковать как
`127.0.0.1:<порт>:<порт>`. Проверка: `sudo ss -tlnp` — снаружи слушают только 22, 80, 443.

**Б5. api ходит к моделям или Qdrant через корпоративный прокси: таймауты, 502, 407.**
В окружении контейнеров есть `HTTP_PROXY` (например, из `~/.docker/config.json` → `proxies`).
Убрать прокси для контейнеров или задать
`NO_PROXY=localhost,127.0.0.1,api,llm-chat,llm-utility,embed,rerank,qdrant,redis,postgres,data-gateway`.

**Б6. Большие ответы или загрузки обрываются, мелкие проходят (только у части пользователей,
например через VPN).**
MTU. В `daemon.json` — `"mtu": 1400` (или по значению сети), перезапуск Docker и пересоздание сетей.

### В. Модели (vLLM, TEI)

**В1. vLLM падает при старте: «CUDA out of memory» или «No available memory for the cache blocks».**
- Сумма `--gpu-memory-utilization` всех сервисов на карте больше 0,95 или на карте висит лишний
  процесс → `nvidia-smi` (смотреть процессы), остановить лишнее.
- Мелкие сервисы стартовали раньше крупного → соблюдать порядок 7.2.
- Слишком большой `--max-model-len` для оставшейся памяти → уменьшить или поднять долю памяти.

**В2. «The model's max seq len (…) is larger than the maximum number of tokens that can be stored in
KV cache».**
Уменьшить `--max-model-len` (и `context_length` в `models.yaml` вместе с ним) или уменьшить
`--max-num-seqs`.

**В3. Чат с TP = 2 зависает на старте (последняя строка про NCCL) или падает с ошибкой shared memory.**
- Нет общей памяти → `ipc: host` (или `shm_size: 16g`) у `llm-chat`.
- Диагностика: `NCCL_DEBUG=INFO` в окружении, смотреть, какой транспорт выбран.
- Проблема P2P между картами → временно `NCCL_P2P_DISABLE=1` (медленнее) и проверить топологию (А6).

**В4. vLLM или TEI пытается скачать модель: «We couldn't connect to huggingface.co».**
Передан идентификатор репозитория, а не локальный путь, или веса не докачаны.
`--model /models/<папка>` (путь в контейнере), `HF_HUB_OFFLINE=1`; проверить, что в папке есть
`config.json` и все `*.safetensors`.

**В5. Модель пишет вызов инструмента текстом (`<tool_call>…`) в ответе, инструменты не выполняются.**
Нет `--enable-auto-tool-choice` или не тот `--tool-call-parser` для модели. Флаги — по рецепту vLLM
для конкретной модели; проверка — запрос с `tools` из 7.2.

**В6. В чате «Модель недоступна» (`model_unavailable`), а модель здорова; в логах vLLM — 404
«The model … does not exist».**
Имя `model` в `models.yaml` не совпадает с тем, что отдаёт vLLM. При запуске с локального пути vLLM
по умолчанию называет модель путём. Задать `--served-model-name` равным `model` из `models.yaml`
(как в 7.1). Проверка: `curl …/v1/models`.

**В7. В ответах видны размышления модели или ответ пустой.**
Нет `--reasoning-parser` или он не тот. Для режима thinking приложение передаёт
`chat_template_kwargs.enable_thinking` (`models.yaml` → `thinking`) — он должен соответствовать
шаблону модели.

**В8. Первый старт моделей идёт 10–20 минут, в «Инцидентах» — «модель недоступна».**
Нормально для первой загрузки и компиляции. `start_period` у healthcheck моделей — с запасом (7.1);
api стартует после здорового `llm-chat`. Инциденты, созданные за время загрузки, закрыть вручную.

**В9. vLLM падает при загрузке весов: «safetensors … invalid header», «unexpected EOF».**
Файл весов повреждён или не докачан. `cd /srv/models && sha256sum -c SHA256SUMS`, перекачать
повреждённый файл тем же `hf download`.

**В10. TEI (embed или rerank) не стартует на GPU: ошибка о compute capability или CUDA.**
Образ TEI собран под другую архитектуру. Для A100 нужен образ под Ampere 80 (см. таблицу образов в
документации TEI). Временный обход — CPU-образ, как на дев-стенде: медленнее индексация, но работает.

**В11. Генерация медленнее, чем на бенчмарке, при той же нагрузке.**
- Троттлинг: `nvidia-smi -q -d PERFORMANCE,TEMPERATURE` (причины снижения частот).
- Не включён `--enable-prefix-caching`.
- Длинные контексты RAG: проверить в трассировке ответа (админка → переписка), сколько фрагментов
  ушло в модель.
- Шаги из §3.5 SPEC.

### Г. Приложение

**Г1. api не стартует, в логе — ошибка конфигурации.**
Конфиг проверяется при старте, сообщение называет параметр: «auth.providers: провайдер dev запрещён
при APP_ENV=prod», «ldap.urls: не задан ни один контроллер домена», «models: не описаны обязательные
роли …». Проверка без запуска — `config check` (5.3). Помните о слоях: `app.yaml` → `app.prod.yaml` →
переменные `APP_*`; переменная окружения перекрывает YAML.

**Г2. `/ready` — не все проверки `ok`.**
Ответ называет, что недоступно (`postgres`, `redis`, `qdrant`). Смотреть логи этого сервиса и
пароли/ключи в `.env`.

**Г3. `migrate` или api: «password authentication failed for user "assistant"».**
- PostgreSQL берёт `POSTGRES_PASSWORD` **только при первой инициализации тома**: если том остался
  от прошлой попытки с другим паролем, новый пароль не применится. На пустой установке — удалить том
  (`docker volume rm ai-assistant_postgres-data`; **только если данных ещё нет**). На рабочей — сменить
  пароль: `docker compose … exec postgres psql -U assistant -c "ALTER USER assistant PASSWORD '<из .env>'"`.
- Спецсимволы в пароле ломают DSN → только hex (5.2).

**Г4. После перезагрузки сервера api не может прочитать секрет (`/run/secrets/…` нет).**
Секреты лежали в `/run/secrets` хоста — это tmpfs, он очищается. Хранить в
`/srv/ai-assistant-secrets` и монтировать через `secrets:` compose (5.2, 8.2).

**Г5. «Permission denied» на `/run/secrets/…` или `/srv/storage`.**
Процессы api и воркеров работают от пользователя `app` (uid 10001).
Секреты — `chown root:10001`, `chmod 640`. Том хранилища создаётся с правильным владельцем; если
вместо тома смонтирован каталог хоста — `sudo chown -R 10001 <каталог>`.

**Г6. Вложения или документы баз висят «в обработке».**
- Воркер не запущен или упал → `ps`, логи `worker` и `worker-kb`.
- `worker check` — нет LibreOffice или Tesseract → это не тот образ (нужен `ai-assistant/worker`).
- embed недоступен → документы базы встают в ошибку; после починки — «Переиндексировать» в админке.
- Сбой задачи даёт статус «ошибка» и инцидент `worker_failed` — карточка инцидента со стеком.

**Г7. Выгрузки не удаляются по сроку, удалённые чаты не стираются, лимиты пишутся в
`usage_records_default`.**
Не работает `scheduler` (Celery beat) — плановые задачи не ставятся. `ps`, логи `scheduler`;
задачи выполняет `worker`, он тоже должен работать.

**Г8. Время в интерфейсе и сбросах лимитов — не московское.**
`chat.timezone` в конфиге. Время сервера и NTP (4.1) — для логов и бэкапов.

**Г9. После `up -d` с новой версией у пользователей «висит» ответ.**
Ожидаемое поведение — идущие ответы дорабатывает старый `generator` (до 180 с), новые сообщения
ждут в очереди и начинаются, когда поднимется новый; чат переподключается сам. Если ответ не
начинается дольше 3–4 минут — см. Г10; страница перечитывается кнопкой обновления.

**Г10. Сообщение отправлено, ответ не начинается, через несколько минут — «Генерация прервана».**
Не работает `generator`: api только ставит задания в очередь Redis (`generation.mode: queue`).
В админке — инцидент «Исполнитель генерации» и ноль исполнителей на дашборде.
`ps` — сервис должен быть `healthy`; логи `generator`; `docker compose … exec generator python -m
app.cli generator check`. Длина очереди: `redis-cli LLEN gen:queue` — растёт, значит задания никто
не забирает. Если `stop_grace_period` у `generator` меньше `generation.shutdown_grace_seconds`,
Docker убивает его при остановке, и ответы остаются прерванными.

### Д. Вход и AD

**Д1. `ad check`: «certificate verify failed».**
- В `corp_ca.pem` нет промежуточного CA или это не тот CA → взять полную цепочку у админов AD.
  Проверка с хоста: `openssl s_client -connect <dc>:636 -CAfile /srv/ai-assistant-secrets/corp_ca.pem`
  → `Verify return code: 0 (ok)`.
- В `ldap.urls` — IP или короткое имя, а в сертификате контроллера — FQDN → писать FQDN.

**Д2. `ad check`: bind сервисной учётки не проходит (`invalidCredentials`, код 49).**
Расшифровка `data …` в сообщении AD: `52e` — неверный пароль (лишний перевод строки в файле
секрета; `sudoedit` обычно добавляет его — приложение обрезает пробелы, но проверьте, что пароль
верный); `775` — учётка заблокирована; `532` или `773` — пароль истёк или требует смены → «пароль
не истекает» для сервисной учётки; `533` — учётка отключена.

**Д3. `ad check`: учётка сервиса работает, пользователь «не найден».**
`base_dn` не охватывает OU пользователей; `user_filter` не подходит (другой атрибут логина);
пользователь отключён; при заданной `access_group` пользователь не в группе (включая вложенные
при `nested_groups: true`).

**Д4. Таймаут подключения к контроллерам.**
Фаервол между сервером и DC на 636 или DNS (Б2). Проверка с хоста — `nc -vz <dc-fqdn> 636`, из
контейнера — `ad check`: он показывает доступность и TLS каждого контроллера. Приложение перебирает контроллеры по порядку `ldap.urls` — недоступный
первый замедляет вход: поставить первым ближайший.

**Д5. Сотрудник входит, но у него нет ролей и баз знаний отдела.**
У заказчика отдел в AD не заполнен (решение 57): роли назначаются в админке «Роли» списком логинов.
Если атрибут есть, но в другом поле — `ldap.attributes` (маппинг).

**Д6. Учётки сотрудников блокируются в AD после неудачных входов.**
Наш порог (`auth.bruteforce.per_login.max_failures` = 5) должен быть ниже порога политики AD.
Узнать порог у админов AD и при необходимости снизить наш.

**Д7. Вдруг никто не может войти: «Слишком много попыток» или «Доступ с вашего адреса заблокирован»
у всех сразу.**
Приложение видит всех пользователей с одного адреса — адреса nginx, потому что не доверяет его
`X-Forwarded-For`; блокировка по IP после чужих неудачных попыток бьёт по всем.
`trusted_proxies` = подсеть сети Docker, в которой nginx (5.3; после смены пулов — Б1). Снять
блокировку (✅):

```bash
docker compose -f docker-compose.yml -f compose.prod.yml exec api python -m app.cli ip list
```

```bash
docker compose -f docker-compose.yml -f compose.prod.yml exec api python -m app.cli ip unblock <IP или подсеть>
```

Проверка после правки: раздел «Входы» в админке показывает **разные** IP пользователей.

**Д8. Вход проходит, но сразу выбрасывает на страницу входа, или изменяющие запросы дают 403 CSRF.**
Cookie сессии ставится с флагом `Secure` и не работает по `http://`. Открывать только по
`https://` (редирект в 9.1). Также проверить, что портал открывают по одному имени — cookie
привязана к домену.

### Е. nginx, TLS, браузер

**Е1. Ответ модели появляется целиком в конце, а не печатается.**
Буферизация где-то по пути. `proxy_buffering off` и `gzip off` в `location /api/` (9.1). Если между
пользователем и сервером есть ещё прокси (корпоративный или балансировщик) — буферизацию отключить
и там, либо исключить портал из проксирования в настройках браузеров (PAC/GPO).

**Е2. Длинные ответы обрываются примерно через 60 секунд.**
`proxy_read_timeout` по умолчанию — 60 с. Поставить 3600 с (9.1). Обрыв всё равно переживается:
чат переподключается и дочитывает ответ, но лучше без этого.

**Е3. Загрузка большого файла: «413 Request Entity Too Large».**
`client_max_body_size` меньше лимита файла. Поднять вместе с `files.max_file_mb` (лимит в админке
«Настройки» перекрывает конфиг — смотреть оба).

**Е4. Браузер ругается на сертификат.**
- Нет промежуточного сертификата → в `tls_fullchain.pem` сертификат портала и промежуточные
  (проверка: `openssl s_client -connect ai.corp.local:443 -showcerts`).
- Имя портала не в SAN → перевыпустить.
- Корпоративный CA не установлен на рабочих местах → GPO.

**Е5. Не открывается просмотр PDF (пустая область), в консоли браузера — ошибка MIME для `.mjs`.**
Статику должен отдавать контейнер frontend: в его nginx тип `.mjs` уже настроен. Если статика
отдаётся шлюзом напрямую — добавить `types { application/javascript mjs; }`.

**Е6. После обновления у части пользователей старый интерфейс или белый экран.**
Закэширован `index.html`. У frontend он с `Cache-Control: no-cache` — проверить, что промежуточный
прокси не кэширует; пользователю — обновить страницу с Ctrl+F5.

### Ж. Эксплуатация после запуска

**Ж1. Заканчивается место на диске.**
`df -h`, `docker system df`, `sudo du -xh --max-depth=2 /data/docker | sort -h | tail`.
Частые причины: старые образы после обновлений (`docker image prune` — кроме образов текущей и
предыдущей версии), кэш сборки (`docker builder prune`), снапшоты Qdrant и дампы на том же диске
(бэкапы — только на отдельный том), рост логов без ротации (проверить `log-opts`). Алерт на 85% —
в доводке (§16.6).

**Ж2. Модель «зависла»: не отвечает, healthcheck красный.**
Перезапустить только её: `docker compose … restart llm-chat` — приложение не трогается, у пользователей
текущие ответы прервутся с сообщением об ошибке. Логи модели и `dmesg` (Xid — А7). Монитор моделей
создаёт инцидент после `monitoring.model_health_failures` неудачных проверок подряд.

**Ж3. В часы пик ответы начинаются с задержкой.**
Очередь в vLLM: `curl …/metrics` у модели (`num_requests_waiting`). Сначала лимит одновременных
генераций на пользователя («Лимиты»), затем `--max-num-seqs`, затем шаги §3.5 SPEC.

**Ж4. Поиск по базам знаний находит не то или «не нашёл».**
Подобрать порог реранкера на реальных вопросах: `make eval-rag KB=<коды> QUESTIONS=<файл>`,
результат — в админку «Базы знаний» → «Параметры поиска» (действует без перезапуска). Проверить
статусы документов (ошибки разбора) и права: база доступна роли пользователя.

**Ж5. Уволенный сотрудник ещё может войти.**
Синхронизация с AD раз в `ldap.sync_interval_minutes` (60). Срочно — отключить в AD и запустить
синхронизацию вручную (✅):

```bash
docker compose -f docker-compose.yml -f compose.prod.yml exec api python -m app.cli ad sync
```

**Ж6. После перезагрузки сервера приложение работает, а модели — ещё нет.**
Все сервисы с `restart: unless-stopped` поднимаются сами, но модели грузятся минуты. Пока они не
готовы, в чате «Модель недоступна» и инциденты монитора. Перезагрузки — в нерабочее время; после —
проверить раздел «Модели» в админке.

**Ж7. Бэкап не снялся.**
`/var/log/ai-assistant-backup.log`; частые причины — нет места на диске бэкапов, диск не
смонтирован после перезагрузки (запись пошла на системный диск!), Qdrant не может записать снапшот
(`permission denied` → `chown` каталога снапшотов на пользователя процесса Qdrant:
`docker compose … exec qdrant id`). Диск бэкапов — в `/etc/fstab` с `nofail` и проверкой
`mountpoint -q /backup` в начале скрипта.

**Ж8. Нужно срочно отключить функцию.**
Инструменты — админка «Инструменты» (например, `run_sql_query`); сценарии — «Сценарии»; модерация
guard — `moderation.guard_enabled`. Изменения в админке действуют без перезапуска.
