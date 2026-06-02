"""Tests for the bio-catalog: the tool→recipe→component linking table.

Covers flat-file + folder loading, the find/columns/recipe/renders_as model and
its validators, role grounding (against declared columns *and* against the
recipe's real output), match recognition, identity URLs, decoupling from the
suggestion engine, and JSON-Schema freshness.
"""

from __future__ import annotations

from pathlib import Path

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


def test_single_output_tool_is_a_flat_file():
    entries = {e.id: e for e in load_catalog_entries()}
    assert (REPO_ROOT / "depictio" / "catalog" / "ivar.yaml").is_file()
    assert len(entries["ivar"].outputs) == 1


def test_multi_output_tool_is_a_folder():
    entries = {e.id: e for e in load_catalog_entries()}
    assert (REPO_ROOT / "depictio" / "catalog" / "qiime2").is_dir()
    assert len(entries["qiime2"].outputs) >= 5


def test_identity_is_stored_as_urls():
    ivar = next(e for e in load_catalog_entries() if e.id == "ivar")
    assert ivar.biotools_url == "https://bio.tools/ivar"
    assert ivar.nf_core_url.endswith("/modules/nf-core/ivar/variants")


# ---------------------------------------------------------------------------
# find
# ---------------------------------------------------------------------------


def test_find_requires_a_condition():
    with pytest.raises(ValueError, match="at least one"):
        CatalogFind()


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
    with pytest.raises(ValueError, match="no recipe and no 'columns'"):
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
    for comp in ("figure", "card", "jbrowse", "multiqc"):
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
# Role grounding against the recipe's REAL output columns (the CI guarantee)
# ---------------------------------------------------------------------------


def test_all_recipe_output_roles_resolve_against_the_recipe():
    for entry in load_catalog_entries():
        for out in entry.outputs:
            if not out.recipe:
                continue
            cols = set(recipe_output_columns(out.recipe))  # raises if recipe missing
            for r in out.renders_as:
                missing = set(r.roles.values()) - cols
                assert not missing, (
                    f"{out.id} render {r.kind}: roles {sorted(missing)} "
                    f"not in recipe output {sorted(cols)}"
                )


def test_ivar_roles_match_recipe_output():
    ivar = next(e for e in load_catalog_entries() if e.id == "ivar").outputs[0]
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
    assert "multiqc_report" in by_output
    # matches carry the viz they render (the dashboard building blocks)
    assert by_output["mosdepth_genome_coverage"].renders == ["advanced_viz:coverage_track"]


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
# The catalog does NOT feed the column→viz suggestion engine (decoupled)
# ---------------------------------------------------------------------------


def test_catalog_is_decoupled_from_suggestion_engine():
    from depictio.models.components.advanced_viz.producers import KNOWN_PRODUCERS, all_producers

    assert all_producers() == KNOWN_PRODUCERS  # catalog is not merged in


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
