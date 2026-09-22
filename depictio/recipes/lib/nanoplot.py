"""Which sample a NanoPlot report belongs to.

``NanoStats.txt`` never names its sample. Pipelines put the name either in the
directory NanoPlot wrote into (nf-core/nanoseq:
``nanoplot/fastq/<sample>/NanoStats.txt``) or in the file name itself
(``<sample>_NanoStats.txt``, which is what the nf-core NanoPlot module emits
when it is given a prefix). Reading the file name first and falling back on
the nearest directory that is not one of NanoPlot's own input-kind folders
covers both without a per-pipeline regex.

Shared here because the two NanoPlot recipes need exactly this and recipes may
not import each other.
"""

from __future__ import annotations

import re

from depictio.recipes.lib.sample_ids import strip_stage_suffixes

#: Column holding one full report line (the raw DC scans with a separator that
#: never occurs in the file, so every line lands in this single column).
RAW_LINE_COL = "raw_line"
#: Column carrying the report's path (``include_file_paths`` on the raw DC).
SOURCE_PATH_COL = "source_path"

#: Directory names that describe what NanoPlot was run on, not which sample.
GENERIC_DIRS: frozenset[str] = frozenset(
    {"fastq", "fastq_bam", "bam", "cram", "summary", "sequencing_summary", "nanoplot", "qc"}
)

_REPORT_SUFFIX = re.compile(r"[._-]?nanostats$", re.IGNORECASE)


def sample_of_report(path: str) -> str:
    """The sample a NanoPlot report belongs to, from its path."""
    parts = str(path).replace("\\", "/").split("/")
    stem = parts[-1]
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    stem = _REPORT_SUFFIX.sub("", stem)
    if stem:
        return strip_stage_suffixes(stem)
    for part in reversed(parts[:-1]):
        if part and part.lower() not in GENERIC_DIRS:
            return part
    return "unknown"
