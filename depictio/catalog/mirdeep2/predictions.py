"""miRNA precursor predictions from miRDeep2 result tables, one row per candidate.

miRDeep2 writes one ``result_<sample>.csv`` per sample. Despite the extension
it is a tab-separated report in blocks separated by blank lines::

    miRDeep2 score  novel miRNAs reported by miRDeep2  ...     <- score summary
    10  1  1 +/- 1  ...
    <blank lines>
    novel miRNAs predicted by miRDeep2                        <- block title
    provisional id  miRDeep2 score  estimated probability ...  <- header
    14_5926  33.2  37 +/- 49%  -  62  50  0  12  yes  ...     <- one candidate
    <blank lines>
    mature miRBase miRNAs detected by miRDeep2
    tag id  miRDeep2 score  ...
    <blank lines>
    #miRBase miRNAs not detected by miRDeep2
    ...

This recipe keeps the two candidate blocks: ``novel`` precursors (not in
miRBase) and ``known`` ones (miRBase hairpins miRDeep2 re-discovered). Both
share one column layout, so they stack into one table with a ``category``
column. The block of undetected miRBase entries carries no score and is left
out; the score summary is ``mirdeep2/score_summary.py``.

The probability column reads ``37 +/- 49%``: the estimated probability that a
candidate with this score is a true positive, with its spread. It is split into
two numbers. The precursor coordinate ``14:36673762..36673820:+`` is split into
chromosome, start, end and strand, and ``locus`` keeps it as one key.

The table does not name its sample inside, so the id is the file name with the
``result_`` prefix and the extension removed.

Input: a data collection reading every matched table one LINE per row (a
separator the report cannot contain), with ``include_file_paths: source_path``.

Output schema:
    prediction_id : Utf8          sample + candidate id, unique per row
    sample : Utf8                 sample the table was written for
    category : Utf8               novel | known
    candidate_id : Utf8           miRDeep2 provisional id (novel) or tag id (known)
    score : Float64               miRDeep2 score (log-odds the hairpin is a real precursor)
    true_positive_pct : Float64   estimated probability a candidate at this score is real, %
    true_positive_sd : Float64    its spread, %
    rfam_alert : Utf8             Rfam family the precursor also matches (rRNA, tRNA), or "-"
    total_reads : Int64           reads on the precursor
    mature_reads : Int64          reads on the mature arm
    loop_reads : Int64            reads on the loop
    star_reads : Int64            reads on the star arm
    randfold_significant : Utf8   yes | no: the fold is more stable than shuffled sequences
    mirbase_mirna : Utf8          miRBase mature miRNA the candidate matches, or "-"
    seed_match : Utf8             a miRBase miRNA sharing the seed, or "-"
    mature_sequence : Utf8        consensus mature sequence
    star_sequence : Utf8          consensus star sequence
    precursor_sequence : Utf8     consensus precursor sequence
    precursor_length : Int64      length of the precursor, nt
    chromosome : Utf8
    start : Int64
    end : Int64
    strand : Utf8
    locus : Utf8                  chromosome:start-end:strand
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the template must scan the result tables into.
RAW_DC_TAG = "mirdeep2_results_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="results", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "prediction_id": pl.Utf8,
    "sample": pl.Utf8,
    "category": pl.Utf8,
    "candidate_id": pl.Utf8,
    "score": pl.Float64,
    "true_positive_pct": pl.Float64,
    "true_positive_sd": pl.Float64,
    "rfam_alert": pl.Utf8,
    "total_reads": pl.Int64,
    "mature_reads": pl.Int64,
    "loop_reads": pl.Int64,
    "star_reads": pl.Int64,
    "randfold_significant": pl.Utf8,
    "mirbase_mirna": pl.Utf8,
    "seed_match": pl.Utf8,
    "mature_sequence": pl.Utf8,
    "star_sequence": pl.Utf8,
    "precursor_sequence": pl.Utf8,
    "precursor_length": pl.Int64,
    "chromosome": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "strand": pl.Utf8,
    "locus": pl.Utf8,
}

RAW_LINE_COL = "raw"
SOURCE_PATH_COL = "source_path"

#: Block titles (lower-cased) -> the category their rows get.
_BLOCKS = {
    "novel mirnas predicted by mirdeep2": "novel",
    "mature mirbase mirnas detected by mirdeep2": "known",
}

#: Column position in a candidate row -> field. Both blocks share this layout.
_FIELDS = [
    "candidate_id",
    "score",
    "probability",
    "rfam_alert",
    "total_reads",
    "mature_reads",
    "loop_reads",
    "star_reads",
    "randfold_significant",
    "mirbase_mirna",
    "seed_match",
    "ucsc",
    "blast",
    "mature_sequence",
    "star_sequence",
    "precursor_sequence",
    "coordinate",
]

_PROBABILITY = re.compile(r"^\s*([\d.]+)\s*\+/-\s*([\d.]+)\s*%?\s*$")
_COORDINATE = re.compile(r"^(?P<chrom>.+):(?P<start>\d+)\.\.(?P<end>\d+):(?P<strand>[+-])$")


def _sample_from_path(source_path: str) -> str:
    name = str(source_path).replace("\\", "/").rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return stem[len("result_") :] if stem.startswith("result_") else stem


def _int(value: str) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse(source_path: str, lines: list[str | None]) -> list[dict]:
    sample = _sample_from_path(source_path)
    rows: list[dict] = []
    category: str | None = None
    expect_header = False
    for line in lines:
        text = (line or "").rstrip("\r\n")
        if not text.strip():
            category = None
            continue
        title = text.strip().lstrip("#").strip().lower()
        if title in _BLOCKS:
            category = _BLOCKS[title]
            expect_header = True
            continue
        if category is None:
            continue
        if expect_header:
            expect_header = False
            continue
        cells = text.split("\t")
        if len(cells) < len(_FIELDS):
            cells += [""] * (len(_FIELDS) - len(cells))
        record = dict(zip(_FIELDS, cells))
        prob = _PROBABILITY.match(record["probability"] or "")
        coord = _COORDINATE.match((record["coordinate"] or "").strip())
        precursor = (record["precursor_sequence"] or "").strip()
        rows.append(
            {
                "prediction_id": f"{sample}:{record['candidate_id']}",
                "sample": sample,
                "category": category,
                "candidate_id": record["candidate_id"],
                "score": _float(record["score"]),
                "true_positive_pct": float(prob.group(1)) if prob else None,
                "true_positive_sd": float(prob.group(2)) if prob else None,
                "rfam_alert": record["rfam_alert"] or "-",
                "total_reads": _int(record["total_reads"]),
                "mature_reads": _int(record["mature_reads"]),
                "loop_reads": _int(record["loop_reads"]),
                "star_reads": _int(record["star_reads"]),
                "randfold_significant": record["randfold_significant"] or None,
                "mirbase_mirna": record["mirbase_mirna"] or "-",
                "seed_match": record["seed_match"] or "-",
                "mature_sequence": record["mature_sequence"] or None,
                "star_sequence": record["star_sequence"] or None,
                "precursor_sequence": precursor or None,
                "precursor_length": len(precursor) if precursor else None,
                "chromosome": coord.group("chrom") if coord else None,
                "start": int(coord.group("start")) if coord else None,
                "end": int(coord.group("end")) if coord else None,
                "strand": coord.group("strand") if coord else None,
                "locus": (
                    f"{coord.group('chrom')}:{coord.group('start')}-{coord.group('end')}"
                    f":{coord.group('strand')}"
                    if coord
                    else None
                ),
            }
        )
    return rows


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per novel or known candidate, over every scanned table."""
    raw = sources["results"]
    if raw.is_empty():
        raise ValueError("mirdeep2_predictions: the scanned result tables are empty")
    for column in (RAW_LINE_COL, SOURCE_PATH_COL):
        if column not in raw.columns:
            raise ValueError(
                f"mirdeep2_predictions: no {column} column, the data collection must "
                f"scan one line per row with include_file_paths: source_path"
            )
    rows: list[dict] = []
    for (path,), group in raw.group_by([SOURCE_PATH_COL], maintain_order=True):
        rows.extend(_parse(str(path), group[RAW_LINE_COL].to_list()))
    if not rows:
        raise ValueError("mirdeep2_predictions: no table carried a candidate block")
    frame = pl.DataFrame(rows, schema=EXPECTED_SCHEMA)
    return frame.sort(["sample", "category", "score"], descending=[False, True, True])
