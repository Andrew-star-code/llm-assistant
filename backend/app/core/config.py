"""Конфигурация приложения.

Источники (по убыванию приоритета):
1. аргументы конструктора (тесты);
2. переменные окружения с префиксом ``APP_`` (вложенность через ``__``: ``APP_AUTH__PROVIDERS``);
3. файлы секретов в ``/run/secrets`` (имя файла = имя переменной в нижнем регистре);
4. YAML из ``config/``: ``app.yaml`` и ``models.yaml``, поверх них — ``app.<env>.yaml``
   и ``models.<env>.yaml``, если такие есть.

Конфиг валидируется при старте; при ошибке сервис не запускается и печатает понятное
сообщение (§16.4 SPEC). Секреты — только из окружения и файлов секретов, никогда из YAML в git.
Справочник параметров генерируется в ``docs/reference/config.md`` (``make docs-config``).
"""

from __future__ import annotations

import os
import sys
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SecretsSettingsSource,
    SettingsConfigDict,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"
SECRETS_DIR = Path("/run/secrets")
YAML_LAYERS = ("app", "models")


class AppEnv(StrEnum):
    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class _Section(BaseModel):
    """Базовый класс секций: опечатка в имени параметра — ошибка, а не тихое игнорирование."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- логи


class LoggingSettings(_Section):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        "INFO", description="Минимальный уровень логов."
    )
    format: Literal["json", "console"] = Field(
        "json", description="json — для прода (stdout → сборщик логов), console — для разработки."
    )


# --------------------------------------------------------------------------- вход (§6)


class SessionSettings(_Section):
    idle_timeout_minutes: int = Field(480, gt=0, description="Тайм-аут простоя сессии, минут.")
    absolute_timeout_hours: int = Field(168, gt=0, description="Абсолютный срок жизни сессии, ч.")


class BruteforceRule(_Section):
    max_failures: int = Field(gt=0, description="Сколько неудачных попыток допускается в окне.")
    window_minutes: int = Field(gt=0, description="Окно подсчёта, минут.")
    lock_minutes: int = Field(gt=0, description="Длительность блокировки, минут.")


class BruteforceSettings(_Section):
    per_login: BruteforceRule = Field(
        default_factory=lambda: BruteforceRule(max_failures=5, window_minutes=15, lock_minutes=15),
        description="Порог по логину. Должен быть ниже политики блокировки AD (§6.2).",
    )
    per_ip: BruteforceRule = Field(
        default_factory=lambda: BruteforceRule(max_failures=20, window_minutes=15, lock_minutes=60),
        description="Порог по IP-адресу.",
    )


class AuthSettings(_Section):
    providers: list[Literal["ldap", "dev"]] = Field(
        default_factory=lambda: list[Literal["ldap", "dev"]](["ldap"]),
        min_length=1,
        description="Провайдеры входа: ldap | dev. dev запрещён при APP_ENV=prod.",
    )
    bootstrap_admins: list[str] = Field(
        default_factory=list, description="Логины первых superadmin; остальные роли — в админке."
    )
    session: SessionSettings = Field(default_factory=SessionSettings)
    bruteforce: BruteforceSettings = Field(default_factory=BruteforceSettings)


class LdapAttributes(_Section):
    guid: str = "objectGUID"
    login: str = "sAMAccountName"
    email: str = "mail"
    display_name: str = "displayName"
    last_name: str = "sn"
    first_name: str = "givenName"
    middle_name: str = Field("middleName", description="Если пусто — из display_name по шаблону.")
    display_name_pattern: str = "{last} {first} {middle}"
    title: str = "title"
    department: str = "department"
    company: str = "company"
    office: str = "physicalDeliveryOfficeName"
    phone: str = "telephoneNumber"
    mobile: str = "mobile"
    manager: str = "manager"
    employee_id: str = "employeeID"
    photo: str = "thumbnailPhoto"


class AttributeRoleRule(_Section):
    attribute: str = Field(description="Атрибут AD (по ключу маппинга attributes).")
    equals: str | None = None
    contains: str | None = None
    roles: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _one_condition(self) -> Self:
        if (self.equals is None) == (self.contains is None):
            raise ValueError("правило роли: задайте ровно одно условие — equals или contains")
        return self


class DepartmentRoles(_Section):
    auto: bool = Field(
        True, description="Создавать роль «Отдел: <название>» из атрибута department."
    )
    rules: list[AttributeRoleRule] = Field(
        default_factory=list, description="Дополнительные роли по значениям атрибутов."
    )


class GroupRole(_Section):
    group_dn: str
    roles: list[str] = Field(min_length=1)


class LdapSettings(_Section):
    urls: list[str] = Field(
        default_factory=list, description="Контроллеры домена по порядку: ldaps://host:636."
    )
    start_tls: bool = Field(False, description="LDAP (389) + StartTLS вместо LDAPS.")
    ca_cert_file: Path | None = Field(None, description="Сертификат корпоративного CA.")
    bind_dn: str = Field("", description="DN сервисной учётки (только чтение).")
    bind_password_file: Path | None = Field(None, description="Файл с паролем сервисной учётки.")
    base_dn: str = ""
    user_filter: str = "(&(objectCategory=person)(objectClass=user)(sAMAccountName={username}))"
    upn_suffix: str = ""
    netbios_domain: str = ""
    access_group: str = Field("", description="DN группы доступа; пусто — пускать всех включённых.")
    nested_groups: bool = True
    attributes: LdapAttributes = Field(default_factory=LdapAttributes)
    department_roles: DepartmentRoles = Field(default_factory=DepartmentRoles)
    group_roles: list[GroupRole] = Field(default_factory=list)
    sync_interval_minutes: int = Field(60, gt=0)

    @model_validator(mode="after")
    def _check_urls(self) -> Self:
        bad = [u for u in self.urls if not u.startswith(("ldaps://", "ldap://"))]
        if bad:
            raise ValueError(f"ldap.urls: ожидается ldaps://… или ldap://…, получено {bad}")
        plain = [u for u in self.urls if u.startswith("ldap://")]
        if plain and not self.start_tls:
            raise ValueError(
                "ldap.urls: адрес ldap:// без шифрования допустим только с ldap.start_tls: true"
            )
        return self


# --------------------------------------------------------------------------- модели (§8.2)


class SamplingParams(_Section):
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    min_p: float | None = None
    presence_penalty: float | None = None
    repetition_penalty: float | None = None


class Sampling(_Section):
    thinking: SamplingParams = Field(default_factory=SamplingParams)
    default: SamplingParams = Field(default_factory=SamplingParams)


class ThinkingConfig(_Section):
    mode: Literal["chat_template_kwarg", "reasoning_effort", "separate_model", "none"] = Field(
        "none", description="Как включается режим размышлений."
    )
    kwarg: str = Field("enable_thinking", description="Имя флага в chat_template_kwargs.")
    default: bool = Field(False, description="Включён ли thinking по умолчанию.")
    effort: Literal["low", "medium", "high"] | None = Field(
        None, description="Уровень для mode=reasoning_effort."
    )
    model_role: str | None = Field(None, description="Роль модели для mode=separate_model.")

    @model_validator(mode="after")
    def _check_mode(self) -> Self:
        if self.mode == "separate_model" and not self.model_role:
            raise ValueError("thinking.model_role обязателен при mode=separate_model")
        return self


class ModelEndpoint(_Section):
    base_url: str = Field(
        description="OpenAI-совместимый эндпоинт, например http://llm-chat:8000/v1"
    )
    model: str = Field(description="Имя модели на эндпоинте.")
    api_key: SecretStr | None = Field(
        None, description="Ключ эндпоинта (vLLM --api-key), если есть."
    )
    context_length: int | None = Field(
        None, gt=0, description="Сколько контекста реально отдаём, а не максимум модели."
    )
    max_output_tokens: int | None = Field(None, gt=0)
    supports_tools: bool = False
    thinking: ThinkingConfig = Field(default_factory=ThinkingConfig)
    reasoning_history: Literal["model_default", "drop", "keep"] = "model_default"
    sampling: Sampling = Field(default_factory=Sampling)
    dim: int | None = Field(None, gt=0, description="Размерность векторов (для embed).")
    timeout_s: float = Field(600, gt=0, description="Тайм-аут запроса к модели, с.")


REQUIRED_MODEL_ROLES = ("chat", "utility", "embed", "rerank")


# --------------------------------------------------------------------------- корень


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_nested_delimiter="__",
        extra="forbid",
        validate_default=True,
    )

    env: AppEnv = Field(AppEnv.DEV, description="Окружение: dev | test | prod.")
    app_name: str = Field("ИИ-ассистент", description="Название в интерфейсе и логах.")
    config_dir: Path = Field(DEFAULT_CONFIG_DIR, description="Каталог с YAML-конфигами.")

    database_url: SecretStr = Field(
        SecretStr("postgresql+asyncpg://assistant:assistant@localhost:5432/assistant"),
        description="DSN PostgreSQL (секрет: из окружения или /run/secrets/app_database_url).",
    )
    redis_url: SecretStr = Field(SecretStr("redis://localhost:6379/0"), description="DSN Redis.")
    qdrant_url: str = Field("http://localhost:6333", description="HTTP-адрес Qdrant.")
    qdrant_api_key: SecretStr | None = Field(None, description="API-ключ Qdrant (секрет).")
    readiness_timeout_s: float = Field(2.0, gt=0, description="Тайм-аут каждой проверки /ready, с.")

    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    ldap: LdapSettings = Field(default_factory=LdapSettings)
    models: dict[str, ModelEndpoint] = Field(
        default_factory=dict, description="Реестр моделей по ролям (config/models.yaml)."
    )

    @model_validator(mode="after")
    def _cross_checks(self) -> Self:
        errors: list[str] = []
        if self.env == AppEnv.PROD and "dev" in self.auth.providers:
            errors.append("auth.providers: провайдер dev запрещён при APP_ENV=prod")
        if "ldap" in self.auth.providers and not self.ldap.urls:
            errors.append("ldap.urls: не задан ни один контроллер домена")
        missing = [r for r in REQUIRED_MODEL_ROLES if r not in self.models]
        if missing:
            errors.append(f"models: не описаны обязательные роли {missing}")
        for role, m in self.models.items():
            target = m.thinking.model_role
            if m.thinking.mode == "separate_model" and target not in self.models:
                errors.append(f"models.{role}.thinking.model_role: роль {target!r} не описана")
        if errors:
            raise ValueError("; ".join(errors))
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings]
        if SECRETS_DIR.is_dir():
            sources.append(SecretsSettingsSource(settings_cls, secrets_dir=SECRETS_DIR))
        sources.append(LayeredYamlSource(settings_cls))
        return tuple(sources)


# --------------------------------------------------------------------------- YAML


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Рекурсивно сливает словари; списки и скаляры из override заменяют значения base."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_yaml_layers(config_dir: Path, env: str) -> dict[str, Any]:
    """Читает app.yaml, models.yaml и их оверлеи для окружения."""
    merged: dict[str, Any] = {}
    for layer in YAML_LAYERS:
        for name in (f"{layer}.yaml", f"{layer}.{env}.yaml"):
            path = config_dir / name
            if not path.is_file():
                continue
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                raise ValueError(f"{path}: ожидается YAML-словарь на верхнем уровне")
            merged = deep_merge(merged, data)
    return merged


class LayeredYamlSource(PydanticBaseSettingsSource):
    """Источник настроек из YAML. Каталог и окружение берутся из APP_CONFIG_DIR и APP_ENV."""

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls)
        config_dir = Path(os.environ.get("APP_CONFIG_DIR", DEFAULT_CONFIG_DIR))
        env = os.environ.get("APP_ENV", AppEnv.DEV.value)
        self._data = load_yaml_layers(config_dir, env)

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        return self._data.get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        return {k: v for k, v in self._data.items() if k in self.settings_cls.model_fields}


# --------------------------------------------------------------------------- загрузка


class ConfigError(Exception):
    """Конфигурация невалидна; текст уже пригоден для показа человеку."""


def format_validation_error(exc: ValidationError) -> str:
    lines = ["Ошибка конфигурации:"]
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"])
        msg = str(err["msg"]).removeprefix("Value error, ")
        for part in msg.split("; "):
            lines.append(f"  - {loc}: {part}" if loc else f"  - {part}")
    return "\n".join(lines)


def load_settings(**overrides: Any) -> Settings:
    """Загружает и валидирует настройки; при ошибке бросает ConfigError с понятным текстом."""
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        raise ConfigError(format_validation_error(exc)) from exc
    except (ValueError, yaml.YAMLError) as exc:
        raise ConfigError(f"Ошибка конфигурации: {exc}") from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Настройки процесса. При ошибке печатает её и завершает процесс с кодом 1."""
    try:
        return load_settings()
    except ConfigError as exc:
        print(exc, file=sys.stderr)  # логирование ещё не настроено
        raise SystemExit(1) from exc
