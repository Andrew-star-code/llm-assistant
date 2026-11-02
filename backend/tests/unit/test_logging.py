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


def test_captured_lines_have_no_ansi_colors() -> None:
    import logging

    from app.core import log_capture
    from app.core.config import LoggingSettings
    from app.core.logging import configure_logging

    configure_logging(LoggingSettings(level="INFO", format="console"))
    try:
        buffer = log_capture.start_request()
        logging.getLogger("app.test").info("demo.event")
        [line] = [line for line in log_capture.request_lines(buffer) if "demo.event" in line]
        assert "\x1b[" not in line and "info" in line
    finally:
        configure_logging(LoggingSettings())
