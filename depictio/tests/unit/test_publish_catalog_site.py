"""scripts/publish_catalog_site.py: one export per slot, the newest releases kept."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "publish_catalog_site.py"
_spec = importlib.util.spec_from_file_location("publish_catalog_site", _SCRIPT)
assert _spec and _spec.loader
publish_catalog_site = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(publish_catalog_site)


def _export(root: Path, marker: str) -> Path:
    export = root / f"export-{marker}"
    (export / "data").mkdir(parents=True)
    (export / "index.html").write_text(marker)
    (export / "data" / "index.json").write_text("{}")
    return export


def test_release_order_puts_a_beta_before_its_release() -> None:
    names = ["v1.9.0", "v1.10.0-b2", "v1.10.0", "v1.10.0-b10"]
    ordered = sorted(names, key=publish_catalog_site.release_key)
    assert ordered == ["v1.9.0", "v1.10.0-b2", "v1.10.0-b10", "v1.10.0"]


def test_publishing_keeps_the_newest_releases_and_latest(tmp_path) -> None:
    site = tmp_path / "site"
    for version in ["v1.20.0", "v1.21.0", "v1.22.0"]:
        publish_catalog_site.publish(site, _export(tmp_path, version), version, keep=2)
    publish_catalog_site.publish(site, _export(tmp_path, "main"), "latest", keep=2)

    assert sorted(p.name for p in site.iterdir() if p.is_dir()) == ["latest", "v1.21.0", "v1.22.0"]
    assert json.loads((site / "versions.json").read_text()) == {
        "latest": "latest",
        "versions": ["v1.22.0", "v1.21.0"],
    }
    assert "url=latest/" in (site / "index.html").read_text()
    assert (site / ".nojekyll").exists()


def test_republishing_a_slot_replaces_it(tmp_path) -> None:
    site = tmp_path / "site"
    publish_catalog_site.publish(site, _export(tmp_path, "old"), "latest", keep=10)
    (site / "latest" / "data" / "stale.json").write_text("{}")
    publish_catalog_site.publish(site, _export(tmp_path, "new"), "latest", keep=10)

    assert (site / "latest" / "index.html").read_text() == "new"
    assert not (site / "latest" / "data" / "stale.json").exists()


@pytest.mark.parametrize("slot", ["main", "1.22.0", "../v1.22.0", ""])
def test_a_slot_that_is_neither_latest_nor_a_release_is_refused(tmp_path, slot) -> None:
    with pytest.raises(ValueError):
        publish_catalog_site.publish(tmp_path / "site", _export(tmp_path, "x"), slot, keep=10)


def test_a_directory_that_is_not_an_export_is_refused(tmp_path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(SystemExit):
        publish_catalog_site.publish(tmp_path / "site", tmp_path / "empty", "latest", keep=10)


def test_betas_do_not_push_stable_releases_out() -> None:
    present = ["v1.22.0-b1", "v1.21.0", "v1.21.0-b6", "v1.21.0-b5", "v1.20.0", "v1.19.0"]
    assert publish_catalog_site.prunable(present, keep=2) == [
        "v1.21.0-b6",
        "v1.21.0-b5",
        "v1.19.0",
    ]


def test_a_release_older_than_the_kept_ones_is_refused_not_published(tmp_path) -> None:
    site = tmp_path / "site"
    for version in ["v1.21.0", "v1.22.0"]:
        publish_catalog_site.publish(site, _export(tmp_path, version), version, keep=2)

    with pytest.raises(SystemExit, match="older than"):
        publish_catalog_site.publish(site, _export(tmp_path, "old"), "v1.20.6", keep=2)
    assert not (site / "v1.20.6").exists()
    assert (site / "v1.21.0").exists()


def test_a_trailing_newline_is_not_a_release() -> None:
    with pytest.raises(ValueError):
        publish_catalog_site.release_key("v1.22.0\n")
