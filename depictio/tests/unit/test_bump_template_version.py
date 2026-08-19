"""Offline unit tests for scripts/bump_template_version.py (tmp dirs only)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "bump_template_version.py"


@pytest.fixture(scope="module")
def btv() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bump_template_version", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def pipeline_dir(tmp_path: Path) -> Path:
    """A fake nf-core projects root with one pipeline at 2.16.0 (+ legacy 2.14.0)."""
    for version in ("2.14.0", "2.16.0"):
        vdir = tmp_path / "ampliseq" / version
        (vdir / "dashboards").mkdir(parents=True)
        (vdir / "template.yaml").write_text(
            f'template:\n  template_id: "nf-core/ampliseq/{version}"\n  version: "{version}"\n'
        )
        (vdir / "dashboards" / "base.yaml").write_text(f"# ampliseq {version} dashboard\n")
        (vdir / "data.parquet").write_bytes(bytes([0, 159, 146, 150]) + version.encode())
    return tmp_path


def test_bump_copies_and_rewrites_versions(btv: ModuleType, pipeline_dir: Path) -> None:
    new_dir = btv.bump("ampliseq", "2.18.0", projects_dir=pipeline_dir)
    assert new_dir == pipeline_dir / "ampliseq" / "2.18.0"
    template = (new_dir / "template.yaml").read_text()
    assert 'template_id: "nf-core/ampliseq/2.18.0"' in template
    assert "2.16.0" not in template
    assert "2.18.0 dashboard" in (new_dir / "dashboards" / "base.yaml").read_text()
    # Binary payloads are copied verbatim, never text-rewritten.
    assert (new_dir / "data.parquet").read_bytes().endswith(b"2.16.0")
    # Source dir is untouched; latest now resolves to the new version.
    old = (pipeline_dir / "ampliseq" / "2.16.0" / "template.yaml").read_text()
    assert '"2.16.0"' in old
    assert btv.latest_version(pipeline_dir / "ampliseq") == "2.18.0"


def test_bump_defaults_to_latest_source_not_legacy(btv: ModuleType, pipeline_dir: Path) -> None:
    new_dir = btv.bump("ampliseq", "2.18.0", projects_dir=pipeline_dir)
    # Copied from 2.16.0 (the latest), not 2.14.0.
    assert "2.14.0" not in (new_dir / "template.yaml").read_text()


def test_bump_refuses_existing_target_and_non_ascending(
    btv: ModuleType, pipeline_dir: Path
) -> None:
    with pytest.raises(FileExistsError):
        btv.bump("ampliseq", "2.16.0", from_version="2.14.0", projects_dir=pipeline_dir)
    # A "new" version sorting below the source would never be picked by
    # latest-resolution — refuse instead of shipping a dead directory.
    with pytest.raises(ValueError, match="does not sort above"):
        btv.bump("ampliseq", "2.15.0", projects_dir=pipeline_dir)
    with pytest.raises(FileNotFoundError):
        btv.bump("nope", "1.0.0", projects_dir=pipeline_dir)


def test_bump_dry_run_writes_nothing(btv: ModuleType, pipeline_dir: Path) -> None:
    btv.bump("ampliseq", "2.18.0", projects_dir=pipeline_dir, dry_run=True)
    assert not (pipeline_dir / "ampliseq" / "2.18.0").exists()
