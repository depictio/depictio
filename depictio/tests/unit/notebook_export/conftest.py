"""Shared fixtures: the seeded reference dashboards as plain dicts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECTS = REPO_ROOT / "depictio" / "projects"
PENGUINS_SEEDS = PROJECTS / "init" / "penguins" / ".db_seeds"
AMPLISEQ_SEEDS = PROJECTS / "nf-core" / "ampliseq" / "2.16.0" / ".db_seeds"


def strip_extended_json(obj: Any) -> Any:
    """``{"$oid": "..."}`` → ``"..."`` and ``{"$date": ...}`` → its value, recursively.

    Seeds are Mongo extended JSON; the endpoints read them back from Mongo
    where ids are ``ObjectId``s that stringify cleanly. Tests that read the
    seed files directly need the same plain strings.
    """
    if isinstance(obj, dict):
        if set(obj.keys()) == {"$oid"}:
            return str(obj["$oid"])
        if set(obj.keys()) == {"$date"}:
            return obj["$date"]
        return {k: strip_extended_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [strip_extended_json(v) for v in obj]
    return obj


def load_seed(path: Path) -> dict[str, Any]:
    return strip_extended_json(json.loads(path.read_text()))


@pytest.fixture(scope="session")
def penguins_tabs() -> list[dict[str, Any]]:
    return [
        load_seed(PENGUINS_SEEDS / "dashboard.json"),
        load_seed(PENGUINS_SEEDS / "dashboard_island_season.json"),
    ]


@pytest.fixture(scope="session")
def ampliseq_tabs() -> list[dict[str, Any]]:
    return [load_seed(p) for p in sorted(AMPLISEQ_SEEDS.glob("dashboard_*.json"))]
