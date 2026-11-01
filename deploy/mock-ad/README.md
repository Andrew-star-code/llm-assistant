# deploy/mock-ad

Samba AD DC для разработки и тестов без доступа к настоящему AD (§6.7). **Не для прода.**

- Домен `CORP.LOCAL` (NetBIOS `CORP`), контроллер `dc1.corp.local`, LDAP 389 и LDAPS 636.
- Свой CA выпускается при первом старте; `ca.pem` выкладывается в том `mock-ad-export`
  (в api смонтирован как `/run/mock-ad/ca.pem`).
- Политика блокировки AD — 10 неудачных попыток; наш порог (5) ниже, как требует §6.2.
- Данные живут в томах `mock-ad-samba` и `mock-ad-etc`; пересоздать домен — `make dev-reset`.
- Контейнеру нужен `cap_add: SYS_ADMIN`: Samba пишет NT ACL в xattr `security.*`.

Пароль всех тестовых пользователей — `MOCK_AD_USER_PASSWORD` (по умолчанию `Passw0rd!`).
Сервисная учётка — `CN=svc-ai-assistant,OU=Service Accounts,DC=corp,DC=local`, пароль — `LDAP_BIND_PASSWORD`.

| Логин | ФИО | Должность | department | Руководитель | Особенности |
| --- | --- | --- | --- | --- | --- |
| `ivanov` | Иванов Иван Петрович | Руководитель ИТ-отдела | ИТ-отдел | — | в `bootstrap_admins` дев-конфига; только в `AI-Admins` (вложена в `AI-Assistant-Users`) |
| `kim` | Ким Александр | Инженер технической поддержки | ИТ-отдел | ivanov | **без отчества** |
| `smirnova` | Смирнова Анна Викторовна | Главный бухгалтер | Бухгалтерия | — | |
| `petrov` | Петров Сергей Алексеевич | Бухгалтер | Бухгалтерия | smirnova | без мобильного |
| `sidorova` | Сидорова Елена Николаевна | Юрисконсульт | Юридический отдел | — | роль `legal` по правилу |
| `kuznetsov` | Кузнецов Дмитрий Олегович | Менеджер по продажам | Отдел продаж | — | **отключён** |
| `volkov` | Волков Павел Игоревич | Менеджер по закупкам | Отдел закупок | — | **не в группах** — не входит при заданной `access_group` |

У всех, кроме `kuznetsov` и `volkov`, есть фото (`thumbnailPhoto`, `seed/photos/`).
Группы: `CN=AI-Assistant-Users,CN=Users,DC=corp,DC=local`, `CN=AI-Admins,CN=Users,DC=corp,DC=local`.

Проверка вручную (нужен `ldap-utils`):

```bash
docker compose -f deploy/compose/docker-compose.yml -f deploy/compose/compose.dev.yml --env-file deploy/compose/.env exec mock-ad \
  env LDAPTLS_CACERT=/export/ca.pem ldapsearch -LLL -H ldaps://dc1.corp.local -D ivanov@corp.local -w 'Passw0rd!' \
  -b DC=corp,DC=local '(sAMAccountName=kim)' displayName department title manager
```
