"""Run metrics per lane and read from ``interop_summary --csv=1``: SAV's summary table.

The InterOp ``summary`` executable prints, after a run-level block, one block
per read (``Read 1``, ``Read 2 (I)`` for an index read, ...), each a CSV table
with one row per lane and surface::

    Read 1
    Lane,Surface,Tiles,Density,Cluster PF,Phas/Prephas,...,%>=Q30,Yield,...,Error,...
    1,-,112,2355 +/- 0,76.69 +/- 2.37,0.123 / 0.068,...,94.30,54.54,...,0.33 +/- 0.09,...
    1,1,56,...

The recipe keeps the lane rows (``Surface`` is ``-``) of every read block: the
error rate and the phasing that the demultiplexer reports do not carry, next
to the density, the cluster pass-filter rate and the Q30 share. ``+/-``
spreads are split into a mean and a standard deviation where the spread is
worth keeping (error rate, cluster PF); ``nan`` becomes null.

The file is read one LINE per row (the text-scan idiom) because it mixes
several tables of different widths::

    dc_specific_properties:
      format: TSV
      polars_kwargs:
        separator: "\\x1f"
        quote_char: null
        has_header: false
        new_columns: ["raw"]
        include_file_paths: "source_path"
        infer_schema_length: 0

Output schema:
    run_id : Utf8               run folder name the summary names on its second line
    lane : Int64                lane number
    lane_label : Utf8           "Lane <n>"
    read : Int64                read number, index reads included
    read_label : Utf8           "Read <n>", with " (I)" on an index read
    is_index_read : Boolean     true on an index read
    tiles : Int64               tiles imaged
    density_k_mm2 : Float64     cluster density, thousands per square millimetre
    pct_cluster_pf : Float64    clusters passing filter, percent (mean over tiles)
    pct_cluster_pf_sd : Float64 its standard deviation over tiles
    phasing : Float64           phasing, percent per cycle
    prephasing : Float64        prephasing, percent per cycle
    reads_m : Float64           clusters, millions
    reads_pf_m : Float64        clusters passing filter, millions
    pct_q30 : Float64           bases at Q30 or above, percent
    frac_q30 : Float64          the same as a fraction, 0 to 1
    yield_gb : Float64          yield, gigabases
    pct_aligned : Float64       reads aligned to the PhiX control, percent
    error_rate : Float64        PhiX error rate, percent (null without a PhiX spike-in)
    error_rate_sd : Float64     its standard deviation over tiles
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the template must scan the summary files into, one line per row.
RAW_DC_TAG = "interop_summary_raw"

SOURCES: list[RecipeSource] = [RecipeSource(ref="summary", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "run_id": pl.Utf8,
    "lane": pl.Int64,
    "lane_label": pl.Utf8,
    "read": pl.Int64,
    "read_label": pl.Utf8,
    "is_index_read": pl.Boolean,
    "tiles": pl.Int64,
    "density_k_mm2": pl.Float64,
    "pct_cluster_pf": pl.Float64,
    "pct_cluster_pf_sd": pl.Float64,
    "phasing": pl.Float64,
    "prephasing": pl.Float64,
    "reads_m": pl.Float64,
    "reads_pf_m": pl.Float64,
    "pct_q30": pl.Float64,
    "frac_q30": pl.Float64,
    "yield_gb": pl.Float64,
    "pct_aligned": pl.Float64,
    "error_rate": pl.Float64,
    "error_rate_sd": pl.Float64,
}

RAW_LINE_COL = "raw"
SOURCE_PATH_COL = "source_path"
_READ_HEADER = re.compile(r"^Read (\d+)( \(I\))?$")


def _mean_sd(cell: str | None) -> tuple[float | None, float | None]:
    """``"76.69 +/- 2.37"`` -> (76.69, 2.37); a bare number has no spread."""
    if cell is None:
        return None, None
    mean, _, sd = cell.partition("+/-")
    return _float(mean), _float(sd) if sd else None


def _float(cell: str | None) -> float | None:
    if cell is None:
        return None
    text = cell.strip()
    if not text or text in {"-", "nan", "NaN"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse(lines: list[str]) -> list[dict]:
    """Lane rows of every read block of one summary file."""
    run_id = lines[1].strip().strip(",") if len(lines) > 1 else ""
    rows: list[dict] = []
    i = 0
    while i < len(lines):
        match = _READ_HEADER.match(lines[i].strip())
        if not match or i + 1 >= len(lines):
            i += 1
            continue
        read_no, is_index = int(match.group(1)), bool(match.group(2))
        header = [h.strip() for h in lines[i + 1].split(",")]
        i += 2
        while i < len(lines) and lines[i].strip() and not _READ_HEADER.match(lines[i].strip()):
            cells = dict(zip(header, (c.strip() for c in lines[i].split(",")), strict=False))
            i += 1
            if cells.get("Surface") != "-":
                continue
            lane = int(cells["Lane"])
            pf, pf_sd = _mean_sd(cells.get("Cluster PF"))
            density, _ = _mean_sd(cells.get("Density"))
            phas, _, prephas = (cells.get("Phas/Prephas") or "").partition("/")
            err, err_sd = _mean_sd(cells.get("Error"))
            aligned, _ = _mean_sd(cells.get("Aligned"))
            q30 = _float(cells.get("%>=Q30"))
            rows.append(
                {
                    "run_id": run_id,
                    "lane": lane,
                    "lane_label": f"Lane {lane}",
                    "read": read_no,
                    "read_label": f"Read {read_no}" + (" (I)" if is_index else ""),
                    "is_index_read": is_index,
                    "tiles": int(_float(cells.get("Tiles")) or 0),
                    "density_k_mm2": density,
                    "pct_cluster_pf": pf,
                    "pct_cluster_pf_sd": pf_sd,
                    "phasing": _float(phas),
                    "prephasing": _float(prephas),
                    "reads_m": _float(cells.get("Reads")),
                    "reads_pf_m": _float(cells.get("Reads PF")),
                    "pct_q30": q30,
                    "frac_q30": q30 / 100.0 if q30 is not None else None,
                    "yield_gb": _float(cells.get("Yield")),
                    "pct_aligned": aligned,
                    # An index read is never aligned to PhiX: its 0.00 is "not measured".
                    "error_rate": None if is_index else err,
                    "error_rate_sd": None if is_index else err_sd,
                }
            )
    return rows


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (lane, read) of every scanned summary."""
    raw = sources["summary"]
    if raw is None or raw.is_empty():
        raise ValueError("interop_summary: the scanned summaries are empty")
    for column in (RAW_LINE_COL, SOURCE_PATH_COL):
        if column not in raw.columns:
            raise ValueError(
                f"interop_summary: no {column} column, the collection must scan one line "
                f"per row with include_file_paths: source_path"
            )
    rows: list[dict] = []
    for _, group in raw.group_by([SOURCE_PATH_COL], maintain_order=True):
        rows.extend(_parse([line or "" for line in group[RAW_LINE_COL].to_list()]))
    if not rows:
        raise ValueError("interop_summary: no Read block with lane rows was found")
    return pl.DataFrame(rows, schema=EXPECTED_SCHEMA).sort(["run_id", "lane", "read"])
