"""Shared parsing for OptiType's HLA class I calls (nf-core/hlatyping).

nf-core/hlatyping writes one ``optitype/<sample>/<sample>_result.tsv`` per
sample: a pandas-style table whose first, unnamed column is the solution index
(0 is the optimum; ``--enumerations N`` adds the N - 1 next best), then one
column per locus and haplotype (``A1``, ``A2``, ``B1``, ``B2``, ``C1``, ``C2``)
holding a two-field allele (``A*02:01``), then ``Reads`` (the reads the solution
explains) and ``Objective`` (the integer linear programme's objective value)::

    \tA1\tA2\tB1\tB2\tC1\tC2\tReads\tObjective
    0\tA*02:01\tA*02:01\tB*07:02\tB*44:02\tC*05:01\tC*07:02\t1129.0\t1108.67

A homozygous locus repeats its allele in both columns. A locus OptiType could
not type is left empty.

Alleles are normalised exactly as the epitopeprediction recipes normalise
theirs (``depictio.recipes.lib.epitope_predictions.normalize_allele``):
``HLA-<gene>*<field1>:<field2>``, so a typed allele and a predicted one are the
same string, and ``hla_locus`` / ``mhc_class`` give the same ``HLA-A`` and
``Class I`` labels as the prediction tables.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

import polars as pl

from depictio.recipes.lib.epitope_predictions import hla_locus, mhc_class, normalize_allele

#: ``A1`` ... ``C2``: the locus letter(s), then the haplotype 1 or 2.
_CALL_COLUMN_RE = re.compile(r"^(?P<gene>[A-Z]{1,4}\d?)(?P<haplotype>[12])$")
_SOLUTION_COLUMNS = ("", "_duplicated_0", "column_1", "index", "Unnamed: 0")
_BLANKS = {"", "NA", "nan", "NaN", "None", "-"}

HOMOZYGOUS = "Homozygous"
HETEROZYGOUS = "Heterozygous"
#: A locus with one haplotype typed and the other left empty.
PARTIAL = "One allele typed"


def sample_of(path: str) -> str:
    """The sample of ``optitype/<sample>/<sample>_result.tsv``.

    The folder names the sample; the file stem without ``_result`` is the
    fallback for a file that sits outside a per-sample folder.
    """
    p = PurePosixPath(str(path))
    stem = re.sub(r"_result$", "", p.stem)
    parent = p.parent.name
    if parent and parent != "optitype" and stem.startswith(parent):
        return parent
    return stem


def allele_group(allele: str | None) -> str | None:
    """The first field of a normalised allele: ``HLA-A*02:01`` is ``HLA-A*02``."""
    if not allele or "*" not in allele:
        return allele
    gene, fields = allele.split("*", 1)
    return f"{gene}*{fields.split(':', 1)[0]}"


def _clean(value: object) -> str | None:
    text = "" if value is None else str(value).strip()
    return None if text in _BLANKS else text


def _float(value: object) -> float | None:
    text = _clean(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def read_calls(raw: pl.DataFrame) -> pl.DataFrame:
    """Every allele call of every solution, one row per sample, solution, locus and haplotype.

    ``raw`` is the glob source: every result table read as text, with the
    ``source_path`` column the recipe source adds. Columns:
    ``sample_id, solution, locus, haplotype, allele, reads, objective``. A locus
    left empty is dropped; a solution with no call at all keeps no row.
    """
    if "source_path" not in raw.columns:
        raise ValueError("OptiType results: the source must carry `source_path`")
    solution_col = next((c for c in _SOLUTION_COLUMNS if c in raw.columns), None)
    call_cols = [(c, m) for c in raw.columns if (m := _CALL_COLUMN_RE.match(c))]
    if not call_cols:
        raise ValueError(f"OptiType results: no allele column (A1, A2, B1 ...) in {raw.columns}")
    rows: list[dict] = []
    # A run's tables are a handful of rows each; plain iteration keeps the
    # melt readable and the per-file solution index exact.
    position: dict[str, int] = {}
    for record in raw.iter_rows(named=True):
        path = str(record["source_path"])
        sample = sample_of(path)
        index = position.get(path, 0)
        position[path] = index + 1
        solution_raw = _float(record.get(solution_col)) if solution_col else None
        solution = int(solution_raw) if solution_raw is not None else index
        reads = _float(record.get("Reads"))
        objective = _float(record.get("Objective"))
        for col, match in call_cols:
            allele = normalize_allele(_clean(record.get(col)))
            if allele is None:
                continue
            rows.append(
                {
                    "sample_id": sample,
                    "solution": solution,
                    "locus": hla_locus(allele)
                    if allele.startswith("HLA-")
                    else f"HLA-{match['gene']}",
                    "haplotype": int(match["haplotype"]),
                    "allele": allele,
                    "reads": None if reads is None else int(round(reads)),
                    "objective": objective,
                }
            )
    schema = {
        "sample_id": pl.Utf8,
        "solution": pl.Int64,
        "locus": pl.Utf8,
        "haplotype": pl.Int64,
        "allele": pl.Utf8,
        "reads": pl.Int64,
        "objective": pl.Float64,
    }
    return pl.DataFrame(rows, schema=schema, orient="row")


def best_calls(calls: pl.DataFrame) -> pl.DataFrame:
    """The optimal solution of each sample (the lowest solution index)."""
    if calls.is_empty():
        return calls
    best = calls.group_by("sample_id").agg(pl.col("solution").min().alias("_best"))
    return (
        calls.join(best, on="sample_id").filter(pl.col("solution") == pl.col("_best")).drop("_best")
    )


def with_call_annotations(calls: pl.DataFrame) -> pl.DataFrame:
    """Add ``allele_group``, ``hla_class`` and ``zygosity`` (per sample and locus).

    ``zygosity`` is ``Homozygous`` when both haplotypes carry one allele,
    ``Heterozygous`` when they differ, and ``One allele typed`` when OptiType
    left one of the two empty.
    """
    distinct = calls.group_by(["sample_id", "solution", "locus"]).agg(
        pl.col("allele").n_unique().alias("_n"),
        pl.len().alias("_calls"),
    )
    return (
        calls.join(distinct, on=["sample_id", "solution", "locus"], how="left")
        .with_columns(
            pl.col("allele").map_elements(allele_group, return_dtype=pl.Utf8).alias("allele_group"),
            pl.col("allele")
            .map_elements(lambda a: mhc_class(a, None), return_dtype=pl.Utf8)
            .alias("hla_class"),
            pl.when(pl.col("_calls") < 2)
            .then(pl.lit(PARTIAL))
            .when(pl.col("_n") == 1)
            .then(pl.lit(HOMOZYGOUS))
            .otherwise(pl.lit(HETEROZYGOUS))
            .alias("zygosity"),
        )
        .drop("_n", "_calls")
    )
