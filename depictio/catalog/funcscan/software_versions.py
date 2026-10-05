"""Software versions the run recorded, one row per process and tool.

nf-core/funcscan feeds MultiQC nothing but the software-versions table: the
4.0.0 megatest parquet holds a single ``run_metadata`` row, ``list_plots()``
returns two modules with no plots and ``list_samples()`` is empty, so there is
no MultiQC panel to bind. The payload is still there, in the row's
``software_versions`` field, and this recipe turns it into a table: one row per
(process, tool) with the version the process reported and the screen the
process belongs to.

The screen is read from the process name, which nf-core spells in upper case
with the sub-workflow as a prefix (``AMP_HMMER_HMMSEARCH``,
``ARG_HAMRONIZATION_SUMMARIZE``) or with the tool's own name
(``ANTISMASH_ANTISMASH``). A process that matches no screen is workflow
plumbing (untar, gunzip, MultiQC itself) and is labelled as such rather than
dropped, so the table accounts for the whole run.

Output columns:
    process, tool, version, screen, tools
"""

import json

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="report",
        # The report sits at multiqc/multiqc_data/ in a plain run and one level
        # deeper when the pipeline writes a per-aligner report; `**` covers both.
        glob_pattern="**/multiqc_data/multiqc.parquet",
        format="parquet",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "process": pl.Utf8,
    "tool": pl.Utf8,
    "version": pl.Utf8,
    "screen": pl.Utf8,
    "tools": pl.Int64,
}

# Matched in order against the upper-cased process name: the first hit wins, so
# the sub-workflow prefixes come before the bare tool names they contain.
_SCREEN_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "ARG",
        (
            "ARG_",
            "ABRICATE",
            "AMRFINDERPLUS",
            "DEEPARG",
            "FARGENE",
            "RGI",
            "HAMRONIZATION",
        ),
    ),
    ("AMP", ("AMP_", "AMPIR", "AMPLIFY", "AMPCOMBI", "MACREL")),
    ("BGC", ("BGC_", "ANTISMASH", "DEEPBGC", "GECCO", "COMBGC")),
    ("CAZyme", ("CAZYME", "DBCAN")),
    ("Annotation", ("ANNOTATION", "PYRODIGAL", "PRODIGAL", "BAKTA", "PROKKA")),
    ("Taxonomy", ("TAXA_", "MMSEQS", "KRAKEN")),
]
_OTHER_SCREEN = "Workflow"


def _screen(process: str) -> str:
    name = process.upper()
    for label, prefixes in _SCREEN_RULES:
        if any(token in name for token in prefixes):
            return label
    return _OTHER_SCREEN


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Explode the report's software_versions mapping into a tidy table."""
    df = sources["report"]
    if "software_versions" not in df.columns:
        raise ValueError("software_versions: the MultiQC report carries no software_versions field")

    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for payload in df["software_versions"].drop_nulls().to_list():
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            continue
        for process, tools in payload.items():
            if not isinstance(tools, dict):
                continue
            for tool, versions in tools.items():
                if isinstance(versions, (list, tuple)):
                    version = ", ".join(str(v) for v in versions)
                else:
                    version = str(versions)
                key = (str(process), str(tool), version)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    {
                        "process": str(process),
                        "tool": str(tool),
                        "version": version,
                        "screen": _screen(str(process)),
                        "tools": 1,
                    }
                )

    if not rows:
        raise ValueError("software_versions: the MultiQC report listed no software versions")

    return (
        pl.DataFrame(rows, schema=EXPECTED_SCHEMA)
        .sort("screen", "process", "tool")
        .select(list(EXPECTED_SCHEMA))
    )
