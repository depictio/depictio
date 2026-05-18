"""Unit tests for the MultiQC multi-report uniformity guard."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from depictio.api.v1.endpoints.multiqc_endpoints.uniformity import (
    validate_multiqc_reports_uniform,
)


def _report(
    label: str,
    *,
    modules: list[str],
    plots: dict[str, Any] | None = None,
    samples: list[str] | None = None,
    multiqc_version: str | None = "1.21.0",
) -> dict:
    """Build a minimal report-shaped dict matching the raw MongoDB layout."""
    return {
        "original_file_path": label,
        "multiqc_version": multiqc_version,
        "metadata": {
            "modules": modules,
            "plots": plots or {m: {"id": m} for m in modules},
            "samples": samples or [],
        },
    }


class TestUniformityValidation:
    def test_single_report_passes_trivially(self):
        validate_multiqc_reports_uniform([_report("r1", modules=["fastqc", "samtools"])])

    def test_identical_reports_pass(self):
        a = _report("r1", modules=["fastqc", "samtools"], samples=["s1"])
        b = _report("r2", modules=["fastqc", "samtools"], samples=["s2"])
        validate_multiqc_reports_uniform([a, b])

    def test_module_added_in_one_report_raises_modules_mismatch(self):
        a = _report("r1", modules=["fastqc", "samtools"], samples=["s1"])
        b = _report("r2", modules=["fastqc", "samtools", "picard"], samples=["s2"])
        with pytest.raises(HTTPException) as exc_info:
            validate_multiqc_reports_uniform([a, b])
        assert exc_info.value.status_code == 422
        detail = exc_info.value.detail
        assert detail["code"] == "multiqc_report_mismatch"
        assert detail["kind"] == "modules"
        assert "picard" in detail["details"]["added_in_compared"]

    def test_module_removed_in_one_report_raises_modules_mismatch(self):
        a = _report("r1", modules=["fastqc", "samtools", "picard"], samples=["s1"])
        b = _report("r2", modules=["fastqc", "samtools"], samples=["s2"])
        with pytest.raises(HTTPException) as exc_info:
            validate_multiqc_reports_uniform([a, b])
        assert exc_info.value.detail["kind"] == "modules"
        assert "picard" in exc_info.value.detail["details"]["removed_in_compared"]

    def test_plot_key_dropped_raises_plots_mismatch(self):
        # `_flat_plot_ids` expects `{module: [plot_name | {plot_name: [...]}]}`
        # (the shape `multiqc.list_plots()` returns). It flattens to
        # `{"module::plot"}` identifiers and compares those sets, so dropping
        # one plot inside the same module is what trips the validator.
        a = _report(
            "r1",
            modules=["fastqc"],
            plots={"fastqc": ["quality", "gc_content", "adapter_content"]},
            samples=["s1"],
        )
        b = _report(
            "r2",
            modules=["fastqc"],
            plots={"fastqc": ["quality", "gc_content"]},
            samples=["s2"],
        )
        with pytest.raises(HTTPException) as exc_info:
            validate_multiqc_reports_uniform([a, b])
        assert exc_info.value.detail["kind"] == "plots"
        assert "fastqc::adapter_content" in exc_info.value.detail["details"]["removed_in_compared"]

    def test_major_version_mismatch_raises_version(self):
        a = _report("r1", modules=["fastqc"], samples=["s1"], multiqc_version="1.21.0")
        b = _report("r2", modules=["fastqc"], samples=["s2"], multiqc_version="2.0.0")
        with pytest.raises(HTTPException) as exc_info:
            validate_multiqc_reports_uniform([a, b])
        assert exc_info.value.detail["kind"] == "version"

    def test_patch_version_drift_passes(self, caplog):
        a = _report("r1", modules=["fastqc"], samples=["s1"], multiqc_version="1.21.0")
        b = _report("r2", modules=["fastqc"], samples=["s2"], multiqc_version="1.21.1")
        # Same major.minor — should not raise.
        validate_multiqc_reports_uniform([a, b])

    def test_minor_version_mismatch_raises_version(self):
        a = _report("r1", modules=["fastqc"], samples=["s1"], multiqc_version="1.21.0")
        b = _report("r2", modules=["fastqc"], samples=["s2"], multiqc_version="1.22.0")
        with pytest.raises(HTTPException) as exc_info:
            validate_multiqc_reports_uniform([a, b])
        assert exc_info.value.detail["kind"] == "version"

    def test_missing_version_on_one_report_is_tolerated(self):
        # If we can't compute major.minor for one side, skip the check (can't
        # detect a mismatch we don't have evidence for).
        a = _report("r1", modules=["fastqc"], samples=["s1"], multiqc_version=None)
        b = _report("r2", modules=["fastqc"], samples=["s2"], multiqc_version="1.22.0")
        validate_multiqc_reports_uniform([a, b])

    def test_sample_appears_in_multiple_reports_raises_samples(self):
        a = _report("r1", modules=["fastqc"], samples=["s1", "shared"])
        b = _report("r2", modules=["fastqc"], samples=["shared", "s2"])
        with pytest.raises(HTTPException) as exc_info:
            validate_multiqc_reports_uniform([a, b])
        assert exc_info.value.detail["kind"] == "samples"
        assert "shared" in exc_info.value.detail["details"]["duplicate_samples"]

    def test_empty_input_passes(self):
        validate_multiqc_reports_uniform([])

    def test_handles_flat_metadata_shape(self):
        # Some callers pass already-flat dicts (e.g. MultiQCMetadata.model_dump).
        flat_a = {"modules": ["fastqc"], "plots": {"fastqc": {}}, "samples": ["s1"]}
        flat_b = {"modules": ["fastqc"], "plots": {"fastqc": {}}, "samples": ["s2"]}
        validate_multiqc_reports_uniform([flat_a, flat_b])

    def test_patch_drift_logs_at_info(self, caplog):
        a = _report("r1", modules=["fastqc"], samples=["s1"], multiqc_version="1.21.0")
        b = _report("r2", modules=["fastqc"], samples=["s2"], multiqc_version="1.21.1")
        with caplog.at_level("INFO", logger="depictio"):
            validate_multiqc_reports_uniform([a, b])
        # The validator emits a logger.info() noting the patch-level drift so
        # anomalies surface in logs even though no exception is raised.
        assert any("patch-version drift" in rec.message for rec in caplog.records), (
            "expected an INFO log noting patch-level version drift"
        )

    def test_422_payload_shape_is_well_formed(self):
        # The frontend reads `detail.code`, `detail.kind`, `detail.summary`,
        # `detail.details` to render the error banner. Lock that contract.
        a = _report("r1", modules=["fastqc", "samtools"], samples=["s1"])
        b = _report("r2", modules=["fastqc"], samples=["s2"])
        with pytest.raises(HTTPException) as exc_info:
            validate_multiqc_reports_uniform([a, b])
        assert exc_info.value.status_code == 422
        detail = exc_info.value.detail
        assert isinstance(detail, dict)
        assert detail["code"] == "multiqc_report_mismatch"
        assert detail["kind"] == "modules"
        assert isinstance(detail["summary"], str) and detail["summary"]
        assert isinstance(detail["details"], dict)
        assert "baseline_report" in detail["details"]
        assert "compared_report" in detail["details"]

    def test_modules_duplicates_within_one_report_normalize(self):
        # The validator compares modules as sets, so duplicate entries inside a
        # single report mustn't masquerade as a mismatch with a "clean" peer.
        a = _report("r1", modules=["fastqc", "fastqc", "samtools"], samples=["s1"])
        b = _report("r2", modules=["samtools", "fastqc"], samples=["s2"])
        validate_multiqc_reports_uniform([a, b])

    def test_three_reports_first_mismatch_wins(self):
        # Reports 2 and 3 both differ from the baseline in different ways:
        # report 2 has a different module set, report 3 has a duplicate sample.
        # The validator runs checks in order (modules, plots, version, samples)
        # — so we expect kind="modules" from the report-2 comparison before
        # the sample check ever sees report 3.
        baseline = _report("r1", modules=["fastqc"], samples=["s1"])
        bad_modules = _report("r2", modules=["fastqc", "picard"], samples=["s2"])
        bad_samples = _report("r3", modules=["fastqc"], samples=["s1"])  # duplicate of baseline
        with pytest.raises(HTTPException) as exc_info:
            validate_multiqc_reports_uniform([baseline, bad_modules, bad_samples])
        assert exc_info.value.detail["kind"] == "modules"

    def test_version_prefix_v_falls_through_silently(self):
        # The version regex is anchored on `^(\d+)\.(\d+)`, so values like
        # "v1.21.0" fail to parse and `_major_minor` returns None. When either
        # side can't be parsed, the version check is skipped. This test pins
        # that behavior: a "v"-prefixed version paired with a plain version
        # passes even though they're conceptually equal.
        a = _report("r1", modules=["fastqc"], samples=["s1"], multiqc_version="v1.21.0")
        b = _report("r2", modules=["fastqc"], samples=["s2"], multiqc_version="1.21.0")
        validate_multiqc_reports_uniform([a, b])
