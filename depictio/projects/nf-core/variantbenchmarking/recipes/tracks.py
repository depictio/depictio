"""Genome-browser track manifest: the false positives and false negatives of every callset.

nf-core/variantbenchmarking writes every benchmark under
``<variant_type>/<callset id>/benchmarks/<tool>/`` and names each file after the
callset: ``<id>.<truth set>.<caller>.<kind>.vcf.gz``. The aggregated summary
tables (the ones the dashboard's own collections read) list one row per
benchmarked callset, so the manifest is spelled out from them rather than
globbed. Per callset it holds the files a reader opens to see *where* the
errors are:

- germline, ``small/`` (rtg-tools vcfeval): ``fp`` and ``fn``, then ``tp``
  (``<id>.<truth>.<caller>.{fp,fn,tp}.vcf.gz``);
- structural, ``structural/`` (Truvari): ``fp`` and ``fn``, then ``tp-comp``
  (``<id>.<truth>.<caller>.{fp,fn,tp-comp}.vcf.gz``).

Every row is keyed on the callset id (``sample_id``), the key the benchmark
tables link on, so picking a callset on the dashboard opens its FP, FN and TP
files side by side. They are small (kilobytes to a few megabytes), so the first
two rows of a callset (false positives, false negatives) are what the browser
opens on.

A run writes one variant type, so either source (or, on a data root that holds
two routes, both) is absent: an absent source contributes no row, and a run that
holds neither has nothing to show and is an error, which the template's
``optional`` flag turns into a left-out collection.

Two ways the files are read:
- ``TRACKS_URI`` is set (the template turns it into ``remote_base_uri``): every
  expected row is kept and read in place under that results folder;
- otherwise the rows whose file and ``.tbi`` index are present under DATA_ROOT
  are kept and the CLI uploads them at ingestion (all rows are kept when none
  is present, so a tables-only run still lists what the pipeline publishes).

Output schema:
    track_id : Utf8     `<tool>.<id>.<truth>.<caller>.<kind>`, unique per file
    sample_id : Utf8    the callset id (links to the benchmark tables' `label`)
    caller : Utf8       the variant caller that made the calls
    truth_set : Utf8    the truth set the callset was compared against
    tool : Utf8         the benchmarking tool that wrote the file (rtgtools / truvari)
    kind : Utf8         fp / fn / tp
    format : Utf8       vcf
    uri : Utf8          path relative to the results folder
    name : Utf8         track label shown in the browser
    color : Utf8        per-kind colour
    category : Utf8     track-selector folder
    order : Int64       row order the browser opens with (``order_column``)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

_CSV_KWARGS = {"infer_schema_length": 0}

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="rtgtools_summary",
        path="small/summary/tables/rtgtools/rtgtools.summary.csv",
        format="CSV",
        input_schema={"Tool": pl.Utf8},
        read_kwargs=_CSV_KWARGS,
        optional=True,
    ),
    RecipeSource(
        ref="truvari_summary",
        path="structural/summary/tables/truvari/truvari.summary.csv",
        format="CSV",
        input_schema={"Tool": pl.Utf8},
        read_kwargs=_CSV_KWARGS,
        optional=True,
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "track_id": pl.Utf8,
    "sample_id": pl.Utf8,
    "caller": pl.Utf8,
    "truth_set": pl.Utf8,
    "tool": pl.Utf8,
    "kind": pl.Utf8,
    "format": pl.Utf8,
    "uri": pl.Utf8,
    "name": pl.Utf8,
    "color": pl.Utf8,
    "category": pl.Utf8,
    "order": pl.Int64,
}

# source ref -> (route directory, tool directory, file kinds in the order they open).
_ROUTES = {
    "rtgtools_summary": ("small", "rtgtools", ("fp", "fn", "tp")),
    "truvari_summary": ("structural", "truvari", ("fp", "fn", "tp-comp")),
}

# kind -> (label shown in the track name, track-selector folder, Okabe-Ito colour).
_KINDS = {
    "fp": ("false positives", "False positives", "rgb(213,94,0)"),
    "fn": ("false negatives", "False negatives", "rgb(0,114,178)"),
    "tp": ("true positives", "True positives", "rgb(0,158,115)"),
    "tp-comp": ("true positives", "True positives", "rgb(0,158,115)"),
}


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _stem(row: dict, label: str) -> str | None:
    """``<id>.<truth set>.<caller>``: the prefix of every file the pipeline wrote for the callset.

    ``File`` names the callset's own result (``<id>.<truth>.<caller>.summary.txt``,
    ``.summary.json``, ``.stats.csv``): its last two tokens are the result's own
    suffix, and what stays holds the truth set whatever dots it has. A row
    without a usable ``File`` has no stem and no row.
    """
    file_name = _text(row.get("File"))
    if file_name.startswith(label + ".") and file_name.count(".") >= 3:
        return file_name.rsplit(".", 2)[0]
    return None


def _truth_of(stem: str, label: str, caller: str) -> str:
    inner = stem[len(label) + 1 :]
    return inner[: -(len(caller) + 1)] if caller and inner.endswith("." + caller) else inner


def _index_of(path: str) -> str:
    return path + ".tbi"


def transform(sources: dict[str, pl.DataFrame | None], context=None) -> pl.DataFrame:
    """Spell out the expected FP, FN and TP files of every callset of the summary tables."""
    in_place = context is None or context.reads_in_place

    def present(path: str) -> bool:
        """The file and its index are under the data root (an upload needs both)."""
        return context is not None and context.exists(path) and context.exists(_index_of(path))

    rows: list[dict] = []
    seen_any_source = False
    for ref, (route, tool, kinds) in _ROUTES.items():
        table = sources.get(ref)
        if table is None:
            continue
        seen_any_source = True
        if "Threshold" in table.columns:
            # A threshold sweep repeats the callset: keep its canonical row.
            table = table.with_columns(pl.col("Threshold").cast(pl.Utf8))
            if (table["Threshold"] == "None").any():
                table = table.filter(pl.col("Threshold") == "None")
        seen: set[str] = set()
        for row in table.iter_rows(named=True):
            label = _text(row.get("Tool"))
            if not label:
                continue
            stem = _stem(row, label)
            if stem is None or stem in seen:
                continue
            seen.add(stem)
            caller = _text(row.get("Caller"))
            truth = _truth_of(stem, label, caller)
            for kind in kinds:
                phrase, category, color = _KINDS[kind]
                rows.append(
                    {
                        "track_id": f"{tool}.{stem}.{kind}",
                        "sample_id": label,
                        "caller": caller or None,
                        "truth_set": truth or None,
                        "tool": tool,
                        "kind": "tp" if kind.startswith("tp") else kind,
                        "format": "vcf",
                        "uri": f"{route}/{label}/benchmarks/{tool}/{stem}.{kind}.vcf.gz",
                        "name": f"{label} {phrase}",
                        "color": color,
                        "category": category,
                    }
                )

    if not seen_any_source:
        raise ValueError(
            "variantbenchmarking tracks: neither small/summary/tables/rtgtools/rtgtools.summary.csv "
            "nor structural/summary/tables/truvari/truvari.summary.csv under the data root; "
            "the genome tracks are written by the germline and the structural routes only"
        )

    if not in_place and any(present(r["uri"]) for r in rows):
        rows = [r for r in rows if present(r["uri"])]
    # Ingestion reorders rows (clustering on link columns): keep the intended
    # order explicit, the browser opens on the first `initial_tracks`.
    for i, row in enumerate(rows, start=1):
        row["order"] = i
    return pl.DataFrame(rows, schema=OUTPUT_SCHEMA)
