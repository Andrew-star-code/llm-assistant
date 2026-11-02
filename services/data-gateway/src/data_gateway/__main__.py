"""``python -m data_gateway`` — запуск шлюза (uvicorn, порт ``DG_PORT``, 8090);
``python -m data_gateway check`` — самопроверка образа (каталог, драйверы, подключения)."""

from __future__ import annotations

import logging
import os
import sys

import uvicorn

from data_gateway.app import create_app


def main() -> None:
    if sys.argv[1:] == ["check"]:
        from data_gateway.check import main as check

        raise SystemExit(check())
    logging.basicConfig(level=os.environ.get("DG_LOG_LEVEL", "INFO"), format="%(message)s")
    uvicorn.run(
        create_app(),
        host=os.environ.get("DG_HOST", "0.0.0.0"),  # noqa: S104 — во внутренней сети Docker
        port=int(os.environ.get("DG_PORT", "8090")),
        access_log=False,
    )


if __name__ == "__main__":
    main()
