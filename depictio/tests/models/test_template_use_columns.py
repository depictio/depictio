"""A template's `use:` must not inherit a column its data collection lacks.

`use: <tool>/<render-id>` on an advanced_viz component copies the catalog
render's roles and config into the component when the dashboard is read, from
the catalog as it is *now*: no older module version is kept. A role added to a
catalog render therefore reaches every template that uses it. When the template
feeds that render from its own recipe, the new column may not exist there, and
the chart fails only once the dashboard is imported and rendered.

This checks every inherited `*_col` / `*_cols` binding against the output
schema of the recipe that builds the component's data collection. Bindings the
dashboard sets itself are left out: they may name a column a join adds.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from depictio.models.components.advanced_viz.component import AdvancedVizLiteComponent
from depictio.recipes import load_recipe

PROJECTS = Path(__file__).resolve().parents[2] / "projects"
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_LIST_KEYS = ("ranks", "value_columns", "steps")


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _recipes(template: dict) -> dict[str, str]:
    """data_collection_tag -> recipe ref, for collections built by a recipe."""
    out: dict[str, str] = {}
    for node in _walk(template):
        tag, config = node.get("data_collection_tag"), node.get("config")
        if not tag or not isinstance(config, dict):
            continue
        recipe = next(
            (n["recipe"] for n in _walk(config) if isinstance(n.get("recipe"), str)), None
        )
        if recipe:
            out[tag] = recipe
    return out


def _columns(recipe: str, version: str | None) -> set[str] | None:
    try:
        module = load_recipe(recipe, version)
    except Exception:  # noqa: BLE001 — recipe loading has its own tests
        return None
    return set(module.OUTPUT_SCHEMA) | set(getattr(module, "OPTIONAL_OUTPUT_SCHEMA", {}) or {})


def _inherited_columns(component: dict) -> dict[str, list[str]]:
    expanded = AdvancedVizLiteComponent._expand_catalog_use(dict(component))
    user = set((component.get("config") or {}).keys())
    out: dict[str, list[str]] = {}
    for key, value in (expanded.get("config") or {}).items():
        if key in user:
            continue
        if key.endswith("_col") and isinstance(value, str):
            out[key] = [value]
        elif (key.endswith("_cols") or key in _LIST_KEYS) and isinstance(value, list):
            out[key] = [v for v in value if isinstance(v, str)]
    return out


def _cases():
    for template_file in sorted(PROJECTS.rglob("template.yaml")):
        root = template_file.parent
        version = root.name if _VERSION.match(root.name) else None
        recipes = _recipes(yaml.safe_load(template_file.read_text()) or {})
        for dashboard in sorted(root.rglob("dashboards/*.yaml")):
            for comp in _walk(yaml.safe_load(dashboard.read_text())):
                if comp.get("component_type") == "advanced_viz" and comp.get("use"):
                    recipe = recipes.get(comp.get("data_collection_tag", ""))
                    if recipe:
                        yield dashboard.relative_to(PROJECTS), version, recipe, comp


def test_use_inherits_only_columns_the_collection_has():
    missing: list[str] = []
    for dashboard, version, recipe, comp in _cases():
        columns = _columns(recipe, version)
        if columns is None:
            continue
        for key, values in _inherited_columns(comp).items():
            absent = [v for v in values if v not in columns]
            if absent:
                missing.append(
                    f"{dashboard}: `use: {comp['use']}` inherits {key}={absent}, "
                    f"which {recipe} does not produce; set {key} in the dashboard's config"
                )
    assert missing == [], "\n".join(missing)


@pytest.mark.parametrize("user_set", [True, False])
def test_a_binding_the_dashboard_sets_is_not_inherited(user_set):
    comp = {"component_type": "advanced_viz", "use": "deseq2/qc_pca_embedding", "config": {}}
    if user_set:
        comp["config"]["color_col"] = "consensus_set"
    assert ("color_col" in _inherited_columns(comp)) is not user_set
