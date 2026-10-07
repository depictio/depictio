"""The composer: a results directory in, an ordinary template out.

Runs on the bundled runs (the catalog conformance run, nf-core/viralrecon and
nf-core/ampliseq) and on small synthetic directories; nothing is ingested.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from depictio.cli.cli.utils.compose import (
    ComposedTemplate,
    Composition,
    _resolve_recipe_sources,
    compose_run,
    compose_template,
    distinct_labels,
    glob_regex,
    include_regex,
    looks_headerless,
    match_files,
    propose_unrecognised,
    walk,
)
from depictio.cli.cli.utils.compose_layout import card_row_widths
from depictio.cli.cli.utils.multiqc_parquet import parquet_plots
from depictio.models.components.advanced_viz.catalog import match_run_dir

REPO = Path(__file__).resolve().parents[4]
PROJECTS = REPO / "depictio" / "projects"
CONFORMANCE = PROJECTS / "init" / "catalog_conformance" / "run_1"
VIRALRECON = PROJECTS / "nf-core" / "viralrecon" / "3.0.0" / "run_1"
AMPLISEQ_214 = PROJECTS / "nf-core" / "ampliseq" / "2.14.0"
AMPLISEQ_216 = PROJECTS / "nf-core" / "ampliseq" / "2.16.0"


def _load(template: ComposedTemplate) -> tuple[dict, dict]:
    project = yaml.safe_load((template.template_dir / "template.yaml").read_text())
    dashboard = yaml.safe_load((template.template_dir / "dashboards/composed.yaml").read_text())
    return project, dashboard


@pytest.fixture(scope="module")
def conformance(tmp_path_factory) -> ComposedTemplate:
    result = compose_template(CONFORMANCE, out_dir=tmp_path_factory.mktemp("conformance"))
    assert isinstance(result, ComposedTemplate)
    return result


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern",
    [
        "**/multiqc/multiqc_data/multiqc.parquet",
        "**/*.tsv",
        "variants/*/variants_long_table.csv",
        "a/[bc]?.txt",
        "**/x/**/y.csv",
    ],
)
def test_glob_regex_matches_like_pathlib(tmp_path, pattern):
    for rel in [
        "multiqc/multiqc_data/multiqc.parquet",
        "deep/multiqc/multiqc_data/multiqc.parquet",
        "a.tsv",
        "d/e/f.tsv",
        "variants/ivar/variants_long_table.csv",
        "variants/ivar/deeper/variants_long_table.csv",
        "a/b1.txt",
        "a/d1.txt",
        "x/y.csv",
        "q/x/r/s/y.csv",
    ]:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x")
    import re

    regex = re.compile(glob_regex(pattern))
    expected = {p.relative_to(tmp_path).as_posix() for p in tmp_path.glob(pattern) if p.is_file()}
    assert {f for f in walk(tmp_path) if regex.match(f)} == expected


@pytest.mark.parametrize("run", [CONFORMANCE, VIRALRECON, AMPLISEQ_214, AMPLISEQ_216])
def test_one_walk_finds_what_match_run_dir_finds(run):
    def key(matches):
        return {(m.tool_id, m.output_id, m.path) for m in matches}

    assert key(match_files(walk(run))) == key(match_run_dir(run))


# ---------------------------------------------------------------------------
# The composed template
# ---------------------------------------------------------------------------


def test_tabs_follow_the_pipeline_stages(conformance):
    assert conformance.tabs == [
        "Overview",
        "Alignment & coverage",
        "Quantification",
        "Taxonomy & diversity",
        "MultiQC",
    ]


def test_every_collection_is_optional_and_scans_what_was_found(conformance):
    project, _ = _load(conformance)
    collections = {c["data_collection_tag"]: c for c in project["workflows"][0]["data_collections"]}
    assert set(collections) >= {
        "multiqc_data",
        "salmon_merged_gene_counts",
        "mosdepth_amplicon_coverage",
        "general_stats",
    }
    assert all(c["optional"] for c in collections.values())
    salmon = collections["salmon_merged_gene_counts"]["config"]["scan"]
    assert salmon == {
        "mode": "single",
        "scan_parameters": {"filename": "{DATA_ROOT}/salmon.merged.gene_counts.tsv"},
    }


def test_the_composed_dashboard_imports(conformance):
    """What the importer checks, offline: every document, section and tile model."""
    from depictio.models.components.advanced_viz.component import AdvancedVizLiteComponent
    from depictio.models.components.lite import TextLiteComponent
    from depictio.models.models.dashboards import DashboardDataLite

    _, dashboard = _load(conformance)
    documents = [dashboard["main_dashboard"], *dashboard["tabs"]]
    for document in documents:
        DashboardDataLite.model_validate(document)
        grid = {s["name"] for s in document.get("grid_sections", [])}
        filters = {s["name"] for s in document.get("filter_sections", [])}
        for component in document["components"]:
            kind = component["component_type"]
            assert component["section"] in (filters if kind == "interactive" else grid)
            if kind == "advanced_viz":
                AdvancedVizLiteComponent.model_validate(component)
            if kind == "text":
                TextLiteComponent.model_validate(component)
            if kind == "table":
                assert component["layout"]["w"] == 8
            assert set(component["layout"]) == {"x", "y", "w", "h"}


def test_card_rows_are_always_full(conformance):
    _, dashboard = _load(conformance)
    for document in [dashboard["main_dashboard"], *dashboard["tabs"]]:
        rows: dict[tuple, int] = {}
        for c in document["components"]:
            if c["component_type"] == "card":
                key = (c["section"], c["layout"]["y"])
                rows[key] = rows.get(key, 0) + c["layout"]["w"]
        assert all(width == 8 for width in rows.values()), rows


@pytest.mark.parametrize("n", range(1, 10))
def test_card_row_widths_fill_every_row(n):
    widths = card_row_widths(n)
    assert len(widths) == n
    assert sum(widths) % 8 == 0


def test_the_multiqc_tab_holds_every_plot_of_the_report(conformance):
    _, dashboard = _load(conformance)
    tab = next(t for t in dashboard["tabs"] if t["title"] == "MultiQC")
    pairs = {(c["selected_module"], c["selected_plot"]) for c in tab["components"]}
    report = CONFORMANCE / "multiqc" / "multiqc_data" / "multiqc.parquet"
    assert pairs == {(p.module, p.plot) for p in parquet_plots(report)}


def test_the_overview_carries_general_statistics(conformance):
    _, dashboard = _load(conformance)
    overview = dashboard["main_dashboard"]
    kinds = {(c["component_type"], c.get("selected_module")) for c in overview["components"]}
    assert ("multiqc", "general_stats") in kinds
    assert conformance.general_stats
    assert (conformance.template_dir / "general_stats.tsv").read_text().startswith("sample\t")
    # Every tab can be filtered by sample: a persistent filter on the report's samples.
    persistent = [s for s in overview["filter_sections"] if s.get("persistent")]
    assert persistent and persistent[0]["name"] == "Samples"


def test_composing_twice_writes_the_same_dashboard(tmp_path):
    first = compose_template(CONFORMANCE, out_dir=tmp_path / "a")
    second = compose_template(CONFORMANCE, out_dir=tmp_path / "b")
    assert isinstance(first, ComposedTemplate) and isinstance(second, ComposedTemplate)
    assert (first.template_dir / "dashboards/composed.yaml").read_text() == (
        second.template_dir / "dashboards/composed.yaml"
    ).read_text()


def test_a_recipe_reading_its_own_output_name_gets_a_raw_provider(tmp_path):
    """mosdepth's recipes read a collection named like their own output."""
    composition = compose_run(VIRALRECON)
    by_tag = {c.tag: c for c in composition.collections}
    assert by_tag["mosdepth_genome_coverage"].kind == "provider"
    view = by_tag["mosdepth_genome_coverage_view"]
    assert view.kind == "recipe" and view.needs == ["mosdepth_genome_coverage"]
    tags = [c.tag for c in composition.collections]
    assert tags.index("mosdepth_genome_coverage") < tags.index("mosdepth_genome_coverage_view")


