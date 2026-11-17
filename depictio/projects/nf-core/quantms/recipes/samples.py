"""Run hub for nf-core/quantms: one row per MS raw file, from the experimental design.

quantms starts from an SDRF (or an OpenMS-style design) and writes what it parsed
out of it under ``sdrfparsing/``: ``<name>_openms_design.tsv``, a two-table file
(the runs, then the samples with their MSstats condition and biological replicate),
and ``<name>_config.tsv``, one row per run with the acquisition method, label,
enzyme and mass tolerances. The copy of the SDRF itself is not published, so the
hub is built from those two files, and the SDRF named by ``METADATA_FILE`` (default
``input/sdrf.tsv``) only adds what the design files do not hold: organism,
instrument, technical replicate and any other factor column.

Every other collection joins on ``run_id``, the raw file name without its extension,
which is the ``Run`` DIA-NN and MSstats write.

``condition_raw`` is the MSstats condition exactly as the statistical test names it
(``CT=Mixture;CN=Spike;QY=0.1 unit`` for an SDRF factor value). ``condition`` is the
reader-facing label: when the conditions are ``KEY=value`` lists, the pairs that are
the same in every condition are dropped and the values of the rest are joined
(``0.1 unit``), so the group filter, the colours and the contrast names stay short.
A condition that is not a ``KEY=value`` list is kept as it is.

A label-free run has one row per file. A multiplexed (TMT, iTRAQ) design has one row
per file and channel; the hub keeps the first row of each file, so this template
describes label-free runs.

Output:
    run_id : Utf8              raw file name without its extension
    sample : Utf8              design sample number
    condition : Utf8           reader-facing condition label
    condition_raw : Utf8       MSstats condition string
    replicate : Int64          rank of the run within its condition, in design order
    run_label : Utf8           short label for an axis: the condition and the replicate
    bio_replicate : Utf8       MSstats biological replicate
    fraction : Utf8            fraction number
    acquisition : Utf8         DIA, DDA or the method as written
    label : Utf8               labelling of the sample
    enzyme : Utf8
    precursor_tolerance : Utf8 value and unit
    fragment_tolerance : Utf8  value and unit
    dissociation : Utf8
    fixed_mods : Utf8
    variable_mods : Utf8
    <SDRF columns>             organism, instrument, ... as Delta-safe names
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    # The design file holds two tables, so it is read as text with every column the
    # widest table needs; transform() splits the tables at the `Sample` header row.
    RecipeSource(
        ref="design",
        glob_pattern="sdrfparsing/*_openms_design.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0, "truncate_ragged_lines": True},
    ),
    RecipeSource(
        ref="config",
        glob_pattern="sdrfparsing/*_config.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        optional=True,
    ),
    RecipeSource(
        ref="sdrf",
        path="input/sdrf.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        optional=True,
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "run_id": pl.Utf8,
    "sample": pl.Utf8,
    "condition": pl.Utf8,
    "condition_raw": pl.Utf8,
    "replicate": pl.Int64,
    "run_label": pl.Utf8,
    "bio_replicate": pl.Utf8,
    "fraction": pl.Utf8,
    "acquisition": pl.Utf8,
    "label": pl.Utf8,
    "enzyme": pl.Utf8,
    "precursor_tolerance": pl.Utf8,
    "fragment_tolerance": pl.Utf8,
    "dissociation": pl.Utf8,
    "fixed_mods": pl.Utf8,
    "variable_mods": pl.Utf8,
}
# SDRF columns are run-dependent and pass through unvalidated.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

_RAW_SUFFIX = re.compile(
    r"\.(d\.tar\.gz|d\.tar|d\.zip|mzml\.gz|mzml|raw|d|wiff|mzxml)$", re.IGNORECASE
)
_KEY_VALUE = re.compile(r"^\s*([A-Za-z]{1,6})\s*=\s*(.+?)\s*$")
_SDRF_KEY = re.compile(r"^(characteristics|comment|factor value)\[(.*)\]$", re.IGNORECASE)
_PLACEHOLDERS = {"", "not available", "not applicable", "na", "n/a", "none"}
# SDRF columns the design files already give (or that only name the file).
_SDRF_SKIP = {
    "data_file",
    "file_uri",
    "technology_type",
    "material_type",
    "label",
    "proteomics_data_acquisition_method",
    "cleavage_agent_details",
    "dissociation_method",
    "precursor_mass_tolerance",
    "fragment_mass_tolerance",
    "modification_parameters",
    "fraction_identifier",
}


def run_id_of(name: str) -> str:
    """File name without directory or MS extension."""
    base = str(name).rstrip("/").split("/")[-1].split("\\")[-1]
    return _RAW_SUFFIX.sub("", base)


def split_design(design: pl.DataFrame) -> tuple[list[tuple], list[tuple]]:
    """The run rows and the sample rows of an OpenMS design file read as one table."""
    runs: list[tuple] = []
    samples: list[tuple] = []
    in_samples = False
    for row in design.iter_rows():
        if all(v is None or str(v).strip() == "" for v in row):
            continue
        if row[0] == "Sample" and str(row[1]).startswith("MSstats_"):
            in_samples = True
            continue
        (samples if in_samples else runs).append(row)
    return runs, samples


def _pairs(condition: str) -> list[tuple[str, str]] | None:
    parts = [p for p in str(condition).split(";") if p.strip()]
    pairs = [_KEY_VALUE.match(p) for p in parts]
    if not parts or any(m is None for m in pairs):
        return None
    return [(m.group(1), m.group(2)) for m in pairs]  # type: ignore[union-attr]


def condition_labels(raw: list[str]) -> dict[str, str]:
    """Short label per MSstats condition (see the module docstring)."""
    parsed = {c: _pairs(c) for c in raw}
    if not raw or any(p is None for p in parsed.values()):
        return {c: c for c in raw}
    if len(raw) > 1:
        common = set.intersection(*[set(p) for p in parsed.values()])  # type: ignore[arg-type]
    else:
        common = set()
    labels = {
        c: ", ".join(v for k, v in p if (k, v) not in common) or c  # type: ignore[union-attr]
        for c, p in parsed.items()
    }
    # Two conditions that collapse to one label stay apart under their raw names.
    counts = pl.Series(list(labels.values())).value_counts()
    clash = {row[0] for row in counts.iter_rows() if row[1] > 1}
    return {c: (c if lab in clash else lab) for c, lab in labels.items()}


def _clean_cell(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    nt = re.search(r"(?:^|;)NT=([^;]+)", text)
    text = nt.group(1).strip() if nt else text
    return None if text.lower() in _PLACEHOLDERS else text


def _snake(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", text.lower()).strip("_") or "column"


def sdrf_columns(sdrf: pl.DataFrame | None, reserved: set[str]) -> pl.DataFrame | None:
    """The SDRF keyed on ``run_id``, its columns as Delta-safe names with clean values."""
    if sdrf is None or sdrf.is_empty():
        return None
    file_col = next(
        (c for c in sdrf.columns if _snake(c) in {"comment_data_file", "data_file"}), None
    )
    if file_col is None:
        file_col = next((c for c in sdrf.columns if "data file" in c.lower()), None)
    if file_col is None:
        return None
    out: dict[str, list[str | None]] = {
        "run_id": [run_id_of(v) if v else None for v in sdrf[file_col].to_list()]
    }
    seen: dict[str, list[str | None]] = {}
    for col in sdrf.columns:
        match = _SDRF_KEY.match(col.strip())
        name = _snake(match.group(2) if match else col)
        if name in _SDRF_SKIP or "modification_parameters" in name or col == file_col:
            continue
        values = [_clean_cell(v) for v in sdrf[col].to_list()]
        if all(v is None for v in values):
            continue
        if name in reserved or name in out:
            # A factor value repeating its characteristic adds nothing.
            if name in out and out[name] == values:
                continue
            name = f"{name}_{_snake(match.group(1)) if match else 'col'}"
        if name in reserved or name in out or seen.get(name) == values:
            continue
        seen[name] = values
        out[name] = values
    if len(out) == 1:
        return None
    frame = pl.DataFrame({k: pl.Series(k, v, dtype=pl.Utf8) for k, v in out.items()})
    return frame.filter(pl.col("run_id").is_not_null()).unique(
        subset="run_id", keep="first", maintain_order=True
    )


def _acquisition(value: str | None) -> str | None:
    if value is None:
        return None
    low = value.lower()
    if "independent" in low or low.strip() == "dia":
        return "DIA"
    if "dependent" in low or low.strip() == "dda":
        return "DDA"
    return value


def _config_columns(config: pl.DataFrame | None) -> pl.DataFrame:
    schema = {
        "run_id": pl.Utf8,
        "acquisition": pl.Utf8,
        "label": pl.Utf8,
        "enzyme": pl.Utf8,
        "precursor_tolerance": pl.Utf8,
        "fragment_tolerance": pl.Utf8,
        "dissociation": pl.Utf8,
        "fixed_mods": pl.Utf8,
        "variable_mods": pl.Utf8,
    }
    if config is None or config.is_empty() or "Filename" not in config.columns:
        return pl.DataFrame(schema=schema)

    def col(name: str) -> pl.Expr:
        return pl.col(name) if name in config.columns else pl.lit(None, dtype=pl.Utf8)

    def tolerance(value: str, unit: str) -> pl.Expr:
        return (
            pl.when(col(value).is_not_null())
            .then(
                pl.concat_str(
                    [col(value), col(unit).fill_null("")], separator=" "
                ).str.strip_chars()
            )
            .otherwise(None)
        )

    return (
        config.select(
            pl.col("Filename").map_elements(run_id_of, return_dtype=pl.Utf8).alias("run_id"),
            col("Proteomics Data Acquisition Method")
            .map_elements(_acquisition, return_dtype=pl.Utf8)
            .alias("acquisition"),
            col("Label").alias("label"),
            col("Enzyme").alias("enzyme"),
            tolerance("PrecursorMassTolerance", "PrecursorMassToleranceUnit").alias(
                "precursor_tolerance"
            ),
            tolerance("FragmentMassTolerance", "FragmentMassToleranceUnit").alias(
                "fragment_tolerance"
            ),
            col("DissociationMethod").alias("dissociation"),
            col("FixedModifications").alias("fixed_mods"),
            col("VariableModifications").alias("variable_mods"),
        )
        .unique(subset="run_id", keep="first", maintain_order=True)
        .cast(schema)
    )


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    design = sources["design"]
    runs, samples = split_design(design)
    if not runs:
        raise ValueError("quantms samples: the design file lists no run")
    run_frame = pl.DataFrame(
        {
            "run_id": [run_id_of(r[2]) for r in runs],
            "sample": [str(r[4]) if r[4] is not None else None for r in runs],
            "fraction": [str(r[1]) if r[1] is not None else None for r in runs],
            "order": list(range(len(runs))),
        },
        schema={"run_id": pl.Utf8, "sample": pl.Utf8, "fraction": pl.Utf8, "order": pl.Int64},
    ).unique(subset="run_id", keep="first", maintain_order=True)

    sample_frame = pl.DataFrame(
        {
            "sample": [str(r[0]) for r in samples],
            "condition_raw": [str(r[1]) if r[1] is not None else None for r in samples],
            "bio_replicate": [str(r[2]) if r[2] is not None else None for r in samples],
        },
        schema={"sample": pl.Utf8, "condition_raw": pl.Utf8, "bio_replicate": pl.Utf8},
    ).unique(subset="sample", keep="first", maintain_order=True)

    hub = run_frame.join(sample_frame, on="sample", how="left").with_columns(
        pl.col("condition_raw").fill_null(
            pl.col("sample").map_elements(lambda s: f"Sample {s}", return_dtype=pl.Utf8)
        )
    )
    labels = condition_labels(hub["condition_raw"].unique(maintain_order=True).to_list())
    hub = hub.with_columns(
        pl.col("condition_raw").replace_strict(labels, default=None).alias("condition"),
        pl.col("order")
        .rank(method="ordinal")
        .over("condition_raw")
        .cast(pl.Int64)
        .alias("replicate"),
    ).with_columns(
        # A raw file name runs to 30 characters and more: the axes read the condition and
        # the replicate instead ("0.1 unit #2").
        (pl.col("condition") + pl.lit(" #") + pl.col("replicate").cast(pl.Utf8)).alias("run_label")
    )
    hub = hub.join(_config_columns(sources.get("config")), on="run_id", how="left")

    out = hub.sort("order").select(list(OUTPUT_SCHEMA))
    extra = sdrf_columns(sources.get("sdrf"), set(OUTPUT_SCHEMA))
    if extra is not None:
        out = out.join(extra, on="run_id", how="left")
        # The factor value is the MSstats condition again, as written in the SDRF.
        same = [
            c
            for c in extra.columns[1:]
            if out.select((pl.col(c) == pl.col("condition_raw")).all()).item()
        ]
        out = out.drop(same)
    return out
