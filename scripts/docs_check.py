"""make docs-check (§17.4): документация не отстаёт от кода.

Проверяет:
1. у каждого модуля backend/app/modules/* есть README.md;
2. docs/reference/config.md совпадает со сгенерированным из настроек;
3. docs/reference/api.md и frontend/src/api/openapi.json совпадают с текущей схемой OpenAPI
   (иначе не запущен make gen-api и клиент фронтенда разошёлся с бэкендом);
4. относительные ссылки в Markdown (docs/, корневые *.md, README модулей) ведут на существующие
   файлы.

Запуск: uv run python scripts/docs_check.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("APP_CONFIG_DIR", str(ROOT / "config"))
os.environ["APP_ENV"] = "dev"
sys.path.insert(0, str(ROOT / "backend"))

from app.cli import api_docs, config_docs  # noqa: E402

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
SKIP_DIRS = {"node_modules", ".venv", ".git", "dist"}


def check_module_readmes() -> list[str]:
    modules = ROOT / "backend/app/modules"
    return [
        f"нет README.md у модуля {d.relative_to(ROOT)}"
        for d in sorted(modules.iterdir())
        if d.is_dir() and not d.name.startswith("__") and not (d / "README.md").is_file()
    ]


def check_generated() -> list[str]:
    schema = api_docs.build_openapi()
    expected = {
        "docs/reference/config.md": (config_docs.render(), "make docs-config"),
        "docs/reference/api.md": (api_docs.render(schema), "make gen-api"),
        "frontend/src/api/openapi.json": (api_docs.dump_openapi(schema), "make gen-api"),
    }
    errors = []
    for rel, (content, command) in expected.items():
        path = ROOT / rel
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            errors.append(f"{rel} устарел — выполните `{command}`")
    return errors


def markdown_files() -> list[Path]:
    files = list(ROOT.glob("*.md"))
    for base in (
        ROOT / "docs",
        ROOT / "backend",
        ROOT / "services",
        ROOT / "deploy",
        ROOT / "config",
        ROOT / "frontend",
        ROOT / "eval",
    ):
        if base.is_dir():
            files += [p for p in base.rglob("*.md") if not SKIP_DIRS & set(p.parts)]
    return files


def check_links() -> list[str]:
    errors = []
    for md in markdown_files():
        text = md.read_text(encoding="utf-8")
        # Ссылки внутри блоков кода не проверяем.
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        for raw in LINK.findall(text):
            target = raw.removeprefix("<")
            if re.match(r"^[a-z]+:", target) or target.startswith("#"):
                continue
            path = target.split("#", 1)[0]
            if path and not (md.parent / path).exists():
                errors.append(f"{md.relative_to(ROOT)}: битая ссылка {target}")
    return errors


def main() -> int:
    errors = check_module_readmes() + check_generated() + check_links()
    for error in errors:
        print(f"docs-check: {error}", file=sys.stderr)
    if not errors:
        print("docs-check: OK")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
