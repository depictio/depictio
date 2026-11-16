"""The bundle's MultiQC sample expansion: same answer as the server, in linear-ish time.

``expansion_from_mappings`` must equal, id for id, the naive per-id
``expand_canonical_samples_to_variants([id], remap_mappings_to_hub(mappings,
[id]))`` it replaces. That one is quadratic and ran a viralrecon export
(~21k ids) for ten minutes, past the task's limit.
"""

from __future__ import annotations

import random
import time

from depictio.api.v1.services.multiqc.patching import expand_canonical_samples_to_variants
from depictio.cli.cli.utils.sample_mapping import remap_mappings_to_hub
from depictio.serverless.producer_a import expansion_from_mappings


def _naive(mappings: dict[str, list[str]]) -> dict[str, list[str]]:
    ids = {k for k in mappings} | {v for vs in mappings.values() for v in vs}
    out: dict[str, list[str]] = {}
    for sample in sorted(ids):
        variants = expand_canonical_samples_to_variants(
            [sample], remap_mappings_to_hub(mappings, [sample])
        )
        extra = [str(v) for v in variants if str(v) != sample]
        if extra:
            out[sample] = extra
    return out


# Names exercising every matching rule: read suffixes, annotation tails,
# stage tokens, path prefixes, infix ids, nested ids, case and _R/_L suffixes.
TRICKY = {
    "SRR1": ["SRR1_1", "SRR1_2", "SRR1 - First read: Adapter 1", "srr1_val_1"],
    "SRR10": ["SRR10_1", "SRR10.md", "SRR10.trimmed"],
    "S1": ["S1_2.md", "FLYE-MaxBin2-S1.003.fa", "dir/S1.bam"],
    "S1_2": ["S1_2_val_1"],
    "CAPES_S11": ["FLYE-CAPES_S11", "FLYE-MaxBin2-CAPES_S11.003.fa"],
    "HG001_R1": ["HG001_R1.fastq.gz"],
    "HG001_R2": ["HG001_R2.fastq.gz"],
    "hg002": ["HG002_L001", " HG002 "],
    "Sample_2024": ["Sample_2024_1"],
    "NA12878_75M": ["NA12878_75M.deepvariant_VEP.ann", "NA12878_75M-1_1", "NA12878_75MX"],
    "A-B": ["X-A-B-Y", "A-B.C"],
    "lonely": [],
}


def test_matches_the_server_expansion_on_tricky_names() -> None:
    assert expansion_from_mappings(TRICKY) == _naive(TRICKY)


def test_matches_the_server_expansion_on_random_mappings() -> None:
    rng = random.Random(1303)
    tokens = ["S1", "S12", "SRR7", "srr7", "A", "A_B", "x", "MAG"]
    suffixes = ["", "_1", "_2", "_R1", "_L001", ".md", ".bam", "_val_1", " - adapter", "-bin.1"]
    for _ in range(40):
        mappings: dict[str, list[str]] = {}
        for _ in range(rng.randint(1, 8)):
            key = rng.choice(tokens) + rng.choice(["", "_R1", "_REP1", "-2"])
            mappings.setdefault(key, [])
            for _ in range(rng.randint(0, 4)):
                prefix = rng.choice(["", "run-", "dir/", "FLYE-"])
                mappings[key].append(prefix + rng.choice(tokens) + rng.choice(suffixes))
        assert expansion_from_mappings(mappings) == _naive(mappings), mappings


def test_twenty_thousand_ids_take_seconds_not_minutes() -> None:
    mappings = {
        f"SRR{1_000_000 + i}": [f"SRR{1_000_000 + i}_1", f"SRR{1_000_000 + i}_2"]
        for i in range(7_000)
    }
    started = time.monotonic()
    out = expansion_from_mappings(mappings)
    elapsed = time.monotonic() - started
    assert out["SRR1000000"] == ["SRR1000000_1", "SRR1000000_2"]
    assert elapsed < 30, f"{elapsed:.1f}s for 21k ids"
