"""MSstats group comparisons: one row per protein and contrast.

nf-core/quantms ends a label-free run with MSstats' ``groupComparison``, written to
``msstats/<name>_comparisons.csv`` (tab separated despite the name): per protein and
contrast the log2 fold change of the first condition over the second, its standard error,
the moderated t statistic, the p-value and the Benjamini-Hochberg adjusted p-value, the
share of missing and imputed values, and an ``issue`` when MSstats could not test the
protein (a condition with no value). The column names a condition by the MSstats condition
string, so the contrast ``A-B`` is split into its two conditions by matching the hub's
conditions, and both sides get the hub's reader-facing label.

The fold change is the first condition over the second, so ``Up`` means higher in the
first condition of the contrast. A call needs an adjusted p-value under 0.05 and a fold
change of at least two (|log2 fold change| of 1), the cut-offs the volcano draws.

MSstats names the protein by the entry name DIA-NN writes (``Protein.Names``); the
accession and gene come from the protein table, and the per-condition mean intensities
(``mean_a``, ``mean_b``) and their average (``avg_log2_intensity``, the A axis of the MA
view) from ``quantms_protein_conditions``. Those means are keyed on the hub's ``condition``,
so they are empty when the template's group column is another one.

Output schema:
    protein : Utf8                 protein name as MSstats writes it
    protein_group : Utf8           DIA-NN protein group, when the protein table has it
    genes : Utf8
    contrast : Utf8                "<first condition> vs <second condition>"
    condition_a : Utf8             first condition (numerator)
    condition_b : Utf8             second condition (denominator)
    log2fc : Float64               null where MSstats gave an infinite value
    abs_log2fc : Float64
    se : Float64
    t_value : Float64
    df : Float64
    p_value : Float64
    adj_p_value : Float64
    missing_pct : Float64          percent of the protein's feature values that are missing
    imputed_pct : Float64          percent imputed by MSstats
    issue : Utf8                   why MSstats could not test the protein, else null
    mean_a : Float64               mean log2 intensity in the first condition
    mean_b : Float64               mean log2 intensity in the second condition
    avg_log2_intensity : Float64   mean of mean_a and mean_b
    direction : Utf8               Up, Down or Not significant
"""

from __future__ import annotations

import io

import polars as pl

from depictio.models.models.transforms import RecipeSource

