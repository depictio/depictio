"""A transformed data collection comes after every collection its recipe reads.

Ingest builds a template's data collections in the order ``template.yaml``
declares them, and a recipe's ``dc_ref`` source reads the referenced
collection's table as it stands at that moment. Declared too early, an
optional reference resolves to ``None`` and the recipe quietly drops what it
would have joined: smrnaseq's sample hub lost its miRTrace and miRDeep2
columns that way.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from depictio.recipes import load_recipe

NF_CORE_DIR = Path(__file__).resolve().parents[2] / "projects" / "nf-core"
TEMPLATES = sorted(NF_CORE_DIR.glob("*/*/template.yaml"))


def _data_collections(template: Path) -> list[dict[str, Any]]:
    doc = yaml.safe_load(template.read_text())
    return [dc for wf in doc.get("workflows") or [] for dc in wf.get("data_collections") or []]


@pytest.mark.parametrize(
    "template", TEMPLATES, ids=[str(t.parent.relative_to(NF_CORE_DIR)) for t in TEMPLATES]
)
def test_recipe_dc_refs_are_declared_first(template: Path) -> None:
    version = template.parent.name
    dcs = _data_collections(template)
    position = {dc["data_collection_tag"]: i for i, dc in enumerate(dcs)}
    late: list[str] = []
    for i, dc in enumerate(dcs):
        recipe = ((dc.get("config") or {}).get("transform") or {}).get("recipe")
        if not recipe:
            continue
        for source in load_recipe(recipe, version).SOURCES:
            ref = source.dc_ref
            if ref in position and position[ref] > i:
                late.append(f"{dc['data_collection_tag']} reads {ref}, declared after it")
    assert not late, "; ".join(late)
