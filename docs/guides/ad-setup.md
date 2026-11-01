# Настройка подключения к Active Directory

Вход — по доменному логину и паролю через LDAPS (636) или LDAP + StartTLS (§6). Всё, что зависит
от конкретного AD, — в `config/app.yaml` (секция `ldap`) и проверяется одной командой.

## 1. Что запросить у администраторов домена

- Адреса контроллеров домена (FQDN, как в их сертификатах) и порт LDAPS.
- Сертификат корпоративного CA (PEM), которым подписаны сертификаты контроллеров.
- Сервисную учётку **только на чтение**, например `CN=svc-ai-assistant,OU=Service Accounts,DC=corp,DC=local`.
- Base DN, UPN-суффикс (`corp.local`), NetBIOS-имя домена (`CORP`).
- Порог блокировки учёток в политике AD — наш порог `auth.bruteforce.per_login.max_failures` (5)
  должен быть **ниже**.
- По желанию: группу доступа (`access_group`) и группы для ролей (`group_roles`).

## 2. Секреты

```bash
install -m 600 /dev/null /run/secrets/ldap_bind_password
```

Пароль сервисной учётки — в файл `ldap.bind_password_file`, CA — в `ldap.ca_cert_file`
(в compose — Docker secrets). В YAML и git секретов нет.

## 3. Конфигурация

```yaml
ldap:
  urls: ["ldaps://dc1.corp.local:636", "ldaps://dc2.corp.local:636"]  # по порядку
  ca_cert_file: /run/secrets/corp_ca.pem
  bind_dn: "CN=svc-ai-assistant,OU=Service Accounts,DC=corp,DC=local"
  bind_password_file: /run/secrets/ldap_bind_password
  base_dn: "DC=corp,DC=local"
  upn_suffix: "corp.local"
  netbios_domain: "CORP"
  access_group: ""          # DN группы; пусто — пускать всех включённых пользователей домена
  department_roles:
    auto: true              # роль «Отдел: <department>» для каждого отдела
    rules:
      - {attribute: department, equals: "Юридический отдел", roles: [legal]}
auth:
  bootstrap_admins: [ivanov]
```

Все параметры — [reference/config.md](../reference/config.md). Атрибуты берутся по маппингу
`ldap.attributes` (например, если отдел хранится не в `department`, поменяйте маппинг).

## 4. Проверка

```bash
docker compose exec api python -m app.cli ad check --user ivanov
```

Команда показывает доступность и TLS каждого контроллера, bind сервисной учёткой, найденную запись,
атрибуты, ФИО и форму обращения, отдел, вычисленные роли и итог «вход возможен / невозможен».
Проверка пароля конкретного пользователя — отдельно:

```bash
docker compose exec api python -m app.cli ad check --user ivanov --password-prompt
```

То же без проверки пароля — в админке: «Диагностика AD».

## 4а. Роли сотрудников

Если атрибут `department` в AD не заполнен (так у заказчика, решение 57 в `docs/status.md`), роли
назначают вручную: админка → «Роли» → «Новая роль» (например, `legal` «Юристы») → «Добавить
сотрудников списком» — логины или e-mail по одному в строке или столбцом из Excel. Кто ещё ни разу
не входил, будет найден в AD и заведён; не найденные останутся в поле для исправления. Ручные роли
синхронизация с AD не снимает.

## 5. Первые администраторы

Логины в `auth.bootstrap_admins` получают роль `superadmin` при входе. Или командой:

```bash
docker compose exec api python -m app.cli create-admin --login ivanov
```

## Частые проблемы

| Симптом в `ad check` | Причина |
| --- | --- |
| Контроллер `ERR`, `certificate verify failed` | Не тот CA или адрес не совпадает с именем в сертификате |
| `Bind сервисной учёткой: ERR — bad_credentials` | Неверный пароль в `bind_password_file` |
| Пользователь не найден | Не тот `base_dn` или `user_filter` |
| `В группе доступа: НЕТ` | Пользователь не входит в `access_group` (вложенность учитывается при `nested_groups: true`) |
| Нет отчества | `middleName` пуст и `displayName` не совпал с шаблоном `display_name_pattern` |

В журнале входов (админка → «Входы») — точная причина каждого отказа: `bad_credentials`,
`ad_disabled`, `ad_locked`, `password_expired`, `not_in_access_group`, `locked_login`, `ad_unavailable`.

## Добавить поле профиля из AD

1. Имя атрибута — в `LdapAttributes` (`backend/app/core/config.py`) и в `config/app.yaml`.
2. Поле в `DirectoryUser` и чтение в `providers/ldap.py::_to_user`.
3. Колонка в `modules/users/models.py` + миграция Alembic, заполнение в `users/service.py`.
4. Поле в `users/schemas.py::Profile` и в `frontend/src/features/profile/`; `make gen-api`, `make docs-db`.
