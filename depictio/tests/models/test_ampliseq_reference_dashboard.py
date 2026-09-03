"""``reference_extended.yaml`` must be what its generator produces.

The ampliseq reference dashboard is ``base.yaml`` plus a demo layer (a sampling
map, a date range, CTD filters and two extra tabs) applied by
``build_reference_dashboard.py``. Committing the generated file keeps the seed
build reproducible without a Python step, but it also makes silent drift
possible: edit ``base.yaml``, forget to regenerate, and the demo dashboard keeps
shipping the previous template. That is the failure this file exists to catch.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from depictio.api.v1.db_init_reference_datasets import STATIC_IDS
from depictio.cli.cli.utils.templates import latest_template_version
from depictio.models.models.dashboards import DashboardDataLite

# The version db_init seeds from (highest shipped version), so the guard follows a bump.
_AMPLISEQ_DIR = Path(__file__).resolve().parents[3] / "depictio/projects/nf-core/ampliseq"
PROJECT_DIR = _AMPLISEQ_DIR / (latest_template_version(_AMPLISEQ_DIR) or "")
GENERATOR = PROJECT_DIR / "build_reference_dashboard.py"
COMMITTED = PROJECT_DIR / "dashboards" / "reference_extended.yaml"

_PLACEHOLDER = re.compile(r"\{[A-Z_][A-Z0-9_]*\}")


def _load_generator() -> ModuleType:
    """Import the generator by path — `nf-core` and a version dir are not module names."""
    spec = importlib.util.spec_from_file_location("build_reference_dashboard", GENERATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def generated() -> dict:
    return _load_generator().build()


@pytest.fixture(scope="module")
def committed() -> dict:
    return yaml.safe_load(COMMITTED.read_text())


def test_committed_yaml_matches_the_generator(generated: dict, committed: dict) -> None:
    assert committed == generated, (
        "dashboards/reference_extended.yaml is out of date with base.yaml. "
        "Regenerate it with:\n"
        f"  python {GENERATOR.relative_to(PROJECT_DIR.parents[3])}"
    )


def test_no_template_placeholders_survive(committed: dict) -> None:
    """The reference YAML is imported directly, and that path substitutes nothing."""
    leftover = sorted(set(_PLACEHOLDER.findall(COMMITTED.read_text())))
    assert not leftover, f"unresolved template variables in the reference dashboard: {leftover}"


def test_every_tab_validates(committed: dict) -> None:
    tabs = [committed["main_dashboard"], *committed["tabs"]]
    for tab in tabs:
        lite = DashboardDataLite.model_validate(tab)
        lite.to_full()


def test_demo_tab_ids_are_the_reserved_static_ids(committed: dict) -> None:
    by_title = {t["title"]: t["dashboard_id"] for t in committed["tabs"]}
    dashboards = STATIC_IDS["ampliseq"]["dashboards"]
    assert by_title["Sampling Campaign"] == dashboards["ampliseq_sampling_campaign"]
    assert by_title["Environment (CTD)"] == dashboards["ampliseq_environment"]


def test_tab_titles_match_the_template_family(committed: dict) -> None:
    """`_import_multi_tab_dashboard` matches tabs by title, not by the YAML's id.

    So the reference file must reuse the template's titles byte for byte, or
    importing it on top of a base.yaml import mints a second family instead of
    extending the first.
    """
    base = yaml.safe_load((PROJECT_DIR / "dashboards" / "base.yaml").read_text())
    base_titles = [base["main_dashboard"]["title"], *[t["title"] for t in base["tabs"]]]
    ref_titles = [committed["main_dashboard"]["title"], *[t["title"] for t in committed["tabs"]]]
    assert ref_titles[: len(base_titles)] == base_titles
    assert ref_titles[len(base_titles) :] == ["Sampling Campaign", "Environment (CTD)"]
