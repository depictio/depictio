"""Run-provenance collection: generic params/versions capture (see ProvenanceSpec)."""

import json

from depictio.cli.cli.utils.templates import collect_run_provenance
from depictio.models.models.templates import (
    ProvenanceGroupRule,
    ProvenanceSource,
    ProvenanceSpec,
)

# The stubbed S3 listing lives with the template tests.
from depictio.tests.cli.s3_stubs import s3_data_root


def _write_params(tmp_path, name, payload):
    d = tmp_path / "pipeline_info"
    d.mkdir(exist_ok=True)
    (d / name).write_text(json.dumps(payload))


def test_default_spec_reads_latest_params(tmp_path):
    _write_params(tmp_path, "params_2026-01-01_00-00-00.json", {"max_ee": 1})
    _write_params(tmp_path, "params_2026-02-02_00-00-00.json", {"max_ee": 2})
    entries, files = collect_run_provenance(str(tmp_path), None)
    assert files == ["pipeline_info/params_2026-02-02_00-00-00.json"]
    assert [(e.group, e.key, e.value) for e in entries] == [("Parameters", "max_ee", "2")]


def test_grouping_exclude_and_catch_all(tmp_path):
    _write_params(
        tmp_path,
        "params.json",
        {
            "FW_primer": "GTGY",
            "dada_ref_databases": {"huge": "catalog"},
            "some_novel_key": None,
            "skip_qiime": False,
        },
    )
    spec = ProvenanceSpec(
        sources=[
            ProvenanceSource(
                name="params",
                glob="pipeline_info/params*.json",
                format="json",
                exclude_keys=["*_ref_databases*"],
            )
        ],
        groups=[
            ProvenanceGroupRule(group="Cutadapt", key_patterns=["FW_primer", "RV_primer"]),
            ProvenanceGroupRule(group="Skips", key_patterns=["skip_*"]),
        ],
        highlight=["FW_primer"],
    )
    entries, _ = collect_run_provenance(str(tmp_path), spec)
    by_key = {e.key: e for e in entries}
    assert by_key["FW_primer"].group == "Cutadapt"
    assert by_key["FW_primer"].highlight is True
    assert by_key["skip_qiime"].group == "Skips"
    assert by_key["skip_qiime"].value == "false"
    # Unmatched keys land in Other — completeness contract; None renders as null.
    assert by_key["some_novel_key"].group == "Other"
    assert by_key["some_novel_key"].value == "null"
    # Excluded catalog keys are the only omission.
    assert not any("ref_databases" in k for k in by_key)
    # Group order: spec groups first, Other last.
    groups_in_order = [e.group for e in entries]
    assert groups_in_order.index("Cutadapt") < groups_in_order.index("Other")


def test_yaml_source_with_fixed_group_flattens_nested(tmp_path):
    d = tmp_path / "pipeline_info"
    d.mkdir()
    (d / "software_versions.yml").write_text(
        "CUTADAPT:\n  cutadapt: 4.6\nDADA2:\n  dada2: 1.30.0\n"
    )
    spec = ProvenanceSpec(
        sources=[
            ProvenanceSource(
                name="software_versions",
                glob="pipeline_info/software_versions.yml",
                format="yaml",
                group="Software versions",
            )
        ]
    )
    entries, _ = collect_run_provenance(str(tmp_path), spec)
    assert {e.key: e.value for e in entries} == {
        "CUTADAPT.cutadapt": "4.6",
        "DADA2.dada2": "1.30.0",
    }
    assert all(e.group == "Software versions" for e in entries)


def test_user_provenance_file_tsv(tmp_path):
    _write_params(tmp_path, "params.json", {"a": 1})
    recap = tmp_path / "recap.tsv"
    recap.write_text("# comment\nmy_cutoff\t0.05\nnotes\tcustom run\n")
    entries, files = collect_run_provenance(str(tmp_path), None, [str(recap)])
    user = [e for e in entries if e.source == "user"]
    assert {e.key: e.value for e in user} == {"my_cutoff": "0.05", "notes": "custom run"}
    assert all(e.group == "User provided" for e in user)
    assert str(recap) in files


def test_missing_sources_are_quiet(tmp_path):
    entries, files = collect_run_provenance(str(tmp_path), None)
    assert entries == [] and files == []


class TestProvenanceThroughADataRoot:
    """The same collection, off an ``s3://`` listing instead of a directory.

    ``pipeline_info/`` is read out of the prefix, and the files-read list stays
    root-relative so the ingestion report reads the same either way.
    """

    def test_params_are_read_from_a_remote_prefix(self, monkeypatch):
        root = s3_data_root(
            monkeypatch,
            {"pipeline_info/params_2026-02-02.json": json.dumps({"max_ee": 2}).encode()},
        )
        entries, files = collect_run_provenance(root, None)
        assert files == ["pipeline_info/params_2026-02-02.json"]
        assert [(e.group, e.key, e.value) for e in entries] == [("Parameters", "max_ee", "2")]

    def test_the_run_subdir_fallback_works_remotely(self, monkeypatch):
        """sequencing-runs layouts keep pipeline_info one level down."""
        root = s3_data_root(
            monkeypatch,
            {"run_1/pipeline_info/params.json": json.dumps({"max_ee": 3}).encode()},
        )
        entries, files = collect_run_provenance(root, None)
        assert files == ["run_1/pipeline_info/params.json"]
        assert [e.value for e in entries] == ["3"]

    def test_a_prefix_with_no_params_is_quiet(self, monkeypatch):
        root = s3_data_root(monkeypatch, {"multiqc/report.html": b"<html>"})
        assert collect_run_provenance(root, None) == ([], [])

    def test_a_path_object_is_accepted(self, tmp_path):
        """db_init passes a string; a Path must mean the same thing."""
        _write_params(tmp_path, "params.json", {"max_ee": 1})
        assert collect_run_provenance(tmp_path, None) == collect_run_provenance(str(tmp_path), None)
