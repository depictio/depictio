"""`depictio template check`: a template's variables against a pipeline's params.

What a pipeline developer relies on: each variable says what sets it, a rule is
evaluated on a default run (the schema's defaults) and on a given run, the
conditionals that fire are named with what they drop or repoint, and a rule
reading a param the release lacks fails the command (it would silently never
hold at ingestion).
"""

import json

import pytest
from typer.testing import CliRunner

from depictio.cli.cli.commands import template as template_cmd
from depictio.cli.cli.utils.template_check import (
    check_template,
    effect_text,
    nfcore_target,
    rule_text,
    schema_params,
)
from depictio.models.models.templates import ParamRule, TemplateConditional, TemplateMetadata

runner = CliRunner()

SCHEMA = {
    "$defs": {
        "skipping": {
            "title": "Process skipping options",
            "properties": {
                "skip_alignment": {"type": "boolean"},
                "skip_multiqc": {"type": "boolean", "default": False},
                "skip_bigwig": {"type": "boolean"},
                "skip_linting": {"type": "boolean"},
            },
        },
        "main": {"properties": {"aligner": {"type": "string", "default": "star_salmon"}}},
    },
    "properties": {"tools": {"type": "string", "default": "arriba"}},
}

TEMPLATE = {
    "template_id": "nf-core/demo/1.0.0",
    "description": "demo",
    "version": "1.0.0",
    "dashboards": ["dashboards/base.yaml"],
    "variables": [
        {"name": "DATA_ROOT", "description": "root", "required": True},
        {"name": "METADATA_FILE", "description": "metadata", "required": False},
        {
            "name": "PSEUDOALIGNER_ONLY",
            "description": "--skip_alignment",
            "from_params": {"param": "skip_alignment"},
        },
        {
            "name": "SKIP_MULTIQC",
            "description": "--skip_multiqc",
            "from_params": {"param": "skip_multiqc"},
        },
        {
            "name": "NO_ARRIBA",
            "description": "arriba not among --tools",
            "from_params": {"param": "tools", "not_contains": "arriba"},
        },
        {"name": "TRACKS_URI", "description": "tracks in place", "required": False},
    ],
    "conditional": [
        {
            "if_var_present": "PSEUDOALIGNER_ONLY",
            "remove_dc_tags": ["tracks"],
            "override_dcs": [{"data_collection_tag": "gene_counts", "scan_filename": "x"}],
            "dashboards": ["dashboards/base.yaml"],
        },
        {"if_var_present": "SKIP_MULTIQC", "remove_dc_tags": ["multiqc_data"]},
        {"if_var_absent": "METADATA_FILE", "remove_dc_tags": ["metadata"]},
    ],
}

TEXT = "tracks: bigwig files\nmultiqc_data"


@pytest.fixture
def meta() -> TemplateMetadata:
    return TemplateMetadata(**TEMPLATE)


def test_schema_params_reads_every_group_and_top_level():
    found = schema_params(SCHEMA)
    assert set(found) == {
        "skip_alignment",
        "skip_multiqc",
        "skip_bigwig",
        "skip_linting",
        "aligner",
        "tools",
    }
    assert found["skip_multiqc"].group == "Process skipping options"
    assert found["aligner"].default == "star_salmon"


def test_nfcore_target():
    assert nfcore_target("nf-core/rnaseq/3.26.0") == ("rnaseq", "3.26.0")
    assert nfcore_target("nf-core/variantbenchmarking/1.4.0/categories/indel") == (
        "variantbenchmarking",
        "1.4.0",
    )
    assert nfcore_target("my-lab/rnaseq/1") is None


@pytest.mark.parametrize(
    "rule",
    [
        {"param": "skip_alignment"},
        {"param": "ancombc", "is": False},
        {"param": "platform", "equals": "nanopore"},
        {
            "all": [
                {"param": "tools", "not_contains": "arriba"},
                {"param": "tools", "not_contains": "all"},
            ]
        },
    ],
)
def test_rule_text_reads_like_the_yaml(rule):
    import yaml

    text = rule_text(ParamRule.model_validate(rule))
    assert ParamRule.model_validate(yaml.safe_load(text)) == ParamRule.model_validate(rule)


def test_effect_text_leaves_out_the_default_dashboards():
    cond = TemplateConditional(
        if_var_present="X", remove_dc_tags=["a"], dashboards=["dashboards/base.yaml"]
    )
    assert effect_text(cond, ["dashboards/base.yaml"]) == "drops a"
    assert "dashboards/other.yaml" in effect_text(
        TemplateConditional(if_var_present="X", dashboards=["dashboards/other.yaml"]),
        ["dashboards/base.yaml"],
    )


