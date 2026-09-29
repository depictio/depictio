"""Paths the server resolves at runtime must work from a wheel install, not only /app."""

from pathlib import Path

from depictio import version
from depictio.api.v1.configs.settings_models import PerformanceConfig
from depictio.api.v1.db_init_reference_datasets import (
    _PACKAGE_ROOT,
    _relocate_container_paths,
)


def test_relocate_container_paths_rewrites_nested_values():
    config = {
        "locations": ["/app/depictio/projects/init/iris"],
        "scan": {"filename": "/app/depictio/projects/init/iris/data/iris.csv"},
        "name": "iris",
        "other": "/app/data/unrelated.csv",
        "count": 3,
    }

    relocated = _relocate_container_paths(config)

    assert relocated["locations"] == [str(_PACKAGE_ROOT / "projects/init/iris")]
    assert relocated["scan"]["filename"] == str(_PACKAGE_ROOT / "projects/init/iris/data/iris.csv")
    assert Path(relocated["scan"]["filename"]).is_file()
    assert relocated["name"] == "iris"
    assert relocated["other"] == "/app/data/unrelated.csv"
    assert relocated["count"] == 3


def test_screenshots_path_defaults_to_the_package_and_can_move(tmp_path):
    default = PerformanceConfig().screenshots_path
    assert default == _PACKAGE_ROOT / "api" / "static" / "screenshots"

    assert PerformanceConfig(screenshots_dir=str(tmp_path)).screenshots_path == tmp_path


def test_get_version_falls_back_to_package_metadata(monkeypatch):
    monkeypatch.setattr(version.Path, "is_file", lambda self: False)
    monkeypatch.setattr("importlib.metadata.version", lambda name: "9.9.9")

    assert version.get_version() == "9.9.9"
