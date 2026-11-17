"""The nf-core/viralmetagenome hubs (``nf-core/viralmetagenome/samples.py``, ``genomes.py``, ``read_funnel.py``).

The hubs are pipeline recipes, not catalog ones: they join the catalog
collections (the overview tables, CheckV) and the optional metadata table into
the one row per sample and the one row per consensus genome every tab filters
through. The catalog recipes are tested in ``test_viralmetagenome_recipes.py``;
here their outputs are built in memory, as the ingest hands the dc_ref sources
over.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe, load_recipe
from depictio.recipes.lib.viralmetagenome import GENOME_SCHEMA, NO_GROUP_COL


def _run(recipe: str, frames: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """The recipe's output, its dc_ref sources fed from ``frames`` (keyed by DC tag)."""
    module = load_recipe(recipe)
    extra = {s.ref: frames[s.dc_ref] for s in module.SOURCES if frames.get(s.dc_ref) is not None}
    return execute_recipe(recipe, Path("."), extra_sources=extra)


@pytest.fixture()
def overview() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "sample": ["S1", "S2", "S3"],
            "raw_read_pairs": [1000, 200, 500],
            "trimmed_read_pairs": [990, 190, 500],
            "host_filtered_read_pairs": [980, 171, None],
            "host_pct": [1.0, 10.0, None],
            "assembly_n50": [29000, 900, 3000],
            "meta_library_strategy": ["WGS", "WGS", "AMPLICON"],
            "meta_run_accession": ["R1", "R2", "R3"],
            "meta_layout": ["PAIRED", "PAIRED", "PAIRED"],
        },
        schema_overrides={"host_filtered_read_pairs": pl.Int64, "host_pct": pl.Float64},
    )


def _genomes(rows: list[dict]) -> pl.DataFrame:
    full = [{c: r.get(c) for c in GENOME_SCHEMA} for r in rows]
    return pl.DataFrame(full, schema=GENOME_SCHEMA)


def test_samples_hub_joins_the_metadata(overview: pl.DataFrame) -> None:
    meta = pl.DataFrame(
        {"sample": ["S1", "S2", "S3"], "specimen": ["a", "b", "a"], "host_pct": ["x"] * 3}
    )
    hub = _run(
        "nf-core/viralmetagenome/samples.py", {"vmg_samples_overview": overview, "metadata": meta}
    )
    # The factor follows the sample; a metadata column cannot replace a measure.
    assert hub.columns[:2] == ["sample", "specimen"]
    assert hub["host_pct"].to_list() == [1.0, 10.0, None]
    assert NO_GROUP_COL not in hub.columns
    assert "library_strategy" not in hub.columns


def test_samples_hub_without_metadata_keeps_the_overview_factors(overview: pl.DataFrame) -> None:
    hub = _run("nf-core/viralmetagenome/samples.py", {"vmg_samples_overview": overview})
    assert hub[NO_GROUP_COL].unique().to_list() == ["All samples"]
    # A factor groups the samples: not an accession, not a constant.
    assert "library_strategy" in hub.columns
    assert "run_accession" not in hub.columns and "layout" not in hub.columns
    # Measures the overview did not hold are null, not missing.
    assert hub["denovo_consensus"].null_count() == 3


def test_read_funnel_is_long_and_ordered(overview: pl.DataFrame) -> None:
    hub = _run("nf-core/viralmetagenome/samples.py", {"vmg_samples_overview": overview})
    funnel = _run("nf-core/viralmetagenome/read_funnel.py", {"samples": hub})
    s1 = funnel.filter(pl.col("sample") == "S1")
    assert s1["stage"].to_list() == ["Raw", "Trimmed", "Host removed"]
    assert s1["pct_of_raw"].to_list() == [100.0, 99.0, 98.0]
    # A stage the sample has no count for has no row.
    assert funnel.filter(pl.col("sample") == "S3").height == 2
    assert NO_GROUP_COL in funnel.columns


def test_genome_hub_stacks_the_routes_and_reads_checkv() -> None:
    denovo = _genomes(
        [
            {
                "genome_id": "S1_cl0",
                "sample": "S1",
                "reference": "cl0",
                "route": "de novo",
                "step": "it1",
            }
        ]
    )
    constraint = _genomes(
        [{"genome_id": "S1_REF1", "sample": "S1", "reference": "REF1", "route": "constraint"}]
    )
    checkv = pl.DataFrame(
        {
            "sample": ["S1", "S1", "S1", "S1"],
            "contig_id": [
                "S1_cl0_consensus",
                "S1_cl0_it1.consensus_bcftools",
                "S1_cl0_itvariant-calling.consensus_ivar",
                "S1_REF1-CONSTRAINT_itvariant-calling.consensus_ivar",
            ],
            "completeness": [10.0, 50.0, 60.0, 95.0],
            "completeness_method": ["AAI"] * 4,
        }
    )
    samples = pl.DataFrame({"sample": ["S1"], "specimen": ["a"], "raw_read_pairs": [1000]})
    hub = _run(
        "nf-core/viralmetagenome/genomes.py",
        {
            "vmg_contigs_overview": denovo,
            "vmg_mapping_overview": constraint,
            "checkv_quality": checkv,
            "samples": samples,
        },
    )
    completeness = dict(zip(hub["genome_id"], hub["checkv_completeness"], strict=True))
    # The de novo genome reads the step it ended at; the constraint one its
    # variant-calling consensus.
    assert completeness == {"S1_cl0": 50.0, "S1_REF1": 95.0}
    assert hub.columns[:3] == ["genome_id", "sample", "specimen"]
    assert "raw_read_pairs" not in hub.columns


def test_genome_hub_survives_one_route_and_no_checkv() -> None:
    constraint = _genomes(
        [{"genome_id": "S1_REF1", "sample": "S1", "reference": "REF1", "route": "constraint"}]
    )
    hub = _run("nf-core/viralmetagenome/genomes.py", {"vmg_mapping_overview": constraint})
    assert hub["genome_id"].to_list() == ["S1_REF1"]
    assert hub["checkv_completeness"].to_list() == [None]
    assert hub[NO_GROUP_COL].to_list() == ["All samples"]


def test_genome_hub_needs_a_route() -> None:
    with pytest.raises(Exception, match="neither the contigs nor the mapping overview"):
        _run("nf-core/viralmetagenome/genomes.py", {})
