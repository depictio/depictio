"""`genome_view`: the registry entries and the renamed kind's own contract.

The kind used to be called `genomespy_track` (the #1083 spike). Renaming a viz
kind touches seven registries that no single import forces to agree, so these
tests pin the agreement rather than any one of them: the Literal, the canonical
schema, the optional roles, the sampling policy, the config model and the
discriminated union all have to name `genome_view`, and none of them may still
name the old string.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from depictio.models.components.advanced_viz.configs import GenomeViewConfig, VizConfig
from depictio.models.components.advanced_viz.sampling import KIND_SAMPLING_POLICY, TAIL_ROLE
from depictio.models.components.advanced_viz.schemas import (
    _OPTIONAL_ROLES,
    CANONICAL_SCHEMAS,
    KIND_METADATA,
    ROLE_NAMES,
    suggest_viz_kinds,
)
from depictio.models.components.types import AdvancedVizKind

REPO = Path(__file__).resolve().parents[3]
KIND = "genome_view"
OLD_KIND = "genomespy_track"

VIZ_CONFIG = TypeAdapter(VizConfig)


def test_kind_is_registered_everywhere():
    assert KIND in get_args(AdvancedVizKind)
    assert KIND in CANONICAL_SCHEMAS
    assert KIND in ROLE_NAMES
    assert KIND in _OPTIONAL_ROLES
    assert KIND in KIND_METADATA
    assert KIND_SAMPLING_POLICY[KIND] == "tail"
    assert TAIL_ROLE[KIND] == ("score", "auto")


def test_old_kind_string_is_gone_from_every_registry():
    assert OLD_KIND not in get_args(AdvancedVizKind)
    for table in (
        CANONICAL_SCHEMAS,
        ROLE_NAMES,
        _OPTIONAL_ROLES,
        KIND_METADATA,
        KIND_SAMPLING_POLICY,
    ):
        assert OLD_KIND not in table


def test_required_roles_match_manhattan_so_the_same_dc_binds_both():
    """The spike's promise: a DC a Manhattan reads renders here unchanged."""
    assert CANONICAL_SCHEMAS[KIND] == CANONICAL_SCHEMAS["manhattan"]


def test_optional_roles_cover_intervals_lanes_and_colour():
    assert set(_OPTIONAL_ROLES[KIND]) == {"feature", "end", "sample", "category"}


def test_config_defaults_are_a_plain_point_track():
    config = GenomeViewConfig()
    assert config.viz_kind == KIND
    assert config.mark == "point"
    assert config.annotation == "none"
    assert config.facet_by_sample is False
    # The brush is on by default: a region filter is unambiguous, unlike a
    # click, which needs the dashboard to say what a mark stands for.
    assert config.region_filter_enabled is True
    assert config.follow_region_filter is False
    assert config.selection_enabled is False
    assert config.selection_column is None


def test_union_discriminates_on_the_new_kind():
    parsed = VIZ_CONFIG.validate_python(
        {
            "viz_kind": KIND,
            "chr_col": "chrom",
            "pos_col": "start",
            "score_col": "coverage",
            "end_col": "end",
            "sample_col": "sample",
            "category_col": "gene_region",
            "mark": "bar",
            "facet_by_sample": True,
            "max_facets": 6,
            "annotation": "hg38",
            "follow_region_filter": True,
        }
    )
    assert isinstance(parsed, GenomeViewConfig)
    assert parsed.mark == "bar"
    assert parsed.annotation == "hg38"


@pytest.mark.parametrize("mark", ["point", "rect", "bar"])
def test_every_mark_the_renderer_offers_validates(mark: str):
    assert GenomeViewConfig(mark=mark).mark == mark  # type: ignore[arg-type]


def test_line_is_not_a_mark_because_genomespy_has_none():
    """GenomeSpy 0.88 ships point/rect/arrow/rule/tick/link/text and no line.

    `coverage_track` keeps its Plotly line; this kind draws a profile as bars.
    """
    with pytest.raises(ValidationError):
        GenomeViewConfig(mark="line")  # type: ignore[arg-type]


def test_annotation_only_offers_assemblies_with_a_shipped_gene_table():
    for assembly in ("hg38", "mm10"):
        assert GenomeViewConfig(annotation=assembly).annotation == assembly  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        GenomeViewConfig(annotation="hg19")  # type: ignore[arg-type]


def test_max_facets_is_bounded_so_lanes_stay_readable():
    with pytest.raises(ValidationError):
        GenomeViewConfig(max_facets=0)
    with pytest.raises(ValidationError):
        GenomeViewConfig(max_facets=999)


def test_extra_keys_are_forbidden_like_every_other_viz_config():
    with pytest.raises(ValidationError):
        GenomeViewConfig(some_key_that_does_not_exist=1)  # type: ignore[call-arg]


def test_a_coordinate_dc_suggests_the_kind():
    """A mosdepth-shaped collection (chrom / start / end / depth) ranks it.

    `_score_role` matches on Polars dtype names, which is what
    `/advanced_viz/suggestions` is handed.
    """
    schema = {"chrom": "String", "start": "Int64", "coverage": "Float64", "end": "Int64"}
    kinds = {s.viz_kind: s.score for s in suggest_viz_kinds(schema)}
    assert kinds[KIND] > 0.5
    # It binds the same required roles as the Manhattan, plus two optional ones
    # this shape fills, so it may not rank below it on a collection with ends.
    assert kinds[KIND] >= kinds["manhattan"]


# --- Shipped gene annotation assets ---------------------------------------

ASSET_DIR = REPO / "depictio" / "viewer" / "public" / "assets" / "genomes"
#: The lane lazily fetches the whole file, so it stays inside a budget a
#: dashboard can pay on a slow link. Raise it deliberately, not by accident.
MAX_ASSET_BYTES = 1_500_000


@pytest.mark.parametrize("assembly", ["hg38", "mm10"])
def test_gene_asset_is_present_compact_and_well_formed(assembly: str):
    path = ASSET_DIR / f"{assembly}.genes.json"
    assert path.is_file(), (
        f"{path} is missing. Rebuild it with "
        f"`python dev/advanced_viz_kinds/build_genome_gene_assets.py --assembly {assembly}`."
    )
    size = path.stat().st_size
    assert size <= MAX_ASSET_BYTES, (
        f"{path.name} is {size} bytes, over the {MAX_ASSET_BYTES} budget"
    )

    payload = json.loads(path.read_text())
    assert payload["assembly"] == assembly
    assert payload["columns"] == ["name", "chrom", "start", "end", "strand"]
    genes = payload["genes"]
    # A protein-coding gene set for a mammal is tens of thousands of rows; an
    # order of magnitude either way means the GTF filter silently changed.
    assert 15_000 <= len(genes) <= 30_000
    for row in genes[:50]:
        name, chrom, start, end, strand = row
        assert isinstance(name, str) and name
        assert chrom.startswith("chr")
        assert isinstance(start, int) and isinstance(end, int)
        assert 0 <= start < end
        assert strand in {"+", "-"}
    # Sorted by contig then start, which is what lets the lane be scanned.
    first_chrom_rows = [r for r in genes if r[1] == genes[0][1]]
    assert first_chrom_rows == sorted(first_chrom_rows, key=lambda r: r[2])
