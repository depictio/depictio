"""nf-core/drop's genome-track manifest and the cohort size of the sample hub.

The manifest opens on the reads of the sample holding the strongest gene and carries no
colour column: the browser colours its tracks by ``drop_group`` from the dashboard's
``category_colors``, the same key as the navigator's lanes and the cards.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
import yaml

from depictio.cli.cli.utils.templates import substitute_template_variables
from depictio.models.models.data_collections_types.genomic_tracks import DCGenomicTracksConfig
from depictio.recipes import load_recipe, validate_schema

TEMPLATE = Path(__file__).parents[2] / "projects/nf-core/drop/1.0.0/template.yaml"
DASHBOARD = TEMPLATE.parent / "dashboards/base.yaml"


class _Context:
    """Just enough of the recipe context: every file is a URL or exists."""

    reads_in_place = True

    def exists(self, path: str) -> bool:
        return True

    def glob(self, pattern: str) -> list[str]:
        return []


def _sheet() -> pl.DataFrame:
    rows = [
        ("A1", "outrider,batch_a"),
        ("A2", "outrider,batch_a"),
        ("B1", "outrider,batch_b"),
        ("C1", "outrider,batch_c"),
    ]
    return pl.DataFrame(
        {
            "RNA_ID": [r[0] for r in rows],
            "DROP_GROUP": [r[1] for r in rows],
            "RNA_BAM_FILE": [f"https://h/{r[0]}.bam" for r in rows],
            "RNA_BAI_FILE": [f"https://h/{r[0]}.bam.bai" for r in rows],
            "DNA_VCF_FILE": [f"https://h/{r[0]}.vcf.gz" for r in rows],
            "DNA_TBI_FILE": [f"https://h/{r[0]}.vcf.gz.tbi" for r in rows],
        }
    )


def _hub() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "sample": ["A1", "A2", "B1", "C1"],
            "drop_group": ["batch_a", "batch_a", "batch_b", "batch_c"],
        }
    )


def _run(genes: pl.DataFrame | None) -> pl.DataFrame:
    module = load_recipe("nf-core/drop/tracks.py")
    out = module.transform({"hub": _hub(), "sheet": _sheet(), "genes": genes}, _Context())
    validate_schema(out, module.OUTPUT_SCHEMA, "tracks", None)
    return out


@pytest.mark.no_db
def test_no_manifest_colour_column() -> None:
    out = _run(None)
    assert "color" not in out.columns
    assert "drop_group" in out.columns


@pytest.mark.no_db
def test_opens_on_the_reads_and_genotypes_of_the_strongest_genes_sample() -> None:
    genes = pl.DataFrame(
        {
            "sample": ["A1", "B1", "C1"],
            "significance": [2.0, 7.5, 3.0],
            "chrom": ["chr1", "chr2", "chr3"],
        }
    )
    out = _run(genes)
    ids = out["track_id"].to_list()
    # The reads of B1, its genotypes, then the reads of one sample of each other group.
    assert ids[:4] == ["B1.alignments", "B1.genotypes", "A1.alignments", "C1.alignments"]
    assert out["order"].to_list() == list(range(1, out.height + 1))
    assert len(ids) == 8
    assert len(set(ids)) == 8


@pytest.mark.no_db
def test_a_gene_without_a_position_does_not_name_the_sample() -> None:
    genes = pl.DataFrame(
        {"sample": ["A1", "B1"], "significance": [2.0, 9.0], "chrom": ["chr1", None]}
    )
    assert _run(genes)["track_id"][0] == "A1.alignments"


@pytest.mark.no_db
def test_without_genes_the_first_sample_opens() -> None:
    out = _run(None)
    assert out["track_id"].to_list()[:2] == ["A1.alignments", "A1.genotypes"]


@pytest.mark.no_db
def test_sample_hub_carries_the_cohort_size() -> None:
    module = load_recipe("nf-core/drop/samples.py")
    out = module.transform({"sheet": _sheet()})
    sizes = dict(zip(out["sample"].to_list(), out["group_size"].to_list(), strict=True))
    # Every sample belongs to the 4-sample outrider group, whatever its batch holds.
    assert set(sizes.values()) == {4}


def test_template_tracks_dc_has_no_colour_column_and_the_dashboard_colours_by_group() -> None:
    resolved = substitute_template_variables(
        yaml.safe_load(TEMPLATE.read_text()), {"DATA_ROOT": "/data", "GENOME": "hg38"}
    )
    dcs = [dc for wf in resolved["workflows"] for dc in wf["data_collections"]]
    tracks = next(dc for dc in dcs if dc["data_collection_tag"] == "tracks")
    props = tracks["config"]["dc_specific_properties"]
    assert "color_column" not in props
    assert "color" not in props["columns_description"]
    assert DCGenomicTracksConfig(**props).color_column is None

    board = yaml.safe_load(DASHBOARD.read_text())
    tabs = board["tabs"] if "tabs" in board else board
    tiles = [c for tab in tabs if isinstance(tab, dict) for c in tab.get("components", [])]
    browser = next(t for t in tiles if t["component_type"] == "jbrowse")
    nav = next(t for t in tiles if t.get("config", {}).get("viz_kind") == "genome_view")
    # The lanes and the tracks share one colour key, and the navigator does not filter on load.
    assert browser["color_by"] == nav["config"]["category_col"] == "drop_group"
    assert "default_region" not in nav["config"]
