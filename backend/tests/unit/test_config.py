from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import AppEnv, ConfigError, deep_merge, load_settings


@pytest.mark.parametrize("env", list(AppEnv))
def test_repo_config_is_valid_for_every_env(monkeypatch: pytest.MonkeyPatch, env: AppEnv) -> None:
    monkeypatch.setenv("APP_ENV", env.value)
    settings = load_settings()
    assert settings.env == env
    assert {"chat", "utility", "embed", "rerank"} <= settings.models.keys()


def test_dev_overlay_points_to_fake_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    settings = load_settings()
    assert settings.models["chat"].base_url == "http://fake-llm:8080/v1"
    # Поля, не переопределённые оверлеем, берутся из базового models.yaml.
    assert settings.models["chat"].thinking.mode == "chat_template_kwarg"
    assert settings.models["embed"].dim == 1024
    assert "dev" in settings.auth.providers
    # Логи упавшей модели в инциденте — через docker-proxy дев-стенда.
    assert settings.monitoring.docker_url == "http://docker-proxy:2375"
    assert settings.models["chat"].container == "ai-assistant-fake-llm-1"
    assert "172.16.0.0/12" in settings.trusted_proxies


def test_trusted_proxies_must_be_ip_or_network() -> None:
    with pytest.raises(ConfigError, match="trusted_proxies: 'nginx' — не IP и не подсеть"):
        load_settings(trusted_proxies=["10.0.0.1", "nginx"])


def test_dev_provider_forbidden_in_prod() -> None:
    with pytest.raises(ConfigError, match="провайдер dev запрещён при APP_ENV=prod"):
        load_settings(env=AppEnv.PROD, auth={"providers": ["dev", "ldap"]})


def test_ldap_provider_requires_controllers() -> None:
    with pytest.raises(ConfigError, match=r"ldap\.urls: не задан ни один контроллер домена"):
        load_settings(ldap={"urls": []})


def test_plain_ldap_requires_starttls() -> None:
    with pytest.raises(ConfigError, match="start_tls"):
        load_settings(ldap={"urls": ["ldap://dc1.corp.local:389"]})
    settings = load_settings(ldap={"urls": ["ldap://dc1.corp.local:389"], "start_tls": True})
    assert settings.ldap.start_tls


def test_required_model_roles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "models.yaml").write_text(
        "models:\n  chat: {base_url: 'http://x/v1', model: m}\n", encoding="utf-8"
    )
    monkeypatch.setenv("APP_CONFIG_DIR", str(tmp_path))
    with pytest.raises(ConfigError, match=r"обязательные роли \['utility', 'embed', 'rerank'\]"):
        load_settings(auth={"providers": ["dev"]})


def test_separate_model_must_reference_known_role(settings_models: dict[str, object]) -> None:
    models = dict(settings_models)
    models["chat"] = {
        "base_url": "http://x/v1",
        "model": "m",
        "thinking": {"mode": "separate_model", "model_role": "chat-thinking"},
    }
    with pytest.raises(ConfigError, match="роль 'chat-thinking' не описана"):
        load_settings(models=models)


def test_unknown_key_is_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "app.yaml").write_text("logging:\n  levl: DEBUG\n", encoding="utf-8")
    monkeypatch.setenv("APP_CONFIG_DIR", str(tmp_path))
    with pytest.raises(ConfigError, match=r"logging\.levl"):
        load_settings(auth={"providers": ["dev"]})


def test_env_overrides_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_LOGGING__LEVEL", "DEBUG")
    monkeypatch.setenv("APP_MODELS__CHAT__BASE_URL", "http://localhost:11434/v1")
    settings = load_settings()
    assert settings.logging.level == "DEBUG"
    assert settings.models["chat"].base_url == "http://localhost:11434/v1"
    assert settings.models["chat"].model == "Qwen/Qwen3.8-27B"


def test_secrets_are_not_rendered() -> None:
    settings = load_settings(database_url="postgresql+asyncpg://u:topsecret@db/x")
    assert "topsecret" not in repr(settings)
    assert "topsecret" not in settings.model_dump_json()


def test_deep_merge() -> None:
    base = {"a": {"b": 1, "c": [1, 2]}, "d": 1}
    override = {"a": {"c": [3]}, "e": 2}
    assert deep_merge(base, override) == {"a": {"b": 1, "c": [3]}, "d": 1, "e": 2}


@pytest.fixture
def settings_models() -> dict[str, object]:
    return {
        role: {"base_url": "http://x/v1", "model": role}
        for role in ("chat", "utility", "embed", "rerank")
    }