def test_variables_say_what_sets_them(meta):
    rows = {r.name: r for r in check_template(meta).rows}
    assert rows["DATA_ROOT"].source == "auto"
    assert rows["METADATA_FILE"].source == "auto"
    assert rows["PSEUDOALIGNER_ONLY"].source == "rule"
    assert rows["PSEUDOALIGNER_ONLY"].how == "{param: skip_alignment}"
    assert rows["TRACKS_URI"].source == "user"
    assert rows["PSEUDOALIGNER_ONLY"].effects == ["set → drops tracks; repoints gene_counts"]
    assert rows["METADATA_FILE"].effects == ["unset → drops metadata"]


def test_a_rule_is_evaluated_on_a_default_run(meta):
    rows = {r.name: r for r in check_template(meta, schema=SCHEMA).rows}
    assert rows["PSEUDOALIGNER_ONLY"].on_default_run is False
    assert rows["SKIP_MULTIQC"].on_default_run is False
    # tools defaults to arriba: not_contains arriba does not hold on a default run
    assert rows["NO_ARRIBA"].on_default_run is False


def test_a_param_the_release_lacks_fails(meta):
    schema = {"properties": {"skip_alignment": {"type": "boolean"}}}
    result = check_template(meta, schema=schema)
    assert result.unknown_params == {"SKIP_MULTIQC": ["skip_multiqc"], "NO_ARRIBA": ["tools"]}
    assert not result.ok


def test_unread_skip_params_and_the_ones_the_template_names(meta):
    result = check_template(meta, schema=SCHEMA, template_text=TEXT)
    assert result.unread_skip_params == ["skip_bigwig", "skip_linting"]
    assert result.suspect_skip_params == ["skip_bigwig"]


def test_a_run_fires_its_conditionals(meta):
    result = check_template(meta, run_params={"skip_alignment": "true", "tools": "arriba"})
    assert [f.condition for f in result.fired] == [
        "if_var_present: PSEUDOALIGNER_ONLY",
        "if_var_absent: METADATA_FILE",
    ]
    assert {r.name for r in result.rows if r.on_this_run} == {"PSEUDOALIGNER_ONLY"}


def test_an_explicit_off_unsets_a_rule_and_a_var_sets_a_route(meta):
    result = check_template(
        meta,
        run_params={"skip_alignment": True, "skip_multiqc": True},
        run_vars={"SKIP_MULTIQC": "false", "METADATA_FILE": "input/metadata.tsv"},
    )
    fired = [f.condition for f in result.fired]
    assert "if_var_present: SKIP_MULTIQC" not in fired
    assert "if_var_absent: METADATA_FILE" not in fired
    assert "if_var_present: PSEUDOALIGNER_ONLY" in fired


def _cli(monkeypatch, *args):
    import depictio.models.config  # noqa: F401

    monkeypatch.setenv("DEPICTIO_CONTEXT", "CLI")
    return runner.invoke(template_cmd.app, ["check", *args], env={"COLUMNS": "200"})


def test_cli_on_a_bundled_template_with_a_run(monkeypatch, tmp_path):
    schema = tmp_path / "nextflow_schema.json"
    schema.write_text(
        json.dumps(
            {
                "properties": {
                    "skip_alignment": {"type": "boolean"},
                    "skip_multiqc": {"type": "boolean"},
                    "skip_quantification_merge": {"type": "boolean"},
                }
            }
        )
    )
    params = tmp_path / "params_2026-11-02_10-12-00.json"
    params.write_text(json.dumps({"skip_alignment": True, "skip_multiqc": False}))
    result = _cli(
        monkeypatch, "nf-core/rnaseq/3.26.0", "--schema", str(schema), "--params", str(params)
    )
    assert result.exit_code == 0, result.output
    assert "if_var_present: PSEUDOALIGNER_ONLY" in result.output
    assert "every param a rule reads exists" in result.output


def test_cli_fails_on_a_param_the_release_lacks(monkeypatch, tmp_path):
    schema = tmp_path / "nextflow_schema.json"
    schema.write_text(json.dumps({"properties": {"skip_alignment": {"type": "boolean"}}}))
    result = _cli(monkeypatch, "nf-core/rnaseq/3.26.0", "--schema", str(schema))
    assert result.exit_code == 1
    assert "skip_multiqc" in result.output


def test_cli_reports_a_template_that_does_not_load(monkeypatch, tmp_path):
    bad = tmp_path / "t"
    bad.mkdir()
    (bad / "template.yaml").write_text(
        "template:\n  template_id: x/y/1\n  description: d\n  version: '1'\n"
        "  variables:\n    - {name: A, description: a, from_param: {param: p}}\n"
    )
    result = _cli(monkeypatch, str(bad))
    assert result.exit_code == 1
    assert "does not load" in result.output
