"""The protein families and structure confidence tabs of the advanced-viz showcase.

The fixtures are built by ``scripts/generate_fixtures.py`` from the demo alignment
and structure; these tests hold the committed files to the contracts the five
second-wave protein kinds read, and each tab's column bindings to the tables they
point at (a typo in a ``*_col`` field draws an empty tile and raises nothing).
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
import yaml

from depictio.recipes.lib.hmm import PROFILE_SCHEMA, parse_hmm, reference_positions_from_stockholm
from depictio.recipes.lib.pae import read_pae
from depictio.recipes.lib.secondary_structure import parse_ss2

SHOWCASE = Path(__file__).resolve().parents[2] / "projects" / "init" / "advanced_viz_showcase"
DATA = SHOWCASE / "data"
DASHBOARDS = SHOWCASE / "dashboards"
ENTITY = "demo_protein"
N_RESIDUES = 172

#: Columns of the hmmer ``hmmsearch_domtbl`` recipe, in its order.
DOMTBL_COLUMNS = [
    "entity",
    "sample",
    "source",
    "label",
    "accession",
    "description",
    "start",
    "end",
    "protein_length",
    "hmm_length",
    "domain_index",
    "domain_count",
    "seq_evalue",
    "seq_score",
    "c_evalue",
    "i_evalue",
    "dom_score",
    "dom_bias",
    "hmm_from",
    "hmm_to",
    "ali_from",
    "ali_to",
    "acc",
    "hmm_coverage",
    "neg_log10_evalue",
]


def _tsv(name: str) -> pl.DataFrame:
    return pl.read_csv(DATA / name, separator="\t")


# --- fixtures ---------------------------------------------------------------


def test_profile_table_is_the_hmm_recipes_table():
    profile = _tsv("protein_family_hmm_demo.tsv")
    assert profile.columns == list(PROFILE_SCHEMA)
    assert set(profile["entity"]) == {ENTITY}
    assert profile["position"].null_count() == 0


def test_hmm_library_matches_the_profile_table_and_the_stockholm_records():
    models = parse_hmm((DATA / "protein_family_demo.hmm").read_text())
    assert [m.name for m in models] == ["DemoFamA", "DemoFamB"]
    assert all("not hmmbuild" in (m.desc or "") for m in models)
    profile = _tsv("protein_family_hmm_demo.tsv")
    records = (DATA / "protein_family_demo.sto").read_text().split("//\n")[:-1]
    assert len(records) == len(models)
    for model, record in zip(models, records, strict=True):
        states = profile.filter(pl.col("hmm_name") == model.name)
        assert states["hmm_position"].n_unique() == model.length
        by_state = (
            states.filter(pl.col("hmm_letter") == "A").sort("hmm_position")["position"].to_list()
        )
        assert by_state == reference_positions_from_stockholm(record + "//\n", ENTITY, model.length)
        # The insert lane has something to show: a few states stand clear of the rest.
        insert = states.filter(pl.col("hmm_letter") == "A")["insert_prob"].to_list()
        assert sum(p > 5 * sorted(insert)[len(insert) // 2] for p in insert) >= 1


def test_hits_table_has_the_domtbl_columns_and_a_range_of_architectures():
    hits = _tsv("protein_family_hits_demo.tsv")
    assert hits.columns == DOMTBL_COLUMNS
    assert set(hits["label"]) == {
        "DemoFamA",
        "DemoFamB",
        "OtherFamC",
        "OtherFamD",
        "OtherFamE",
    }
    architectures = {
        tuple(group.sort("start")["label"].to_list())
        for _, group in hits.group_by("entity", maintain_order=True)
    }
    assert len(architectures) == 6
    # Fragments: domains that match only part of their HMM, on either side.
    partial = hits.filter((pl.col("hmm_from") > 1) | (pl.col("hmm_to") < pl.col("hmm_length")))
    assert partial["entity"].n_unique() >= 6
    assert (hits["start"] <= hits["ali_from"]).all()
    assert (hits["end"] >= hits["ali_to"]).all()
    assert (hits["end"] <= hits["protein_length"]).all()


def test_hit_scores_are_monotone():
    """Ranking by bit score and by E-value must agree, as in real hmmsearch output."""
    hits = _tsv("protein_family_hits_demo.tsv").sort("dom_score")
    assert hits["i_evalue"].is_sorted(descending=True)
    assert (hits["c_evalue"] <= hits["i_evalue"]).all()


def test_secondary_structure_table_compares_a_prediction_with_the_structure():
    table = _tsv("protein_ss_demo.tsv")
    assert table.columns == [
        "entity",
        "position",
        "ss_source",
        "ss_code",
        "ss_probability",
        "p_helix",
        "p_strand",
        "p_coil",
    ]
    predicted = table.filter(pl.col("ss_source") == "S4PRED").sort("position")
    structure = table.filter(pl.col("ss_source") == "structure").sort("position")
    assert predicted.height == structure.height == N_RESIDUES
    assert structure["ss_probability"].null_count() == N_RESIDUES
    ss2 = parse_ss2((DATA / f"{ENTITY}.ss2").read_text(), ENTITY).sort("position")
    assert ss2["ss_code"].to_list() == predicted["ss_code"].to_list()
    # Two deliberate disagreements, three residues each.
    differing = (predicted["ss_code"] != structure["ss_code"]).sum()
    assert differing == 6
    totals = predicted["p_helix"] + predicted["p_strand"] + predicted["p_coil"]
    assert ((totals - 1.0).abs() < 0.01).all()


def test_pae_matrix_is_square_and_in_range():
    matrix = read_pae((DATA / f"{ENTITY}.pae.tsv").read_text())
    assert len(matrix) == N_RESIDUES
    values = [v for row in matrix for v in row]
    assert 0.0 <= min(values) and max(values) <= 31.75
    residues = _tsv("protein_residues_demo.tsv")
    assert residues.height == N_RESIDUES


# --- tab bindings -----------------------------------------------------------


def _collections() -> dict[str, str]:
    project = yaml.safe_load((SHOWCASE / "project.yaml").read_text())
    return {
        dc["id"]: Path(dc["config"]["scan"]["scan_parameters"]["filename"]).name
        for workflow in project["workflows"]
        for dc in workflow["data_collections"]
    }


def _tags() -> dict[str, str]:
    project = yaml.safe_load((SHOWCASE / "project.yaml").read_text())
    return {
        dc["data_collection_tag"]: dc["id"]
        for workflow in project["workflows"]
        for dc in workflow["data_collections"]
    }


#: Companion collections a config names by id, by the prefix of their ``*_col`` fields.
COMPANION_PREFIXES = {
    "hits_": "hits_dc_id",
    "domain_": "domains_dc_id",
    "variant_": "variants_dc_id",
}


@pytest.mark.parametrize("tab", ["protein_families", "protein_quality"])
def test_every_bound_column_exists_in_its_table(tab: str):
    files = _collections()
    tags = _tags()
    document = yaml.safe_load((DASHBOARDS / f"{tab}.yaml").read_text())
    checked = 0
    for component in document["components"]:
        if "data_collection_tag" not in component:  # a text block binds nothing
            continue
        table = DATA / files[tags[component["data_collection_tag"]]]
        if component["component_type"] == "table":
            wanted = {("columns", c): table for c in component["columns"]}
        elif component["component_type"] == "interactive":
            wanted = {("column_name", component["column_name"]): table}
        elif component["component_type"] == "advanced_viz":
            wanted = {}
            for key, value in component["config"].items():
                if not key.endswith("_col") or "_for_selection" in key or value is None:
                    continue
                target = table
                for prefix, id_key in COMPANION_PREFIXES.items():
                    if key.startswith(prefix):
                        target = DATA / files[component["config"][id_key]]
                wanted[(key, value)] = target
        else:
            continue
        for (key, column), path in wanted.items():
            assert column in pl.read_csv(path, separator="\t", n_rows=0).columns, (
                f"{tab} {component['tag']}: {key}={column!r} is not a column of {path.name}"
            )
            checked += 1
    assert checked > 20


def test_second_wave_tabs_pin_ids_and_keep_compact_controls_behind_the_icon():
    ids = {
        "protein_families": ("646b0f3c1e4a2d7f8e5b8de0", 48),
        "protein_quality": ("646b0f3c1e4a2d7f8e5b8de5", 49),
    }
    for tab, (dashboard_id, order) in ids.items():
        document = yaml.safe_load((DASHBOARDS / f"{tab}.yaml").read_text())
        assert document["dashboard_id"] == dashboard_id
        assert document["tab_order"] == order
        assert document["parent_dashboard_tag"] == "volcano"
        for component in document["components"]:
            if component["component_type"] != "advanced_viz" or component["layout"]["w"] > 5:
                continue
            assert component["controls_placement"] == "popover", component["tag"]
            assert component["config"]["controls_placement"] == "popover", component["tag"]
