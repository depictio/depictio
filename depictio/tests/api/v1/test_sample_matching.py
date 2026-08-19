"""Tests for the shared sample-matching module (issue #938 regression suite).

These pin the fixes for the MultiQC sample-mapping bugs:
- a canonical-only mapping (``{sample: []}``, synthesized when no explicit
  mapping exists) must count as *matched*, not unmapped;
- a source value that is itself a variant name must match (reverse lookup);
- suffix stripping must also apply to the source value, not only the keys;
- surrounding whitespace must never break a match;
- resolved lists are deduplicated while preserving order;
- the canonical key stays among the targets alongside its variants (General
  Stats tables key rows by the canonical ID while plot traces use variants).
"""

from depictio.api.v1.services.multiqc.sample_matching import (
    SampleLookup,
    expand_samples,
    match_samples,
)


def test_canonical_only_mapping_counts_as_matched():
    """``{sample: []}`` fallback mappings: the sample is known, not unmapped."""
    resolved, unmapped = expand_samples(["S1"], {"S1": []})
    assert resolved == ["S1"]
    assert unmapped == []


def test_variant_identity_lookup():
    """A source value that IS a variant resolves to itself (mapped)."""
    mappings = {"SRR001": ["SRR001_1", "SRR001_2"]}
    resolved, unmapped = expand_samples(["SRR001_1"], mappings)
    assert resolved == ["SRR001_1"]
    assert unmapped == []


def test_source_suffix_stripped():
    """``HG001_R1`` selected against a mapping keyed by the base ``HG001``."""
    mappings = {"HG001": ["HG001 - adapter"]}
    resolved, unmapped = expand_samples(["HG001_R1"], mappings)
    assert unmapped == []
    assert "HG001 - adapter" in resolved


def test_whitespace_stripped_on_both_sides():
    mappings = {" HG001 ": ["HG001_R1"]}
    resolved, unmapped = expand_samples(["HG001  "], mappings)
    assert unmapped == []
    assert "HG001_R1" in resolved


def test_resolved_deduplicated_across_source_values():
    """Two source values expanding to the same variant emit it once."""
    mappings = {
        "HG001": ["shared", "HG001_R1"],
        "HG002": ["shared", "HG002_R1"],
    }
    resolved, unmapped = expand_samples(["HG001", "HG002"], mappings)
    assert unmapped == []
    assert resolved.count("shared") == 1


def test_canonical_key_kept_among_targets():
    """The canonical ID must survive expansion for GS-style exact matching."""
    mappings = {"S1": ["S1_1", "S1_2"]}
    resolved, _ = expand_samples(["S1"], mappings)
    assert set(resolved) == {"S1", "S1_1", "S1_2"}


def test_match_detail_reports_via():
    mappings = {"HG001_R1": ["HG001_R1"], "S1": ["S1_1"]}
    details = {m.source: m for m in match_samples(["HG001_R1", "HG001", "S1_1", "NOPE"], mappings)}
    assert details["HG001_R1"].via == "exact"
    assert details["HG001"].via == "base"
    assert details["S1_1"].via == "variant"
    assert details["NOPE"].via == "passthrough"
    assert not details["NOPE"].matched
    assert details["NOPE"].targets == ["NOPE"]


def test_case_sensitive_lookup_is_strict():
    lookup = SampleLookup({"HG001": ["HG001_R1"]}, case_sensitive=True)
    assert lookup.match("hg001").matched is False
    assert lookup.match("HG001").matched is True


def test_no_overstrip_of_plain_digit_suffixes():
    """``Sample_2024`` must not collapse onto a ``Sample`` base bucket."""
    mappings = {"Sample_2024": ["Sample_2024"], "Sample_2025": ["Sample_2025"]}
    resolved, unmapped = expand_samples(["Sample"], mappings)
    assert resolved == ["Sample"]
    assert unmapped == ["Sample"]
