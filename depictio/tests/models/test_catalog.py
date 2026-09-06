"""Tests for the bio-catalog: the tool→recipe→component linking table.

Covers flat-file + folder loading, the find/columns/recipe/renders_as model and
its validators, role grounding (against declared columns *and* against the
recipe's real output), match recognition, identity URLs, decoupling from the
suggestion engine, and JSON-Schema freshness.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from depictio.models.components.advanced_viz.catalog import (
    CatalogEntry,
    CatalogFind,
    CatalogOutput,
    load_catalog_entries,
    match_run_dir,
    recipe_output_columns,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Loading: flat file = one tool; folder = one tool split across files
# ---------------------------------------------------------------------------


def test_bundled_catalog_loads():
    tools = {e.id for e in load_catalog_entries()}
    assert {"pangolin", "nextclade", "ivar", "mosdepth", "qiime2", "metaphlan", "multiqc"} <= tools


def test_every_tool_is_a_folder_with_module_yaml():
    # architecture: one folder per module (module.yaml + output yamls + fixtures)
    catalog = REPO_ROOT / "depictio" / "catalog"
    entries = {e.id: e for e in load_catalog_entries()}
    for tool_id in entries:
        assert (catalog / tool_id / "module.yaml").is_file()
    assert len(entries["multiqc"].outputs) > 1  # multi-output tool
    assert len(entries["qiime2"].outputs) >= 5  # multi-output tool


def test_identity_is_stored_as_urls():
    entries = {e.id: e for e in load_catalog_entries()}
    # nf-core-backed module keeps its nf_core_url pointer; the bio.tools id is
    # declared explicitly (sourced from the nf-core meta.yml `identifier:`), since
    # nothing fetches the meta.yml at runtime to derive it.
    ivar = entries["ivar"]
    assert ivar.nf_core_url.endswith("/modules/nf-core/ivar/variants")
    assert ivar.biotools_url == "https://bio.tools/andersen-lab_ivar"
    # QIIME 2 has no single nf-core module → identity stays declared in full,
    # and when declared it must be a full URL (not a bare id).
    qiime2 = entries["qiime2"]
    assert qiime2.biotools_url == "https://bio.tools/qiime2"
    assert qiime2.nf_core_url is None


# ---------------------------------------------------------------------------
# find
# ---------------------------------------------------------------------------


def test_find_requires_a_condition():
    with pytest.raises(ValueError, match="at least one"):
        CatalogFind()


def test_find_path_glob_alt_requires_canonical():
    with pytest.raises(ValueError, match="path_glob_alt requires path_glob"):
        CatalogFind(filename="*.csv", path_glob_alt=["**/tool/*/*.csv"])
    with pytest.raises(ValueError, match="path_glob_alt requires path_glob"):
        CatalogFind(path_glob_alt=["**/tool/*/*.csv"])
    find = CatalogFind(path_glob="**/tool/x.csv", path_glob_alt=["**/tool/*/x.csv"])
    assert find.path_globs() == ["**/tool/x.csv", "**/tool/*/x.csv"]
    assert CatalogFind(filename="*.csv").path_globs() == []


# The two MultiQC report layouts every parquet output must recognise, plus the
# same nested report sitting deeper under an aligner-specific results tree.
CANONICAL_MULTIQC = "run_1/multiqc/multiqc_data/multiqc.parquet"
NESTED_MULTIQC = "run_1/multiqc/star_salmon/multiqc_report_data/multiqc.parquet"  # rnaseq
DEEP_NESTED_MULTIQC = (
    "results/aligner_star_salmon/multiqc/star_salmon/multiqc_report_data/multiqc.parquet"
)


def _multiqc_parquet_outputs() -> list[CatalogOutput]:
    return [
        o
        for e in load_catalog_entries()
        for o in e.outputs
        if o.find.path_glob and o.find.path_glob.endswith("multiqc.parquet")
    ]


def test_every_multiqc_parquet_output_accepts_both_layouts():
    """`PurePosixPath.match` (the compose endpoint's primitive) reads `**` as one
    segment and `full_match` is 3.13-only, so the canonical glob alone cannot
    reach a nested report dir: that is what `path_glob_alt` carries."""
    outputs = _multiqc_parquet_outputs()
    assert len(outputs) >= 15
    for output in outputs:
        globs = output.find.path_globs()
        assert len(globs) > 1, output.id
        # the guard is only meaningful while the canonical glob misses the nested layout
        assert not PurePosixPath(NESTED_MULTIQC).match(output.find.path_glob), output.id
        for layout in (CANONICAL_MULTIQC, NESTED_MULTIQC, DEEP_NESTED_MULTIQC):
            assert any(PurePosixPath(layout).match(g) for g in globs), (output.id, layout)


# ---------------------------------------------------------------------------
# columns ownership: the recipe owns output columns; no duplication in YAML
# ---------------------------------------------------------------------------


def _output(**kw) -> dict:
    base = {"id": "o", "find": {"filename": "*.csv"}}
    base.update(kw)
    return base


def test_recipe_and_columns_are_mutually_exclusive():
    with pytest.raises(ValueError, match="recipe is set"):
        CatalogOutput.model_validate(_output(recipe="nf-core/x/y.py", columns={"a": "String"}))


def test_roles_without_columns_or_recipe_is_rejected():
    with pytest.raises(ValueError, match="no 'columns', 'recipe' or 'fixture'"):
        CatalogOutput.model_validate(
            _output(
                renders_as=[
                    {"component": "advanced_viz", "kind": "manhattan", "roles": {"chr": "c"}}
                ]
            )
        )


def test_no_recipe_roles_must_bind_to_declared_columns():
    with pytest.raises(ValueError, match="unknown column"):
        CatalogOutput.model_validate(
            _output(
                columns={"chrom": "String", "start": "Int64", "value": "Float64"},
                renders_as=[
                    {
                        "component": "advanced_viz",
                        "kind": "coverage_track",
                        "roles": {"chromosome": "chrom", "position": "start", "value": "NOPE"},
                    }
                ],
            )
        )


def test_unknown_dtype_rejected():
    with pytest.raises(ValueError, match="unknown dtype"):
        CatalogOutput.model_validate(_output(columns={"a": "Flaot64"}))


# ---------------------------------------------------------------------------
# renders_as
# ---------------------------------------------------------------------------


def test_advanced_viz_requires_kind():
    with pytest.raises(ValueError, match="requires a 'kind'"):
        CatalogOutput.model_validate(
            _output(columns={"a": "String"}, renders_as=[{"component": "advanced_viz"}])
        )


def test_unknown_role_for_viz_rejected():
    with pytest.raises(ValueError, match="unknown role"):
        CatalogOutput.model_validate(
            _output(
                columns={"a": "String"},
                renders_as=[
                    {"component": "advanced_viz", "kind": "manhattan", "roles": {"bogus": "a"}}
                ],
            )
        )


def test_kind_forbidden_on_non_advanced_component():
    with pytest.raises(ValueError, match="only valid for component=advanced_viz"):
        CatalogOutput.model_validate(
            _output(columns={"a": "String"}, renders_as=[{"component": "table", "kind": "volcano"}])
        )


def test_table_and_multiqc_plot_need_no_columns():
    # non-tabular renders are allowed without recipe/columns/roles
    CatalogOutput.model_validate(_output(renders_as=[{"component": "table"}]))
    CatalogOutput.model_validate(
        _output(renders_as=[{"component": "multiqc", "section": "fastqc"}])
    )


def test_component_must_be_a_real_depictio_type():
    # `component` is validated against the real ComponentType registry (+ multiqc)
    with pytest.raises(ValueError):
        CatalogOutput.model_validate(_output(renders_as=[{"component": "multiqc_plot"}]))
    with pytest.raises(ValueError):
        CatalogOutput.model_validate(_output(renders_as=[{"component": "not_a_component"}]))
    # components that need no extra binding fields are valid bare
    for comp in ("table", "jbrowse", "text", "image", "map", "multiqc"):
        CatalogOutput.model_validate(_output(renders_as=[{"component": comp}]))


def test_identity_url_format_is_validated():
    from depictio.models.components.advanced_viz.catalog import CatalogTool

    with pytest.raises(ValueError, match="bio.tools"):
        CatalogTool.model_validate(
            {"id": "x", "name": "X", "biotools_url": "https://example.com/x"}
        )
    with pytest.raises(ValueError, match="nf-core/modules"):
        CatalogTool.model_validate({"id": "x", "name": "X", "nf_core_url": "https://github.com/x"})
    with pytest.raises(ValueError, match="edamontology"):
        CatalogTool.model_validate({"id": "x", "name": "X", "edam_topics": ["topic_3174"]})


def test_source_url_scheme_is_validated():
    from depictio.models.components.advanced_viz.catalog import CatalogTool

    # A Snakemake/Galaxy source URL has no authority to check — only its scheme.
    tool = CatalogTool.model_validate(
        {
            "id": "x",
            "name": "X",
            "source_url": "https://github.com/snakemake/snakemake-wrappers/tree/master/bio/x",
        }
    )
    assert tool.source_url.endswith("/bio/x")
    with pytest.raises(ValueError, match="http"):
        CatalogTool.model_validate({"id": "x", "name": "X", "source_url": "ftp://nope"})


def test_output_edam_operation_prefix_enforced():
    with pytest.raises(ValueError, match="operation_"):
        CatalogOutput.model_validate(
            _output(
                columns={"a": "String"},
                edam_operations=["http://edamontology.org/format_3752"],  # wrong category
                renders_as=[{"component": "table"}],
            )
        )


# ---------------------------------------------------------------------------
# figure (UI + code mode) + card renders
# ---------------------------------------------------------------------------


def test_figure_render_ui_and_code_modes():
    CatalogOutput.model_validate(  # UI mode
        _output(
            columns={"habitat": "String", "shannon": "Float64"},
            renders_as=[
                {
                    "component": "figure",
                    "visu_type": "box",
                    "dict_kwargs": {"x": "habitat", "y": "shannon"},
                }
            ],
        )
    )
    CatalogOutput.model_validate(  # code mode
        _output(renders_as=[{"component": "figure", "code": "fig = px.box(df)"}])
    )
    with pytest.raises(ValueError, match="requires 'visu_type'"):
        CatalogOutput.model_validate(_output(renders_as=[{"component": "figure"}]))


def test_card_render_requires_column_and_aggregation():
    CatalogOutput.model_validate(
        _output(
            columns={"shannon": "Float64"},
            renders_as=[{"component": "card", "column": "shannon", "aggregation": "average"}],
        )
    )
    with pytest.raises(ValueError, match="card requires"):
        CatalogOutput.model_validate(_output(renders_as=[{"component": "card", "column": "x"}]))


def test_multi_metric_card_with_secondary_aggregations():
    CatalogOutput.model_validate(  # hero + secondary aggregations = multi-metric card
        _output(
            columns={"shannon": "Float64"},
            renders_as=[
                {
                    "component": "card",
                    "column": "shannon",
                    "aggregation": "average",
                    "aggregations": ["median", "min", "max", "std_dev"],
                }
            ],
        )
    )
    with pytest.raises(ValueError):  # unknown aggregation rejected (typed)
        CatalogOutput.model_validate(
            _output(
                columns={"a": "Float64"},
                renders_as=[{"component": "card", "column": "a", "aggregation": "avrage"}],
            )
        )
    with pytest.raises(ValueError, match="card fields"):  # card kwargs scoped to card
        CatalogOutput.model_validate(
            _output(
                columns={"a": "String"},
                renders_as=[{"component": "table", "aggregations": ["median"]}],
            )
        )


def test_figure_and_card_fields_are_component_scoped():
    with pytest.raises(ValueError, match="figure fields"):
        CatalogOutput.model_validate(
            _output(
                columns={"a": "String"}, renders_as=[{"component": "table", "visu_type": "box"}]
            )
        )
    with pytest.raises(ValueError, match="card fields"):
        CatalogOutput.model_validate(
            _output(columns={"a": "String"}, renders_as=[{"component": "table", "column": "a"}])
        )


def test_bound_columns_covers_roles_dict_kwargs_and_card_column():
    from depictio.models.components.advanced_viz.catalog import Render

    fig = Render.model_validate(
        {
            "component": "figure",
            "visu_type": "box",
            "dict_kwargs": {"x": "habitat", "y": "shannon", "title": "t"},
        }
    )
    assert fig.bound_columns() == {"habitat", "shannon"}  # 'title' is not a column kwarg
    card = Render.model_validate(
        {"component": "card", "column": "shannon", "aggregation": "average"}
    )
    assert card.bound_columns() == {"shannon"}
    code = Render.model_validate({"component": "figure", "code": "fig = px.box(df)"})
    assert code.bound_columns() == set()  # code mode is free-form


def test_alpha_diversity_has_code_figure_and_metric_cards():
    out = next(
        o
        for e in load_catalog_entries()
        if e.id == "qiime2"
        for o in e.outputs
        if o.id == "qiime2_alpha_diversity"
    )
    components = [r.component for r in out.renders_as]
    assert components.count("card") == 4 and "figure" in components
    fig = next(r for r in out.renders_as if r.component == "figure")
    assert fig.code and "fig = px.box" in fig.code  # code-mode figure
    card = next(r for r in out.renders_as if r.component == "card")
    # Tukey card: median hero (the box's own centre) + the box_plot_stats
    # aggregation, which is what makes the server compute the strip at all.
    assert card.aggregation == "median" and card.secondary_layout == "box_plot"
    assert card.aggregations == ["box_plot_stats"]
    assert out.fixture == "alpha_diversity.tsv"  # co-located in qiime2/


def test_every_bundled_card_declares_a_secondary_strip():
    """No bundled card is a bare hero number.

    A lone aggregate says nothing about spread or composition, so every card the
    catalog offers declares a secondary layout — and the two families that are
    computed from an aggregation list (`box_plot` and the stats layouts) declare
    that list too, since the server keys the computation off it and a card with
    the layout but no `aggregations` renders as a bare number.
    """
    from depictio.api.v1.services.card_metrics import NUMERIC_LAYOUTS

    # Layouts that carry their own config field instead of an aggregation list.
    SELF_DESCRIBING = {"top_n", "concentration", "composition", "donut", "coverage", "gauge"}
    bare: list[str] = []
    missing_aggs: list[str] = []
    for entry in load_catalog_entries():
        for output in entry.outputs:
            for render in output.renders_as:
                if render.component != "card":
                    continue
                where = f"{entry.id}/{output.id}:{render.column}"
                layout = render.secondary_layout
                if not layout:
                    bare.append(where)
                elif layout not in SELF_DESCRIBING and layout not in NUMERIC_LAYOUTS:
                    if not render.aggregations:
                        missing_aggs.append(f"{where} ({layout})")
    assert bare == [], f"cards with no secondary strip: {bare}"
    assert missing_aggs == [], f"cards whose layout needs `aggregations`: {missing_aggs}"


def test_fixture_is_co_located_and_readable():
    from depictio.models.components.advanced_viz.catalog import read_fixture_columns

    out = next(
        o
        for e in load_catalog_entries()
        if e.id == "qiime2"
        for o in e.outputs
        if o.id == "qiime2_alpha_diversity"
    )
    fx = out.fixture_file()  # resolved next to qiime2/alpha_diversity.yaml
    assert fx is not None and fx.parent.name == "qiime2" and fx.exists()
    cols = read_fixture_columns(fx)
    assert {"sample_id", "shannon", "evenness", "faith_pd"} <= set(cols)


# ---------------------------------------------------------------------------
# Role grounding against the recipe's REAL output columns (the CI guarantee)
# ---------------------------------------------------------------------------


def test_all_recipe_output_roles_resolve_against_the_recipe():
    for entry in load_catalog_entries():
        for out in entry.outputs:
            if not out.recipe:
                continue
            cols = set(recipe_output_columns(out.recipe))  # raises if recipe missing
            for r in out.renders_as:
                # A role binds either one column or a list of them (sunburst ranks,
                # sankey steps, complex_heatmap row_annotation_cols), so flatten before
                # comparing. Taking set(roles.values()) raises on the list-valued ones,
                # which turned this assertion into a crash instead of a check.
                role_cols: set[str] = set()
                for value in r.roles.values():
                    if isinstance(value, str):
                        role_cols.add(value)
                    elif isinstance(value, (list, tuple)):
                        role_cols.update(v for v in value if isinstance(v, str))
                missing = role_cols - cols
                assert not missing, (
                    f"{out.id} render {r.kind}: roles {sorted(missing)} "
                    f"not in recipe output {sorted(cols)}"
                )


def test_ivar_roles_match_recipe_output():
    entry = next(e for e in load_catalog_entries() if e.id == "ivar")
    ivar = next(o for o in entry.outputs if o.id == "ivar_variants_long")
    cols = set(recipe_output_columns(ivar.recipe))
    assert {"sample", "CHROM", "POS", "AF", "GENE", "EFFECT"} <= cols  # post-recipe (sample, AF)


# ---------------------------------------------------------------------------
# Recognition
# ---------------------------------------------------------------------------


def test_match_run_dir_recognises_bundled_viralrecon_files():
    run = REPO_ROOT / "depictio" / "projects" / "nf-core" / "viralrecon" / "3.0.0" / "run_1"
    if not run.exists():
        pytest.skip("bundled viralrecon run_1 not present")
    by_output = {m.output_id: m for m in match_run_dir(run)}
    assert "mosdepth_genome_coverage" in by_output
    # MultiQC is surfaced as one output per module (multiqc_fastqc, multiqc_samtools…)
    assert any(oid.startswith("multiqc_") for oid in by_output)
    # matches carry the viz they render (the dashboard building blocks)
    assert "advanced_viz:coverage_track" in by_output["mosdepth_genome_coverage"].renders


def test_compose_run_dir_groups_modules_with_their_viz():
    from depictio.models.components.advanced_viz.catalog import compose_run_dir

    run = REPO_ROOT / "depictio" / "projects" / "nf-core" / "viralrecon" / "3.0.0" / "run_1"
    if not run.exists():
        pytest.skip("bundled viralrecon run_1 not present")
    by_tool = compose_run_dir(run)
    # pipeline-agnostic composition: recognised modules grouped, each with renders
    assert "mosdepth" in by_tool and "multiqc" in by_tool
    assert all(isinstance(m.renders, list) for ms in by_tool.values() for m in ms)
    # a component without a kind renders as just "component" (no ":kind")
    assert by_tool["multiqc"][0].renders == ["multiqc"]


def test_match_run_dir_confirm_with_versions_scopes_by_software_versions(tmp_path):
    # ivar + pangolin files present, but software_versions.yml lists only ivar
    (tmp_path / "variants_long_table.csv").write_text("x\n")  # → ivar find
    (tmp_path / "sample.pangolin.csv").write_text("x\n")  # → pangolin find
    (tmp_path / "software_versions.yml").write_text(
        "IVAR_VARIANTS:\n  ivar: '1.4'\nWORKFLOW:\n  nf-core/viralrecon: 3.0.0\n"
    )
    unconfirmed = {m.tool_id for m in match_run_dir(tmp_path)}
    assert {"ivar", "pangolin"} <= unconfirmed
    confirmed = {m.tool_id for m in match_run_dir(tmp_path, confirm_with_versions=True)}
    assert "ivar" in confirmed and "pangolin" not in confirmed  # scoped to executed tools


def test_confirm_with_versions_is_noop_without_versions_file(tmp_path):
    (tmp_path / "variants_long_table.csv").write_text("x\n")
    # no software_versions.yml → confirm must not filter (non-breaking)
    assert {m.tool_id for m in match_run_dir(tmp_path, confirm_with_versions=True)} == {"ivar"}


def test_match_run_dir_recognises_nested_report_data_layout(tmp_path):
    """rnaseq writes multiqc/star_salmon/multiqc_report_data/, not multiqc/multiqc_data/."""
    nested = tmp_path / "multiqc" / "star_salmon" / "multiqc_report_data" / "multiqc.parquet"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"x")
    matches = [m for m in match_run_dir(tmp_path) if m.tool_id == "multiqc"]
    assert {m.output_id for m in matches} == {o.id for o in _multiqc_parquet_outputs()}
    assert {m.path for m in matches} == {"multiqc/star_salmon/multiqc_report_data/multiqc.parquet"}


def test_match_run_dir_reports_a_file_reached_by_two_globs_once(tmp_path):
    """The canonical layout satisfies both `path_glob` and the `*_data` alt."""
    canonical = tmp_path / "multiqc" / "multiqc_data" / "multiqc.parquet"
    canonical.parent.mkdir(parents=True)
    canonical.write_bytes(b"x")
    matches = [m for m in match_run_dir(tmp_path) if m.tool_id == "multiqc"]
    output_ids = [m.output_id for m in matches]
    assert len(output_ids) == len(set(output_ids))
    assert set(output_ids) == {o.id for o in _multiqc_parquet_outputs()}


# ---------------------------------------------------------------------------
# Existence checks against the vendored indices (nf-core + EDAM)
# ---------------------------------------------------------------------------


def test_existence_check_passes_on_bundled_catalog():
    from depictio.models.components.advanced_viz.catalog import check_existence

    assert check_existence(load_catalog_entries()) == []


def test_existence_check_flags_unknown_module_and_edam():
    from depictio.models.components.advanced_viz.catalog import check_existence

    entry = CatalogEntry.model_validate(
        {
            "id": "x",
            "name": "X",
            # well-formed URL (passes format) but not a real module:
            "nf_core_url": "https://github.com/nf-core/modules/tree/master/modules/nf-core/bogusmod",
            "edam_topics": ["http://edamontology.org/topic_9999999"],  # well-formed, nonexistent
            "outputs": [
                {"id": "x_o", "find": {"filename": "*.csv"}, "renders_as": [{"component": "table"}]}
            ],
        }
    )
    problems = check_existence([entry])
    assert any("bogusmod" in p for p in problems)
    assert any("topic_9999999" in p for p in problems)


# ---------------------------------------------------------------------------
# Fixture aspect: every fixture reads + grounds its renders; recipes resolve
# ---------------------------------------------------------------------------


def test_every_fixture_reads_and_grounds_its_renders():
    from depictio.models.components.advanced_viz.catalog import read_fixture_columns

    seen = 0
    for entry in load_catalog_entries():
        for out in entry.outputs:
            fx = out.fixture_file()
            if fx is None:
                continue
            seen += 1
            cols = set(read_fixture_columns(fx))  # reads (csv/tsv/parquet) or raises
            for r in out.renders_as:
                missing = r.bound_columns() - cols
                assert not missing, (
                    f"{out.id} render {r.kind or r.component}: {sorted(missing)} ∉ fixture"
                )
    assert seen >= 8  # most tabular outputs carry a co-located fixture


def test_every_recipe_resolves_to_a_real_file():
    for entry in load_catalog_entries():
        for out in entry.outputs:
            if out.recipe:
                recipe_output_columns(out.recipe)  # raises RecipeError if missing


def test_module_owned_recipes_are_co_located_in_the_module_folder():
    # A module-owned recipe ref is `<module>/<name>.py` and the file lives next to
    # the module's YAMLs — the tool owns its reshape, pipeline-agnostically.
    from depictio.recipes import CATALOG_DIR, resolve_recipe_path

    seen = 0
    for entry in load_catalog_entries():
        for out in entry.outputs:
            ref = out.recipe or ""
            if "/" not in ref or ref.startswith("nf-core/"):
                continue  # pipeline-keyed legacy ref (kept for version-specific reshapes)
            seen += 1
            module, name = ref.split("/")
            assert module == entry.id, f"{ref} must be owned by module '{entry.id}'"
            resolved = resolve_recipe_path(ref)
            assert resolved == CATALOG_DIR / module / name
            assert resolved.parent.name == entry.id and resolved.exists()
    assert seen >= 6  # ivar, nextclade, pangolin, mosdepth(x2), qiime2(x4)


def test_legacy_pipeline_keyed_recipe_still_resolves():
    # Pipeline-version-specific reshapes stay under projects/<pipeline>/recipes/.
    from depictio.recipes import resolve_recipe_path

    shared = resolve_recipe_path("nf-core/ampliseq/taxonomy_rel_abundance.py")
    assert shared.parts[-2:] == ("recipes", "taxonomy_rel_abundance.py")
    override = resolve_recipe_path("nf-core/ampliseq/taxonomy_rel_abundance.py", "2.14.0")
    assert "2.14.0" in override.parts  # version override still wins


def test_fixtures_are_co_located_with_their_module():
    # each fixture is a bare filename, resolved inside its module's folder —
    # EXCEPT multiqc, which reuses the bundled nf-core pipeline multiqc.parquet
    # under projects/ via a relative path (no per-module copy).
    for entry in load_catalog_entries():
        for out in entry.outputs:
            if not out.fixture:
                continue
            if "/" in out.fixture:  # escaping fixture (multiqc → projects/ parquet)
                fx = out.fixture_file()
                assert fx is not None and fx.exists()
                continue
            assert "/" not in out.fixture  # bare filename, not a path
            fx = out.fixture_file()
            assert fx is not None and fx.exists()
            assert fx.parent.name == entry.id  # lives in the module folder


def test_card_top_n_requires_breakdown_col():
    with pytest.raises(ValueError, match="requires 'breakdown_col'"):
        CatalogOutput.model_validate(
            _output(
                columns={"x": "String"},
                renders_as=[
                    {
                        "component": "card",
                        "column": "x",
                        "aggregation": "count",
                        "secondary_layout": "top_n",
                    }
                ],
            )
        )


def test_card_coverage_requires_coverage_max():
    with pytest.raises(ValueError, match="requires 'coverage_max'"):
        CatalogOutput.model_validate(
            _output(
                columns={"x": "Int64"},
                renders_as=[
                    {
                        "component": "card",
                        "column": "x",
                        "aggregation": "count",
                        "secondary_layout": "coverage",
                    }
                ],
            )
        )


# ---------------------------------------------------------------------------
# CLI integration (via CliRunner) — the commands a contributor/CI runs
# ---------------------------------------------------------------------------


def _cli():
    from typer.testing import CliRunner

    # `app` holds the user-facing commands (list/info); `dev_app` holds the
    # maintainer/CI commands (validate/columns/schema/refresh-index/match/compose)
    # that live under the hidden `depictio dev catalog` group.
    from depictio.cli.cli.commands.catalog import app, dev_app

    return CliRunner(), app, dev_app


def test_cli_validate_exits_zero_on_bundled_catalog():
    runner, _app, dev_app = _cli()
    result = runner.invoke(dev_app, ["validate"])
    assert result.exit_code == 0, result.stdout


def test_cli_commands_smoke():
    runner, app, dev_app = _cli()
    run = REPO_ROOT / "depictio" / "projects" / "nf-core" / "viralrecon" / "3.0.0" / "run_1"
    user_facing = (
        ["list"],
        ["info", "qiime2"],
    )
    maintainer = (
        ["columns", "qiime2/ancombc.py"],  # module-owned recipe (co-located in catalog/qiime2/)
        ["schema"],
        ["schema", "--model", "module"],
        ["schema", "--model", "output"],
        ["match", str(run)],
        ["compose", str(run)],
        # The three snapshot generators tool-studio's build depends on. They
        # were never smoke-tested, which is how `figure-params` shipped printing
        # a DEBUG line before its JSON.
        ["kinds"],
        ["manifest"],
        ["figure-params"],
    )
    for args in user_facing:
        result = runner.invoke(app, args)
        assert result.exit_code == 0, f"{args} → {result.stdout}"
    for args in maintainer:
        result = runner.invoke(dev_app, args)
        assert result.exit_code == 0, f"dev {args} → {result.stdout}"


@pytest.mark.parametrize("command", ["kinds", "manifest", "figure-params", "schema"])
def test_cli_json_output_is_machine_readable(command):
    """`--json` must put NOTHING on stdout but the payload.

    tool-studio's `genKinds.ts` only checks that stdout starts with `{`; a
    stray log line in front means it silently keeps the committed snapshot
    instead of regenerating, so the drift check then passes against a stale
    file. `figure-params` did exactly this (depictio's logger writes to stdout).
    """
    import json

    runner, _app, dev_app = _cli()
    args = [command] if command == "schema" else [command, "--json"]
    result = runner.invoke(dev_app, args)
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)  # raises if anything precedes the JSON
    assert isinstance(payload, dict) and payload


def test_cli_schema_rejects_an_unknown_model():
    runner, _app, dev_app = _cli()
    result = runner.invoke(dev_app, ["schema", "--model", "nonsense"])
    assert result.exit_code == 1
    assert "nonsense" in result.stdout


# ---------------------------------------------------------------------------
# Dtype grounding: bindings must be dtype-compatible, not just name-present
# ---------------------------------------------------------------------------


def test_ground_render_dtypes():
    from depictio.models.components.advanced_viz.catalog import Render, ground_render_dtypes

    dtypes = {"chrom": "String", "start": "Int64", "coverage": "Float64", "region": "String"}

    # advanced_viz: a numeric role fed a String column is flagged; correct is not.
    bad = Render(
        component="advanced_viz",
        kind="coverage_track",
        roles={"chromosome": "chrom", "position": "start", "value": "region"},
    )
    assert any("value" in p and "region" in p for p in ground_render_dtypes("o", bad, dtypes))
    ok = Render(
        component="advanced_viz",
        kind="coverage_track",
        roles={"chromosome": "chrom", "position": "start", "value": "coverage"},
    )
    assert ground_render_dtypes("o", ok, dtypes) == []

    # card: a numeric aggregation on a String column is flagged; on numeric it's fine.
    card_bad = Render(component="card", column="region", aggregation="average")
    assert ground_render_dtypes("o", card_bad, dtypes)
    card_ok = Render(component="card", column="coverage", aggregation="average")
    assert ground_render_dtypes("o", card_ok, dtypes) == []
    # count/nunique/min/max work on any dtype.
    card_count = Render(component="card", column="region", aggregation="count")
    assert ground_render_dtypes("o", card_count, dtypes) == []

    # No dtype info (e.g. a recipe output) → checks are skipped.
    assert ground_render_dtypes("o", bad, {}) == []


# ---------------------------------------------------------------------------
# read_fixture_schema: the dtypes every binding is grounded against
# ---------------------------------------------------------------------------


def test_read_fixture_schema_csv_and_tsv(tmp_path):
    from depictio.models.components.advanced_viz.catalog import read_fixture_schema

    csv = tmp_path / "a.csv"
    csv.write_text("gene,cov,flag\nBRCA1,120,true\nTP53,98,false\n")
    assert read_fixture_schema(csv) == {"gene": "String", "cov": "Int64", "flag": "Boolean"}

    tsv = tmp_path / "a.tsv"
    tsv.write_text("gene\tcov\nBRCA1\t120\n")
    assert read_fixture_schema(tsv) == {"gene": "String", "cov": "Int64"}


def test_read_fixture_schema_all_empty_column_is_a_string_not_a_hole(tmp_path):
    from depictio.models.components.advanced_viz.catalog import read_fixture_schema

    csv = tmp_path / "a.csv"
    csv.write_text("gene,note\nBRCA1,\nTP53,\n")
    # A Null dtype would match no role spec and no numeric aggregation, so an
    # all-empty column would fail every binding rather than simply being unused.
    assert read_fixture_schema(csv)["note"] == "String"


def test_read_fixture_schema_parquet_dtypes_are_not_parametrised(tmp_path):
    """`ALLOWED_DTYPES` and the role specs speak base names.

    `str(pl.Datetime)` is `Datetime(time_unit='us', time_zone=None)`, which
    matches nothing — a parquet fixture with a datetime or list column used to
    make every binding to it look like a dtype error.
    """
    import datetime

    import polars as pl

    from depictio.models.components.advanced_viz.catalog import (
        ALLOWED_DTYPES,
        read_fixture_schema,
    )

    path = tmp_path / "a.parquet"
    pl.DataFrame(
        {"when": [datetime.datetime(2024, 1, 1)], "many": [[1, 2]], "value": [1.5]}
    ).write_parquet(path)
    schema = read_fixture_schema(path)
    assert schema == {"when": "Datetime", "many": "List", "value": "Float64"}
    assert set(schema.values()) <= ALLOWED_DTYPES


# ---------------------------------------------------------------------------
# Fixture sanity: a fixture that grounds everything and shows nothing
# ---------------------------------------------------------------------------


def _write_tool(directory, tool_id, fixture_text, fixture_name="results.csv"):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "module.yaml").write_text(f"id: {tool_id}\nname: {tool_id}\n")
    (directory / "results.yaml").write_text(
        f'id: {tool_id}_results\nfind: {{path_glob: "**/{tool_id}/*.csv"}}\n'
        f"fixture: {fixture_name}\n"
        "renders_as:\n  - {{ component: card, column: a, aggregation: count }}\n".replace(
            "{{", "{"
        ).replace("}}", "}")
    )
    (directory / fixture_name).write_text(fixture_text)


def test_validate_rejects_a_fixture_with_no_data_rows(tmp_path):
    runner, _app, dev_app = _cli()
    _write_tool(tmp_path / "emptyfix", "emptyfix", "a,b\n")
    result = runner.invoke(dev_app, ["validate", "--path", str(tmp_path / "emptyfix")])
    assert result.exit_code == 1
    assert "no data rows" in result.stdout


def test_validate_rejects_a_fixture_copied_from_another_tool(tmp_path):
    # The failure mode PR #904 shipped: a demo table dropped in as the sample
    # for an unrelated output. Grounding is happy; the entry describes nothing.
    runner, _app, dev_app = _cli()
    shared = "a,b\n1,2\n"
    _write_tool(tmp_path / "toola", "toola", shared)
    _write_tool(tmp_path / "toolb", "toolb", shared)
    result = runner.invoke(dev_app, ["validate", "--path", str(tmp_path)])
    assert result.exit_code == 1
    assert "byte-identical" in result.stdout


def test_validate_allows_two_outputs_of_one_tool_to_share_a_fixture(tmp_path):
    runner, _app, dev_app = _cli()
    directory = tmp_path / "sametool"
    _write_tool(directory, "sametool", "a,b\n1,2\n")
    (directory / "second.yaml").write_text(
        'id: sametool_second\nfind: {path_glob: "**/sametool/*.tsv"}\n'
        "fixture: results.csv\n"
        "renders_as:\n  - { component: card, column: b, aggregation: count }\n"
    )
    result = runner.invoke(dev_app, ["validate", "--path", str(directory)])
    assert result.exit_code == 0, result.stdout


# ---------------------------------------------------------------------------
# nf-core URL normalisation + per-layout card requirements
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/nf-core/modules/tree/master/modules/nf-core/ivar/consensus",
        "https://github.com/nf-core/modules/tree/master/modules/nf-core/ivar/consensus/meta.yml",
        "https://github.com/nf-core/modules/tree/master/modules/nf-core/ivar/consensus/main.nf",
        "https://github.com/nf-core/modules/tree/master/modules/nf-core/ivar/consensus/",
    ],
)
def test_nf_core_module_is_read_from_the_url_the_docs_link_to(url):
    """The docs link to meta.yml; the vendored index holds module directories.

    Existence checking compares the two, so without this the real modules a
    contributor pastes were rejected as unknown.
    """
    from depictio.models.components.advanced_viz.catalog import _nf_core_module

    assert _nf_core_module(url) == "ivar/consensus"


def test_nf_core_module_ignores_a_non_module_url():
    from depictio.models.components.advanced_viz.catalog import _nf_core_module

    assert _nf_core_module("https://example.org/tool") is None
    assert _nf_core_module(None) is None


@pytest.mark.parametrize(
    ("layout", "companion"),
    [
        ("top_n", {"breakdown_col": "sample"}),
        ("concentration", {"breakdown_col": "sample"}),
        ("composition", {"breakdown_col": "sample"}),
        ("donut", {"breakdown_col": "sample"}),
        ("coverage", {"coverage_max": 100.0}),
        ("gauge", {"coverage_max": 100.0}),
        ("threshold", {"threshold_value": 30.0}),
        ("attrition", {"attrition_cols": ["mapped"]}),
        ("trend", {"trend_col": "day"}),
    ],
)
def test_card_layout_requires_its_companion_field(layout, companion):
    """Each secondary_layout needs a companion field; tool-studio mirrors this
    table in `cardRules.ts` so the author is told before CI is."""
    from pydantic import ValidationError as PydanticValidationError

    from depictio.models.components.advanced_viz.catalog import Render

    base = {"component": "card", "column": "cov", "aggregation": "average"}
    with pytest.raises(PydanticValidationError):
        Render(**base, secondary_layout=layout)
    Render(**base, secondary_layout=layout, **companion)  # complete → accepted


@pytest.mark.parametrize("layout", ["vertical", "compact", "grid", "box_plot", "histogram"])
def test_card_layouts_with_no_companion_field(layout):
    from depictio.models.components.advanced_viz.catalog import Render

    Render(component="card", column="cov", aggregation="average", secondary_layout=layout)


def test_card_bound_columns_include_the_layout_companions():
    """trend/attrition bind extra columns, so grounding must see them."""
    from depictio.models.components.advanced_viz.catalog import Render

    trend = Render(
        component="card",
        column="cov",
        aggregation="average",
        secondary_layout="trend",
        trend_col="day",
    )
    assert "day" in trend.bound_columns()
    attrition = Render(
        component="card",
        column="raw",
        aggregation="sum",
        secondary_layout="attrition",
        attrition_cols=["trimmed", "mapped"],
    )
    assert {"raw", "trimmed", "mapped"} <= attrition.bound_columns()


# ---------------------------------------------------------------------------
# interactive + table renders
# ---------------------------------------------------------------------------


def test_interactive_render_requires_widget_and_column():
    """`InteractiveLiteComponent` requires both, so a render missing either
    could never be turned into a filter control."""
    from pydantic import ValidationError as PydanticValidationError

    from depictio.models.components.advanced_viz.catalog import Render

    ok = Render(component="interactive", interactive_type="MultiSelect", column_name="variety")
    assert ok.bound_columns() == {"variety"}

    for incomplete in ({"column_name": "variety"}, {"interactive_type": "MultiSelect"}, {}):
        with pytest.raises(PydanticValidationError):
            Render(component="interactive", **incomplete)


def test_table_render_options_are_all_optional():
    """A bare `{component: table}` still means "every column, defaults" — that
    is what every committed entry says, and it must keep validating."""
    from depictio.models.components.advanced_viz.catalog import Render

    assert Render(component="table").bound_columns() == set()
    configured = Render(
        component="table",
        columns=["sample", "coverage"],
        page_size=25,
        sortable=False,
        row_selection_enabled=True,
        row_selection_column="sample",
    )
    # Displayed + selection columns are real column references, so grounding
    # has to check them against the fixture like every other binding.
    assert configured.bound_columns() == {"sample", "coverage"}


def test_optional_roles_are_accepted():
    """The builder's binding panel offers every role a kind declares, required
    and optional. Validating only the canonical (required) ones rejected the
    optional bindings a user could make there — a volcano's `label`, an
    embedding's `color` — so they could be authored but never exported."""
    from depictio.models.components.advanced_viz.catalog import Render

    volcano = Render(
        component="advanced_viz",
        kind="volcano",
        roles={
            "feature_id": "gene",
            "effect_size": "log2fc",
            "significance": "pvalue",
            "label": "gene",
            "category": "class",
        },
    )
    assert volcano.bound_columns() == {"gene", "log2fc", "pvalue", "class"}


def test_list_typed_roles_bind_a_column_list():
    """`steps` / `ranks` / the ComplexHeatmap column lists are list-typed in the
    per-kind config, so `roles` has to carry a list for them and a single
    column for everything else."""
    from pydantic import ValidationError as PydanticValidationError

    from depictio.models.components.advanced_viz.catalog import Render

    sankey = Render(
        component="advanced_viz", kind="sankey", roles={"steps": ["sample", "lineage", "clade"]}
    )
    assert sankey.bound_columns() == {"sample", "lineage", "clade"}

    heatmap = Render(
        component="advanced_viz",
        kind="complex_heatmap",
        roles={"index": "taxon", "value_columns": ["s1", "s2"]},
    )
    assert heatmap.bound_columns() == {"taxon", "s1", "s2"}

    with pytest.raises(PydanticValidationError, match="binds one column, not a list"):
        Render(
            component="advanced_viz",
            kind="volcano",
            roles={"feature_id": ["a", "b"], "effect_size": "e", "significance": "p"},
        )
    with pytest.raises(PydanticValidationError, match="binds a list of columns"):
        Render(component="advanced_viz", kind="sunburst", roles={"ranks": "kingdom"})


def test_sankey_requires_at_least_two_steps():
    """`SankeyConfig.step_cols` is required with >=2 entries and nothing
    downstream can infer it, so a sankey without steps renders nothing."""
    from pydantic import ValidationError as PydanticValidationError

    from depictio.models.components.advanced_viz.catalog import Render

    for roles in ({}, {"steps": ["only_one"]}):
        with pytest.raises(PydanticValidationError, match="at least 2 columns"):
            Render(component="advanced_viz", kind="sankey", roles=roles)


def test_dtype_grounding_handles_list_and_setting_roles():
    """`ground_render_dtypes` walks `roles` — a list value used to reach
    `dict.get()` as a key and raise TypeError: unhashable type."""
    from depictio.models.components.advanced_viz.catalog import Render, ground_render_dtypes

    dtypes = {"sample": "String", "lineage": "String", "pc1": "Float64", "pc2": "Float64"}
    sankey = Render(component="advanced_viz", kind="sankey", roles={"steps": ["sample", "lineage"]})
    assert ground_render_dtypes("out", sankey, dtypes) == []

    embedding = Render(
        component="advanced_viz",
        kind="embedding",
        roles={"sample_id": "sample", "dim_1": "pc1", "dim_2": "pc2", "compute_method": "pca"},
    )
    assert ground_render_dtypes("out", embedding, dtypes) == []

    # A real dtype mismatch is still reported.
    wrong = Render(
        component="advanced_viz",
        kind="embedding",
        roles={"sample_id": "sample", "dim_1": "lineage", "dim_2": "pc2"},
    )
    assert any("dim_1" in p for p in ground_render_dtypes("out", wrong, dtypes))


def test_setting_roles_are_not_grounded_as_columns():
    """`compute_method` picks the reduction algorithm, not a column — grounding
    it would look for a column called "pca"."""
    from depictio.models.components.advanced_viz.catalog import Render

    embedding = Render(
        component="advanced_viz",
        kind="embedding",
        roles={"sample_id": "sample", "dim_1": "pc1", "dim_2": "pc2", "compute_method": "pca"},
    )
    assert embedding.bound_columns() == {"sample", "pc1", "pc2"}


@pytest.mark.parametrize(
    "field",
    [
        {"interactive_type": "Select"},
        {"column_name": "variety"},
        {"columns": ["a"]},
        {"page_size": 10},
        {"sortable": False},
        {"row_selection_enabled": True},
        {"row_selection_column": "a"},
    ],
)
def test_interactive_and_table_fields_are_component_scoped(field):
    from pydantic import ValidationError as PydanticValidationError

    from depictio.models.components.advanced_viz.catalog import Render

    with pytest.raises(PydanticValidationError):
        Render(component="card", column="cov", aggregation="average", **field)


# ---------------------------------------------------------------------------
# Committed JSON Schema stays in sync with the model
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "model", "flag"),
    [
        ("catalog.schema.json", "CatalogEntry", "entry"),
        # A folder splits an entry in two, so each half needs its own schema:
        # the generated YAMLs carry `$schema=../{module,output}.schema.json` in
        # their yaml-language-server header. Pointing them at the whole-entry
        # schema (required `outputs`, extras forbidden) made every editor flag
        # a freshly generated file as invalid.
        ("module.schema.json", "CatalogTool", "module"),
        ("output.schema.json", "CatalogOutput", "output"),
    ],
)
def test_committed_json_schema_is_current(filename, model, flag):
    import json

    import depictio.models.components.advanced_viz.catalog as catalog_models

    schema_path = REPO_ROOT / "depictio" / "catalog" / filename
    committed = json.loads(schema_path.read_text())
    assert committed == getattr(catalog_models, model).model_json_schema(), (
        f"{filename} is stale — run: "
        f"depictio dev catalog schema --model {flag} -o depictio/catalog/{filename}"
    )


