"""Tests for two pure helpers driving MultiQC ingestion + plot patching:

- ``_extract_multiqc_folder_name`` (depictio.dash.api_calls): turns a relative
  upload path into the folder identifier the processor groups by. Mirrored
  by ``_multiqc_folder_from_path`` in project_data_collections.py for UI
  previews — the two MUST agree.
- ``expand_canonical_samples_to_variants`` (depictio.dash.modules.multiqc_component.callbacks.core):
  expands base sample IDs to MultiQC variants, with the same suffix-stripping
  fallback as the SampleMappingResolver.

Pure functions — no DB required. Marked ``no_db`` so the dash conftest's
``setup_test_database`` autouse fixture skips its Mongo connect.
"""

import pytest

from depictio.dash.api_calls import _extract_multiqc_folder_name
from depictio.dash.layouts.project_data_collections import _multiqc_folder_from_path
from depictio.dash.modules.multiqc_component.callbacks.core import (
    expand_canonical_samples_to_variants,
)

pytestmark = pytest.mark.no_db


# ----------------------------------------------------------------------------
# _extract_multiqc_folder_name
# ----------------------------------------------------------------------------


def test_folder_from_run_xx_relative_path():
    assert _extract_multiqc_folder_name("run_01/multiqc_data/multiqc.parquet", 0) == "run_01"


def test_folder_skips_multiqc_data_sibling_dir():
    """``parent/multiqc_data/multiqc.parquet`` should yield ``parent``, not ``multiqc_data``."""
    assert (
        _extract_multiqc_folder_name("test_data/run_01/multiqc_data/multiqc.parquet", 0) == "run_01"
    )


def test_folder_uses_immediate_parent_when_not_multiqc_data():
    """Some uploads use a flatter layout: ``my_run/multiqc.parquet``."""
    assert _extract_multiqc_folder_name("my_run/multiqc.parquet", 0) == "my_run"


def test_folder_falls_back_on_basename_only():
    """No path separators at all — fall back to the ordinal."""
    assert _extract_multiqc_folder_name("multiqc.parquet", 7) == "report_7"


def test_folder_handles_windows_separators():
    """Browsers on Windows can ship backslash separators."""
    assert _extract_multiqc_folder_name(r"run_03\multiqc_data\multiqc.parquet", 0) == "run_03"


def test_folder_strips_leading_and_repeated_slashes():
    assert _extract_multiqc_folder_name("//run_05//multiqc_data//multiqc.parquet", 0) == "run_05"


def test_ui_helper_matches_server_helper():
    """``_multiqc_folder_from_path`` (UI preview) must agree with the server.

    The DC-card preview promises ``N folder(s)`` based on the UI-side helper,
    but the server actually creates the folder structure via the api_calls
    helper. If they drift, the user sees a count that doesn't match what
    gets ingested.
    """
    cases = [
        ("run_01/multiqc_data/multiqc.parquet", 0),
        ("test_data/run_02/multiqc_data/multiqc.parquet", 1),
        ("flat/multiqc.parquet", 2),
        ("multiqc.parquet", 3),
        (r"run_04\multiqc_data\multiqc.parquet", 4),
    ]
    for path, idx in cases:
        assert _extract_multiqc_folder_name(path, idx) == _multiqc_folder_from_path(path, idx), (
            f"helpers disagree on {path!r}"
        )


# ----------------------------------------------------------------------------
# expand_canonical_samples_to_variants
# ----------------------------------------------------------------------------


def test_expand_exact_match_wins():
    mappings = {
        "HG001_R1": ["HG001_R1", "HG001_R1 - adapter"],
        "HG001_R2": ["HG001_R2"],
    }
    assert expand_canonical_samples_to_variants(["HG001_R1"], mappings) == [
        "HG001_R1",
        "HG001_R1 - adapter",
    ]


def test_expand_base_name_falls_back_to_bucket():
    mappings = {
        "HG001_R1": ["HG001_R1", "HG001_R1 - adapter"],
        "HG001_R2": ["HG001_R2", "HG001_R2 - adapter"],
    }
    out = expand_canonical_samples_to_variants(["HG001"], mappings)
    assert set(out) == {
        "HG001_R1",
        "HG001_R1 - adapter",
        "HG001_R2",
        "HG001_R2 - adapter",
    }


def test_expand_dedups_across_buckets():
    mappings = {
        "HG001_R1": ["HG001_R1", "shared"],
        "HG001_R2": ["HG001_R2", "shared"],
    }
    out = expand_canonical_samples_to_variants(["HG001"], mappings)
    assert out.count("shared") == 1


def test_expand_unknown_passes_through():
    mappings = {"HG001_R1": ["HG001_R1"]}
    assert expand_canonical_samples_to_variants(["UNKNOWN"], mappings) == ["UNKNOWN"]


def test_expand_does_not_overstrip_year_suffix():
    mappings = {
        "Sample_2024": ["Sample_2024"],
        "Sample_2025": ["Sample_2025"],
    }
    # ``Sample`` shouldn't be merged with year-suffixed sibling IDs.
    assert expand_canonical_samples_to_variants(["Sample"], mappings) == ["Sample"]


def test_expand_does_not_overstrip_plain_digit_suffix():
    """``_1`` / ``_2`` (without the R/L prefix) is no longer treated as a strip target."""
    mappings = {"Patient_1": ["Patient_1"], "Patient_2": ["Patient_2"]}
    assert expand_canonical_samples_to_variants(["Patient"], mappings) == ["Patient"]


def test_expand_lane_suffix_stripped():
    mappings = {"Sample_L001": ["Sample_L001"], "Sample_L002": ["Sample_L002"]}
    out = expand_canonical_samples_to_variants(["Sample"], mappings)
    assert set(out) == {"Sample_L001", "Sample_L002"}


def test_expand_empty_mappings_passes_through():
    assert expand_canonical_samples_to_variants(["HG001"], {}) == ["HG001"]


def test_expand_mixed_inputs_in_one_call():
    mappings = {
        "HG001_R1": ["HG001_R1"],
        "HG001_R2": ["HG001_R2"],
        "DONOR_A_R1": ["DONOR_A_R1"],
    }
    out = expand_canonical_samples_to_variants(["HG001", "DONOR_A_R1", "MISSING"], mappings)
    assert "HG001_R1" in out
    assert "HG001_R2" in out
    assert "DONOR_A_R1" in out
    assert "MISSING" in out
