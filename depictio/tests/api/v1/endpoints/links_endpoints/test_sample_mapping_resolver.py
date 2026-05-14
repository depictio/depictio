"""Tests for SampleMappingResolver — pinning the suffix-stripping fallback.

The resolver expands canonical sample IDs (e.g. ``HG001``) into the variant
list MultiQC uses internally (``HG001_R1``, ``HG001_R1 - illumina_*``, ...).
``build_sample_mapping`` keys are typically suffixed (``HG001_R1`` /
``HG001_R2``) but the source DC's sample column emits base names. The
fallback path strips a *restricted* set of suffixes so unrelated IDs ending
in plain digits aren't mistakenly merged.
"""

from depictio.api.v1.endpoints.links_endpoints.resolvers import SampleMappingResolver
from depictio.models.models.links import LinkConfig


def _config(mappings: dict[str, list[str]], case_sensitive: bool = False) -> LinkConfig:
    return LinkConfig(
        resolver="sample_mapping",
        mappings=mappings,
        case_sensitive=case_sensitive,
    )


def test_exact_key_match_takes_precedence():
    resolver = SampleMappingResolver()
    mappings = {
        "HG001_R1": ["HG001_R1", "HG001_R1 - adapter"],
        "HG001_R2": ["HG001_R2"],
    }
    resolved, unmapped = resolver.resolve(["HG001_R1"], _config(mappings))
    assert resolved == ["HG001_R1", "HG001_R1 - adapter"]
    assert unmapped == []


def test_base_name_falls_back_to_suffix_bucket():
    """``HG001`` → union of every key whose stripped base is HG001."""
    resolver = SampleMappingResolver()
    mappings = {
        "HG001_R1": ["HG001_R1", "HG001_R1 - adapter"],
        "HG001_R2": ["HG001_R2", "HG001_R2 - adapter"],
        "DONOR_A_R1": ["DONOR_A_R1"],
    }
    resolved, unmapped = resolver.resolve(["HG001"], _config(mappings))
    assert set(resolved) == {
        "HG001_R1",
        "HG001_R1 - adapter",
        "HG001_R2",
        "HG001_R2 - adapter",
    }
    assert unmapped == []


def test_truly_missing_canonical_passes_through():
    resolver = SampleMappingResolver()
    mappings = {"HG001_R1": ["HG001_R1"]}
    resolved, unmapped = resolver.resolve(["XXXXX"], _config(mappings))
    assert resolved == ["XXXXX"]
    assert unmapped == ["XXXXX"]


def test_dedup_when_multiple_keys_share_a_variant():
    resolver = SampleMappingResolver()
    mappings = {
        "HG001_R1": ["HG001_R1", "shared_variant"],
        "HG001_R2": ["HG001_R2", "shared_variant"],
    }
    resolved, _ = resolver.resolve(["HG001"], _config(mappings))
    # ``shared_variant`` should appear once even though it's in both buckets.
    assert resolved.count("shared_variant") == 1


def test_lane_suffix_stripped():
    """Illumina lane suffix (``_L001``) is part of the supported stripped set."""
    resolver = SampleMappingResolver()
    mappings = {
        "Sample_L001": ["Sample_L001"],
        "Sample_L002": ["Sample_L002"],
    }
    resolved, _ = resolver.resolve(["Sample"], _config(mappings))
    assert set(resolved) == {"Sample_L001", "Sample_L002"}


def test_replicate_and_tech_suffixes_stripped():
    resolver = SampleMappingResolver()
    mappings = {
        "Sample_REP1": ["Sample_REP1"],
        "Sample_REP2": ["Sample_REP2"],
        "Other_TECH1": ["Other_TECH1"],
    }
    resolved, _ = resolver.resolve(["Sample"], _config(mappings))
    assert set(resolved) == {"Sample_REP1", "Sample_REP2"}


def test_does_not_overstrip_year_suffix():
    """Bug guard: ``Sample_2024`` was being treated as a base of ``Sample``."""
    resolver = SampleMappingResolver()
    mappings = {
        "Sample_2024": ["Sample_2024"],
        "Sample_2025": ["Sample_2025"],
    }
    # A source value of ``Sample`` should NOT collapse to both years.
    resolved, unmapped = resolver.resolve(["Sample"], _config(mappings))
    assert resolved == ["Sample"]
    assert unmapped == ["Sample"]


def test_does_not_overstrip_patient_id():
    """``Patient_42`` is the canonical sample, not ``Patient`` with a replicate."""
    resolver = SampleMappingResolver()
    mappings = {"Patient_42": ["Patient_42", "Patient_42 - adapter"]}
    resolved, unmapped = resolver.resolve(["Patient"], _config(mappings))
    assert resolved == ["Patient"]
    assert unmapped == ["Patient"]


def test_case_insensitive_default():
    resolver = SampleMappingResolver()
    mappings = {"HG001_R1": ["HG001_R1"]}
    resolved, _ = resolver.resolve(["hg001"], _config(mappings, case_sensitive=False))
    assert resolved == ["HG001_R1"]


def test_case_sensitive_strict_match():
    resolver = SampleMappingResolver()
    mappings = {"HG001_R1": ["HG001_R1"]}
    resolved, unmapped = resolver.resolve(["hg001"], _config(mappings, case_sensitive=True))
    # Lowercase source against suffixed key won't hit either branch under
    # strict case sensitivity.
    assert resolved == ["hg001"]
    assert unmapped == ["hg001"]


def test_empty_mappings_returns_source_unchanged():
    resolver = SampleMappingResolver()
    resolved, unmapped = resolver.resolve(["HG001", "DONOR_A"], _config({}))
    assert resolved == ["HG001", "DONOR_A"]
    assert unmapped == ["HG001", "DONOR_A"]


def test_mixed_exact_and_fallback_in_one_call():
    resolver = SampleMappingResolver()
    mappings = {
        "HG001_R1": ["HG001_R1", "HG001_R1 - adapter"],
        "HG001_R2": ["HG001_R2"],
        "DONOR_A_R1": ["DONOR_A_R1"],
    }
    resolved, unmapped = resolver.resolve(["HG001_R1", "DONOR_A", "MISSING"], _config(mappings))
    assert "HG001_R1" in resolved
    assert "HG001_R1 - adapter" in resolved
    assert "DONOR_A_R1" in resolved
    assert "MISSING" in resolved
    assert unmapped == ["MISSING"]
