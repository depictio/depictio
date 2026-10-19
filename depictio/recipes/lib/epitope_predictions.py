"""Shared parsing for nf-core/epitopeprediction's merged prediction tables.

``predictions/<sample>.tsv`` holds every peptide of a sample with the binding
predictions of every tool (``--tools``) against every allele of the sample. The
pipeline writes it in one of two shapes:

* **long** (the default): one row per peptide, allele and tool, with the columns
  ``allele``, ``BA``, ``rank``, ``binder`` and ``predictor`` beside the input
  columns. A peptide no tool could score keeps one row with those five empty.
* **wide** (``--wide_format_output``): one row per peptide, with three columns
  per tool and allele (``<tool>_<allele>_BA``, ``_binder``, ``_rank``) and the
  ``best_*`` / ``binder`` summary columns.

The wide shape cannot go through a recipe's glob source as it is. A glob source
concatenates its files diagonally, and a sample run against every supported
allele (``HLA-all``) has some 35,000 columns: the concatenation would carry all
of them, mostly null, for every row of every other sample. So the recipes read
each file as raw lines (``LINE_READ_KWARGS``: one text column per line), and
``read_predictions`` splits them file by file, melts the wide shape and returns
the long one for every file. Nothing wider than one file ever exists.

Scores, as the pipeline documents them (docs/output.md, 3.2.0):

* ``BA`` is ``1 - log10(IC50) / log10(50000)``, so ``IC50 = 50000 ** (1 - BA)``
  in nM; MixMHCpred and MixMHC2pred give no IC50, so ``BA`` is empty there.
* ``rank`` is the tool's percentile rank, lower is stronger. MHCnuggets' rank is
  experimental and is written as a fraction of the human proteome (0 to 1), not
  as a percentage; it is kept as written.
* ``binder`` is the pipeline's own call, per tool: ``rank <= 2`` for MHCflurry,
  NetMHCpan and MixMHCpred, ``rank <= 5`` for NetMHCIIpan, ``BA >= 0.425``
  (IC50 <= 500 nM) for MHCnuggets. It is taken as is, never recomputed.

Alleles are normalised to ``HLA-<gene>*<field1>:<field2>`` (``normalize_allele``)
so that an allele typed by another pipeline (OptiType writes ``A*02:01``) joins
on the same string.
"""

from __future__ import annotations

import math
import re

import polars as pl

#: Read every line of a file into one text column (``column_1``). The unit
#: separator never occurs in a TSV, and quoting is off so a stray quote cannot
#: swallow the lines after it.
LINE_READ_KWARGS: dict = {
    "separator": "\x1f",
    "has_header": False,
    "quote_char": None,
    "infer_schema_length": 0,
}
LINE_COLUMN = "column_1"
_BLANKS = ["", "NA", "nan", "NaN", "None"]

_WIDE_COLUMN_RE = re.compile(r"^(?P<tool>[a-z0-9]+)_(?P<allele>.+)_(?P<field>BA|binder|rank)$")
_LONG_COLUMNS = ("allele", "BA", "rank", "binder", "predictor")
#: Summary columns of the wide shape; recomputed from the per-allele values.
_WIDE_SUMMARY_RE = re.compile(r"^(best_value_.+|best_allele_.+|best_allele|binder)$")

#: Variant columns of a VCF-derived table, as pVACseq and the pipeline name them.
VARIANT_COLUMNS = (
    "gene",
    "transcript",
    "consequence",
    "HGVSp",
    "genomic_anchor",
    "uniprot",
)

_ORIGIN_LABELS = {
    "MT": "Mutant",
    "WT": "Wild type",
    "MT;WT": "Mutant and wild type",
    "WT;MT": "Mutant and wild type",
}
INPUT_ORIGIN = "Input sequence"

_CONSEQUENCE_LABELS = {
    "missense": "Missense",
    "fs": "Frameshift",
    "frameshift": "Frameshift",
    "inframe_del": "In-frame deletion",
    "inframe_ins": "In-frame insertion",
}

AFFINITY_CLASSES = (
    "Strong (50 nM or less)",
    "Binder (50 to 500 nM)",
    "Weak (500 to 5000 nM)",
    "Non-binding (over 5000 nM)",
    "No IC50",
)

_LOG10_50K = math.log10(50000.0)

# Two-field HLA nomenclature: gene, then two numeric fields, with or without the
# star and colon (``A*02:01``, ``A02:01``, ``A0201``, ``DRB1*01:01:01``). The gene
# is one letter (class I) or two to four letters and an optional digit (class II),
# so a compact ``A0201`` cannot be misread as gene ``A02``.
_HLA_PART_RE = re.compile(
    r"^(?:HLA-)?(?P<gene>[A-Z]|[A-Z]{2,4}\d?)\*?(?P<f1>\d{2,3}):?(?P<f2>\d{2,3})(?::\d{2,3})*[A-Z]?$",
    re.IGNORECASE,
)
_CLASS_I_GENES = frozenset({"A", "B", "C", "E", "F", "G"})


