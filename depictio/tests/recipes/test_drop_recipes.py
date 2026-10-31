"""nf-core/drop recipes: the background trim, the triage list and the gene grid.

The call tables hold every row a run writes, so the recipes keep the near-null bulk out
(a documented rule) and join the three analyses per sample and gene.
"""

from __future__ import annotations

import polars as pl
import pytest

from depictio.recipes import load_recipe, validate_schema

_AE_PATH = "processed_results/aberrant_expression/v29/outrider/outrider/OUTRIDER_results.tsv"
_AS_PATH = "processed_results/aberrant_splicing/results/v29/fraser/fraser/results.tsv"


def _ae_raw(rows: list[tuple[str, str, float, float, float]]) -> pl.DataFrame:
    """rows = (sample, gene, pValue, padjust, zScore), as strings like the reader."""
    return pl.DataFrame(
        {
            "sampleID": [r[0] for r in rows],
            "hgncSymbol": [r[1] for r in rows],
            "geneID": [f"ENSG_{r[1]}" for r in rows],
            "pValue": [str(r[2]) for r in rows],
            "padjust": [str(r[3]) for r in rows],
            "zScore": [str(r[4]) for r in rows],
            "l2fc": ["1.5" if r[4] > 0 else "-1.5" for r in rows],
            "rawcounts": ["10"] * len(rows),
            "meanCorrected": ["8.0"] * len(rows),
            "source_path": [_AE_PATH] * len(rows),
        }
    )


def _as_raw(rows: list[tuple[str, str, float, float, float]]) -> pl.DataFrame:
    """rows = (sample, gene, pValue, padjustGene, deltaPsi)."""
    return pl.DataFrame(
        {
            "sampleID": [r[0] for r in rows],
            "hgncSymbol": [r[1] for r in rows],
            "seqnames": ["chr1"] * len(rows),
            "start": [str(1000 + i * 100) for i in range(len(rows))],
            "end": [str(1050 + i * 100) for i in range(len(rows))],
            "type": ["jaccard"] * len(rows),
            "deltaPsi": [str(r[4]) for r in rows],
            "pValue": [str(r[2]) for r in rows],
            "padjust": [str(r[3]) for r in rows],
            "padjustGene": [str(r[3]) for r in rows],
            "source_path": [_AS_PATH] * len(rows),
        }
    )


def _background_rows(sample: str, n: int) -> list[tuple[str, str, float, float, float]]:
    """n tested genes of one sample, all with an adjusted p-value of 1 (the near-null bulk)."""
    return [(sample, f"{sample}_G{i:03d}", 0.05 + i * 0.002, 1.0, 0.5) for i in range(n)]


@pytest.mark.no_db
def test_expression_keeps_called_half_adjusted_and_the_top_background_rows():
    module = load_recipe("nf-core/drop/expression_outliers.py")
    rows = _background_rows("S1", 20) + _background_rows("S2", 20)
    rows += [("S1", "CALLED", 1e-9, 0.001, -4.0), ("S1", "HALF", 0.2, 0.4, 1.0)]
    out = module.transform({"results": _ae_raw(rows)}, {"background": "5"})
    validate_schema(out, module.OUTPUT_SCHEMA, "expression_outliers", None)

    s1 = out.filter(pl.col("sample") == "S1")
    s2 = out.filter(pl.col("sample") == "S2")
    # S1: the 5 smallest p-values (the called row is one of them) and the adjusted p-value 0.4 row.
    assert s1.height == 6
    assert {"CALLED", "HALF"} <= set(s1["gene_name"])
    assert s2.height == 5
    # The kept background rows are the most significant ones (smallest raw p-value).
    assert sorted(s2["gene_name"].to_list()) == [f"S2_G{i:03d}" for i in range(5)]
    called = out.filter(pl.col("significant"))
    assert called["gene_name"].to_list() == ["CALLED"]
    assert called["direction"].to_list() == ["under-expressed"]


