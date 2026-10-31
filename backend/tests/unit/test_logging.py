from __future__ import annotations

from app.core.logging import REDACTED, redact_secrets


def test_sensitive_keys_are_redacted() -> None:
    event = {
        "event": "login",
        "login": "ivanov",
        "password": "P@ssw0rd",
        "headers": {"Authorization": "Bearer x", "Accept": "*/*"},
        "items": [{"token": "t"}],
    }
    result = redact_secrets(None, "info", event)
    assert result["login"] == "ivanov"
    assert result["password"] == REDACTED
    assert result["headers"] == {"Authorization": REDACTED, "Accept": "*/*"}
    assert result["items"] == [{"token": REDACTED}]