def normalize_allele(raw: str | None) -> str | None:
    """``HLA-<gene>*<f1>:<f2>``, or the input unchanged when it is not HLA.

    A class II heterodimer keeps both chains, ``HLA-DPA1*01:03/DPB1*02:01``.
    Fields past the second are dropped (``HLA-A*02:01:01`` is ``HLA-A*02:01``):
    binding predictors work at protein level, which is what two fields name.
    """
    if raw is None:
        return None
    text = str(raw).strip().replace(" ", "")
    if not text or text.upper() in {"NA", "NAN", "NONE"}:
        return None
    parts = []
    for part in text.split("/"):
        match = _HLA_PART_RE.match(part)
        if match is None:
            return text
        parts.append(f"{match['gene'].upper()}*{match['f1']}:{match['f2']}")
    return "HLA-" + "/".join(parts)


def hla_locus(allele: str | None) -> str | None:
    """``HLA-A`` ... for class I, ``HLA-DR`` / ``HLA-DQ`` / ``HLA-DP`` for class II."""
    if not allele:
        return None
    if not allele.startswith("HLA-"):
        return "Other"
    gene = allele[4:].split("*", 1)[0].upper()
    if gene in _CLASS_I_GENES:
        return f"HLA-{gene}"
    if gene.startswith("D") and len(gene) >= 2:
        return f"HLA-{gene[:2]}"
    return f"HLA-{gene}"


def mhc_class(allele: str | None, predictor: str | None) -> str:
    """``Class I`` or ``Class II``, from the allele, else from the tool's name."""
    locus = hla_locus(allele)
    if locus and locus.startswith("HLA-"):
        return "Class II" if locus.startswith("HLA-D") else "Class I"
    tool = (predictor or "").lower()
    return "Class II" if ("ii" in tool or "2pred" in tool) else "Class I"


def ic50_from_ba(ba: pl.Expr) -> pl.Expr:
    """IC50 in nM from the pipeline's 0-1 binding-affinity score."""
    return (pl.lit(50000.0).pow(pl.lit(1.0) - ba)).round(2)


def affinity_class(ic50: pl.Expr) -> pl.Expr:
    return (
        pl.when(ic50.is_null())
        .then(pl.lit(AFFINITY_CLASSES[4]))
        .when(ic50 <= 50)
        .then(pl.lit(AFFINITY_CLASSES[0]))
        .when(ic50 <= 500)
        .then(pl.lit(AFFINITY_CLASSES[1]))
        .when(ic50 <= 5000)
        .then(pl.lit(AFFINITY_CLASSES[2]))
        .otherwise(pl.lit(AFFINITY_CLASSES[3]))
    )


def origin_label(origin: pl.Expr) -> pl.Expr:
    """Mutant / Wild type / both, or ``Input sequence`` for protein and peptide input."""
    return (
        pl.when(origin.is_null())
        .then(pl.lit(INPUT_ORIGIN))
        .otherwise(origin.replace(_ORIGIN_LABELS))
        .alias("origin")
    )


def consequence_label(value: str | None) -> str | None:
    """``missense;FS`` -> ``Missense, Frameshift`` (deduplicated, input order)."""
    if value is None or str(value).strip() in {"", "NA"}:
        return None
    seen: list[str] = []
    for token in str(value).split(";"):
        token = token.strip()
        if not token:
            continue
        label = _CONSEQUENCE_LABELS.get(token.lower(), token.replace("_", " ").capitalize())
        if label not in seen:
            seen.append(label)
    return ", ".join(seen) or None


def sample_of(source_path: pl.Expr) -> pl.Expr:
    """``predictions/<sample>.tsv`` -> ``<sample>``."""
    return source_path.str.extract(r"([^/]+)\.tsv$", 1).alias("sample")


def _null_if_blank(columns: list[str]) -> list[pl.Expr]:
    return [
        pl.when(pl.col(c).str.strip_chars().is_in(_BLANKS))
        .then(None)
        .otherwise(pl.col(c).str.strip_chars())
        .alias(c)
        for c in columns
    ]


def _split_file(lines: pl.DataFrame) -> tuple[list[str], pl.DataFrame] | None:
    """One file's raw lines -> its header and its rows as lists of fields."""
    text = lines.get_column(LINE_COLUMN)
    text = text.filter(text.is_not_null() & (text.str.strip_chars() != ""))
    if text.len() < 2:
        return None
    header = [h.strip() for h in str(text[0]).rstrip("\r").split("\t")]
    # A blank header cell would collide with another blank one.
    header = [h or f"column_{i}" for i, h in enumerate(header)]
    body = pl.DataFrame({"line": text[1:]}).select(
        pl.col("line").str.strip_chars_end("\r").str.split("\t").alias("fields")
    )
    return header, body


