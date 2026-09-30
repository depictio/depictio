"""P16: MultiQC sample names joined back to the samples hub.

Names are modelled on the two templates that motivated it: sarek renames each
sample per tool (lane-and-read, stage, caller, annotator), methylseq's Trim
Galore appends ``_1_val_1``.
"""

from __future__ import annotations

import pytest

from depictio.cli.cli.utils.sample_mapping import (
    build_sample_mapping,
    canonicalize_to_hub,
    remap_mappings_to_hub,
    strip_multiqc_suffixes,
)

SAREK_HUB = ["NA12878_75M", "NA12878_200M"]
SAREK_TOOL_SUFFIXES = [
    "-1",
    "-1_1",
    "-1_2",
    ".md",
    ".recal",
    ".deepvariant",
    ".deepvariant_snpEff",
    ".deepvariant_VEP.ann",
    ".freebayes.filtered_VEP.ann",
    ".haplotypecaller.filtered",
    ".manta.diploid_sv",
    ".strelka.variants_snpEff",
]
SAREK_NAMES = [hub + sfx for hub in SAREK_HUB for sfx in SAREK_TOOL_SUFFIXES]

METHYLSEQ_HUB = ["SRR389222_GSM1204465_MShef11_control", "SRR389222_GSM1204466_MShef4_treated"]
METHYLSEQ_NAMES = [
    f"{hub}{sfx}"
    for hub in METHYLSEQ_HUB
    for sfx in ("", "_1", "_2", "_1_val_1", "_2_val_2", "_1_val_1_bismark_bt2_pe")
]


@pytest.mark.parametrize("name", SAREK_NAMES)
def test_sarek_names_join_their_hub_id(name: str) -> None:
    expected = "NA12878_200M" if name.startswith("NA12878_200M") else "NA12878_75M"
    assert canonicalize_to_hub(name, SAREK_HUB) == expected


@pytest.mark.parametrize("name", METHYLSEQ_NAMES)
def test_methylseq_names_join_their_hub_id(name: str) -> None:
    expected = next(h for h in METHYLSEQ_HUB if name.startswith(h))
    assert canonicalize_to_hub(name, METHYLSEQ_HUB) == expected


def test_strip_suffixes_converges() -> None:
    assert strip_multiqc_suffixes("S1_1_val_1") == "S1"
    assert strip_multiqc_suffixes("S1_R1_001") == "S1"
    assert strip_multiqc_suffixes("S1.mLb.clN") == "S1"
    assert strip_multiqc_suffixes("S1 - First read: Adapter 1") == "S1"
    # A bare year / patient number is an id, not a read number.
    assert strip_multiqc_suffixes("Sample_2024") == "Sample_2024"


def test_prefix_needs_a_token_boundary_and_prefers_longest() -> None:
    assert canonicalize_to_hub("NA12878_75MX.md", SAREK_HUB) is None
    # Nested hub ids: the longest one owns the name, the shorter keeps its own.
    hub = ["S1", "S1_2"]
    assert canonicalize_to_hub("S1_2.md", hub) == "S1_2"
    assert canonicalize_to_hub("S1.md", hub) == "S1"
    assert canonicalize_to_hub("S1_2", hub) == "S1_2"
    assert canonicalize_to_hub("S10.md", hub) is None
    assert canonicalize_to_hub("anything", []) is None


def test_build_sample_mapping_with_hub_groups_every_tool_name() -> None:
    mapping = build_sample_mapping(SAREK_NAMES + ["unrelated_R1"], hub_ids=SAREK_HUB)
    assert set(mapping) == {"NA12878_75M", "NA12878_200M", "unrelated_R1"}
    assert len(mapping["NA12878_75M"]) == len(SAREK_TOOL_SUFFIXES)
    assert len(mapping["NA12878_200M"]) == len(SAREK_TOOL_SUFFIXES)


def test_build_sample_mapping_without_hub_is_unchanged() -> None:
    mapping = build_sample_mapping(["SRR1_1", "SRR1_2", "SRR1 - First read: Adapter 1"])
    assert mapping == {"SRR1": ["SRR1_1", "SRR1_2", "SRR1 - First read: Adapter 1"]}


def test_explicit_mappings_win_over_canonicalisation() -> None:
    explicit = {"NA12878_200M": ["NA12878_75M.md"]}
    mapping = build_sample_mapping(
        ["NA12878_75M.md", "NA12878_75M.recal"], hub_ids=SAREK_HUB, explicit_mappings=explicit
    )
    assert mapping == {"NA12878_200M": ["NA12878_75M.md"], "NA12878_75M": ["NA12878_75M.recal"]}


def test_remap_ingest_mapping_to_hub() -> None:
    # What build_sample_mapping produces at ingest without a hub: dotted names
    # are their own keys, `-1_1` collapses to `-1`.
    ingest = build_sample_mapping(SAREK_NAMES)
    assert "NA12878_75M" not in ingest
    remapped = remap_mappings_to_hub(ingest, SAREK_HUB)
    assert set(remapped) == set(SAREK_HUB)
    assert set(SAREK_NAMES) <= {v for vs in remapped.values() for v in vs}