HUB_DC_TAG = "samples"
CONDITIONS_DC_TAG = "quantms_protein_conditions"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    # No input_schema: a comma-separated file is read as one column and re-split by
    # _fix_delimiter, so the columns only exist once transform() starts.
    RecipeSource(
        ref="comparisons",
        glob_pattern="msstats/*comparisons.csv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
    ),
    RecipeSource(
        ref="hub",
        dc_ref=HUB_DC_TAG,
        optional=True,
        input_schema={"condition": pl.Utf8, "condition_raw": pl.Utf8},
    ),
    RecipeSource(
        ref="conditions",
        dc_ref=CONDITIONS_DC_TAG,
        optional=True,
        input_schema={
            "protein_group": pl.Utf8,
            "protein_name": pl.Utf8,
            "genes": pl.Utf8,
            "mean_log2_intensity": pl.Float64,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "protein": pl.Utf8,
    "protein_group": pl.Utf8,
    "genes": pl.Utf8,
    "contrast": pl.Utf8,
    "condition_a": pl.Utf8,
    "condition_b": pl.Utf8,
    "log2fc": pl.Float64,
    "abs_log2fc": pl.Float64,
    "se": pl.Float64,
    "t_value": pl.Float64,
    "df": pl.Float64,
    "p_value": pl.Float64,
    "adj_p_value": pl.Float64,
    "missing_pct": pl.Float64,
    "imputed_pct": pl.Float64,
    "issue": pl.Utf8,
    "mean_a": pl.Float64,
    "mean_b": pl.Float64,
    "avg_log2_intensity": pl.Float64,
    "direction": pl.Utf8,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

#: Adjusted p-value and absolute log2 fold change of a call.
ADJ_P_CUTOFF = 0.05
LOG2FC_CUTOFF = 1.0
_NUMERIC = {
    "log2FC": "log2fc",
    "SE": "se",
    "Tvalue": "t_value",
    "DF": "df",
    "pvalue": "p_value",
    "adj.pvalue": "adj_p_value",
    "MissingPercentage": "missing_pct",
    "ImputationPercentage": "imputed_pct",
}


def _fix_delimiter(df: pl.DataFrame) -> pl.DataFrame:
    """Re-split a comma-separated table that was read with a tab separator."""
    if df.width == 1 and "," in df.columns[0]:
        text = "\n".join([df.columns[0]] + [str(v) for v in df[df.columns[0]].to_list()])
        return pl.read_csv(io.StringIO(text), infer_schema_length=0)
    return df


def split_label(label: str, known: list[str]) -> tuple[str | None, str | None]:
    """The two conditions of an MSstats ``A-B`` contrast label."""
    if label in known or "-" not in label:
        return None, None
    cuts = [i for i, ch in enumerate(label) if ch == "-"]
    for i in cuts:
        left, right = label[:i], label[i + 1 :]
        if left in known and right in known:
            return left, right
    if not known:
        i = cuts[len(cuts) // 2]
        return label[:i], label[i + 1 :]
    return None, None


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    raw = _fix_delimiter(sources["comparisons"])
    missing = [
        c for c in ("Protein", "Label", "log2FC", "pvalue", "adj.pvalue") if c not in raw.columns
    ]
    if missing:
        raise ValueError(f"quantms comparisons: missing column(s) {missing}; got {raw.columns}")

    hub = sources.get("hub")
    labels: dict[str, str] = {}
    if hub is not None and not hub.is_empty():
        labels = {
            r["condition_raw"]: r["condition"]
            for r in hub.select("condition_raw", "condition").unique().iter_rows(named=True)
            if r["condition_raw"] is not None
        }
    known = list(labels)

    numeric = [
        pl.col(src).cast(pl.Float64, strict=False).alias(dst)
        if src in raw.columns
        else pl.lit(None, dtype=pl.Float64).alias(dst)
        for src, dst in _NUMERIC.items()
    ]
    frame = raw.select(
        pl.col("Protein").alias("protein"),
        pl.col("Label").alias("label"),
        pl.col("issue").alias("issue")
        if "issue" in raw.columns
        else pl.lit(None, dtype=pl.Utf8).alias("issue"),
        *numeric,
    ).with_columns(
        pl.when(pl.col("issue").is_in(["NA", ""]))
        .then(None)
        .otherwise(pl.col("issue"))
        .alias("issue"),
        pl.when(pl.col("log2fc").is_infinite())
        .then(None)
        .otherwise(pl.col("log2fc"))
        .alias("log2fc"),
        (pl.col("missing_pct") * 100.0).round(2).alias("missing_pct"),
        (pl.col("imputed_pct") * 100.0).round(2).alias("imputed_pct"),
    )

    parts = {lab: split_label(lab, known) for lab in frame["label"].unique().to_list()}
    sides = pl.DataFrame(
        {
            "label": list(parts),
            "raw_a": [p[0] for p in parts.values()],
            "raw_b": [p[1] for p in parts.values()],
        },
        schema={"label": pl.Utf8, "raw_a": pl.Utf8, "raw_b": pl.Utf8},
    ).with_columns(
        pl.col("raw_a").replace_strict(labels, default=pl.col("raw_a")).alias("condition_a"),
        pl.col("raw_b").replace_strict(labels, default=pl.col("raw_b")).alias("condition_b"),
    )
    frame = frame.join(sides.select("label", "condition_a", "condition_b"), on="label", how="left")
    frame = frame.with_columns(
        pl.when(pl.col("condition_a").is_not_null())
        .then(pl.col("condition_a") + pl.lit(" vs ") + pl.col("condition_b"))
        .otherwise(pl.col("label"))
        .alias("contrast"),
        pl.col("log2fc").abs().round(4).alias("abs_log2fc"),
    ).drop("label")

    # Accession and gene from the protein table, by the entry name MSstats uses.
    conditions = sources.get("conditions")
    if conditions is not None and not conditions.is_empty():
        names = conditions.select("protein_name", "protein_group", "genes").unique(
            subset="protein_name", keep="first"
        )
        frame = frame.join(names, left_on="protein", right_on="protein_name", how="left")
        group_col = "condition" if "condition" in conditions.columns else None
        if group_col is not None:
            means = conditions.select(
                "protein_name", pl.col(group_col).alias("_cond"), "mean_log2_intensity"
            )
            frame = frame.join(
                means.rename({"_cond": "condition_a", "mean_log2_intensity": "mean_a"}),
                left_on=["protein", "condition_a"],
                right_on=["protein_name", "condition_a"],
                how="left",
            ).join(
                means.rename({"_cond": "condition_b", "mean_log2_intensity": "mean_b"}),
                left_on=["protein", "condition_b"],
                right_on=["protein_name", "condition_b"],
                how="left",
            )
    for col in ("protein_group", "genes"):
        if col not in frame.columns:
            frame = frame.with_columns(pl.lit(None, dtype=pl.Utf8).alias(col))
    for col in ("mean_a", "mean_b"):
        if col not in frame.columns:
            frame = frame.with_columns(pl.lit(None, dtype=pl.Float64).alias(col))
    frame = frame.with_columns(
        ((pl.col("mean_a") + pl.col("mean_b")) / 2.0).round(4).alias("avg_log2_intensity"),
        pl.when((pl.col("adj_p_value") < ADJ_P_CUTOFF) & (pl.col("log2fc") >= LOG2FC_CUTOFF))
        .then(pl.lit("Up"))
        .when((pl.col("adj_p_value") < ADJ_P_CUTOFF) & (pl.col("log2fc") <= -LOG2FC_CUTOFF))
        .then(pl.lit("Down"))
        .otherwise(pl.lit("Not significant"))
        .alias("direction"),
    )
    return frame.select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()]).sort(
        ["contrast", "adj_p_value", "protein"]
    )
