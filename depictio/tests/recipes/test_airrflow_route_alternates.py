"""nf-core/airrflow 5.1.0 keeps four Key figures on every route.

The Overview's four headline cards read collections a route can lose:
``--mode assembled`` and ``--skip_report`` have no pRESTO logs (airrflow parses
them inside its report step), ``--skip_clonal_analysis`` has no clones. Each
lost card has a route alternate on the same grid slot, bound to a ``_<route>``
collection that exists on that route only, and the import draws whichever card
of a slot survives. These tests pin that contract without a running stack:

* the ``annotation_counts`` recipe the assembled and no-clonal alternates read,
  on the fastq and the assembled layout of the report's Change-O table;
* for every route, the collections ``template.yaml`` keeps, whether the files
  they read exist on that route, and the Key figure each slot then shows.
"""

from __future__ import annotations

import copy
import itertools
from pathlib import Path
from typing import Any

import pytest
import yaml

from depictio.cli.cli.utils.templates import _apply_conditionals
from depictio.models.models.templates import TemplateMetadata
from depictio.recipes import RecipeError, execute_recipe, load_recipe

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "projects" / "nf-core" / "airrflow" / "5.1.0"
VERSION = "5.1.0"
RECIPE = "nf-core/airrflow/annotation_counts.py"
CHANGEO_TABLE = "repertoire_comparison/Sequence_numbers_summary/Table_sequences_assembled.tsv"

ASSEMBLED, NO_CLONAL, NO_REPORT = "ASSEMBLED_MODE", "SKIP_CLONAL_ANALYSIS", "SKIP_REPORT"

# --- annotation_counts recipe ------------------------------------------------

# The fastq route, as the 5.1.0 megatest writes it: R pads every count to one
# width, and the chain opens on IgBLAST (pRESTO fed it the representatives).
_FASTQ = (
    "sample_id\tAssignGenes-igblast\tMakeDB-igblast\tFilterQuality\tParseDb-split"
    "\tFilterJunctionMod3\tAddMetadata\tCollapseDuplicates\n"
    "S1\t 59111\t 57931\t 57820\t 57493\t 57489\t 57489\t13436\n"
    "S2\t   508\t    62\t    58\t    58\t    58\t    58\t   27\n"
)
# --mode assembled with --reassign (the default) and --remove_chimeric: the
# chain opens on ConvertDb-fasta. S4 has no conversion count, so its first
# logged stage is IgBLAST.
_ASSEMBLED = (
    "sample_id\tConvertDb-fasta\tAssignGenes-igblast\tMakeDB-igblast\tFilterQuality"
    "\tParseDb-split\tFilterJunctionMod3\tAddMetadata\tCreateGermlines\tRemoveChimeric"
    "\tCollapseDuplicates\n"
    "S3\t 1200\t 1200\t 1150\t 1149\t 1100\t 1100\t 1100\t 1100\t 1090\t 800\n"
    "S4\tNA\t  300\t  290\t  290\t  280\t  280\t  280\t  280\t  279\t 200\n"
)


def _run(tmp_path: Path, table: str):
    target = tmp_path / CHANGEO_TABLE
    target.parent.mkdir(parents=True)
    target.write_text(table)
    return execute_recipe(RECIPE, tmp_path, pipeline_version=VERSION)


def test_fastq_route_counts_from_igblast(tmp_path: Path) -> None:
    rows = {r["sample_id"]: r for r in _run(tmp_path, _FASTQ).iter_rows(named=True)}
    assert rows["S1"]["input"] == 59111
    assert rows["S1"]["productive"] == 57493
    assert rows["S1"]["collapsed"] == 13436
    assert rows["S2"]["input"] == 508
    assert rows["S2"]["collapsed"] == 27


def test_assembled_route_counts_from_the_converted_input(tmp_path: Path) -> None:
    df = _run(tmp_path, _ASSEMBLED)
    rows = {r["sample_id"]: r for r in df.iter_rows(named=True)}
    assert rows["S3"]["input"] == 1200
    assert rows["S3"]["chimera_pass"] == 1090
    assert rows["S3"]["collapsed"] == 800
    # An NA stage is a missing count: the first stage the sample did log stands in.
    assert rows["S4"]["converted"] is None
    assert rows["S4"]["input"] == 300
    assert df.columns[:3] == ["sample_id", "input", "converted"]


def test_a_table_without_the_collapse_step_fails_loudly(tmp_path: Path) -> None:
    table = "sample_id\tAssignGenes-igblast\tMakeDB-igblast\nS1\t10\t9\n"
    with pytest.raises(RecipeError, match="CollapseDuplicates"):
        _run(tmp_path, table)


# --- routes --------------------------------------------------------------------

_RAW: dict[str, Any] = yaml.safe_load((TEMPLATE_DIR / "template.yaml").read_text())
_CONDITIONALS = TemplateMetadata(**_RAW["template"]).conditional
_DASHBOARD: dict[str, Any] = yaml.safe_load((TEMPLATE_DIR / "dashboards" / "base.yaml").read_text())

# Every combination of the three flags that move the Key figures.
ROUTES = [
    frozenset(combo)
    for n in range(4)
    for combo in itertools.combinations((ASSEMBLED, NO_CLONAL, NO_REPORT), n)
]
# The other two flags leave the Key figures alone.
ALL_ROUTES = [*ROUTES, frozenset({"SKIP_THRESHOLD_REPORT"}), frozenset({"SKIP_MULTIQC"})]


def _route_id(route: frozenset[str]) -> str:
    return "+".join(sorted(route)) or "default"


