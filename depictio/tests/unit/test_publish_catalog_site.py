"""scripts/publish_catalog_site.py: one export per slot, merged into a deduplicated tree."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "publish_catalog_site.py"
_spec = importlib.util.spec_from_file_location("publish_catalog_site", _SCRIPT)
assert _spec and _spec.loader
pcs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pcs)

T0 = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)

HTML = (
    '<!doctype html><script type="module" crossorigin src="./assets/{entry}.js"></script>'
    '<link rel="modulepreload" href="./assets/vendor.js">'
    '<link rel="stylesheet" href="./assets/{entry}.css">'
)


def _tool(tid: str, version: str, outputs: dict[str, Any]) -> dict[str, Any]:
    """A tool entry; ``outputs`` maps output id to its (figure) payload, None = failed."""
    return {
        "id": tid,
        "name": tid.upper(),
        "version": version,
        "outputs": [
            {
                "output": {"id": oid, "name": f"{oid} name"},
                "renders": [
                    {"index": f"{oid}-0", "component_type": "figure", "_yaml": "y", "config": {}}
                ],
                "ok": payload is not None,
                "fixturePreview": None,
            }
            for oid, payload in outputs.items()
        ],
    }


def _export(
    root: Path,
    name: str,
    version: str,
    tools: list[dict[str, Any]],
    payloads: dict[str, Any],
    entry: str = "main",
) -> Path:
    """A minimal export: index.html, assets, data/index.json and data/outputs/*."""
    export = root / f"export-{name}"
    shutil.rmtree(export, ignore_errors=True)  # a test may build the same export again
    (export / "assets").mkdir(parents=True)
    (export / "data" / "outputs").mkdir(parents=True)
    (export / "index.html").write_text(HTML.format(entry=entry))
    for asset in (f"{entry}.js", f"{entry}.css", "vendor.js"):
        # vendor.js is the same file in every build, the entry chunk is not.
        (export / "assets" / asset).write_text(
            f"// {asset}" + ("" if asset == "vendor.js" else f" of {entry}")
        )
    (export / "data" / "index.json").write_text(
        json.dumps({"version": version, "tools": tools, "data": {}})
    )
    for oid, payload in payloads.items():
        (export / "data" / "outputs" / f"{oid}.json").write_text(json.dumps(payload))
    return export


def _simple(
    root: Path,
    name: str,
    version: str,
    tool_version: str = "1.0.0",
    rows: int = 1,
    entry: str = "main",
):
    """One tool ``t`` with outputs ``a`` (always the same) and ``b`` (``rows`` rows)."""
    payloads = {"a": {"data": "same"}, "b": {"data": list(range(rows))}}
    tools = [_tool("t", tool_version, {"a": payloads["a"], "b": payloads["b"]})]
    return _export(root, name, version, tools, payloads, entry)


def _tree(site: Path) -> dict[str, bytes]:
    return {
        p.relative_to(site).as_posix(): p.read_bytes()
        for p in sorted(site.rglob("*"))
        if p.is_file()
    }


def _index(site: Path, slot: str) -> dict[str, Any]:
    return json.loads((site / slot / "data" / "index.json").read_text())


def _json(site: Path, name: str) -> Any:
    return json.loads((site / name).read_text())


def _objects(site: Path) -> set[str]:
    return {p.stem for p in (site / "objects").glob("*.json")}


def _assets(site: Path) -> set[str]:
    return {p.name for p in (site / "assets").iterdir()}


# --- slots ----------------------------------------------------------------


def test_release_order_puts_a_beta_before_its_release() -> None:
    names = ["v1.9.0", "v1.10.0-b2", "v1.10.0", "v1.10.0-b10"]
    assert sorted(names, key=pcs.release_key) == ["v1.9.0", "v1.10.0-b2", "v1.10.0-b10", "v1.10.0"]


@pytest.mark.parametrize("slot", ["main", "1.22.0", "../v1.22.0", "v1.22.0/x", ""])
def test_a_slot_that_is_neither_latest_nor_a_release_is_refused(tmp_path, slot) -> None:
    with pytest.raises(ValueError):
        pcs.publish(tmp_path / "site", _simple(tmp_path, "x", "1"), slot, now=T0)


def test_a_directory_that_is_not_an_export_is_refused(tmp_path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(SystemExit):
        pcs.publish(tmp_path / "site", tmp_path / "empty", "latest", now=T0)


def test_an_ok_output_without_its_file_is_refused(tmp_path) -> None:
    export = _simple(tmp_path, "x", "1.22.0")
    (export / "data" / "outputs" / "a.json").unlink()
    with pytest.raises(SystemExit):
        pcs.publish(tmp_path / "site", export, "v1.22.0", now=T0)


def test_every_release_is_kept_and_listed_newest_first(tmp_path) -> None:
    site = tmp_path / "site"
    for i in range(1, 15):
        pcs.publish(site, _simple(tmp_path, str(i), f"1.{i}.0"), f"v1.{i}.0", now=T0)
    pcs.publish(site, _simple(tmp_path, "main", "1.15.0+abc"), "latest", now=T0)

    versions = _json(site, "versions.json")
    assert versions["latest"] == "latest"
    assert versions["versions"][:2] == ["v1.14.0", "v1.13.0"] and len(versions["versions"]) == 14
    assert "url=latest/" in (site / "index.html").read_text()
    assert (site / ".nojekyll").exists()


def test_republishing_a_slot_replaces_it(tmp_path) -> None:
    site = tmp_path / "site"
    pcs.publish(site, _simple(tmp_path, "old", "1.0.0", entry="old"), "latest", now=T0)
    (site / "latest" / "data" / "stale.json").write_text("{}")
    pcs.publish(site, _simple(tmp_path, "new", "1.0.0", entry="new"), "latest", now=T1)

    assert not (site / "latest" / "data" / "stale.json").exists()
    assert "new.js" in (site / "latest" / "index.html").read_text()


# --- layout: assets, objects, dataRef -------------------------------------


def test_a_slot_loads_the_shared_assets_and_lists_them(tmp_path) -> None:
    site = tmp_path / "site"
    pcs.publish(site, _simple(tmp_path, "r", "1.22.0"), "v1.22.0", now=T0)

    html = (site / "v1.22.0" / "index.html").read_text()
    assert 'src="../assets/main.js"' in html
    assert 'href="../assets/vendor.js"' in html and 'href="../assets/main.css"' in html
    assert "./assets/" not in html.replace("../assets/", "")
    assert not (site / "v1.22.0" / "assets").exists()
    assert _json(site, "v1.22.0/assets.json") == ["main.css", "main.js", "vendor.js"]
    assert _assets(site) == {"main.css", "main.js", "vendor.js"}


def test_each_ok_output_gets_a_dataref_to_its_content_hash(tmp_path) -> None:
    site = tmp_path / "site"
    pcs.publish(site, _simple(tmp_path, "r", "1.22.0"), "v1.22.0", now=T0)

    outputs = {e["output"]["id"]: e for e in _index(site, "v1.22.0")["tools"][0]["outputs"]}
    body = json.dumps({"data": "same"}).encode()
    assert outputs["a"]["dataRef"] == hashlib.sha256(body).hexdigest()
    assert (site / "objects" / f"{outputs['a']['dataRef']}.json").read_bytes() == body
    assert not (site / "v1.22.0" / "data" / "outputs").exists()


def test_a_failed_output_has_no_dataref(tmp_path) -> None:
    tools = [_tool("t", "1.0.0", {"a": {"d": 1}, "broken": None})]
    export = _export(tmp_path, "x", "1.22.0", tools, {"a": {"d": 1}})
    site = tmp_path / "site"
    pcs.publish(site, export, "v1.22.0", now=T0)

    by_id = {e["output"]["id"]: e for e in _index(site, "v1.22.0")["tools"][0]["outputs"]}
    assert "dataRef" in by_id["a"] and "dataRef" not in by_id["broken"]


# --- deduplication and cleanup --------------------------------------------


def test_two_identical_releases_share_their_objects_and_assets(tmp_path) -> None:
    site = tmp_path / "site"
    pcs.publish(site, _simple(tmp_path, "1", "1.21.0"), "v1.21.0", now=T0)
    pcs.publish(site, _simple(tmp_path, "2", "1.22.0"), "v1.22.0", now=T1)

    assert len(_objects(site)) == 2  # a and b, once each
    assert _assets(site) == {"main.css", "main.js", "vendor.js"}
    refs = lambda s: [e["dataRef"] for e in _index(site, s)["tools"][0]["outputs"]]  # noqa: E731
    assert refs("v1.21.0") == refs("v1.22.0")


def test_a_changed_output_adds_an_object_and_the_old_one_stays_while_referenced(tmp_path) -> None:
    site = tmp_path / "site"
    pcs.publish(site, _simple(tmp_path, "1", "1.21.0", rows=1), "v1.21.0", now=T0)
    pcs.publish(site, _simple(tmp_path, "2", "1.22.0", rows=2), "v1.22.0", now=T1)
    assert len(_objects(site)) == 3  # a, b@1 row, b@2 rows

    # Replacing the only slot that held b@1 row drops that object, and only it.
    pcs.publish(site, _simple(tmp_path, "3", "1.21.0", rows=2), "v1.21.0", now=T2)
    assert len(_objects(site)) == 2


def test_assets_no_slot_references_are_dropped(tmp_path) -> None:
    site = tmp_path / "site"
    pcs.publish(site, _simple(tmp_path, "1", "1.21.0", entry="old"), "v1.21.0", now=T0)
    pcs.publish(site, _simple(tmp_path, "2", "1.21.0", entry="new"), "v1.21.0", now=T1)

    assert _assets(site) == {"new.css", "new.js", "vendor.js"}


def test_the_assets_of_a_replaced_latest_are_kept_one_more_deploy(tmp_path) -> None:
    site = tmp_path / "site"
    pcs.publish(site, _simple(tmp_path, "a", "1.0.0+a", entry="aaa"), "latest", now=T0)
    pcs.publish(site, _simple(tmp_path, "b", "1.0.0+b", entry="bbb"), "latest", now=T1)
    # aaa's chunks survive for tabs opened on the previous deploy...
    assert {"aaa.js", "bbb.js"} <= _assets(site)
    assert _json(site, "latest/assets.previous.json") == ["aaa.css", "aaa.js", "vendor.js"]

    # ...and go at the deploy after.
    pcs.publish(site, _simple(tmp_path, "c", "1.0.0+c", entry="ccc"), "latest", now=T2)
    assert "aaa.js" not in _assets(site) and {"bbb.js", "ccc.js"} <= _assets(site)


def test_republishing_a_release_gives_no_grace(tmp_path) -> None:
    site = tmp_path / "site"
    pcs.publish(site, _simple(tmp_path, "a", "1.22.0", entry="aaa"), "v1.22.0", now=T0)
    pcs.publish(site, _simple(tmp_path, "b", "1.22.0", entry="bbb"), "v1.22.0", now=T1)
    assert "aaa.js" not in _assets(site)
    assert not (site / "v1.22.0" / "assets.previous.json").exists()


# --- modules ---------------------------------------------------------------


def _with_versions(tmp_path: Path, site: Path) -> None:
    pcs.publish(site, _simple(tmp_path, "1", "1.21.0", "1.0.0"), "v1.21.0", now=T0)
    pcs.publish(site, _simple(tmp_path, "2", "1.22.0", "1.0.0"), "v1.22.0", now=T0)
    pcs.publish(site, _simple(tmp_path, "3", "1.23.0", "1.1.0"), "v1.23.0", now=T1)
    pcs.publish(site, _simple(tmp_path, "m", "1.24.0+x", "2.0.0"), "latest", now=T2)


def test_a_module_lists_its_versions_newest_first_with_bump_and_releases(tmp_path) -> None:
    site = tmp_path / "site"
    _with_versions(tmp_path, site)

    module = _json(site, "modules/t.json")
    assert module["id"] == "t" and module["name"] == "T"
    assert [(v["version"], v["bump"], v["releases"]) for v in module["versions"]] == [
        ("2.0.0", "major", ["latest"]),
        ("1.1.0", "minor", ["v1.23.0"]),
        ("1.0.0", None, ["v1.22.0", "v1.21.0"]),
    ]
    first = module["versions"][0]["outputs"][0]
    assert first == {
        "id": "a",
        "name": "a name",
        "renders": [{"index": "a-0", "component_type": "figure", "_yaml": "y"}],
    }


def test_a_patch_step_and_the_optional_render_keys(tmp_path) -> None:
    site = tmp_path / "site"
    tools = [_tool("t", "1.0.1", {"a": {"d": 1}})]
    tools[0]["outputs"][0]["renders"][0].update({"_variant": "v", "kind": "k"})
    pcs.publish(site, _simple(tmp_path, "1", "1.21.0", "1.0.0"), "v1.21.0", now=T0)
    pcs.publish(site, _export(tmp_path, "2", "1.22.0", tools, {"a": {"d": 1}}), "v1.22.0", now=T0)

    top = _json(site, "modules/t.json")["versions"][0]
    assert top["bump"] == "patch"
    assert top["outputs"][0]["renders"][0]["_variant"] == "v"
    assert top["outputs"][0]["renders"][0]["kind"] == "k"


def test_modules_of_tools_that_no_slot_has_are_deleted(tmp_path) -> None:
    site = tmp_path / "site"
    pcs.publish(site, _simple(tmp_path, "1", "1.21.0"), "v1.21.0", now=T0)
    (site / "modules" / "gone.json").write_text("{}")
    pcs.publish(site, _simple(tmp_path, "1", "1.21.0"), "v1.21.0", now=T0)

    assert sorted(p.name for p in (site / "modules").iterdir()) == ["t.json"]


# --- releases --------------------------------------------------------------


def test_releases_record_what_changed_since_the_previous_release(tmp_path) -> None:
    site = tmp_path / "site"
    old = [_tool("t", "1.0.0", {"a": {"d": 1}}), _tool("gone", "1.0.0", {"g": {"d": 1}})]
    new = [
        _tool("t", "1.1.0", {"a": {"d": 1}, "c": {"d": 2}}),
        _tool("fresh", "1.0.0", {"f": {"d": 3}}),
    ]
    pcs.publish(
        site,
        _export(tmp_path, "o", "1.22.0", old, {"a": {"d": 1}, "g": {"d": 1}}),
        "v1.22.0",
        now=T0,
    )
    pcs.publish(
        site,
        _export(tmp_path, "n", "1.23.0", new, {"a": {"d": 1}, "c": {"d": 2}, "f": {"d": 3}}),
        "v1.23.0",
        now=T1,
    )

    by_slot = {r["slot"]: r for r in _json(site, "releases.json")["releases"]}
    assert list(by_slot) == ["v1.23.0", "v1.22.0"]
    assert by_slot["v1.23.0"]["previous"] == "v1.22.0"
    assert by_slot["v1.23.0"]["version"] == "1.23.0"
    assert by_slot["v1.23.0"]["changes"] == {
        "added": ["fresh"],
        "removed": ["gone"],
        "bumped": [{"id": "t", "from": "1.0.0", "to": "1.1.0", "bump": "minor"}],
        "outputs_added": ["c", "f"],
        "outputs_removed": ["g"],
    }
    assert by_slot["v1.22.0"]["previous"] is None
    assert not any(by_slot["v1.22.0"]["changes"].values())


def test_latest_is_compared_with_the_newest_release_and_a_release_with_the_one_below(
    tmp_path,
) -> None:
    site = tmp_path / "site"
    pcs.publish(site, _simple(tmp_path, "1", "1.21.0", "1.0.0"), "v1.21.0", now=T0)
    pcs.publish(site, _simple(tmp_path, "3", "1.23.0", "1.2.0"), "v1.23.0", now=T0)
    pcs.publish(site, _simple(tmp_path, "2", "1.22.0", "1.1.0"), "v1.22.0", now=T0)  # out of order
    pcs.publish(site, _simple(tmp_path, "m", "1.24.0+x", "1.3.0"), "latest", now=T0)

    rel = {r["slot"]: r for r in _json(site, "releases.json")["releases"]}
    assert list(rel) == ["latest", "v1.23.0", "v1.22.0", "v1.21.0"]
    assert rel["latest"]["previous"] == "v1.23.0"
    assert rel["latest"]["changes"]["bumped"] == [
        {"id": "t", "from": "1.2.0", "to": "1.3.0", "bump": "minor"}
    ]
    assert rel["v1.23.0"]["previous"] == "v1.22.0"
    assert rel["v1.22.0"]["changes"]["bumped"][0]["from"] == "1.0.0"


def test_published_is_kept_for_slots_that_were_not_republished(tmp_path) -> None:
    site = tmp_path / "site"
    pcs.publish(site, _simple(tmp_path, "1", "1.21.0"), "v1.21.0", now=T0)
    pcs.publish(site, _simple(tmp_path, "2", "1.22.0"), "v1.22.0", now=T1)
    pcs.publish(site, _simple(tmp_path, "2", "1.22.0"), "v1.22.0", now=T2)

    published = {r["slot"]: r["published"] for r in _json(site, "releases.json")["releases"]}
    assert published == {"v1.22.0": "2026-11-22T10:00:00Z", "v1.21.0": "2026-11-20T10:00:00Z"}


# --- migration and idempotence ---------------------------------------------


def _legacy_slot(site: Path, slot: str, export: Path) -> None:
    """A slot as the earlier publisher left it: the export, copied as is."""
    shutil.copytree(export, site / slot)


def test_a_slot_in_the_earlier_format_is_converted_on_the_next_publish(tmp_path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    _legacy_slot(site, "v1.21.0", _simple(tmp_path, "old", "1.21.0", entry="legacy"))
    _legacy_slot(site, "latest", _simple(tmp_path, "oldl", "1.22.0+x", entry="legacy"))
    (site / "versions.json").write_text('{"latest": "latest", "versions": ["v1.21.0"]}')

    pcs.publish(site, _simple(tmp_path, "new", "1.22.0", entry="fresh"), "v1.22.0", now=T1)

    for slot in ("v1.21.0", "latest"):
        assert not (site / slot / "assets").exists()
        assert not (site / slot / "data" / "outputs").exists()
        assert 'src="../assets/legacy.js"' in (site / slot / "index.html").read_text()
        assert _json(site, f"{slot}/assets.json") == ["legacy.css", "legacy.js", "vendor.js"]
        assert all("dataRef" in e for e in _index(site, slot)["tools"][0]["outputs"])
    # The legacy slots share their objects with the new one (same payloads).
    assert len(_objects(site)) == 2
    assert {"legacy.js", "fresh.js"} <= _assets(site)
    assert [r["slot"] for r in _json(site, "releases.json")["releases"]] == [
        "latest",
        "v1.22.0",
        "v1.21.0",
    ]


def test_a_replaced_legacy_latest_still_gets_its_grace_period(tmp_path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    _legacy_slot(site, "latest", _simple(tmp_path, "oldl", "1.22.0+x", entry="legacy"))

    pcs.publish(site, _simple(tmp_path, "new", "1.22.0+y", entry="fresh"), "latest", now=T1)

    assert _json(site, "latest/assets.previous.json") == ["legacy.css", "legacy.js", "vendor.js"]
    assert "legacy.js" in _assets(site)


def test_normalising_twice_changes_nothing(tmp_path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    _legacy_slot(site, "v1.21.0", _simple(tmp_path, "old", "1.21.0"))
    pcs.normalize_slot(site, "v1.21.0")
    before = _tree(site)
    pcs.normalize_slot(site, "v1.21.0")
    assert _tree(site) == before


def test_publishing_the_same_export_twice_gives_the_same_tree(tmp_path) -> None:
    site = tmp_path / "site"
    pcs.publish(site, _simple(tmp_path, "1", "1.21.0"), "v1.21.0", now=T0)
    pcs.publish(site, _simple(tmp_path, "m", "1.22.0+x", entry="m"), "latest", now=T0)
    first = _tree(site)

    pcs.publish(site, _simple(tmp_path, "m", "1.22.0+x", entry="m"), "latest", now=T0)
    assert _tree(site) == first
    pcs.publish(site, _simple(tmp_path, "1", "1.21.0"), "v1.21.0", now=T0)
    assert _tree(site) == first


def test_republishing_only_moves_the_published_stamp_of_that_slot(tmp_path) -> None:
    site = tmp_path / "site"
    pcs.publish(site, _simple(tmp_path, "1", "1.21.0"), "v1.21.0", now=T0)
    first = _tree(site)
    pcs.publish(site, _simple(tmp_path, "1", "1.21.0"), "v1.21.0", now=T1)

    second = _tree(site)
    assert {k for k in first if first[k] != second[k]} == {"releases.json"}
