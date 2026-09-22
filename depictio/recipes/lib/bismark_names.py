"""Recover a library name from a Bismark output file name.

Every Bismark output a methylseq run publishes is named after the read-1 FASTQ
it came from, with the trimming stage, the aligner and the step that wrote the
file glued on::

    SRR389222_1_val_1_bismark_bt2_PE_report.txt           bismark align
    SRR389222_1_val_1_bismark_bt2_pe.deduplication_report.txt
    SRR389222_1_val_1_bismark_hisat2_pe.deduplicated.M-bias.txt
    SRR389222_1_val_1_bismark_bt2_pe.deduplicated.bedGraph.gz

The tail differs per step, so each recipe owns the regex for the file it reads;
what is shared is the stripping itself, which every bismark recipe needs and
which recipes may not import from one another.

Shared here rather than copied because seven recipes in one tool need exactly
this, and two of them used to run the regex through a one-element polars Series
(the Rust regex crate) while the other five used Python ``re``, which is two
implementations of one idea.
"""

from __future__ import annotations

import re
from pathlib import Path


def sample_id_from_filename(path: str, suffix: re.Pattern[str]) -> str:
    """The library name left once ``suffix`` is stripped from the file's name.

    Never returns an empty string: a name that is entirely suffix is handed back
    as it came, because dropping a sample id silently merges samples.
    """
    name = Path(str(path)).name
    return suffix.sub("", name) or name
