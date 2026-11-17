"""A bundle's dashboards must be renderable here; a newer source is flagged (#1303)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from depictio.api.v1.endpoints.migrate_endpoints import inbound_routes
from depictio.api.v1.endpoints.migrate_endpoints.inbound_routes import (
    CheckBody,
    _source_is_newer,
    _version_key,
)
from depictio.api.v1.services import project_bundle
from depictio.api.v1.services.project_bundle import compatibility_errors
from depictio.version import get_version

from .push_helpers import build_world, push
from .test_bundle_roundtrip import _export_zip

PROJECTS = Path(__file__).resolve().parents[5] / "projects"


def _seed_dashboards() -> list[tuple[str, dict]]:
    out = []
    for path in sorted(PROJECTS.rglob("*.json")):
        if path.parent.name != ".db_seeds":
            continue
        doc = json.loads(path.read_text())
        if isinstance(doc, dict) and "stored_metadata" in doc:
            out.append((str(path.relative_to(PROJECTS)), doc))
    return out


def test_every_shipped_dashboard_seed_is_compatible():
    seeds = _seed_dashboards()
    assert len(seeds) > 10, "the seed list must not silently be empty"
    offenders = {name: compatibility_errors([d]) for name, d in seeds if compatibility_errors([d])}
    assert offenders == {}


def test_all_dashboards_checked_together_too():
    assert compatibility_errors([d for _, d in _seed_dashboards()]) == []


def test_known_and_empty_dashboards_pass():
    assert compatibility_errors([]) == []
    assert compatibility_errors([{"stored_metadata": None}, {}]) == []
    assert compatibility_errors([{"stored_metadata": ["junk", {"component_type": "figure"}]}]) == []


def test_unknown_component_type_is_named_with_the_version_and_a_remedy():
    errors = compatibility_errors(
        [{"stored_metadata": [{"component_type": "hologram"}, {"component_type": "figure"}]}]
    )
    assert len(errors) == 1
    assert "'hologram'" in errors[0] and "figure" not in errors[0]
    assert get_version() in errors[0] and "update" in errors[0].lower()


@pytest.mark.parametrize(
    "comp",
    [
        {"component_type": "advanced_viz", "viz_kind": "teleporter"},
        {"component_type": "advanced_viz", "config": {"viz_kind": "teleporter"}},
    ],
)
def test_unknown_advanced_viz_kind_is_refused(comp):
    errors = compatibility_errors([{"stored_metadata": [comp]}])
    assert len(errors) == 1 and "'teleporter'" in errors[0] and get_version() in errors[0]


def test_known_advanced_viz_kind_passes():
    from typing import get_args

    from depictio.models.components.types import AdvancedVizKind

    kind = get_args(AdvancedVizKind)[0]
    comps = [
        {"component_type": "advanced_viz", "viz_kind": kind},
        {"component_type": "advanced_viz", "config": {"viz_kind": kind}},
        {"component_type": "advanced_viz"},
    ]
    assert compatibility_errors([{"stored_metadata": comps}]) == []


def test_several_unknowns_are_reported_once_in_one_message():
    errors = compatibility_errors(
        [
            {"stored_metadata": [{"component_type": "hologram"}]},
            {"stored_metadata": [{"component_type": "hologram"}, {"component_type": "oracle"}]},
        ]
    )
    assert len(errors) == 1
    assert errors[0].count("'hologram'") == 1 and "'oracle'" in errors[0]


@pytest.fixture
def world(monkeypatch, target_db, captures):
    return build_world(monkeypatch, target_db)


def _poisoned_payload(world, monkeypatch):
    world.src_db.dashboards_collection.update_one(
        {"_id": world.ids["main_dash"]},
        {"$set": {"stored_metadata": [{"index": "c1", "component_type": "hologram"}]}},
    )
    return _export_zip((world.src_db, world.ids, world.s3), monkeypatch)


def test_validate_bundle_strict_reports_the_incompatibility(world, target_db, monkeypatch):
    import io
    import zipfile

    payload = _poisoned_payload(world, monkeypatch)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        meta = json.loads(zf.read("migrate_metadata.json"))
        data = json.loads(zf.read("bundle.json"))
    report = project_bundle.validate_bundle(meta, data, [], strict=True)
    assert any("'hologram'" in e and get_version() in e for e in report.errors)
    lenient = project_bundle.validate_bundle(meta, data, [], strict=False)
    assert any("'hologram'" in e for e in lenient.errors), "an error even for the CLI"


def test_an_upload_with_an_unknown_component_is_refused_and_nothing_is_imported(
    world, target_db, monkeypatch
):
    payload = _poisoned_payload(world, monkeypatch)
    response = push(payload, world.source)
    assert response.status_code == 422
    errors = json.loads(response.body)["errors"]
    assert any("'hologram'" in e and get_version() in e for e in errors)
    assert target_db.projects_collection.count_documents({}) == 0
    assert target_db.dashboards_collection.count_documents({}) == 0
    assert "tgt-bucket" not in world.s3.buckets or not [
        k for k in world.s3.buckets["tgt-bucket"] if not k.startswith("_migration_staging/")
    ]


# ---------------------------------------------------------------------------
# Source newer than this instance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, key",
    [
        ("1.20.5", (1, 20, 5)),
        ("v1.21.0", (1, 21, 0)),
        ("1.20.5+dev", (1, 20, 5)),
        ("1.21.0-rc1", (1, 21, 0)),
        ("2", (2,)),
        ("", None),
        (None, None),
        ("garbage", None),
    ],
)
def test_version_key(raw, key):
    assert _version_key(raw) == key


def test_version_ordering_is_numeric_not_lexical():
    assert _version_key("1.9.0") < _version_key("1.10.0")  # type: ignore[operator]


@pytest.fixture
def ours(monkeypatch):
    monkeypatch.setattr(inbound_routes, "get_version", lambda: "1.20.5")


def test_a_newer_source_gets_a_warning_naming_both_versions(ours):
    for newer in ("1.21.0", "v1.20.6", "2.0.0-rc1"):
        msg = _source_is_newer(newer)
        assert msg and newer in msg and "1.20.5" in msg


@pytest.mark.parametrize("other", ["1.20.5", "1.20.5+dev", "1.20.4", "0.9", "", None, "garbage"])
def test_same_older_or_unreadable_source_versions_give_no_warning(ours, other):
    assert _source_is_newer(other) is None


def _check(world, version):
    body = CheckBody(
        project_id=str(world.ids["project_id"]), source_depictio_version=version, total_bytes=1
    )
    return asyncio.run(inbound_routes.inbound_check(body, source=world.source))


def test_check_includes_the_warning_when_the_source_is_newer(world, ours):
    out = _check(world, "9.9.9")
    warnings = out["preflight"]["warnings"]
    assert any("9.9.9" in w and "1.20.5" in w for w in warnings)
    assert out["preflight"]["ok"] is True, "a warning does not block"


def test_check_has_no_version_warning_for_an_older_source(world, ours):
    warnings = _check(world, "1.0.0")["preflight"]["warnings"]
    assert not any("newer than this instance" in w for w in warnings)
    assert not any(
        "newer than this instance" in w for w in _check(world, None)["preflight"]["warnings"]
    )