@pytest.mark.no_db
def test_expression_negative_background_keeps_every_row():
    module = load_recipe("nf-core/drop/expression_outliers.py")
    raw = _ae_raw(_background_rows("S1", 30))
    assert module.transform({"results": raw}, {"background": "-1"}).height == 30
    # The default keeps the 300 most significant rows per sample: all 30 here.
    assert module.transform({"results": raw}).height == 30
    # Zero keeps only the called rows, the nominal hits (p at most 0.05) and the adjusted
    # p-value of 0.5 or less: here the one row at p = 0.05.
    kept = module.transform({"results": raw}, {"background": "0"})
    assert kept.height == 1
    assert kept["status"].to_list() == ["nominal p only"]


@pytest.mark.no_db
def test_splicing_trim_follows_the_same_rule():
    module = load_recipe("nf-core/drop/splicing_outliers.py")
    rows = [("S1", f"G{i:02d}", 0.05 + i * 0.01, 1.0, 0.1) for i in range(12)]
    rows += [("S1", "HIT", 1e-8, 0.001, 0.6), ("S1", "HALF", 0.3, 0.45, 0.2)]
    out = module.transform({"results": _as_raw(rows)}, {"background": "4"})
    validate_schema(out, module.OUTPUT_SCHEMA, "splicing_outliers", module.OPTIONAL_OUTPUT_SCHEMA)

    # The 4 smallest p-values (the called junction is one of them) and the gene-level 0.45 row.
    assert out.height == 5
    assert {"HIT", "HALF"} <= set(out["gene_name"])
    called = out.filter(pl.col("significant"))
    assert called["gene_name"].to_list() == ["HIT"]
    assert called["direction"].to_list() == ["more usage"]
    assert module.transform({"results": _as_raw(rows)}, {"background": "-1"}).height == 14


def _hub() -> pl.DataFrame:
    return pl.DataFrame({"sample": ["S1", "S2"], "drop_group": ["batch_a", "batch_b"]})


def _with_nominal(df: pl.DataFrame) -> pl.DataFrame:
    """The recipes' ``nominal``: a call, or a raw p-value of 0.05 or less."""
    return df.with_columns(
        pl.coalesce("nominal", pl.col("significant") | (pl.col("p_value") <= 0.05)).alias("nominal")
    )


def _expression(rows: list[dict]) -> pl.DataFrame:
    base = {
        "sample": "S1",
        "gene_id": "ENSG",
        "gene_name": "G",
        "z_score": 0.0,
        "abs_z_score": 0.0,
        "l2fc": 0.0,
        "p_value": 0.5,
        "padj": 1.0,
        "significant": False,
        "nominal": None,
        "hpo_match": False,
        "chrom": None,
        "start": None,
        "end": None,
    }
    schema = {
        "sample": pl.Utf8,
        "gene_id": pl.Utf8,
        "gene_name": pl.Utf8,
        "z_score": pl.Float64,
        "abs_z_score": pl.Float64,
        "l2fc": pl.Float64,
        "p_value": pl.Float64,
        "padj": pl.Float64,
        "significant": pl.Boolean,
        "nominal": pl.Boolean,
        "hpo_match": pl.Boolean,
        "chrom": pl.Utf8,
        "start": pl.Int64,
        "end": pl.Int64,
    }
    return _with_nominal(pl.DataFrame([{**base, **r} for r in rows], schema=schema))


def _splicing(rows: list[dict]) -> pl.DataFrame:
    base = {
        "sample": "S1",
        "gene_name": "G",
        "delta_psi": 0.0,
        "abs_delta_psi": 0.0,
        "p_value": 0.5,
        "padj_gene": 1.0,
        "significant": False,
        "nominal": None,
        "hpo_match": False,
        "chrom": "chr1",
        "start": 5000,
        "end": 5100,
    }
    schema = {
        "sample": pl.Utf8,
        "gene_name": pl.Utf8,
        "delta_psi": pl.Float64,
        "abs_delta_psi": pl.Float64,
        "p_value": pl.Float64,
        "padj_gene": pl.Float64,
        "significant": pl.Boolean,
        "nominal": pl.Boolean,
        "hpo_match": pl.Boolean,
        "chrom": pl.Utf8,
        "start": pl.Int64,
        "end": pl.Int64,
    }
    return _with_nominal(pl.DataFrame([{**base, **r} for r in rows], schema=schema))


