"""Invariants on `ReferenceDatasetRegistry.resolve_template_for_init`.

The init resolver converts recipe-based DCs (`source: "transformed"` with a
`transform.recipe` block) into file_scan DCs pointing at a bundled
`{data_root}/{dc_tag}.tsv` seed. Two things must be true after conversion:

1. The DC keeps `source: "transformed"` so the viewer's data-source info
   card / admin panel still surfaces the recipe lineage (see also
   ``deltatables.py:process_data_collection`` which falls through to
   file-scan when ``source == "transformed"`` *and* ``transform is None``).
2. ``dc_specific_properties.format`` must be ``"tsv"`` regardless of what
   the template declared — the template's original format hint described
   the recipe's *input* source (e.g. summary_metrics' input is a real CSV
   from multiqc) which is irrelevant once we replace the recipe with a
   file_scan reading the tab-separated seed.

This test exists because viralrecon's template declared
``format: "CSV"`` on 12 of 13 recipe DCs (matching the *input* CSVs the
recipes consumed) — after PRs #765 + #767 turned on the file-scan code
path for bundled seeds, the CSV-hint caused polars to parse the
tab-delimited seeds with a comma separator and collapse the whole header
row into a single column name, breaking every dashboard tile bound to
those DCs.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from depictio.api.v1.db_init_reference_datasets import ReferenceDatasetRegistry


def _make_template_with_recipe_dc(declared_format: str) -> dict:
    """Build a minimal template config exercising the recipe-DC branch."""
    return {
        "name": "test-project",
        "workflows": [
            {
                "name": "test-wf",
                "data_collections": [
                    {
                        "data_collection_tag": "demo",
                        "config": {
                            "type": "Table",
                            "source": "transformed",
                            "transform": {"recipe": "test/demo.py"},
                            "dc_specific_properties": {"format": declared_format},
                        },
                    },
                ],
            },
        ],
    }


def _write_seed_tsv(data_root: Path, dc_tag: str) -> None:
    seed = data_root / f"{dc_tag}.tsv"
    seed.write_text("col_a\tcol_b\nv1\tv2\n")


def test_recipe_dc_conversion_forces_tsv_format() -> None:
    """A CSV-declared recipe DC keeps a TSV seed → format must be coerced to tsv."""
    with tempfile.TemporaryDirectory() as td:
        data_root = Path(td)
        _write_seed_tsv(data_root, "demo")
        cfg = _make_template_with_recipe_dc(declared_format="CSV")
        resolved = ReferenceDatasetRegistry.resolve_template_for_init(cfg, str(data_root))

        dcs = resolved["workflows"][0]["data_collections"]
        assert len(dcs) == 1
        dc_cfg = dcs[0]["config"]

        assert dc_cfg["source"] == "transformed", (
            "recipe lineage must survive conversion (viewer reads source=transformed)"
        )
        assert "transform" not in dc_cfg, "transform block must be popped after conversion"
        assert dc_cfg["scan"]["mode"] == "single"
        assert dc_cfg["scan"]["scan_parameters"]["filename"] == str(data_root / "demo.tsv")
        assert dc_cfg["dc_specific_properties"]["format"] == "tsv", (
            "format must be coerced to tsv so polars uses tab separator on the bundled seed; "
            f"got {dc_cfg['dc_specific_properties']['format']!r}"
        )


def test_recipe_dc_conversion_drops_when_seed_missing() -> None:
    """If `{data_root}/{dc_tag}.tsv` is absent, the DC must be pruned entirely."""
    with tempfile.TemporaryDirectory() as td:
        cfg = _make_template_with_recipe_dc(declared_format="TSV")
        resolved = ReferenceDatasetRegistry.resolve_template_for_init(cfg, td)
        assert resolved["workflows"][0]["data_collections"] == [], (
            "missing seed → DC dropped so workflow scan doesn't abort downstream"
        )


def test_recipe_dc_conversion_handles_null_dc_specific_properties() -> None:
    """Resolver must tolerate missing dc_specific_properties block."""
    with tempfile.TemporaryDirectory() as td:
        data_root = Path(td)
        _write_seed_tsv(data_root, "demo")
        cfg = _make_template_with_recipe_dc(declared_format="CSV")
        # Strip dc_specific_properties to simulate older template format
        del cfg["workflows"][0]["data_collections"][0]["config"]["dc_specific_properties"]

        resolved = ReferenceDatasetRegistry.resolve_template_for_init(cfg, str(data_root))
        dc_cfg = resolved["workflows"][0]["data_collections"][0]["config"]
        assert dc_cfg["dc_specific_properties"]["format"] == "tsv"
