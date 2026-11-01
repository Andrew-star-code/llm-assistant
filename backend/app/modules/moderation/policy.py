"""Политика модерации из ``config/moderation/policy.yaml`` (§9.6); перечитывается при изменении."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class Category(BaseModel):
    code: str
    name: str
    description: str = ""


class Policy(BaseModel):
    categories: list[Category] = Field(min_length=1)
    severities: list[str] = Field(default_factory=lambda: ["low", "medium", "high", "critical"])
    refusal: str = "Извините, с этим запросом я помочь не могу."
    self_harm_help: str = ""
    guard_categories: list[str] = Field(default_factory=list)

    def category(self, code: str) -> Category | None:
        return next((c for c in self.categories if c.code == code), None)


@dataclass
class _Cached:
    mtime: float
    policy: Policy


_cache: dict[Path, _Cached] = {}


def load_policy(config_dir: Path) -> Policy:
    path = config_dir / "moderation" / "policy.yaml"
    mtime = path.stat().st_mtime
    cached = _cache.get(path)
    if cached is None or cached.mtime != mtime:
        data = yaml.safe_load(path.read_text("utf-8")) or {}
        cached = _Cached(mtime, Policy.model_validate(data))
        _cache[path] = cached
    return cached.policy