def test_nothing_recognised_writes_nothing(tmp_path):
    (tmp_path / "notes.md").write_text("hello")
    result = compose_template(tmp_path, out_dir=tmp_path / "out")
    assert isinstance(result, Composition)
    assert not (tmp_path / "out").exists()


# ---------------------------------------------------------------------------
# Recipes pointed at the files present
# ---------------------------------------------------------------------------

ALPHA = "qiime2/alpha_diversity_multi_canonical.py"
ALPHA_FILES = [
    f"qiime2/diversity/alpha_diversity/{m}_vector/metadata.tsv"
    for m in ("shannon", "observed_features", "faith_pd", "evenness")
]


def test_a_recipe_whose_files_sit_where_it_expects_needs_no_override():
    overrides, used, needs = _resolve_recipe_sources(ALPHA, [], ALPHA_FILES[:1], set(ALPHA_FILES))
    assert overrides == {} and used == set(ALPHA_FILES) and needs == []


def test_sibling_sources_are_rerooted_under_the_matched_file():
    moved = {f"results/{f}" for f in ALPHA_FILES}
    overrides, used, _ = _resolve_recipe_sources(ALPHA, [], sorted(moved)[:1], moved)
    assert {o["path"] for o in overrides.values()} == moved
    assert used == moved


def test_a_missing_required_source_is_reported():
    present = set(ALPHA_FILES[:3])
    with pytest.raises(ValueError, match="evenness"):
        _resolve_recipe_sources(ALPHA, [], sorted(present)[:1], present)


