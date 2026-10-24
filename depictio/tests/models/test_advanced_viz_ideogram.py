"""The `ideogram` kind: row contract, config guards, and the showcase bindings.

A karyotype is drawn by hand on a canvas (`IdeogramRenderer.tsx`, layout and
level of detail in `ideogram/ideogramLayout.ts` and `ideogram/ideogramView.ts`),
so its contract lives in the canonical schema and this config. Both showcase tiles are checked against the real fixture columns
here: the BUSCO table (named as BUSCO's full table names them, lengths from the
FASTA index) and the binned variant density on GRCh38.

Pure-model + fixture reads: no DB, no network.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import yaml
from pydantic import TypeAdapter, ValidationError

from depictio.models.components.advanced_viz.configs import IdeogramConfig, VizConfig
from depictio.models.components.advanced_viz.sampling import KIND_SAMPLING_POLICY
from depictio.models.components.advanced_viz.schemas import (
    _OPTIONAL_ROLES,
    CANONICAL_SCHEMAS,
    KIND_METADATA,
    ROLE_NAMES,
    role_dtype_specs,
    suggest_viz_kinds,
    validate_binding,
)

REPO = Path(__file__).resolve().parents[3]
SHOWCASE = REPO / "depictio" / "projects" / "init" / "advanced_viz_showcase"
BUSCO_FIXTURE = SHOWCASE / "data" / "ideogram_busco_demo.tsv"
DENSITY_FIXTURE = SHOWCASE / "data" / "ideogram_density_demo.tsv"
DASHBOARD = SHOWCASE / "dashboards" / "ideogram.yaml"
SEED = SHOWCASE / ".db_seeds" / "dashboard_ideogram.json"

VIZ_CONFIG = TypeAdapter(VizConfig)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open() as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert rows, f"{path} has a header but no data rows"
    return rows


def _fixture_schema(path: Path) -> dict[str, str]:
    """Column -> dtype name, numeric against string, as a scanned DC reports it."""
    rows = _rows(path)
    schema: dict[str, str] = {}
    for column in rows[0]:
        values = [row[column] for row in rows if row[column] not in (None, "")]
        schema[column] = (
            "Int64" if values and all(v.lstrip("-").isdigit() for v in values) else "String"
        )
    return schema


def _tile_configs() -> dict[str, dict]:
    doc = yaml.safe_load(DASHBOARD.read_text())
    return {
        c["data_collection_tag"]: c["config"]
        for c in doc["components"]
        if c.get("component_type") == "advanced_viz"
    }


# ---------------------------------------------------------------------------
# The row contract
# ---------------------------------------------------------------------------


def test_required_roles_are_an_interval_on_a_chromosome():
    assert set(CANONICAL_SCHEMAS["ideogram"]) == {"chrom", "start", "end"}
    assert set(_OPTIONAL_ROLES["ideogram"]) == {
        "value",
        "category",
        "sample",
        "label",
        "chrom_length",
    }


def test_every_role_has_a_config_field_and_the_optional_ones_start_unbound():
    config = IdeogramConfig()
    for role in CANONICAL_SCHEMAS["ideogram"]:
        assert getattr(config, f"{role}_col") == role
    # A value nobody declared must not colour the bars, and a length column
    # nobody declared must not size them.
    for role in _OPTIONAL_ROLES["ideogram"]:
        assert getattr(config, f"{role}_col") is None


def test_the_kind_is_listed_with_its_aliases_and_tooltips():
    meta = KIND_METADATA["ideogram"]
    assert meta["label"] and meta["description"] and meta["icon"].startswith("tabler:")
    assert set(ROLE_NAMES["ideogram"]) <= set(CANONICAL_SCHEMAS["ideogram"]) | set(
        _OPTIONAL_ROLES["ideogram"]
    )
    for role in CANONICAL_SCHEMAS["ideogram"]:
        assert role in ROLE_NAMES["ideogram"][role]
    # BUSCO's full table and a binned density table, as they name their columns.
    assert "sequence" in ROLE_NAMES["ideogram"]["chrom"]
    assert "gene_start" in ROLE_NAMES["ideogram"]["start"]
    assert "bin_end" in ROLE_NAMES["ideogram"]["end"]
    specs = role_dtype_specs("ideogram")
    assert all(spec["description"] for spec in specs.values())
    assert specs["chrom_length"]["required"] is False


def test_the_server_never_samples_it():
    """A sampled feature table would leave holes that read as missing genes."""
    assert KIND_SAMPLING_POLICY["ideogram"] == "none"


# ---------------------------------------------------------------------------
# Config: defaults, guards, modes
# ---------------------------------------------------------------------------


def test_defaults():
    config = IdeogramConfig()
    assert config.mode == "marks"
    assert config.orientation == "horizontal"
    assert config.assembly is None
    assert config.bin_size is None
    assert config.chromosomes is None
    assert config.facet_by_sample is True
    assert config.max_features == 20000
    assert config.max_chromosomes == 60
    assert config.lod_threshold == 2000
    assert config.feature_opacity == 0.85
    assert config.hidden_categories is None
    # On by default, as genome_view's brush is: a region is never ambiguous.
    assert config.region_filter_enabled is True


def test_auto_is_a_mode_and_marks_stays_the_default():
    """`auto` (level of detail) was added beside the two existing modes; a
    dashboard that never set `mode` keeps drawing marks."""
    assert IdeogramConfig(mode="auto").mode == "auto"
    assert IdeogramConfig().mode == "marks"


def test_hidden_categories_keep_their_spelling_and_empty_means_none():
    assert IdeogramConfig(hidden_categories=[]).hidden_categories is None
    assert IdeogramConfig(hidden_categories=["Missing", "Missing", " Dup"]).hidden_categories == [
        "Missing",
        " Dup",
    ]


@pytest.mark.parametrize(
    "field, bad",
    [
        ("max_features", 0),
        ("max_features", 1_000_000),
        ("max_chromosomes", 0),
        ("max_chromosomes", 10_000),
        ("max_facets", 0),
        ("max_facets", 100),
        ("bin_size", 0),
        ("lod_threshold", 0),
        ("lod_threshold", 1_000_000),
        ("feature_opacity", 0),
        ("feature_opacity", 1.5),
    ],
)
def test_guards_are_bounded(field: str, bad: float):
    with pytest.raises(ValidationError):
        IdeogramConfig(**{field: bad})


def test_modes_and_orientations_are_closed_sets():
    with pytest.raises(ValidationError):
        IdeogramConfig(mode="heatmap")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        IdeogramConfig(orientation="circular")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        IdeogramConfig(colour_scale="Rainbow")  # type: ignore[arg-type]


def test_a_blank_chromosome_list_means_no_restriction():
    assert IdeogramConfig(chromosomes=[]).chromosomes is None
    assert IdeogramConfig(chromosomes=["", "  "]).chromosomes is None
    assert IdeogramConfig(chromosomes=[" chr1", "chrX "]).chromosomes == ["chr1", "chrX"]


def test_unknown_keys_are_refused():
    with pytest.raises(ValidationError):
        VIZ_CONFIG.validate_python({"viz_kind": "ideogram", "selection_column": "busco_id"})


def test_round_trips_through_the_union():
    parsed = VIZ_CONFIG.validate_python(
        {
            "viz_kind": "ideogram",
            "chrom_col": "sequence",
            "mode": "density",
            "bin_size": 1_000_000,
            "orientation": "vertical",
            "assembly": "hg38",
        }
    )
    assert isinstance(parsed, IdeogramConfig)
    assert (parsed.mode, parsed.bin_size, parsed.orientation) == ("density", 1_000_000, "vertical")


# ---------------------------------------------------------------------------
# Binding validation
# ---------------------------------------------------------------------------


def test_a_position_left_as_a_string_is_reported():
    errors = validate_binding(
        IdeogramConfig(start_col="locus"),
        {"chrom": "String", "locus": "String", "end": "Int64"},
    )
    assert [e.role for e in errors] == ["start"]


def test_a_bound_optional_role_pointing_nowhere_is_an_error():
    schema = {"chrom": "String", "start": "Int64", "end": "Int64"}
    assert validate_binding(IdeogramConfig(), schema) == []
    errors = validate_binding(IdeogramConfig(chrom_length_col="length"), schema)
    assert [e.role for e in errors] == ["chrom_length"]


def test_the_suggester_offers_it_for_a_busco_table():
    schema = _fixture_schema(BUSCO_FIXTURE)
    kinds = [s.viz_kind for s in suggest_viz_kinds(schema)]
    assert "ideogram" in kinds


# ---------------------------------------------------------------------------
# The showcase tab
# ---------------------------------------------------------------------------


def test_both_showcase_tiles_bind_their_fixtures_cleanly():
    tiles = _tile_configs()
    assert set(tiles) == {"ideogram_busco_demo", "ideogram_density_demo"}
    for tag, path in (
        ("ideogram_busco_demo", BUSCO_FIXTURE),
        ("ideogram_density_demo", DENSITY_FIXTURE),
    ):
        config = VIZ_CONFIG.validate_python(tiles[tag])
        assert isinstance(config, IdeogramConfig)
        assert validate_binding(config, _fixture_schema(path)) == [], tag
    # One tile per mode, so the tab shows both readings.
    assert {tiles[t]["mode"] for t in tiles} == {"marks", "density"}


def test_the_busco_fixture_is_three_karyotypes_of_busco_statuses():
    rows = _rows(BUSCO_FIXTURE)
    genomes = {r["genome"] for r in rows}
    assert genomes == {"genome_A", "genome_B", "genome_C"}
    assert {r["status"] for r in rows} == {"Complete", "Duplicated", "Fragmented"}
    for genome in genomes:
        seqs = {r["sequence"] for r in rows if r["genome"] == genome}
        assert 10 <= len(seqs) <= 16, (genome, len(seqs))
    for r in rows:
        start, end, length = int(r["gene_start"]), int(r["gene_end"]), int(r["sequence_length"])
        assert 0 < start < end <= length
    # A sequence has one length, whichever row states it.
    lengths: dict[tuple[str, str], set[str]] = {}
    for r in rows:
        lengths.setdefault((r["genome"], r["sequence"]), set()).add(r["sequence_length"])
    assert all(len(v) == 1 for v in lengths.values())


def test_the_density_fixture_tiles_grch38_in_2mb_bins():
    rows = _rows(DENSITY_FIXTURE)
    assert {r["sample"] for r in rows} == {"sample_01", "sample_02"}
    chroms = {r["chrom"] for r in rows}
    assert len(chroms) == 24 and "chrY" in chroms
    for r in rows:
        start, end = int(r["start"]), int(r["end"])
        assert start % 2_000_000 == 0 and 0 < end - start <= 2_000_000
        assert int(r["variant_count"]) >= 0


def test_the_seed_matches_the_yaml():
    """The seed is what a fresh deployment loads; it must carry both tiles."""
    seed = json.loads(SEED.read_text())
    assert seed["_id"]["$oid"] == "646b0f3c1e4a2d7f8e5b8da6"
    kinds = [
        c.get("viz_kind")
        for c in seed["stored_metadata"]
        if c.get("component_type") == "advanced_viz"
    ]
    assert kinds == ["ideogram", "ideogram"]


def test_the_tab_is_registered_for_seeding():
    from depictio.api.v1.db_init_reference_datasets import STATIC_IDS

    showcase = STATIC_IDS["advanced_viz_showcase"]
    assert showcase["dashboards"]["advanced_viz_ideogram"] == "646b0f3c1e4a2d7f8e5b8da6"
    assert showcase["data_collections"]["ideogram_busco_demo"] == "646b0f3c1e4a2d7f8e5b8da7"
    assert showcase["data_collections"]["ideogram_density_demo"] == "646b0f3c1e4a2d7f8e5b8da8"
    # Every id appears once in the showcase registry.
    ids = list(showcase["data_collections"].values()) + list(showcase["dashboards"].values())
    assert len(ids) == len(set(ids))