def _long_frame(header: list[str], body: pl.DataFrame) -> pl.DataFrame:
    """A long-shape file: few columns, unpacked as they are."""
    frame = body.select(
        pl.col("fields").list.to_struct(fields=header, upper_bound=len(header))
    ).unnest("fields")
    return frame.with_columns(_null_if_blank(header))


def _melt_wide(header: list[str], body: pl.DataFrame) -> pl.DataFrame:
    """A wide-shape file -> long (one row per peptide, tool and allele).

    The cells are exploded by position and named from the header, so a file
    with tens of thousands of allele columns is never built as a frame that
    wide.
    """
    kinds, tools, alleles, fields = [], [], [], []
    for name in header:
        match = _WIDE_COLUMN_RE.match(name)
        if match:
            kinds.append("value")
            tools.append(match["tool"])
            alleles.append(match["allele"])
            fields.append(match["field"])
        else:
            kinds.append("summary" if _WIDE_SUMMARY_RE.match(name) else "meta")
            tools.append(None)
            alleles.append(None)
            fields.append(None)
    names = pl.DataFrame(
        {
            "_pos": list(range(len(header))),
            "_col": header,
            "_kind": kinds,
            "predictor": tools,
            "allele": alleles,
            "_field": fields,
        },
        schema_overrides={"_pos": pl.Int64},
    )
    meta_cols = [n for n, k in zip(header, kinds, strict=True) if k == "meta"]
    rows = body.with_row_index("_peptide_row")
    cells = (
        rows.with_columns(pl.int_ranges(pl.col("fields").list.len()).alias("_pos"))
        .explode(["fields", "_pos"], empty_as_null=True)
        .with_columns(
            pl.col("_pos").cast(pl.Int64),
            pl.when(pl.col("fields").str.strip_chars().is_in(_BLANKS))
            .then(None)
            .otherwise(pl.col("fields").str.strip_chars())
            .alias("_value"),
        )
        .join(names, on="_pos", how="inner")
    )
    peptides = rows.select("_peptide_row")
    meta_cells = cells.filter(pl.col("_kind") == "meta")
    if meta_cols and not meta_cells.is_empty():
        meta = meta_cells.pivot(on="_col", index="_peptide_row", values="_value")
        peptides = peptides.join(meta, on="_peptide_row", how="left")
    for column in meta_cols:
        if column not in peptides.columns:
            peptides = peptides.with_columns(pl.lit(None, dtype=pl.Utf8).alias(column))
    values = cells.filter((pl.col("_kind") == "value") & pl.col("_value").is_not_null())
    if values.is_empty():
        long = pl.DataFrame(
            schema={"_peptide_row": pl.UInt32, "predictor": pl.Utf8, "allele": pl.Utf8}
        )
    else:
        long = values.pivot(
            on="_field", index=["_peptide_row", "predictor", "allele"], values="_value"
        )
    for field in ("BA", "rank", "binder"):
        if field not in long.columns:
            long = long.with_columns(pl.lit(None, dtype=pl.Utf8).alias(field))
    # A peptide no tool scored keeps one row, with the five prediction columns null.
    return (
        peptides.join(long, on="_peptide_row", how="left", maintain_order="left")
        .drop("_peptide_row")
        .select(meta_cols + list(_LONG_COLUMNS))
    )


def read_predictions(raw: pl.DataFrame) -> pl.DataFrame:
    """Raw lines of every ``predictions/<sample>.tsv`` -> one long frame.

    Output columns: ``sample``, the input columns as written, then
    ``predictor``, ``allele`` (normalised),
    ``BA``, ``rank`` (Float64) and ``binder`` (Boolean). A peptide no tool scored
    keeps one row with those five null.
    """
    frames: list[pl.DataFrame] = []
    for (path,), lines in raw.group_by("source_path", maintain_order=True):
        split = _split_file(lines)
        if split is None:
            continue
        header, body = split
        if all(c in header for c in _LONG_COLUMNS):
            frame = _long_frame(header, body)
        else:
            frame = _melt_wide(header, body)
        frames.append(frame.with_columns(pl.lit(str(path)).alias("source_path")))
    if not frames:
        raise ValueError("epitopeprediction: no prediction table holds a peptide")
    out = pl.concat(frames, how="diagonal_relaxed")
    if "sequence" not in out.columns:
        raise ValueError(
            "epitopeprediction: the prediction tables have no `sequence` column "
            "(was the run started with another --peptide_col_name?)"
        )
    alleles = out.get_column("allele").unique().drop_nulls().to_list()
    normalised = {a: normalize_allele(a) for a in alleles}
    return out.with_columns(
        sample_of(pl.col("source_path")),
        pl.col("allele").replace_strict(normalised, default=None, return_dtype=pl.Utf8),
        pl.col("predictor").str.to_lowercase(),
        pl.col("BA").cast(pl.Float64, strict=False),
        pl.col("rank").cast(pl.Float64, strict=False),
        pl.col("binder")
        .str.to_lowercase()
        .replace_strict(
            {"true": True, "false": False, "1": True, "0": False},
            default=None,
            return_dtype=pl.Boolean,
        ),
    ).drop("source_path")


