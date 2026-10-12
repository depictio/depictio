"""Resolving an ad-hoc template against a root, and the plan it makes."""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from depictio.cli.cli.utils.data_root import LocalDataRoot, data_root_for
from depictio.cli.cli.utils.template_preview import FromRunDCPreview
from depictio.project_builder import plan
from depictio.project_builder.assemble import (
    ProjectDraft,
    WorkflowDraft,
    build_template,
)
from depictio.project_builder.errors import BuilderRefused
from depictio.project_builder.validate import INVALID

from ..s3_stubs import S3_ROOT, install_s3_listing, s3_cli_config, write_tree
from ._fixtures import QUANT, project, scan_dc, table_dc

PLAN_KEYS = {
    "project_id",
    "project_name",
    "template_id",
    "detected_template",
    "data_root",
    "detected_runs",
    "resolved_variables",
    "data_collections",
    "dashboards",
    "pruned_optional_dcs",
    "truncated",
    "run_info",
    "input_files",
    "run_id",
    "storage_saved",
    "dry_run",
    "success",
}


def _template(name: str = "Lab Run") -> dict:
    return build_template(project(table_dc("sheet"), scan_dc("quant"), name=name))


def _rows(report: dict) -> dict[str, dict]:
    return {row["data_collection_tag"]: row for row in report["data_collections"]}


def _scans(config: dict) -> dict[str, dict]:
    return {
        dc["data_collection_tag"]: dc["config"]["scan"]
        for workflow in config["workflows"]
        for dc in workflow["data_collections"]
    }


# ── resolve_inline ───────────────────────────────────────────────────────────


class TestResolveInline:
    def test_a_local_root_fills_in_every_location(self, root, run_dir):
        config, metadata, origin, dashboards, variables = plan.resolve_inline(_template(), root)
        assert config["name"] == "Lab Run"
        assert metadata.template_id == "custom/lab-run"
        assert (origin.template_id, origin.data_root) == ("custom/lab-run", str(run_dir))
        assert dashboards == []
        assert variables["DATA_ROOT"] == str(run_dir)
        scans = _scans(config)
        assert scans["sheet"]["scan_parameters"]["filename"] == f"{run_dir}/samplesheet.csv"
        assert scans["quant"]["mode"] == "recursive"
        assert config["workflows"][0]["data_location"]["locations"] == [str(run_dir)]

    def test_the_template_is_left_as_it_was(self, root):
        template = _template()
        before = copy.deepcopy(template)
        plan.resolve_inline(template, root)
        assert template == before

    def test_the_project_name_can_be_overridden(self, root):
        config = plan.resolve_inline(_template(), root, project_name="Another name")[0]
        assert config["name"] == "Another name"

    def test_the_origin_of_the_project_is_the_ad_hoc_template(self, root):
        config = plan.resolve_inline(_template(), root)[0]
        assert config["template_origin"]["template_id"] == "custom/lab-run"
        assert config["template_origin"]["template_version"] == "1"

    def test_an_s3_prefix_turns_a_recursive_scan_into_a_prefix_scan(self, s3_root):
        config, *_ = plan.resolve_inline(_template(), s3_root, CLI_config=s3_cli_config())
        scans = _scans(config)
        assert scans["quant"] == {
            "mode": "s3_prefix",
            "scan_parameters": {
                "prefix": f"{S3_ROOT}/",
                "pattern": r"^quant\.tsv$",
                "pattern_syntax": "regex",
            },
        }
        assert scans["sheet"] == {
            "mode": "url",
            "scan_parameters": {"url": f"{S3_ROOT}/samplesheet.csv"},
        }

    def test_a_template_without_its_section_is_refused_as_invalid(self, root):
        template = _template()
        del template["template"]
        with pytest.raises(BuilderRefused) as exc:
            plan.resolve_inline(template, root)
        assert (exc.value.status, exc.value.code) == (422, INVALID)
        assert exc.value.detail.startswith("Template resolution failed:")
        assert "'template' section" in exc.value.detail

    def test_a_template_section_the_metadata_model_refuses_is_refused_as_invalid(self, root):
        template = _template()
        template["template"]["version"] = None
        with pytest.raises(BuilderRefused) as exc:
            plan.resolve_inline(template, root)
        assert (exc.value.status, exc.value.code) == (422, INVALID)
        assert exc.value.detail.startswith("Template resolution failed:")


# ── declared_variables ───────────────────────────────────────────────────────


