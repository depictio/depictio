"""Template variables derived from a run's own params.json (``from_params``).

A template declares, per variable, the rule that sets it from the pipeline's
parameters (``--skip_*``, platform, tools...). These tests pin the rule
semantics, that every shipped template's rules parse, and that the rules reach
the resolved variables without ever overriding an explicit ``--var``.
"""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from depictio.cli.cli.utils.templates import apply_params_rules
from depictio.models.models.templates import ParamRule, TemplateMetadata, TemplateVariable

PROJECTS = Path(__file__).resolve().parents[3] / "projects"
TEMPLATES = sorted(PROJECTS.glob("**/template.yaml"))


def _rule(**spec) -> ParamRule:
    return ParamRule.model_validate(spec)


def _template(rel: str) -> TemplateMetadata:
    raw = yaml.safe_load((PROJECTS / "nf-core" / rel / "template.yaml").read_text())
    return TemplateMetadata(**raw["template"])


class TestRuleSemantics:
    @pytest.mark.parametrize(
        ("value", "on"),
        [
            (True, True),
            ("true", True),
            ("True", True),
            ("/data/regions.tsv", True),
            (3, True),
            (["a"], True),
            (False, False),
            ("false", False),
            ("", False),
            (None, False),
            (0, False),
            ([], False),
        ],
    )
    def test_a_bare_param_is_on_when_set(self, value, on):
        assert _rule(param="p").holds({"p": value}) is on
        assert _rule(param="p", **{"is": True}).holds({"p": value}) is on
        assert _rule(param="p", **{"is": False}).holds({"p": value}) is (not on)

    def test_an_absent_param_is_off(self):
        assert _rule(param="p").holds({}) is False
        assert _rule(param="p", **{"is": False}).holds({"other": 1}) is True

    def test_equals_ignores_case_and_needs_a_value(self):
        rule = _rule(param="platform", equals="nanopore")
        assert rule.holds({"platform": "Nanopore"})
        assert not rule.holds({"platform": "illumina"})
        assert not rule.holds({})

    def test_not_equals_holds_for_another_value_or_none(self):
        rule = _rule(param="clonal_threshold", not_equals="auto")
        assert rule.holds({"clonal_threshold": 0.1})
        assert rule.holds({})
        assert not rule.holds({"clonal_threshold": "AUTO"})

    @pytest.mark.parametrize(
        ("tools", "has_arriba"),
        [
            ("arriba,starfusion", True),
            ("starfusion, Arriba", True),
            (["arriba"], True),
            ("starfusion", False),
            (None, False),
            ("", False),
        ],
    )
    def test_contains_reads_lists_and_comma_strings(self, tools, has_arriba):
        assert _rule(param="tools", contains="arriba").holds({"tools": tools}) is has_arriba
        assert _rule(param="tools", not_contains="arriba").holds({"tools": tools}) is (
            not has_arriba
        )

    def test_any_and_all_combine(self):
        either = _rule(any=[{"param": "skip_multiqc"}, {"param": "skip_qc"}])
        both = _rule(all=[{"param": "multiregion"}, {"param": "sidle_ref_taxonomy"}])
        assert either.holds({"skip_qc": True}) and not either.holds({"skip_multiqc": False})
        assert both.holds({"multiregion": "r.tsv", "sidle_ref_taxonomy": "silva"})
        assert not both.holds({"multiregion": "r.tsv"})

    def test_params_used(self):
        rule = _rule(any=[{"param": "a"}, {"all": [{"param": "b"}, {"param": "c", "equals": "x"}]}])
        assert rule.params_used() == {"a", "b", "c"}


class TestRuleValidation:
    @pytest.mark.parametrize(
        "spec",
        [
            {},
            {"param": "a", "any": [{"param": "b"}]},
            {"param": "a", "equals": "x", "contains": "y"},
            {"equals": "x"},
            {"any": []},
            {"param": "a", "equal": "x"},  # misspelt test
        ],
    )
    def test_malformed_rules_are_refused(self, spec):
        with pytest.raises(ValidationError):
            ParamRule.model_validate(spec)

    def test_a_misspelt_variable_key_is_refused(self):
        """`from_param:` would otherwise be dropped and the route never set."""
        with pytest.raises(ValidationError):
            TemplateVariable.model_validate(
                {"name": "X", "description": "d", "from_param": {"param": "x"}}
            )


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: str(p.parent.relative_to(PROJECTS)))
def test_every_shipped_template_parses(path):
    """Unknown variable keys and malformed rules fail here, not at ingestion."""
    raw = yaml.safe_load(path.read_text())
    meta = TemplateMetadata(**raw["template"])
    # A run without params sets nothing, whatever the rules say.
    assert meta.variables_from_params({}) == {}
    declared = {v.name for v in meta.variables}
    gated = {c.if_var_present for c in meta.conditional} | {
        c.if_var_absent for c in meta.conditional
    }
    assert gated - {None} <= declared, "a conditional reads an undeclared variable"


class TestShippedRules:
    """The rules of real templates on real-shaped params (defaults of the release)."""

    def test_rnaseq_default_run_sets_nothing(self):
        params = {"skip_alignment": False, "skip_multiqc": False, "skip_qc": False}
        assert _template("rnaseq/3.26.0").variables_from_params(params) == {}

    def test_rnaseq_pseudoaligner_run(self):
        params = {"skip_alignment": True, "skip_qc": "true"}
        assert _template("rnaseq/3.26.0").variables_from_params(params) == {
            "PSEUDOALIGNER_ONLY": "true",
            "SKIP_MULTIQC": "true",
        }

    def test_rnafusion_all_tools_skips_none(self):
        rules = _template("rnafusion/4.1.3").variables_from_params({"tools": "all"})
        assert not {k for k in rules if k.startswith("SKIP_") and k != "SKIP_QC"}

    def test_rnafusion_tools_subset_skips_the_others(self):
        rules = _template("rnafusion/4.1.3").variables_from_params({"tools": "arriba,fusionreport"})
        assert "SKIP_ARRIBA" not in rules
        assert {"SKIP_STARFUSION", "SKIP_FUSIONCATCHER", "SKIP_CTATSPLICING"} <= set(rules)

    def test_ampliseq_ancombc_is_opt_in(self):
        meta = _template("ampliseq/2.18.0")
        assert meta.variables_from_params({"ancombc": False})["SKIP_ANCOM"] == "true"
        assert "SKIP_ANCOM" not in meta.variables_from_params({"ancombc": True})

    def test_airrflow_threshold_report(self):
        meta = _template("airrflow/5.1.2")
        assert "SKIP_THRESHOLD_REPORT" not in meta.variables_from_params(
            {"clonal_threshold": "auto"}
        )
        assert "SKIP_THRESHOLD_REPORT" in meta.variables_from_params({"clonal_threshold": 0.1})


class TestApplyParamsRules:
    def test_an_explicit_var_wins(self):
        variables = {"PSEUDOALIGNER_ONLY": "false"}
        added = apply_params_rules(
            _template("rnaseq/3.26.0"), {"skip_alignment": True, "skip_multiqc": True}, variables
        )
        assert variables["PSEUDOALIGNER_ONLY"] == "false"
        assert added == ["SKIP_MULTIQC"]
        assert variables["SKIP_MULTIQC"] == "true"

    def test_no_params_no_variables(self):
        variables: dict[str, str] = {}
        assert apply_params_rules(_template("rnaseq/3.26.0"), {}, variables) == []
        assert variables == {}