def _mae(rows: list[dict]) -> pl.DataFrame:
    base = {
        "sample": "S1",
        "gene_name": "G",
        "alt_ratio": 0.5,
        "p_value": 0.5,
        "padj": 1.0,
        "mono_allelic": False,
        "chrom": "chr1",
        "start": 9000,
        "end": 9001,
    }
    schema = {
        "sample": pl.Utf8,
        "gene_name": pl.Utf8,
        "alt_ratio": pl.Float64,
        "p_value": pl.Float64,
        "padj": pl.Float64,
        "mono_allelic": pl.Boolean,
        "chrom": pl.Utf8,
        "start": pl.Int64,
        "end": pl.Int64,
    }
    return pl.DataFrame([{**base, **r} for r in rows], schema=schema)


def _genes() -> pl.DataFrame:
    expression = _expression(
        [
            {
                "gene_name": "AAA",
                "significant": True,
                "p_value": 1e-6,
                "padj": 0.01,
                "z_score": -4.0,
                "abs_z_score": 4.0,
                "hpo_match": True,
                "chrom": "chr7",
                "start": 100,
                "end": 900,
            },
            {"gene_name": "BBB", "p_value": 0.01, "padj": 0.9},
            {"gene_name": "CCC", "p_value": 0.4},
            {"gene_name": "AAA", "sample": "S2", "p_value": 0.3},
        ]
    )
    splicing = _splicing(
        [
            {"gene_name": "AAA", "significant": True, "p_value": 1e-5, "padj_gene": 0.02},
            {"gene_name": "BBB", "p_value": 0.2},
            {"gene_name": "unannotated", "significant": True, "p_value": 1e-9},
        ]
    )
    mae = _mae(
        [
            {"gene_name": "AAA", "mono_allelic": True, "p_value": 1e-4, "padj": 0.01},
            {"gene_name": "AAA", "p_value": 0.6, "start": 9500, "end": 9501},
            {"gene_name": "intergenic", "mono_allelic": True, "p_value": 1e-7},
            {"gene_name": "CCC", "p_value": 0.2},
        ]
    )
    return expression, splicing, mae


@pytest.mark.no_db
def test_outlier_genes_joins_the_analyses_and_ranks_the_sample():
    module = load_recipe("nf-core/drop/outlier_genes.py")
    expression, splicing, mae = _genes()
    out = module.transform(
        {"samples": _hub(), "expression": expression, "splicing": splicing, "mae": mae},
        {"top_n": "2"},
    )
    validate_schema(out, module.OUTPUT_SCHEMA, "outlier_genes", module.OPTIONAL_OUTPUT_SCHEMA)

    s1 = out.filter(pl.col("sample") == "S1")
    first = s1.row(0, named=True)
    # AAA is called by all three analyses: it leads the sample's list.
    assert first["gene_name"] == "AAA"
    assert first["sample_rank"] == 1
    assert first["n_analyses"] == 3
    assert first["support"] == "3 analyses"
    assert first["called_in"] == "Expression + Splicing + Mono-allelic"
    assert first["phenotype_gene"] is True
    assert first["phenotype"] == "Phenotype match"
    assert first["drop_group"] == "batch_a"
    # The gene's span comes from the expression table, ahead of junction and variant.
    assert (first["chrom"], first["start"], first["end"]) == ("chr7", 100, 900)
    assert first["locus"] == "chr7:100-900"
    # The sample's two best-ranked genes beyond the called one: top_n = 2 keeps 2 rows in all,
    # but a called gene always stays, so AAA plus the next best.
    assert s1["sample_rank"].to_list() == list(range(1, s1.height + 1))
    assert s1.height == 2
    assert s1["gene_name"].to_list()[1] in {"BBB", "CCC"}
    # Placeholders have no gene symbol to join on.
    assert "unannotated" not in out["gene_name"].to_list()
    assert "intergenic" not in out["gene_name"].to_list()