class TestDeclaredVariables:
    @staticmethod
    def _metadata(*names: str):
        return SimpleNamespace(variables=[SimpleNamespace(name=name) for name in names])

    def test_only_the_variables_the_template_declares_are_reported(self):
        resolved = {"DATA_ROOT": "/data/run", "GROUP_COL": "habitat", "METADATA_ID_COL": "sample"}
        assert plan.declared_variables(resolved, self._metadata("DATA_ROOT")) == {
            "DATA_ROOT": "/data/run"
        }

    def test_a_declared_variable_the_resolution_did_not_fill_is_not_invented(self):
        assert plan.declared_variables({"GROUP_COL": "g"}, self._metadata("DATA_ROOT")) == {}

    def test_a_template_declaring_nothing_reports_nothing(self):
        assert plan.declared_variables({"DATA_ROOT": "/d"}, self._metadata()) == {}

    def test_the_resolved_dict_is_left_as_it_was(self):
        resolved = {"DATA_ROOT": "/d", "GROUP_COL": "g"}
        plan.declared_variables(resolved, self._metadata("DATA_ROOT"))
        assert resolved == {"DATA_ROOT": "/d", "GROUP_COL": "g"}

    def test_the_plan_does_not_offer_the_generic_defaults_a_catalogue_template_reads(
        self, root, s3_root
    ):
        for data_root in (root, s3_root):
            variables = plan.plan_inline(_template(), data_root)["resolved_variables"]
            assert not {"GROUP_COL", "GROUP_COL_DISPLAY", "METADATA_ID_COL"} & set(variables)

    def test_the_plan_reports_a_variable_the_template_declares_when_it_was_resolved(
        self, root, monkeypatch
    ):
        monkeypatch.setattr(
            plan,
            "preview_data_root",
            lambda **kwargs: SimpleNamespace(
                detected_runs=[],
                resolved_variables={"DATA_ROOT": "/d", "GROUP_COL": "g"},
                data_collections=[],
                pruned_optional_dcs=[],
                truncated=False,
            ),
        )
        assert plan.plan_inline(_template(), root)["resolved_variables"] == {"DATA_ROOT": "/d"}


# ── check_project ────────────────────────────────────────────────────────────


class TestCheckProject:
    @pytest.fixture
    def resolved(self, root):
        return plan.resolve_inline(_template(), root)[0]

    def test_a_resolved_config_is_a_project(self, resolved):
        plan.check_project(resolved)

    def test_the_config_is_left_as_it_was(self, resolved):
        before = copy.deepcopy(resolved)
        plan.check_project(resolved)
        assert resolved == before
        assert "template_origin" in resolved and "permissions" not in resolved

    def test_permissions_the_config_already_has_are_kept(self, resolved):
        resolved["permissions"] = {"owners": [], "editors": [], "viewers": []}
        plan.check_project(resolved)

    def test_a_config_the_model_refuses_names_where(self, resolved):
        resolved["workflows"][0]["data_collections"][0]["config"]["type"] = "bogus"
        with pytest.raises(BuilderRefused) as exc:
            plan.check_project(resolved)
        assert (exc.value.status, exc.value.code) == (422, INVALID)
        assert exc.value.detail.startswith("workflows.0.data_collections.0.config.type:")

    def test_a_config_of_the_wrong_shape_is_refused(self, resolved):
        resolved["workflows"] = "none"
        with pytest.raises(BuilderRefused) as exc:
            plan.check_project(resolved)
        assert exc.value.detail.startswith("workflows:")


# ── plan_inline ──────────────────────────────────────────────────────────────


