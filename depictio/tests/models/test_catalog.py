"""Tests for the declarative bio-catalog layer.

Covers: schema validation, the reshape-param validators, compilation to
`Producer` primitives, the merge into `all_producers()` (curated wins), the
end-to-end wiring into `suggest_producers()`, and the offline nf-core
``meta.yml`` importer.
"""

from __future__ import annotations

import pytest

from depictio.models.components.advanced_viz.catalog import (
    CatalogEntry,
    CatalogReshape,
    entry_to_producers,
    load_catalog_entries,
    load_catalog_producers,
    meta_yml_to_entry,
)
from depictio.models.components.advanced_viz.producers import (
    KNOWN_PRODUCERS,
    all_producers,
    get_producer,
)
from depictio.models.components.advanced_viz.schemas import suggest_producers

# ---------------------------------------------------------------------------
# Bundled catalog loads + validates
# ---------------------------------------------------------------------------


def test_bundled_catalog_loads():
    entries = load_catalog_entries()
    tool_ids = {e.tool.id for e in entries}
    assert "qiime2" in tool_ids
    assert "metaphlan" in tool_ids


def test_qiime2_is_multi_mode():
    """The headline 'tool with many running modes' shape: one tool, many outputs."""
    entries = {e.tool.id: e for e in load_catalog_entries()}
    qiime2 = entries["qiime2"]
    modes = {o.mode for o in qiime2.outputs}
    assert len(qiime2.outputs) >= 3
    assert {"diversity", "composition/ancombc", "taxa-barplot"} <= modes


def test_catalog_carries_upstream_identity():
    entries = {e.tool.id: e for e in load_catalog_entries()}
    metaphlan = entries["metaphlan"]
    assert metaphlan.tool.biotools_id == "metaphlan"
    assert any(o.nf_core_module for o in metaphlan.outputs)
    assert any(o.edam_formats for o in metaphlan.outputs)


# ---------------------------------------------------------------------------
# Reshape validation (the user's reformatting requirement)
# ---------------------------------------------------------------------------


def test_reshape_recipe_requires_recipe():
    with pytest.raises(ValueError, match="requires a 'recipe'"):
        CatalogReshape(kind="recipe")


def test_reshape_melt_requires_id_vars():
    with pytest.raises(ValueError, match="requires 'id_vars'"):
        CatalogReshape(kind="melt")


def test_reshape_pivot_requires_on_and_values():
    with pytest.raises(ValueError, match="requires 'on' and 'values'"):
        CatalogReshape(kind="pivot", index=["sample"])


def test_reshape_identity_is_default():
    assert CatalogReshape().kind == "identity"


# ---------------------------------------------------------------------------
# Compilation to Producer + merge semantics
# ---------------------------------------------------------------------------


def test_entry_to_producers_skips_fingerprintless_outputs():
    entry = CatalogEntry.model_validate(
        {
            "tool": {"id": "demo", "name": "Demo"},
            "outputs": [
                {"id": "demo_a", "fingerprint": {"required_columns": ["x", "y"]}},
                {"id": "demo_b"},  # no fingerprint -> not compiled to a Producer
            ],
        }
    )
    producers = entry_to_producers(entry)
    names = {p.name for p in producers}
    assert names == {"demo_a"}


def test_catalog_producers_have_provenance_in_notes():
    producer = get_producer("metaphlan_merged_abundance")
    assert producer is not None
    assert "biotools:metaphlan" in producer.notes
    assert "reshape=melt" in producer.notes


def test_all_producers_merges_catalog_and_curated():
    merged = {p.name for p in all_producers()}
    curated = {p.name for p in KNOWN_PRODUCERS}
    catalog = {p.name for p in load_catalog_producers()}
    assert curated <= merged
    assert catalog <= merged


def test_curated_wins_on_name_collision():
    """A catalog entry must never override a vetted curated fingerprint."""
    fabricated = CatalogEntry.model_validate(
        {
            "tool": {"id": "x", "name": "X"},
            "outputs": [
                {
                    "id": "deseq2_results",  # collides with a curated producer
                    "fingerprint": {"required_columns": ["totally", "different"]},
                }
            ],
        }
    )
    # The curated producer keeps its real fingerprint regardless of the catalog.
    curated = next(p for p in KNOWN_PRODUCERS if p.name == "deseq2_results")
    resolved = get_producer("deseq2_results")
    assert resolved is curated
    # sanity: the fabricated entry would have compiled to a different fingerprint
    assert entry_to_producers(fabricated)[0].required_columns != curated.required_columns


# ---------------------------------------------------------------------------
# End-to-end: catalog feeds the suggestion engine
# ---------------------------------------------------------------------------


def test_suggest_producers_picks_up_catalog_tool():
    """A MetaPhlAn-shaped schema should be recognised via the YAML catalog."""
    schema = {
        "clade_name": "String",
        "NCBI_tax_id": "Int64",
        "sample_A": "Float64",
        "sample_B": "Float64",
    }
    names = {name for name, _ in suggest_producers(schema)}
    assert "metaphlan_merged_abundance" in names


# ---------------------------------------------------------------------------
# Offline nf-core meta.yml importer
# ---------------------------------------------------------------------------

PANGOLIN_META = {
    "name": "pangolin_run",
    "tools": [
        {
            "pangolin": {
                "description": "Phylogenetic Assignment of Named Global Outbreak LINeages",
                "homepage": "https://github.com/cov-lineages/pangolin",
                "identifier": "biotools:pangolin_cov-lineages",
            }
        }
    ],
    "output": {
        "report": [
            [
                {"meta": {"type": "map"}},
                {
                    "*.csv": {
                        "type": "file",
                        "description": "Pangolin lineage report",
                        "pattern": "*.{csv}",
                        "ontologies": [{"edam": "http://edamontology.org/format_3752"}],
                    }
                },
            ]
        ],
        "versions": [{"versions.yml": {"type": "file", "pattern": "versions.yml"}}],
    },
}


def test_meta_yml_importer_scaffolds_entry():
    entry = meta_yml_to_entry(PANGOLIN_META)
    assert entry.tool.id == "pangolin"
    assert entry.tool.biotools_id == "pangolin_cov-lineages"

    # versions channel is skipped; the report channel becomes an output.
    out_ids = {o.id for o in entry.outputs}
    assert "pangolin_report" in out_ids
    assert "pangolin_versions" not in out_ids

    report = next(o for o in entry.outputs if o.id == "pangolin_report")
    assert "*.{csv}" in report.file_patterns
    assert "format_3752" in report.edam_formats
    # Scaffolds leave the fingerprint for the contributor to fill in.
    assert report.fingerprint is None


def test_meta_yml_scaffold_roundtrips_through_model():
    """The scaffold must itself be a valid CatalogEntry."""
    entry = meta_yml_to_entry(PANGOLIN_META)
    CatalogEntry.model_validate(entry.model_dump())
