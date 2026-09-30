from pathlib import Path

import pytest

from app.collectors.registry import resolve_sources_config_path
from app.core.config import get_settings


def test_resolve_uses_configured_path_when_present(tmp_path: Path):
    cfg = tmp_path / "sources.yaml"
    cfg.write_text("sources: []\n", encoding="utf-8")
    start = tmp_path / "deep" / "nested" / "file.py"
    start.parent.mkdir(parents=True)
    start.write_text("", encoding="utf-8")

    assert resolve_sources_config_path(str(cfg), start=start) == cfg


def test_resolve_walks_parents_on_shallow_docker_layout(tmp_path: Path):
    """Docker layout is /app/app/collectors/... — parents[4] does not exist."""
    collectors = tmp_path / "app" / "app" / "collectors"
    collectors.mkdir(parents=True)
    start = collectors / "registry.py"
    start.write_text("", encoding="utf-8")

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    cfg = cfg_dir / "sources.yaml"
    cfg.write_text("sources: []\n", encoding="utf-8")

    missing = tmp_path / "not-mounted" / "sources.yaml"
    assert resolve_sources_config_path(str(missing), start=start) == cfg


def test_resolve_missing_raises_file_not_found_not_index_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    collectors = tmp_path / "app" / "app" / "collectors"
    collectors.mkdir(parents=True)
    start = collectors / "registry.py"
    start.write_text("", encoding="utf-8")
    missing = tmp_path / "missing.yaml"

    # Ignore host/container /config so this test only sees the temp tree.
    real_exists = Path.exists
    root = tmp_path.resolve()

    def exists_scoped(self: Path) -> bool:
        try:
            self.resolve().relative_to(root)
        except ValueError:
            return False
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", exists_scoped)

    with pytest.raises(FileNotFoundError):
        resolve_sources_config_path(str(missing), start=start)


def test_load_sources_config_clears_settings_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cfg = tmp_path / "sources.yaml"
    cfg.write_text(
        "sources:\n  - id: demo\n    enabled: true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SOURCES_CONFIG_PATH", str(cfg))
    get_settings.cache_clear()
    from app.collectors.registry import load_sources_config

    sources = load_sources_config()
    assert sources[0]["id"] == "demo"
    get_settings.cache_clear()
