"""Recover a sample id from an alignment-derived file or BAM name.

The ChIP-family pipelines publish per-sample QC beside a BAM whose name records
every stage it went through, and different tools quote a different amount of it:

    GM12878_STD_R1.mLb.mkD.ccurve.txt          preseq, atacseq
    EZH2_IP_NTKO_R1.ccurve.txt                 preseq, chipseq
    GM12878_OMNI_R1.mLb.clN                    deepTools Sample column, atacseq
    h3k4me3_R1.target.markdup.sorted.bam       deepTools Sample column, cutandrun

All four name the same thing: a sample of the samplesheet. Trimming them with a
regex anchored at the end is fragile — the stage tokens and the format suffix
interleave differently per pipeline, and a single pass leaves whichever half it
did not match. So the name is split on ``.`` and trailing tokens are dropped
while they are known stage or format words, which converges regardless of order
and never eats a token it does not recognise.

Shared here rather than copied because three recipes in two tools need exactly
this, and recipes may not import each other.
"""

from __future__ import annotations

#: Trailing dot-separated tokens that describe a processing stage or a file
#: format rather than the sample. Compared lower-cased.
STAGE_TOKENS: frozenset[str] = frozenset(
    {
        # formats
        "txt",
        "tab",
        "tsv",
        "csv",
        "bam",
        "bed",
        # tool-written suffixes
        "ccurve",
        "c_curve",
        "lc_extrap",
        "plotfingerprint",
        "plotprofile",
        "plotpca",
        "plotcorrelation",
        "qcmetrics",
        "raw",
        "mat",
        # alignment stages: chipseq / atacseq merged library and replicate
        # levels, and the filtering steps applied at each
        "mlb",
        "mrp",
        "mkd",
        "cln",
        "clt",
        # cutandrun
        "target",
        "spikein",
        "markdup",
        "sorted",
        "dedup",
    }
)


def strip_stage_suffixes(name: str) -> str:
    """The sample id inside a published file or BAM name.

    Never returns an empty string: a name made entirely of stage tokens is
    handed back as it came, because dropping it would silently merge samples.
    """
    stem = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    tokens = stem.split(".")
    while len(tokens) > 1 and tokens[-1].lower() in STAGE_TOKENS:
        tokens.pop()
    return ".".join(tokens)
