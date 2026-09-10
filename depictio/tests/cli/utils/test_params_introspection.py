"""Which params*.json the template-variable introspection reads.

A resumed run writes one params file per attempt, so a results directory
routinely holds several and only the last describes the run that produced the
outputs. These tests pin that choice, because getting it wrong is silent: the
flags still resolve, they just describe an abandoned attempt, and the template
prunes the wrong data collections.
"""

import json

from depictio.cli.cli.utils.templates import _introspect_pipeline_params
from depictio.models.models.nextflow import params_files_newest_first


def _write_params(directory, name, payload):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(payload))


class TestNewestParamsWins:
    def test_later_attempt_overrides_the_first(self, tmp_path):
        """The run was resumed with skip_taxonomy off, so the flag must not be set."""
        info = tmp_path / "pipeline_info"
        _write_params(info, "params_2026-06-11_16-37-38.json", {"skip_taxonomy": True})
        _write_params(info, "params_2026-06-12_07-20-45.json", {"skip_taxonomy": False})

        variables: dict[str, str] = {}
        _introspect_pipeline_params(str(tmp_path), variables)

        assert "SKIP_TAXONOMY" not in variables

    def test_later_attempt_can_add_a_flag(self, tmp_path):
        """The mirror case, so the test cannot pass by simply reading nothing."""
        info = tmp_path / "pipeline_info"
        _write_params(info, "params_2026-06-11_16-37-38.json", {"skip_taxonomy": False})
        _write_params(info, "params_2026-06-12_07-20-45.json", {"skip_taxonomy": True})

        variables: dict[str, str] = {}
        _introspect_pipeline_params(str(tmp_path), variables)

        assert variables["SKIP_TAXONOMY"] == "true"

    def test_unparseable_newest_falls_through(self, tmp_path):
        """A run killed mid-write leaves a truncated file; the previous one still counts."""
        info = tmp_path / "pipeline_info"
        _write_params(info, "params_2026-06-11_16-37-38.json", {"platform": "nanopore"})
        info.joinpath("params_2026-06-12_07-20-45.json").write_text('{"platform": "nano')

        variables: dict[str, str] = {}
        _introspect_pipeline_params(str(tmp_path), variables)

        assert variables["IS_NANOPORE"] == "true"


class TestWhereItLooks:
    def test_sequencing_runs_layout_one_level_down(self, tmp_path):
        """DATA_ROOT aggregating run_*/ subdirs: params sits inside a run."""
        _write_params(
            tmp_path / "run_A" / "pipeline_info",
            "params_2026-01-01_00-00-00.json",
            {"protocol": "metagenomic"},
        )

        variables: dict[str, str] = {}
        _introspect_pipeline_params(str(tmp_path), variables)

        assert variables["IS_METAGENOMIC"] == "true"

    def test_params_file_run_shape_is_recognised(self, tmp_path):
        """A `-params-file` run writes nf-params.json, which the old glob missed."""
        _write_params(tmp_path / "pipeline_info", "nf-params.json", {"skip_qiime": True})

        variables: dict[str, str] = {}
        _introspect_pipeline_params(str(tmp_path), variables)

        assert variables["SKIP_QIIME"] == "true"

    def test_no_params_at_all_is_a_no_op(self, tmp_path):
        variables: dict[str, str] = {"GROUP_COL": "treatment"}
        _introspect_pipeline_params(str(tmp_path), variables)
        assert variables == {"GROUP_COL": "treatment"}


class TestExplicitVarsWin:
    def test_a_user_supplied_flag_is_never_overridden(self, tmp_path):
        _write_params(
            tmp_path / "pipeline_info", "params_2026-01-01_00-00-00.json", {"skip_qiime": True}
        )

        variables = {"SKIP_QIIME": "false"}
        _introspect_pipeline_params(str(tmp_path), variables)

        assert variables["SKIP_QIIME"] == "false"


class TestSelectionIsShared:
    def test_helper_orders_newest_first(self, tmp_path):
        """The provenance collector picks matches[-1]; this must name the same file."""
        info = tmp_path / "pipeline_info"
        for name in (
            "params_2026-06-11_16-37-38.json",
            "params_2026-06-11_20-48-02.json",
            "params_2026-06-12_07-20-45.json",
        ):
            _write_params(info, name, {})

        ordered = params_files_newest_first(info)

        assert [p.name for p in ordered] == [
            "params_2026-06-12_07-20-45.json",
            "params_2026-06-11_20-48-02.json",
            "params_2026-06-11_16-37-38.json",
        ]

    def test_patterns_do_not_interleave(self, tmp_path):
        """params*.json wins outright; nf-params.json is not mixed into the order."""
        info = tmp_path / "pipeline_info"
        _write_params(info, "params_2026-01-01_00-00-00.json", {})
        _write_params(info, "nf-params.json", {})

        assert [p.name for p in params_files_newest_first(info)] == [
            "params_2026-01-01_00-00-00.json"
        ]