@pytest.mark.no_db
def test_outlier_genes_not_called_rows_keep_the_strongest_evidence_and_a_position():
    module = load_recipe("nf-core/drop/outlier_genes.py")
    expression, splicing, mae = _genes()
    out = module.transform(
        {"samples": _hub(), "expression": expression, "splicing": splicing, "mae": mae},
        {"top_n": "10"},
    )
    s1 = out.filter(pl.col("sample") == "S1")
    assert s1["gene_name"].to_list() == ["AAA", "BBB", "CCC"]
    bbb = s1.filter(pl.col("gene_name") == "BBB").row(0, named=True)
    assert bbb["n_analyses"] == 0
    assert bbb["support"] == "not called"
    assert bbb["called_in"] == "none"
    # No expression span for the gene's rows without one: the junction gives the position.
    assert bbb["locus"] == "chr1:5000-5100"
    ccc = s1.filter(pl.col("gene_name") == "CCC").row(0, named=True)
    # CCC has an expression row (no position) and a variant: the variant places it.
    assert ccc["locus"] == "chr1:9000-9001"
    assert ccc["expression_score"] is not None and ccc["splicing_score"] is None
    # Evidence is the summed -log10 p-value over the analyses that tested the gene.
    assert s1["significance"].to_list() == sorted(s1["significance"].to_list(), reverse=True)
    s2 = out.filter(pl.col("sample") == "S2")
    assert s2["gene_name"].to_list() == ["AAA"]


@pytest.mark.no_db
def test_outlier_genes_without_an_analysis_and_without_any_rows():
    module = load_recipe("nf-core/drop/outlier_genes.py")
    expression, _, _ = _genes()
    only_expression = module.transform(
        {"samples": _hub(), "expression": expression, "splicing": None, "mae": None},
    )
    validate_schema(only_expression, module.OUTPUT_SCHEMA, "outlier_genes", None)
    assert (
        only_expression.filter(pl.col("gene_name") == "AAA")["called_in"].to_list()[0]
        == "Expression"
    )
    assert only_expression["splicing_score"].null_count() == only_expression.height

    nothing = module.transform(
        {"samples": _hub(), "expression": None, "splicing": None, "mae": None}
    )
    assert nothing.is_empty()
    assert set(module.OUTPUT_SCHEMA) <= set(nothing.columns)


@pytest.mark.no_db
def test_gene_evidence_collapses_the_list_to_one_row_per_gene():
    genes_module = load_recipe("nf-core/drop/outlier_genes.py")
    expression, splicing, mae = _genes()
    triage = genes_module.transform(
        {"samples": _hub(), "expression": expression, "splicing": splicing, "mae": mae},
        {"top_n": "10"},
    )
    module = load_recipe("nf-core/drop/gene_evidence.py")
    out = module.transform({"genes": triage})
    validate_schema(out, module.OUTPUT_SCHEMA, "gene_evidence", None)

    assert out["gene_name"].is_unique().all()
    # The gene called by the most analyses leads; the analyses are columns, absent evidence is 0.
    assert out["gene_name"].to_list()[0] == "AAA"
    top = out.row(0, named=True)
    assert top["best_support"] == 3
    assert top["samples_called"] == 1
    assert top["samples_listed"] == 2
    assert top["Expression"] > 0 and top["Splicing"] > 0 and top["Mono-allelic"] > 0
    assert out.filter(pl.col("gene_name") == "BBB")["Mono-allelic"].to_list() == [0.0]
    assert module.transform({"genes": triage}, {"top_genes": "2"}).height == 2


@pytest.mark.no_db
def test_expression_says_called_nominal_or_neither_when_nothing_passes_the_adjusted_cut_off():
    """A small run has every adjusted p-value at 1: the raw p-values still rank the genes."""
    module = load_recipe("nf-core/drop/expression_outliers.py")
    rows = [
        ("S1", "UNDER", 0.013, 1.0, -2.4),
        ("S1", "OVER", 0.03, 1.0, 2.0),
        ("S1", "QUIET", 0.4, 1.0, 0.5),
        ("S1", "CALLED", 1e-9, 0.001, -4.0),
    ]
    out = module.transform({"results": _ae_raw(rows)})
    validate_schema(out, module.OUTPUT_SCHEMA, "expression_outliers", module.OPTIONAL_OUTPUT_SCHEMA)
    by_gene = {r["gene_name"]: r for r in out.to_dicts()}
    assert by_gene["CALLED"]["status"] == "called (adjusted p)"
    assert by_gene["UNDER"]["status"] == by_gene["OVER"]["status"] == "nominal p only"
    assert by_gene["QUIET"]["status"] == "not significant"
    assert [by_gene[g]["significant"] for g in ("CALLED", "UNDER")] == [True, False]
    # The direction reads on every nominal hit, not only on calls.
    assert by_gene["UNDER"]["direction"] == "under-expressed"
    assert by_gene["OVER"]["direction"] == "over-expressed"
    assert by_gene["QUIET"]["direction"] == "not significant"
    # -log10 of the raw p-value is the volcano's y; the adjusted one is flat at 1.
    assert by_gene["UNDER"]["neg_log10_p"] == pytest.approx(1.886, abs=1e-3)
    assert by_gene["UNDER"]["neg_log10_padj"] == pytest.approx(0.0)
    # Strongest first, by the raw p-value.
    assert out["gene_name"].to_list() == ["CALLED", "UNDER", "OVER", "QUIET"]
    # The nominal cut-off is a parameter.
    strict = module.transform({"results": _ae_raw(rows)}, {"nominal_p": "0.02"})
    assert strict.filter(pl.col("nominal"))["gene_name"].sort().to_list() == ["CALLED", "UNDER"]