class TestPlanInlineLocal:
    def test_it_is_a_from_run_report(self, root, run_dir):
        report = plan.plan_inline(_template(), root)
        assert set(report) == PLAN_KEYS
        assert report["project_name"] == "Lab Run"
        assert report["template_id"] == "custom/lab-run"
        assert report["data_root"] == str(run_dir)
        # A dry run: nothing is created, imported or ingested.
        assert report["project_id"] is None and report["run_id"] is None
        assert report["detected_template"] is None and report["run_info"] is None
        assert report["dashboards"] == [] and report["input_files"] == []
        assert report["storage_saved"] is False
        assert (report["dry_run"], report["success"]) == (True, True)
        assert report["truncated"] is False
        assert report["detected_runs"] == []
        assert report["pruned_optional_dcs"] == []

    def test_the_project_name_can_be_chosen(self, root):
        report = plan.plan_inline(_template(), root, project_name="Chosen")
        assert report["project_name"] == "Chosen"

    def test_rows_have_the_shape_the_run_folder_dialog_renders(self, root, run_dir):
        rows = plan.plan_inline(_template(), root)["data_collections"]
        assert [r["data_collection_tag"] for r in rows] == ["sheet", "quant"]
        for row in rows:
            assert set(row) == set(FromRunDCPreview.model_fields)
            FromRunDCPreview.model_validate(row)
        sheet, quant = rows
        assert (sheet["kind"], sheet["mode"], sheet["status"]) == ("scan", "single", "ok")
        assert sheet["matched"] == 1
        assert sheet["samples"] == [f"{run_dir}/samplesheet.csv"]
        assert (quant["mode"], quant["status"], quant["matched"]) == ("recursive", "ok", 3)
        assert quant["rule"] == r"^quant\.tsv$"
        assert quant["found_in"] == "star"
        assert quant["samples"] == [f"{run_dir}/star/S{i}/quant.tsv" for i in (1, 2, 3)]

    def test_each_collection_is_ok_empty_missing_or_pruned(self, root):
        draft = project(
            table_dc("found", path="samplesheet.csv"),
            table_dc("absent", path="nope.csv"),
            table_dc("optional_absent", path="nope2.csv", optional=True),
            scan_dc("hits", regex=r"^quant\.tsv$"),
            scan_dc("no_hits", regex=r"^zzz$"),
        )
        report = plan.plan_inline(build_template(draft), root)
        rows = _rows(report)
        assert {tag: row["status"] for tag, row in rows.items()} == {
            "found": "ok",
            "absent": "missing",
            "optional_absent": "pruned",
            "hits": "ok",
            "no_hits": "empty",
        }
        assert rows["optional_absent"]["optional"] is True
        assert report["pruned_optional_dcs"] == ["optional_absent"]
        # Every row counts what it found.
        assert (rows["hits"]["matched"], rows["no_hits"]["matched"]) == (3, 0)

    def test_bounds_narrow_what_a_local_scan_finds(self, tmp_path):
        tree = {"quant.tsv": QUANT, "star/quant.tsv": QUANT, "star/deep/quant.tsv": QUANT}
        root = LocalDataRoot(str(write_tree(tmp_path / "t", tree)))
        rows = _rows(plan.plan_inline(build_template(project(scan_dc(max_depth=1))), root))
        assert rows["quant"]["matched"] == 2

    def test_sequencing_runs_list_the_runs_they_found(self, tmp_path):
        base = write_tree(
            tmp_path / "t",
            {"run_1/quant.tsv": QUANT, "run_2/quant.tsv": QUANT, "logs/quant.tsv": QUANT},
        )
        draft = ProjectDraft(
            name="Runs",
            workflows=[
                WorkflowDraft(
                    name="seq",
                    structure="sequencing-runs",
                    runs_regex=r"^run_\d$",
                    data_collections=[scan_dc()],
                )
            ],
        )
        report = plan.plan_inline(build_template(draft), LocalDataRoot(str(base)))
        assert report["detected_runs"] == ["run_1", "run_2"]
        assert _rows(report)["quant"]["matched"] == 2

    def test_a_project_the_model_refuses_is_not_planned(self, root):
        template = _template()
        template["project_type"] = "bogus"
        with pytest.raises(BuilderRefused) as exc:
            plan.plan_inline(template, root)
        assert (exc.value.status, exc.value.code) == (422, INVALID)
        assert exc.value.detail.startswith("project_type:")

    def test_the_template_is_left_as_it_was(self, root):
        template = _template()
        before = copy.deepcopy(template)
        plan.plan_inline(template, root)
        assert template == before


class TestPlanInlineS3:
    def test_a_prefix_is_planned_through_the_listing(self, s3_root):
        report = plan.plan_inline(_template(), s3_root)
        assert set(report) == PLAN_KEYS
        assert report["data_root"] == S3_ROOT
        rows = _rows(report)
        assert (rows["sheet"]["mode"], rows["sheet"]["status"]) == ("url", "ok")
        assert rows["sheet"]["samples"] == [f"{S3_ROOT}/samplesheet.csv"]
        assert (rows["quant"]["mode"], rows["quant"]["status"], rows["quant"]["matched"]) == (
            "s3_prefix",
            "ok",
            3,
        )
        assert rows["quant"]["location"] == f"{S3_ROOT}/"
        assert rows["quant"]["rule"] == r"^quant\.tsv$"
        assert rows["quant"]["found_in"] == "star"

    def test_bounds_are_not_applied_to_a_prefix(self, monkeypatch):
        tree = {"quant.tsv": QUANT, "star/quant.tsv": QUANT, "star/deep/quant.tsv": QUANT}
        install_s3_listing(monkeypatch, tree, key_prefix="p/")
        root = data_root_for("s3://bkt/p", s3_cli_config())
        rows = _rows(plan.plan_inline(build_template(project(scan_dc(max_depth=0))), root))
        assert rows["quant"]["matched"] == 3

    def test_a_prefix_with_nothing_on_it_plans_empty_rows(self, monkeypatch):
        install_s3_listing(monkeypatch, {"other/file.txt": b"x"}, key_prefix="p/")
        root = data_root_for("s3://bkt/p", s3_cli_config())
        rows = _rows(plan.plan_inline(_template(), root))
        assert (rows["sheet"]["status"], rows["quant"]["status"]) == ("missing", "empty")

    def test_a_local_and_a_remote_copy_of_the_tree_plan_alike(self, root, s3_root):
        local, remote = plan.plan_inline(_template(), root), plan.plan_inline(_template(), s3_root)
        for tag in ("sheet", "quant"):
            assert _rows(local)[tag]["matched"] == _rows(remote)[tag]["matched"]
            assert _rows(local)[tag]["status"] == _rows(remote)[tag]["status"]
