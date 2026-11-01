from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Rule:
    label: str
    pattern: str
    weight: float
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Config:
    output_root: Path
    mount_root: Path
    require_mount: bool
    state_dir: Path
    timezone: str
    categories: tuple[str, ...]
    category_weights: dict[str, float]
    rules: tuple[Rule, ...]
    index_threshold: float
    download_threshold: float
    request_interval_seconds: float
    request_timeout_seconds: float
    request_retries: int
    user_agent: str
    author_overrides: dict[str, str]
    api_backfill_days: int = 7
    api_page_size: int = 100
    api_max_results_per_category: int = 500


def _expand_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def load_config(path: Path) -> Config:
    with path.open("rb") as stream:
        data: dict[str, Any] = tomllib.load(stream)

    general = data.get("general", {})
    output_root = os.getenv("ARXIV_SCRAPER_OUTPUT_ROOT", general["output_root"])
    state_dir = os.getenv("ARXIV_SCRAPER_STATE_DIR", general["state_dir"])

    rules = tuple(
        Rule(
            label=str(item.get("label", item["pattern"])),
            pattern=str(item["pattern"]),
            weight=float(item["weight"]),
            fields=tuple(item.get("fields", ["title", "abstract"])),
        )
        for item in data.get("rules", [])
    )

    return Config(
        output_root=_expand_path(output_root),
        mount_root=_expand_path(
            general.get("mount_root", str(Path.home() / "gdrive"))
        ),
        require_mount=bool(general.get("require_mount", True)),
        state_dir=_expand_path(state_dir),
        timezone=str(general.get("timezone", "Asia/Taipei")),
        categories=tuple(data.get("sources", {}).get("categories", [])),
        category_weights={
            str(key): float(value)
            for key, value in data.get("category_weights", {}).items()
        },
        rules=rules,
        index_threshold=float(general.get("index_threshold", 2.0)),
        download_threshold=float(general.get("download_threshold", 7.0)),
        request_interval_seconds=float(general.get("request_interval_seconds", 3.0)),
        request_timeout_seconds=float(general.get("request_timeout_seconds", 60.0)),
        request_retries=int(general.get("request_retries", 3)),
        user_agent=str(general.get("user_agent", "personal-research-arxiv-scraper/0.1")),
        author_overrides={
            str(key): str(value)
            for key, value in data.get("author_overrides", {}).items()
        },
        api_backfill_days=int(general.get("api_backfill_days", 7)),
        api_page_size=int(general.get("api_page_size", 100)),
        api_max_results_per_category=int(
            general.get("api_max_results_per_category", 500)
        ),
    )