@pytest.mark.no_db
def test_splicing_says_called_nominal_or_neither():
    module = load_recipe("nf-core/drop/splicing_outliers.py")
    rows = [
        ("S1", "LESS", 0.006, 1.0, -0.17),
        ("S1", "MORE", 0.025, 1.0, 0.15),
        ("S1", "NONE", 0.5, 1.0, 0.2),
    ]
    out = module.transform({"results": _as_raw(rows)})
    validate_schema(out, module.OUTPUT_SCHEMA, "splicing_outliers", module.OPTIONAL_OUTPUT_SCHEMA)
    by_gene = {r["gene_name"]: r for r in out.to_dicts()}
    assert by_gene["LESS"]["status"] == by_gene["MORE"]["status"] == "nominal p only"
    assert by_gene["NONE"]["status"] == "not significant"
    assert not out["significant"].any()
    assert by_gene["LESS"]["direction"] == "less usage"
    assert by_gene["MORE"]["direction"] == "more usage"
    assert out["gene_name"].to_list() == ["LESS", "MORE", "NONE"]


@pytest.mark.no_db
def test_triage_list_and_sample_table_stay_informative_when_nothing_is_called():
    genes_module = load_recipe("nf-core/drop/outlier_genes.py")
    expression = _expression(
        [
            {"gene_name": "AAA", "p_value": 0.01},
            {"gene_name": "BBB", "p_value": 0.2},
            {"gene_name": "CCC", "p_value": 0.03},
        ]
    )
    splicing = _splicing([{"gene_name": "AAA", "p_value": 0.02}])
    out = genes_module.transform(
        {"samples": _hub(), "expression": expression, "splicing": splicing, "mae": None},
        {"top_n": "2"},
    )
    validate_schema(
        out, genes_module.OUTPUT_SCHEMA, "outlier_genes", genes_module.OPTIONAL_OUTPUT_SCHEMA
    )
    # Nothing is called: the top 2 genes by raw p-value stay, strongest first, with their count
    # of nominal analyses.
    s1 = out.filter(pl.col("sample") == "S1")
    assert s1["gene_name"].to_list() == ["AAA", "CCC"]
    assert s1["n_analyses"].to_list() == [0, 0]
    assert s1["support"].to_list() == ["not called", "not called"]
    assert s1["n_nominal"].to_list() == [2, 1]

    module = load_recipe("nf-core/drop/sample_outliers.py")
    hub = pl.DataFrame(
        {"sample": ["S1", "S2"], "drop_group": ["a", "b"], "count_source": ["Alignment"] * 2}
    )
    table = module.transform(
        {"samples": hub, "expression": expression, "splicing": splicing, "mae": None}
    )
    validate_schema(table, module.OUTPUT_SCHEMA, "sample_outliers", None)
    s1_row = table.filter(pl.col("sample") == "S1").row(0, named=True)
    assert s1_row["total_outliers"] == 0  # calls only
    assert (s1_row["expression_nominal"], s1_row["splicing_nominal"], s1_row["nominal_hits"]) == (
        2,
        1,
        3,
    )
    assert table.filter(pl.col("sample") == "S2")["nominal_hits"].to_list() == [0]
