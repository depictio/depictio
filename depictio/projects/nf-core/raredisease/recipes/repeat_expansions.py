"""nf-core/raredisease repeat expansions: one row per catalog locus and sample.

ExpansionHunter genotypes every locus of the variant catalog in each sample,
SVDB merges the per-sample VCFs into one family VCF, and Stranger annotates each
locus with its pathogenic thresholds and disease. The result is
``repeat_expansions/<family>_repeat_expansion_stranger.vcf.gz``: one record per
locus, the per-sample genotype in the sample columns and the catalog's fields in
INFO. This recipe unpivots the sample columns into one row per locus and sample.

``repeat_status`` is derived per sample from the larger of the two allele repeat counts
(``REPCN``) against the locus thresholds Stranger writes: ``Pathogenic range`` at
or above ``STR_PATHOLOGIC_MIN``, ``Intermediate`` above ``STR_NORMAL_MAX``,
``Normal`` otherwise and ``No call`` when the caller reported none. A locus
status Stranger itself assigned stays as ``str_status``.

Sources:
    raw  ``repeat_expansions/*_repeat_expansion_stranger.vcf.gz``, one VCF line per row

Output schema (a field the catalog does not carry is null):
    variant_key : Utf8       chrom:start:locus
    locus : Utf8             REPID, the catalog's locus name
    chrom : Utf8, start : Int64, end : Int64
    repeat_unit : Utf8       RU, in the reference orientation
    disease : Utf8           the disorder the catalog associates with the locus
    inheritance : Utf8       main mode of inheritance
    sample : Utf8
    gt : Utf8                the sample's genotype as written
    repeat_count : Float64   larger allele, in repeat units
    repeat_counts : Utf8     both alleles as written (REPCN)
    spanning_reads : Int64   reads spanning the larger allele
    locus_coverage : Float64 LC
    filter_status : Utf8     the record's FILTER (LowDepth, PASS)
    str_status : Utf8        Stranger's status for the locus
    normal_max : Int64       repeats still normal
    pathologic_min : Int64   repeats from which the locus is pathogenic
    repeat_status : Utf8     Pathogenic range / Intermediate / Normal / No call
    rank_score : Int64       Stranger's rank score of the locus
    pop_mean : Float64       population mean repeat count (SweGen)
    pop_sd : Float64
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="raw",
        glob_pattern="repeat_expansions/*_repeat_expansion_stranger.vcf.gz",
        format="csv",
        # One full VCF line per row: no separator, quote or header can occur in it.
        read_kwargs={
            "separator": "\x1e",
            "has_header": False,
            "new_columns": ["raw_line"],
            "quote_char": None,
            "infer_schema_length": 0,
        },
        source_path="source_path",
        input_schema={"raw_line": pl.Utf8, "source_path": pl.Utf8},
        # A run that skipped repeat expansion calling publishes none of it.
        optional=True,
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "variant_key": pl.Utf8,
    "locus": pl.Utf8,
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "repeat_unit": pl.Utf8,
    "disease": pl.Utf8,
    "inheritance": pl.Utf8,
    "sample": pl.Utf8,
    "gt": pl.Utf8,
    "repeat_count": pl.Float64,
    "repeat_counts": pl.Utf8,
    "spanning_reads": pl.Int64,
    "locus_coverage": pl.Float64,
    "filter_status": pl.Utf8,
    "str_status": pl.Utf8,
    "normal_max": pl.Int64,
    "pathologic_min": pl.Int64,
    "repeat_status": pl.Utf8,
    "rank_score": pl.Int64,
    "pop_mean": pl.Float64,
    "pop_sd": pl.Float64,
}


def _info(info: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in info.split(";"):
        key, _, value = item.partition("=")
        if key:
            out[key] = value
    return out


def _number(value: str | None) -> float | None:
    if value is None or value in ("", "."):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if number == number else None


def _alleles(value: str) -> list[float]:
    """``2/2`` -> [2.0, 2.0]; a ``.`` allele is dropped."""
    return [n for n in (_number(x) for x in value.replace("|", "/").split("/")) if n is not None]


def _status(count: float | None, normal_max: float | None, pathologic_min: float | None) -> str:
    if count is None:
        return "No call"
    if pathologic_min is not None and count >= pathologic_min:
        return "Pathogenic range"
    if normal_max is not None and count > normal_max:
        return "Intermediate"
    return "Normal"


def _rows(lines: pl.Series) -> list[dict]:
    header = lines.filter(lines.str.starts_with("#CHROM"))
    if header.is_empty():
        return []
    names = header[0].split("\t")[9:]
    rows = []
    for line in lines.filter(~lines.str.starts_with("#")).to_list():
        c = line.split("\t")
        if len(c) < 10:
            continue
        info = _info(c[7])
        keys = c[8].split(":")
        chrom, start = c[0], int(c[1])
        locus = info.get("REPID") or info.get("VARID") or f"{chrom}:{start}"
        end = _number(info.get("END"))
        normal_max, pathologic_min = (
            _number(info.get("STR_NORMAL_MAX")),
            _number(info.get("STR_PATHOLOGIC_MIN")),
        )
        rank = _number(info.get("RankScore", "").rsplit(":", 1)[-1])
        for name, cell in zip(names, c[9:], strict=False):
            parts = cell.split(":")

            def get(k: str, parts: list[str] = parts) -> str:
                return parts[keys.index(k)] if k in keys and keys.index(k) < len(parts) else ""

            counts = _alleles(get("REPCN"))
            count = max(counts) if counts else None
            spanning = _alleles(get("ADSP"))
            rows.append(
                {
                    "variant_key": f"{chrom}:{start}:{locus}",
                    "locus": locus,
                    "chrom": chrom,
                    "start": start,
                    "end": None if end is None else int(end),
                    "repeat_unit": info.get("RU") or None,
                    "disease": info.get("Disease") or None,
                    "inheritance": info.get("InheritanceMode") or None,
                    "sample": name,
                    "gt": get("GT") or None,
                    "repeat_count": count,
                    "repeat_counts": get("REPCN") if counts else None,
                    "spanning_reads": int(max(spanning)) if spanning else None,
                    "locus_coverage": _number(get("LC")),
                    "filter_status": c[6],
                    "str_status": info.get("STR_STATUS") or None,
                    "normal_max": None if normal_max is None else int(normal_max),
                    "pathologic_min": None if pathologic_min is None else int(pathologic_min),
                    "repeat_status": _status(count, normal_max, pathologic_min),
                    "rank_score": None if rank is None else int(rank),
                    "pop_mean": _number(info.get("SweGenMean")),
                    "pop_sd": _number(info.get("SweGenStd")),
                }
            )
    return rows


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """One row per catalog locus and sample."""
    raw = sources.get("raw")
    if raw is None:
        raise ValueError("raredisease repeat_expansions: no repeat_expansions/*_stranger.vcf.gz")
    rows: list[dict] = []
    for path in raw["source_path"].unique(maintain_order=True).to_list():
        rows.extend(_rows(raw.filter(pl.col("source_path") == path)["raw_line"].drop_nulls()))
    if not rows:
        raise ValueError("raredisease repeat_expansions: the Stranger VCF holds no locus")
    return pl.DataFrame(rows, schema=OUTPUT_SCHEMA, strict=False).sort(["chrom", "start", "sample"])