def test_every_bundled_output_declares_a_short_name():
    """`name` is what a picker lists; `description` is too long to scan.

    Optional on the model so a third-party catalog can omit it, but every output
    shipped here must carry one — otherwise the UI silently falls back to the
    raw id and the list reads like a database dump.
    """
    missing = [
        f"{entry.id}/{output.id}"
        for entry in load_catalog_entries()
        for output in entry.outputs
        if not (output.name or "").strip()
    ]
    assert not missing, f"catalog outputs without a `name:`: {missing}"


def test_short_names_are_unique_within_a_tool():
    """Two entries under the same tool header must be tellable apart."""
    for entry in load_catalog_entries():
        names = [o.name for o in entry.outputs if o.name]
        dupes = {n for n in names if names.count(n) > 1}
        assert not dupes, f"tool {entry.id!r} reuses output name(s): {sorted(dupes)}"


# MultiQC is an aggregator: its outputs are other tools' numbers, so each one
# names its producer. The two exceptions are pipeline-generated custom content.
_MULTIQC_WITHOUT_ORIGIN = {
    "multiqc_summary",
    "multiqc_summary_metrics",
    # Assembled by MultiQC from every module that ran, so there is no
    # single producing tool to name.
    "multiqc_general_stats",
}


def test_multiqc_outputs_name_their_origin_tool():
    multiqc = next(e for e in load_catalog_entries() if e.id == "multiqc")
    missing = [
        o.id
        for o in multiqc.outputs
        if o.id not in _MULTIQC_WITHOUT_ORIGIN and not (o.origin_tool or "").strip()
    ]
    assert not missing, f"MultiQC outputs without an `origin_tool:`: {missing}"
    unexpected = [
        o.id for o in multiqc.outputs if o.id in _MULTIQC_WITHOUT_ORIGIN and o.origin_tool
    ]
    assert not unexpected, f"pipeline-generated sections must not claim a tool: {unexpected}"


def test_origin_tool_is_only_for_aggregator_tools():
    """A tool that produces its own output does not repeat its name per output."""
    claimed = [
        f"{entry.id}/{output.id}"
        for entry in load_catalog_entries()
        if entry.id != "multiqc"
        for output in entry.outputs
        if output.origin_tool
    ]
    assert not claimed, f"origin_tool set outside an aggregator tool: {claimed}"


def test_loader_records_the_yaml_each_output_came_from():
    """`_source_file` is what lets the API link an output to its definition."""
    for entry in load_catalog_entries():
        for output in entry.outputs:
            path = output._source_file
            assert path is not None and path.is_file(), f"{entry.id}/{output.id}"
            assert path.suffix == ".yaml"
