"""Командная строка: ``python -m app.cli <команда>``.

Команды этапа 0:
  config check        — загрузить и проверить конфиг, вывести сводку без секретов
  config docs [-o F]  — сгенерировать справочник конфигурации (docs/reference/config.md)
  openapi [-o F]      — выгрузить схему OpenAPI (для генерации клиента фронтенда)
  api-docs [-o F]     — сгенерировать справочник API (docs/reference/api.md)
  db-docs [-o F]      — сгенерировать схему БД (docs/reference/db-schema.md)

Этап 1:
  ad check --user L [--password-prompt] [--json] — диагностика AD для пользователя (§6.7)
  ad sync                                        — синхронизировать пользователей с AD
  create-admin --login L                         — выдать роль superadmin

Дальше появятся (§10.3): ``kb import``, ``purge``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.core.config import ConfigError, Settings, load_settings


def _write(text: str, output: str | None) -> None:
    if output:
        Path(output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def cmd_config_check(_: argparse.Namespace) -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Конфигурация корректна (env={settings.env.value}, каталог {settings.config_dir})")
    print(f"  Провайдеры входа: {', '.join(settings.auth.providers)}")
    print(f"  Контроллеры AD:   {', '.join(settings.ldap.urls) or '—'}")
    print("  Модели:")
    for role, model in sorted(settings.models.items()):
        print(f"    {role:<8} {model.model} @ {model.base_url} (thinking: {model.thinking.mode})")
    return 0


def cmd_config_docs(args: argparse.Namespace) -> int:
    from app.cli.config_docs import render

    _write(render(), args.output)
    return 0


def cmd_openapi(args: argparse.Namespace) -> int:
    from app.cli.api_docs import build_openapi, dump_openapi

    _write(dump_openapi(build_openapi()), args.output)
    return 0


def cmd_api_docs(args: argparse.Namespace) -> int:
    from app.cli.api_docs import build_openapi, render

    _write(render(build_openapi()), args.output)
    return 0


def cmd_db_docs(args: argparse.Namespace) -> int:
    from app.cli.db_docs import render

    _write(render(), args.output)
    return 0


def _settings_or_exit() -> Settings | None:
    try:
        return load_settings()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return None


def cmd_ad(args: argparse.Namespace) -> int:
    from app.cli import ad

    settings = _settings_or_exit()
    if settings is None:
        return 1
    if args.ad_command == "check":
        return ad.cmd_ad_check(settings, args.user, args.password_prompt, args.json)
    return ad.cmd_ad_sync(settings)


def cmd_create_admin(args: argparse.Namespace) -> int:
    from app.cli import ad

    settings = _settings_or_exit()
    return 1 if settings is None else ad.cmd_create_admin(settings, args.login)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    config = sub.add_parser("config", help="Работа с конфигурацией")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    config_sub.add_parser("check", help="Проверить конфиг").set_defaults(func=cmd_config_check)
    docs = config_sub.add_parser("docs", help="Сгенерировать справочник конфигурации")
    docs.add_argument("-o", "--output")
    docs.set_defaults(func=cmd_config_docs)

    openapi = sub.add_parser("openapi", help="Выгрузить схему OpenAPI")
    openapi.add_argument("-o", "--output")
    openapi.set_defaults(func=cmd_openapi)

    api_docs = sub.add_parser("api-docs", help="Сгенерировать docs/reference/api.md")
    api_docs.add_argument("-o", "--output")
    api_docs.set_defaults(func=cmd_api_docs)

    db_docs = sub.add_parser("db-docs", help="Сгенерировать docs/reference/db-schema.md")
    db_docs.add_argument("-o", "--output")
    db_docs.set_defaults(func=cmd_db_docs)

    ad = sub.add_parser("ad", help="Active Directory")
    ad_sub = ad.add_subparsers(dest="ad_command", required=True)
    check = ad_sub.add_parser("check", help="Диагностика AD для пользователя")
    check.add_argument("--user", required=True, help="Логин: ivanov, CORP\\ivanov или UPN")
    check.add_argument("--password-prompt", action="store_true", help="Проверить и пароль")
    check.add_argument("--json", action="store_true", help="Вывести отчёт в JSON")
    check.set_defaults(func=cmd_ad)
    ad_sub.add_parser("sync", help="Синхронизировать пользователей с AD").set_defaults(func=cmd_ad)

    admin = sub.add_parser("create-admin", help="Выдать пользователю роль superadmin")
    admin.add_argument("--login", required=True)
    admin.set_defaults(func=cmd_create_admin)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
