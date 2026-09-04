"""Run-provenance collection: generic params/versions capture (see ProvenanceSpec)."""

import json

from depictio.cli.cli.utils.templates import collect_run_provenance
from depictio.models.models.templates import (
    ProvenanceGroupRule,
    ProvenanceSource,
    ProvenanceSpec,
)


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


def test_default_spec_reads_the_nf_params_shape(tmp_path):
    """The connector accepts three params filenames; the default spec must too.

    A pipeline writing `nf-params.json` used to get a correct identity and
    template from the Nextflow connector, then an ingestion report whose
    Parameters section was empty, with nothing explaining the gap.
    """
    _write_params(tmp_path, "nf-params.json", {"max_ee": 2})
    entries, files = collect_run_provenance(str(tmp_path), None)
    assert files == ["pipeline_info/nf-params.json"]
    assert [(e.key, e.value) for e in entries] == [("max_ee", "2")]


def test_default_spec_reads_the_underscore_params_shape(tmp_path):
    _write_params(tmp_path, "nf_params.json", {"max_ee": 3})
    entries, files = collect_run_provenance(str(tmp_path), None)
    assert files == ["pipeline_info/nf_params.json"]
    assert [(e.key, e.value) for e in entries] == [("max_ee", "3")]


class TestSequencingRunsFallbackPicksOneRun:
    """Parameters must describe the run whose identity the report shows.

    Globbing `*/pipeline_info/params*.json` across every run sorts the run
    directory name before the timestamp, so `pick: latest` returned the LAST
    run alphabetically while `NextflowRunInfoReader` reads its identity from the
    FIRST. Measured on a real five-run viralrecon project, 19 parameters
    differed between those two runs: the report showed the nanopore run's
    parameters next to the amplicon run's pipeline version.
    """

    @staticmethod
    def _project(tmp_path):
        for run, payload in (
            ("run_amplicon", {"platform": "illumina", "primer_set": "artic"}),
            ("run_nanopore", {"platform": "nanopore", "primer_set": "midnight"}),
        ):
            d = tmp_path / run / "pipeline_info"
            d.mkdir(parents=True)
            (d / "params_2026-01-01_00-00-00.json").write_text(json.dumps(payload))
        return tmp_path

    def test_it_reads_the_first_run_not_the_last(self, tmp_path):
        entries, files = collect_run_provenance(str(self._project(tmp_path)), None)
        assert files == ["run_amplicon/pipeline_info/params_2026-01-01_00-00-00.json"]
        assert dict((e.key, e.value) for e in entries)["platform"] == "illumina"

    def test_it_does_not_merge_parameters_across_runs(self, tmp_path):
        """Merging would invent a run that never happened."""
        entries, _ = collect_run_provenance(str(self._project(tmp_path)), None)
        values = dict((e.key, e.value) for e in entries)
        assert values["primer_set"] == "artic"
        assert len([e for e in entries if e.key == "primer_set"]) == 1

    def test_the_newest_params_of_that_run_still_wins(self, tmp_path):
        """`pick: latest` keeps its meaning inside the chosen run."""
        root = self._project(tmp_path)
        (root / "run_amplicon" / "pipeline_info" / "params_2026-03-03_00-00-00.json").write_text(
            json.dumps({"platform": "illumina", "primer_set": "artic-v5"})
        )
        entries, files = collect_run_provenance(str(root), None)
        assert files == ["run_amplicon/pipeline_info/params_2026-03-03_00-00-00.json"]
        assert dict((e.key, e.value) for e in entries)["primer_set"] == "artic-v5"

    def test_a_flat_layout_is_unaffected(self, tmp_path):
        """The nested fallback only runs when the top level matched nothing."""
        _write_params(tmp_path, "params_2026-01-01_00-00-00.json", {"platform": "flat"})
        (tmp_path / "run_x" / "pipeline_info").mkdir(parents=True)
        (tmp_path / "run_x" / "pipeline_info" / "params_2026-09-09_00-00-00.json").write_text(
            json.dumps({"platform": "nested"})
        )
        entries, _ = collect_run_provenance(str(tmp_path), None)
        assert dict((e.key, e.value) for e in entries)["platform"] == "flat"