def test_a_single_source_follows_its_file_wherever_it_is():
    found = {"star_salmon/salmon.merged.gene_tpm.tsv"}
    overrides, _, _ = _resolve_recipe_sources("salmon/sample_pca.py", [], sorted(found), found)
    assert overrides == {"matrix": {"path": "star_salmon/salmon.merged.gene_tpm.tsv"}}


# ---------------------------------------------------------------------------
# Files nothing recognises
# ---------------------------------------------------------------------------


@pytest.fixture
def run_with_unknown(tmp_path) -> Path:
    run = tmp_path / "run"
    shutil.copytree(CONFORMANCE, run)
    (run / "stats").mkdir()
    (run / "stats" / "per_sample.tsv").write_text(
        "sample\treads\tgc\tcondition\n"
        + "".join(f"S{i}\t{1000 + i * 37}\t{40 + i % 7}\t{'ab'[i % 2]}\n" for i in range(12))
    )
    return run


def test_an_unrecognised_table_is_proposed_not_added(run_with_unknown, tmp_path):
    result = compose_template(run_with_unknown, out_dir=tmp_path / "out")
    assert isinstance(result, ComposedTemplate)
    proposal = next(
        p for p in result.composition.unrecognised if p["path"] == "stats/per_sample.tsv"
    )
    assert proposal["sample_column"] == "sample"
    assert proposal["proposal"] == [
        "card: mean of reads",
        "card: mean of gc",
        "filter: sample",
        "filter: condition",
        "figure: scatter of gc against reads",
        "table",
    ]
    project, dashboard = _load(result)
    assert "Other data" not in [t["title"] for t in dashboard["tabs"]]
    listed = project["template"]["unrecognised_files"]
    assert [f["path"] for f in listed] == ["stats/per_sample.tsv"]


def test_include_unknown_adds_an_other_data_tab(run_with_unknown, tmp_path):
    result = compose_template(run_with_unknown, out_dir=tmp_path / "out", include=["stats/*.tsv"])
    assert isinstance(result, ComposedTemplate)
    project, dashboard = _load(result)
    tab = next(t for t in dashboard["tabs"] if t["title"] == "Other data")
    kinds = sorted(c["component_type"] for c in tab["components"])
    assert kinds == ["card", "card", "figure", "interactive", "interactive", "table"]
    figure = next(c for c in tab["components"] if c["component_type"] == "figure")
    assert figure["dict_kwargs"] == {"x": "reads", "y": "gc", "color": "condition"}
    assert project["template"]["unrecognised_files"] == []
    tags = [c["data_collection_tag"] for c in project["workflows"][0]["data_collections"]]
    assert "stats_per_sample" in tags