def annotate(df: pl.DataFrame) -> pl.DataFrame:
    """Derived peptide and score columns shared by every output."""
    for column in (*VARIANT_COLUMNS, "peptide_origin", "wildtype", "protein_ids", "counts", "id"):
        if column not in df.columns:
            df = df.with_columns(pl.lit(None, dtype=pl.Utf8).alias(column))
    alleles = df.get_column("allele").unique().drop_nulls().to_list()
    loci = {a: hla_locus(a) for a in alleles}
    pairs = df.select("allele", "predictor").unique().drop_nulls("predictor").rows()
    classes = {f"{a}|{p}": mhc_class(a, p) for a, p in pairs}
    consequences = {
        c: consequence_label(c)
        for c in df.get_column("consequence").unique().drop_nulls().to_list()
    }
    ic50 = pl.col("ic50_nm")
    return df.with_columns(
        pl.col("sequence").str.len_chars().cast(pl.Int64).alias("length"),
        origin_label(pl.col("peptide_origin")),
        pl.col("consequence").replace_strict(consequences, default=None, return_dtype=pl.Utf8),
        pl.col("allele")
        .replace_strict(loci, default=None, return_dtype=pl.Utf8)
        .alias("hla_locus"),
        (pl.col("allele").fill_null("") + "|" + pl.col("predictor").fill_null(""))
        .replace_strict(classes, default=None, return_dtype=pl.Utf8)
        .alias("mhc_class"),
        ic50_from_ba(pl.col("BA")).alias("ic50_nm"),
        pl.when(pl.col("wildtype").is_in(["NA", ""]))
        .then(None)
        .otherwise(pl.col("wildtype"))
        .alias("wildtype"),
    ).with_columns(
        (pl.col("length").cast(pl.Utf8) + "-mer").alias("length_class"),
        pl.when(ic50 > 0).then(ic50.log10().round(3)).otherwise(None).alias("log10_ic50"),
        affinity_class(ic50).alias("affinity_class"),
    )


def scored(df: pl.DataFrame) -> pl.DataFrame:
    """The rows that carry a prediction (a tool and an allele with a value)."""
    return df.filter(
        pl.col("allele").is_not_null()
        & pl.col("predictor").is_not_null()
        & (
            pl.col("BA").is_not_null()
            | pl.col("rank").is_not_null()
            | pl.col("binder").is_not_null()
        )
    )


def with_wildtype(df: pl.DataFrame) -> pl.DataFrame:
    """Join each mutant row to the prediction of its wild-type peptide.

    The wild-type peptide of a missense mutant is a row of the same sample whose
    ``sequence`` is the mutant's ``wildtype``, scored against the same allele by
    the same tool. It exists only with ``--wild_type``.
    """
    wt = df.select(
        "sample",
        pl.col("sequence").alias("wildtype"),
        "allele",
        "predictor",
        pl.col("ic50_nm").alias("wt_ic50_nm"),
        pl.col("rank").alias("wt_rank"),
        pl.col("binder").alias("wt_binder"),
    ).unique(subset=["sample", "wildtype", "allele", "predictor"], keep="first")
    out = df.join(wt, on=["sample", "wildtype", "allele", "predictor"], how="left")
    return out.with_columns(
        pl.when((pl.col("ic50_nm") > 0) & (pl.col("wt_ic50_nm") > 0))
        .then((pl.col("ic50_nm") / pl.col("wt_ic50_nm")).round(4))
        .otherwise(None)
        .alias("agretopicity")
    )


def load(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Read and annotate the ``predictions`` source of a recipe."""
    return annotate(read_predictions(sources["predictions"]))


__all__ = [
    "AFFINITY_CLASSES",
    "INPUT_ORIGIN",
    "LINE_COLUMN",
    "LINE_READ_KWARGS",
    "VARIANT_COLUMNS",
    "annotate",
    "consequence_label",
    "hla_locus",
    "load",
    "mhc_class",
    "normalize_allele",
    "read_predictions",
    "scored",
    "with_wildtype",
]
