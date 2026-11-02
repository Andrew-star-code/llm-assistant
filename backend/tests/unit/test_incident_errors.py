"""Отпечаток system_error: числа, id и адреса не плодят новые инциденты; место в коде — плодит."""

from __future__ import annotations

from app.modules.incidents.errors import fingerprint, location, normalize


def _raise(message: str) -> BaseException:
    try:
        raise ValueError(message)
    except ValueError as exc:
        return exc


def test_same_error_with_different_numbers_has_same_fingerprint() -> None:
    a = _raise("заказ 101 для 3f2b1c9e-1d2c-4b5a-9c8d-112233445566 не найден")
    b = _raise("заказ 9 для 00000000-0000-0000-0000-000000000000 не найден")
    assert fingerprint(a) == fingerprint(b)
    assert normalize("адрес 0xdeadbeef, попытка 7") == "адрес #, попытка #"


def test_different_place_or_type_gives_different_fingerprint() -> None:
    a = _raise("x")
    try:
        raise KeyError("x")
    except KeyError as exc:
        b = exc
    assert fingerprint(a) != fingerprint(b)
    assert "test_incident_errors.py" in location(a)
