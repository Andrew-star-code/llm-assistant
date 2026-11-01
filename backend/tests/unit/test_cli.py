from __future__ import annotations

import pytest

from app.cli.__main__ import main
from app.cli.config_docs import render


def test_config_check_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["config", "check"]) == 0
    assert "Конфигурация корректна" in capsys.readouterr().out


def test_config_check_reports_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("APP_LDAP__URLS", "[]")
    assert main(["config", "check"]) == 1
    assert "ldap.urls: не задан ни один контроллер домена" in capsys.readouterr().err


def test_config_docs_cover_all_sections() -> None:
    text = render()
    for path in (
        "`auth.bruteforce.per_login.max_failures`",
        "`ldap.urls`",
        "`models.<роль>.base_url`",
    ):
        assert path in text
    assert "| `auth.bruteforce.per_ip.max_failures` | int | 20 |" in text