def test_template_compose_command_writes_and_reports(run_with_unknown, tmp_path):
    from depictio.cli.cli.commands.template import app

    out = tmp_path / "ejected"
    result = CliRunner().invoke(app, ["compose", str(run_with_unknown), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert (out / "template.yaml").is_file()
    text = " ".join(result.output.split())
    assert "Not recognised" in text and "stats/per_sample.tsv" in text
    assert f"depictio run --template {out}" in text


def test_template_compose_command_on_nothing(tmp_path):
    from depictio.cli.cli.commands.template import app

    result = CliRunner().invoke(app, ["compose", str(tmp_path)])
    assert result.exit_code == 1


def test_multiqc_tabs_are_named_by_what_tells_their_reports_apart():
    """nf-core/sarek writes one report per test profile: the tab says which."""
    paths = [
        "test_aws/multiqc/multiqc_data/multiqc.parquet",
        "test_full_aws/multiqc/multiqc_data/multiqc.parquet",
    ]
    assert distinct_labels(paths) == ["test_aws", "test_full_aws"]
    assert distinct_labels(
        [
            "multiqc/star_salmon/multiqc_report_data/multiqc.parquet",
            "multiqc/star_rsem/multiqc_report_data/multiqc.parquet",
        ]
    ) == ["star_salmon", "star_rsem"]
    nested = distinct_labels(["a/multiqc.parquet", "a/b/multiqc.parquet"])
    assert len(set(nested)) == 2 and all(nested)


def test_a_headerless_report_is_read_without_a_header(tmp_path):
    """A Kraken-style report has no header row: its first line is data, not names."""
    (tmp_path / "sample.kraken2.report.txt").write_text(
        "100.00\t438151\t0\tR\t1\troot\n"
        "99.50\t435960\t12\tD\t2\tBacteria\n"
        "40.10\t175699\t3\tS\t562\tEscherichia coli\n"
    )
    assert looks_headerless(["100.00", "438151", "0", "R", "1", "root"])
    assert not looks_headerless(["sample", "reads", "percent"])

    proposal = propose_unrecognised(tmp_path, "sample.kraken2.report.txt")
    assert proposal is not None
    assert proposal["_headerless"] is True
    assert proposal["proposal"][0] == "no header row: columns numbered"
    assert all(c.startswith("column_") for c in proposal["columns"])
    assert not any("100.00" in item for item in proposal["proposal"])


def test_identifier_columns_are_not_averaged(tmp_path):
    (tmp_path / "abundance.tsv").write_text(
        "name\ttaxonomy_id\ttaxID\treads\tfraction\n"
        "E. coli\t562\t562\t1200\t0.4\n"
        "B. subtilis\t1423\t1423\t900\t0.3\n"
        "S. aureus\t1280\t1280\t600\t0.2\n"
    )
    proposal = propose_unrecognised(tmp_path, "abundance.tsv")
    assert proposal is not None
    assert proposal["_numeric"] == ["reads", "fraction"]


@pytest.mark.parametrize(
    ("pattern", "path", "matches"),
    [
        ("amp/**", "amp/macrel/s1.macrel/s1.prediction.tsv", True),
        ("amp*/**", "amp/macrel/s1.tsv", True),
        ("amp/**", "arg/rgi/s1.tsv", False),
        ("*.prediction.tsv", "amp/macrel/s1.prediction.tsv", True),
        ("*penguins*", "extra_penguins.csv", True),
        ("amp/*.tsv", "amp/macrel/s1.tsv", False),
    ],
)
def test_include_globs_read_as_a_person_means_them(pattern, path, matches):
    import re

    assert bool(re.match(include_regex(pattern), path)) is matches


def test_a_named_file_is_included_past_the_listing_cap(tmp_path, monkeypatch):
    import depictio.cli.cli.utils.compose as compose

    monkeypatch.setattr(compose, "MAX_UNRECOGNISED", 2)
    for i in range(4):
        (tmp_path / f"t{i}.tsv").write_text("sample\treads\nA\t1\nB\t2\n")
    composition = compose_run(tmp_path, include=["t3.tsv"])
    included = [p["path"] for p in composition.unrecognised if p.get("_include")]
    assert included == ["t3.tsv"]
