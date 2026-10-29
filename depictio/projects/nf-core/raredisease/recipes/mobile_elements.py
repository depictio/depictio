"""nf-core/raredisease mobile element insertions: one row per insertion and carrying sample.

The mobile element caller runs per sample and writes one VCF each; SVDB merges them into
``call_mobile_elements/<family>_mobile_elements.vcf.gz``: one record per insertion
site, ``<INS:ME>`` as ALT, the element family in ``MEINFO`` (``NAME,START,END,POLARITY``)
and the per-sample evidence in FORMAT (``GT:GQ:FL:SP:CLIP5:CLIP3``). This recipe
unpivots the sample columns and keeps the samples carrying the insertion (a genotype
with an alternate allele).

``me_type`` folds the element name onto ALU, L1, SVA, HERV or Other (a name such as
``unknown-ALU`` takes the family it names). ``samples_sharing`` is how many samples of
the family carry the insertion, so a call every sample shares reads apart from one
private to a sample.

Sources:
    raw  ``call_mobile_elements/*_mobile_elements.vcf.gz``, one VCF line per row

Output schema (a field a record does not carry is null):
    variant_key : Utf8       chrom:pos:ME type
    chrom : Utf8, pos : Int64, end : Int64   insertion site, MEINFO end
    me_type : Utf8           ALU / L1 / SVA / HERV / Other
    sample : Utf8
    gt : Utf8
    qual : Float64           the record's QUAL
    gq : Float64             the sample's genotype quality
    flag : Int64             FL, the caller's call status flag
    spanning_pairs : Float64 SP, read pairs spanning the breakpoint
    clipped_5p : Float64     CLIP5, soft-clipped reads upstream
    clipped_3p : Float64     CLIP3, soft-clipped reads downstream
    filter_status : Utf8
    samples_sharing : Int64  samples of the family carrying the insertion
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="raw",
        glob_pattern="call_mobile_elements/*_mobile_elements.vcf.gz",
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
        # A run that skipped mobile element calling publishes none of it.
        optional=True,
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "variant_key": pl.Utf8,
    "chrom": pl.Utf8,
    "pos": pl.Int64,
    "end": pl.Int64,
    "me_type": pl.Utf8,
    "sample": pl.Utf8,
    "gt": pl.Utf8,
    "qual": pl.Float64,
    "gq": pl.Float64,
    "flag": pl.Int64,
    "spanning_pairs": pl.Float64,
    "clipped_5p": pl.Float64,
    "clipped_3p": pl.Float64,
    "filter_status": pl.Utf8,
    "samples_sharing": pl.Int64,
}


def _number(value: str | None) -> float | None:
    if value is None or value in ("", "."):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if number == number else None


def _me_type(name: str) -> str:
    upper = name.upper()
    for family in ("ALU", "SVA", "HERV", "L1"):
        if family in upper:
            return family
    return "Other"


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
        meinfo = re.search(r"(?:^|;)MEINFO=([^;]*)", c[7])
        parts = meinfo.group(1).split(",") if meinfo else []
        me_type = _me_type(parts[0]) if parts else "Other"
        end = _number(parts[2]) if len(parts) > 2 else None
        keys = c[8].split(":")
        pos = int(c[1])
        carriers = []
        for name, cell in zip(names, c[9:], strict=False):
            cells = cell.split(":")
            gt = cells[keys.index("GT")] if "GT" in keys and keys.index("GT") < len(cells) else ""
            if re.search(r"[1-9]", gt):
                carriers.append((name, cells, gt))
        for name, cells, gt in carriers:

            def get(k: str, cells: list[str] = cells) -> str:
                return cells[keys.index(k)] if k in keys and keys.index(k) < len(cells) else ""

            flag = _number(get("FL"))
            rows.append(
                {
                    "variant_key": f"{c[0]}:{pos}:{me_type}",
                    "chrom": c[0],
                    "pos": pos,
                    "end": None if end is None else int(end),
                    "me_type": me_type,
                    "sample": name,
                    "gt": gt,
                    "qual": _number(c[5]),
                    "gq": _number(get("GQ")),
                    "flag": None if flag is None else int(flag),
                    "spanning_pairs": _number(get("SP")),
                    "clipped_5p": _number(get("CLIP5")),
                    "clipped_3p": _number(get("CLIP3")),
                    "filter_status": c[6],
                    "samples_sharing": len(carriers),
                }
            )
    return rows


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """One row per insertion and carrying sample."""
    raw = sources.get("raw")
    if raw is None:
        raise ValueError(
            "raredisease mobile_elements: no call_mobile_elements/*_mobile_elements.vcf.gz"
        )
    rows: list[dict] = []
    for path in raw["source_path"].unique(maintain_order=True).to_list():
        rows.extend(_rows(raw.filter(pl.col("source_path") == path)["raw_line"].drop_nulls()))
    if not rows:
        raise ValueError(
            "raredisease mobile_elements: no sample carries a mobile element insertion"
        )
    return pl.DataFrame(rows, schema=OUTPUT_SCHEMA, strict=False).sort(["chrom", "pos", "sample"])
