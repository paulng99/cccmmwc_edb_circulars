from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.core.config import get_settings


def load_sources_config() -> list[dict[str, Any]]:
    path = Path(get_settings().sources_config_path)
    if not path.exists():
        # fallback for local non-docker runs
        alt = Path(__file__).resolve().parents[4] / "config" / "sources.yaml"
        path = alt if alt.exists() else path
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return list(data.get("sources") or [])


def get_enabled_sources() -> list[dict[str, Any]]:
    return [s for s in load_sources_config() if s.get("enabled")]
