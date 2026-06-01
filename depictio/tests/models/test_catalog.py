"""Tests for the declarative bio-catalog layer (MultiQC-module-style).

Covers: flat-file + folder module loading, MultiQC-section binding, the `find`
recognition (incl. `match_run_dir` against bundled data), file_schema, optional
recipe, compilation to `Producer` primitives, the merge into `all_producers()`
(curated wins), end-to-end `suggest_producers()`, URL identity, the offline
nf-core ``meta.yml`` importer, and JSON-Schema freshness.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from depictio.models.components.advanced_viz.catalog import (
    CatalogEntry,
    CatalogFind,
    entry_to_producers,
    load_catalog_entries,
    load_catalog_producers,
    match_run_dir,
    meta_yml_to_entry,
)
from depictio.models.components.advanced_viz.producers import (
    KNOWN_PRODUCERS,
    all_producers,
    get_producer,
)
from depictio.models.components.advanced_viz.schemas import suggest_producers

REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Loading: flat file = one module; folder = one module split across files
# ---------------------------------------------------------------------------


def test_bundled_catalog_loads():
    modules = {e.module.id for e in load_catalog_entries()}
    assert {
        "pangolin",
        "nextclade",
        "ivar",
        "mosdepth",
        "qiime2",
        "metaphlan",
        "multiqc",
    } <= modules


def test_single_output_tool_is_a_flat_file():
    entries = {e.module.id: e for e in load_catalog_entries()}
    assert len(entries["pangolin"].outputs) == 1
    assert (REPO_ROOT / "depictio" / "catalog" / "pangolin.yaml").is_file()


def test_multi_output_tool_is_a_folder():
    entries = {e.module.id: e for e in load_catalog_entries()}
    qiime2 = entries["qiime2"]
    assert (REPO_ROOT / "depictio" / "catalog" / "qiime2").is_dir()
    assert len(qiime2.outputs) >= 6
    modes = {o.mode for o in qiime2.outputs}
    assert {"taxa-barplot", "rel-abundance", "composition/ancombc", "phylogeny"} <= modes


# ---------------------------------------------------------------------------
# MultiQC-covered tools are bound to the multiqc module, not standalone
# ---------------------------------------------------------------------------


def test_fastqc_is_bound_to_multiqc_module():
    entries = {e.module.id: e for e in load_catalog_entries()}
    assert "fastqc" not in entries  # no standalone fastqc module
    fastqc = next(o for o in entries["multiqc"].outputs if o.id == "fastqc")
    assert fastqc.multiqc_module == "fastqc"


# ---------------------------------------------------------------------------
# Recognition: the `find` block (MultiQC search_patterns analogue)
# ---------------------------------------------------------------------------


def test_find_requires_a_condition():
    with pytest.raises(ValueError, match="at least one"):
        CatalogFind()


def test_match_run_dir_recognises_bundled_viralrecon_files():
    run = REPO_ROOT / "depictio" / "projects" / "nf-core" / "viralrecon" / "3.0.0" / "run_1"
    if not run.exists():
        pytest.skip("bundled viralrecon run_1 not present")
    by_output = {m.output_id: m for m in match_run_dir(run)}
    # mosdepth (3 files) + multiqc parquet are all recognised by their find rules
    assert "mosdepth_genome_coverage" in by_output
    assert "mosdepth_amplicon_heatmap" in by_output
    assert "multiqc_parquet" in by_output
    # and recognition carries the viz mapping through
    assert by_output["mosdepth_genome_coverage"].feeds_viz == ["coverage_track"]


# ---------------------------------------------------------------------------
# The raw file schema is documented; recipe is optional
# ---------------------------------------------------------------------------


def test_outputs_declare_raw_file_schema():
    entries = {e.module.id: e for e in load_catalog_entries()}
    genome = next(o for o in entries["mosdepth"].outputs if o.id == "mosdepth_genome_coverage")
    assert genome.file_schema["chrom"] == "String"
    assert genome.file_schema["coverage"] == "Float64"


def test_recipe_is_optional():
    entries = {e.module.id: e for e in load_catalog_entries()}
    metaphlan = entries["metaphlan"].outputs[0]
    assert metaphlan.recipe is None  # raw file already bindable
    pangolin = entries["pangolin"].outputs[0]
    assert pangolin.recipe == "nf-core/viralrecon/pangolin_lineages.py"


# ---------------------------------------------------------------------------
# Identity is stored as directly-clickable URLs (no resolver helpers)
# ---------------------------------------------------------------------------


def test_identity_is_stored_as_urls():
    entries = {e.module.id: e for e in load_catalog_entries()}
    pangolin = entries["pangolin"].module
    assert pangolin.biotools_url == "https://bio.tools/pangolin_cov-lineages"
    assert pangolin.nf_core_url.endswith("/modules/nf-core/pangolin/run")
    assert all(t.startswith("http://edamontology.org/") for t in pangolin.edam_topics)


# ---------------------------------------------------------------------------
# Compilation to Producer + merge semantics
# ---------------------------------------------------------------------------


def test_entry_to_producers_uses_find_required_columns():
    entry = CatalogEntry.model_validate(
        {
            "module": {"id": "demo", "name": "Demo"},
            "outputs": [
                {"id": "demo_a", "find": {"required_columns": ["x", "y"]}},
                {"id": "demo_b", "find": {"filename": "*.txt"}},  # no columns -> not a producer
            ],
        }
    )
    names = {p.name for p in entry_to_producers(entry)}
    assert names == {"demo_a"}


def test_catalog_producers_have_url_provenance_in_notes():
    producer = get_producer("metaphlan_profile")
    assert producer is not None
    assert "https://bio.tools/metaphlan" in producer.notes


def test_all_producers_merges_catalog_and_curated():
    merged = {p.name for p in all_producers()}
    assert {p.name for p in KNOWN_PRODUCERS} <= merged
    assert {p.name for p in load_catalog_producers()} <= merged


def test_curated_wins_on_name_collision():
    fabricated = CatalogEntry.model_validate(
        {
            "module": {"id": "x", "name": "X"},
            "outputs": [
                {
                    "id": "deseq2_results",  # collides with a curated producer
                    "find": {"required_columns": ["totally", "different"]},
                }
            ],
        }
    )
    curated = next(p for p in KNOWN_PRODUCERS if p.name == "deseq2_results")
    assert get_producer("deseq2_results") is curated
    assert entry_to_producers(fabricated)[0].required_columns != curated.required_columns


# ---------------------------------------------------------------------------
# End-to-end: catalog feeds the suggestion engine
# ---------------------------------------------------------------------------


def test_suggest_producers_picks_up_catalog_tool():
    schema = {
        "clade_name": "String",
        "NCBI_tax_id": "String",
        "relative_abundance": "Float64",
    }
    names = {name for name, _ in suggest_producers(schema)}
    assert "metaphlan_profile" in names


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


def test_meta_yml_importer_scaffolds_entry_with_urls():
    entry = meta_yml_to_entry(PANGOLIN_META)
    assert entry.module.id == "pangolin"
    assert entry.module.biotools_url == "https://bio.tools/pangolin_cov-lineages"
    assert entry.module.nf_core_url.endswith("/modules/nf-core/pangolin/run")
    out_ids = {o.id for o in entry.outputs}
    assert "pangolin_report" in out_ids
    assert "pangolin_versions" not in out_ids
    report = next(o for o in entry.outputs if o.id == "pangolin_report")
    assert report.find.filename == "*.{csv}"
    assert "http://edamontology.org/format_3752" in report.edam_formats


def test_meta_yml_scaffold_roundtrips_through_model():
    entry = meta_yml_to_entry(PANGOLIN_META)
    CatalogEntry.model_validate(entry.model_dump())


# ---------------------------------------------------------------------------
# Committed JSON Schema stays in sync with the model
# ---------------------------------------------------------------------------


def test_committed_json_schema_is_current():
    import json

    schema_path = REPO_ROOT / "depictio" / "catalog" / "catalog.schema.json"
    committed = json.loads(schema_path.read_text())
    assert committed == CatalogEntry.model_json_schema(), (
        "catalog.schema.json is stale — run: "
        "depictio catalog schema -o depictio/catalog/catalog.schema.json"
    )
