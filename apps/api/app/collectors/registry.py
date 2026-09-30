from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.core.config import get_settings


def resolve_sources_config_path(configured: str, *, start: Path | None = None) -> Path:
    """Resolve sources.yaml for Docker (/config/...) and local checkout layouts.

    Docker copies code under /app/app/... so Path.parents[4] does not exist.
    Walk ancestors instead of using a fixed parent index.
    """
    path = Path(configured)
    if path.exists():
        return path

    here = (start or Path(__file__)).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "sources.yaml"
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        f"sources config not found at {path} "
        f"(also searched ancestors of {here} for config/sources.yaml)"
    )


def load_sources_config() -> list[dict[str, Any]]:
    path = resolve_sources_config_path(get_settings().sources_config_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return list(data.get("sources") or [])


def get_enabled_sources() -> list[dict[str, Any]]:
    return [s for s in load_sources_config() if s.get("enabled")]