def _written(route: frozenset[str]) -> set[str]:
    """Top-level folders an airrflow 5.1.0 bulk run writes on this route.

    From the 5.1.0 workflow: PARSE_LOGS runs inside REPERTOIRE_ANALYSIS_REPORTING
    and only on --mode fastq, the report writes repertoire_comparison/, and the
    clonal analysis writes clonal_analysis/.
    """
    out = {"pipeline_info"}
    if "SKIP_MULTIQC" not in route:
        out.add("multiqc")
    if not route & {ASSEMBLED, NO_REPORT}:
        out.add("parsed_logs")
    if NO_REPORT not in route:
        out.add("repertoire_comparison")
    if NO_CLONAL not in route:
        out.add("clonal_analysis")
    return out


def _resolve(route: frozenset[str]) -> dict[str, Any]:
    config, _, _ = _apply_conditionals(
        copy.deepcopy(_RAW), _CONDITIONALS, {"DATA_ROOT", *route}, TEMPLATE_DIR
    )
    return config


def _kept_dcs(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        dc["data_collection_tag"]: dc for wf in config["workflows"] for dc in wf["data_collections"]
    }


def _key_figure_cards() -> list[dict[str, Any]]:
    return [
        c
        for c in _DASHBOARD["main_dashboard"]["components"]
        if c.get("component_type") == "card" and c.get("section") == "Key figures"
    ]


def _slot(card: dict[str, Any]) -> tuple[int, int, int, int]:
    lay = card["layout"]
    return (lay["x"], lay["y"], lay["w"], lay["h"])


def _shown(route: frozenset[str]) -> dict[tuple[int, int, int, int], list[dict[str, Any]]]:
    kept = _kept_dcs(_resolve(route))
    slots: dict[tuple[int, int, int, int], list[dict[str, Any]]] = {}
    for card in _key_figure_cards():
        if card["data_collection_tag"] in kept:
            slots.setdefault(_slot(card), []).append(card)
    return slots


@pytest.mark.parametrize("route", ALL_ROUTES, ids=_route_id)
def test_every_kept_collection_has_its_files_on_the_route(route: frozenset[str]) -> None:
    """A required collection whose source folder the route never writes fails the ingest."""
    written = _written(route)
    missing: list[str] = []
    for tag, dc in _kept_dcs(_resolve(route)).items():
        recipe = ((dc.get("config") or {}).get("transform") or {}).get("recipe")
        if dc.get("optional") or not recipe:
            continue
        for source in load_recipe(recipe, VERSION).SOURCES:
            where = source.path or source.glob_pattern or ""
            if source.optional or source.dc_ref or where.startswith("**"):
                continue
            if where.split("/", 1)[0] not in written:
                missing.append(f"{tag} reads {where}")
    assert not missing, "; ".join(missing)


EXPECTED_TITLES: dict[frozenset[str], list[str]] = {
    frozenset(): ["Samples", "Input reads", "Clones", "Sequences per clone"],
    frozenset({ASSEMBLED}): ["Samples", "Input sequences", "Clones", "Sequences per clone"],
    frozenset({NO_REPORT}): ["Samples", "Sequences", "Clones", "Sequences per clone"],
    frozenset({NO_CLONAL}): ["Samples", "Input reads", "Unique sequences", "V genes"],
    frozenset({ASSEMBLED, NO_REPORT}): ["Samples", "Sequences", "Clones", "Sequences per clone"],
    frozenset({ASSEMBLED, NO_CLONAL}): [
        "Samples",
        "Input sequences",
        "Unique sequences",
        "V genes",
    ],
    # Without the report and the clones, nothing but the sample sheet is left to count.
    frozenset({NO_CLONAL, NO_REPORT}): ["Samples"],
    frozenset({ASSEMBLED, NO_CLONAL, NO_REPORT}): ["Samples"],
    frozenset({"SKIP_THRESHOLD_REPORT"}): [
        "Samples",
        "Input reads",
        "Clones",
        "Sequences per clone",
    ],
    frozenset({"SKIP_MULTIQC"}): ["Samples", "Input reads", "Clones", "Sequences per clone"],
}


@pytest.mark.parametrize("route", ALL_ROUTES, ids=_route_id)
def test_each_slot_shows_one_card(route: frozenset[str]) -> None:
    slots = _shown(route)
    doubled = {slot: [c["title"] for c in cards] for slot, cards in slots.items() if len(cards) > 1}
    assert not doubled, f"slots keeping two cards: {doubled}"
    titles = [cards[0]["title"] for _, cards in sorted(slots.items())]
    assert titles == EXPECTED_TITLES[route]
    colours = [cards[0]["display"]["icon_color"] for cards in slots.values()]
    assert len(set(colours)) == len(colours), f"repeated icon colour: {colours}"


def _surviving_tabs(kept: set[str]) -> set[str]:
    """Child tabs the import keeps: those with a visualisation whose collection survives."""
    return {
        tab["title"]
        for tab in _DASHBOARD["tabs"]
        if any(
            c.get("data_collection_tag") in kept
            for c in tab.get("components", [])
            if c.get("component_type") not in ("text", "interactive")
        )
    }


@pytest.mark.parametrize("route", ROUTES, ids=_route_id)
def test_kept_cards_open_a_kept_tab_and_follow_the_filters(route: frozenset[str]) -> None:
    config = _resolve(route)
    kept = set(_kept_dcs(config))
    tabs = _surviving_tabs(kept)
    linked = {
        link["target_dc_tag"]
        for link in config["links"]
        if link["source_dc_tag"] == "samplesheet" and link["source_column"] == "sample_id"
    }
    for cards in _shown(route).values():
        card = cards[0]
        tab = card["display"]["link"].removeprefix("tab:")
        assert tab in tabs, f"{card['title']} opens {tab}, which this route drops"
        dc = card["data_collection_tag"]
        assert dc == "samplesheet" or dc in linked, f"{dc} is not narrowed by the sample filter"
