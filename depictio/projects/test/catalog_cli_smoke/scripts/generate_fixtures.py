"""Stage the raw tool outputs this project's recipes consume.

The catalog ships one fixture per output — but a fixture is a recipe's *result*,
which is what `catalog_conformance` seeds directly. This project takes the other
route: it stages what the pipeline would have written, so `depictio-cli run`
executes the recipes for real.

So each raw file below is derived from the matching catalog fixture, inverted
back into the tool's own on-disk shape (wide QIIME 2 tables, per-sample Pangolin
CSVs, the pre-annotation variants table). Deriving rather than inventing keeps
the values coherent with the catalog's own preview data, and keeps the recipes'
declared input columns honest: if a recipe changes what it reads, regenerating
here is what surfaces it.

Rebuild with:

    uv run python -m depictio.projects.test.catalog_cli_smoke.scripts.generate_fixtures
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

CATALOG = Path(__file__).resolve().parents[4] / "catalog"
PROJECT = Path(__file__).resolve().parents[1]
DATA = PROJECT / "run_1"

# The viral fixtures carry 44 samples; a smoke project needs a handful. Taking a
# fixed prefix rather than a sample keeps regeneration reproducible.
VIRAL_SAMPLES = [f"SAMPLE_{i:02d}" for i in range(1, 9)]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    print(f"  wrote {path.relative_to(PROJECT)} ({len(text.splitlines())} lines)")


def stage_rel_abundance_table() -> None:
    """QIIME 2 `rel-table-2.tsv` — wide taxa x samples, biom header line.

    The recipe reads it with ``skip_rows: 1``, so the comment line the biom
    exporter writes has to be there: without it the header row is consumed as
    data and every sample column parses as a string.
    """
    long = pl.read_csv(CATALOG / "qiime2" / "rel_abundance.tsv", separator="\t")
    wide = (
        long.pivot(values="rel_abundance", index="taxonomy", on="sample", aggregate_function="sum")
        .fill_null(0.0)
        .rename({"taxonomy": "#OTU ID"})
        .sort("#OTU ID")
    )
    body = wide.write_csv(separator="\t", float_precision=6)
    _write(
        DATA / "qiime2" / "rel_abundance_tables" / "rel-table-2.tsv",
        "# Constructed from biom file\n" + body,
    )


def stage_barplot_level_2() -> None:
    """QIIME 2 `barplot/level-2.csv` — wide sample x taxon counts plus metadata.

    Taxonomy columns are recognised by the semicolon in their *name*, so the
    lineage strings become the header; `habitat` rides alongside as the metadata
    column the recipe passes through untouched.
    """
    long = pl.read_csv(CATALOG / "qiime2" / "taxonomy_composition.tsv", separator="\t")
    wide = (
        long.pivot(
            values="count", index=["sample", "habitat"], on="taxonomy", aggregate_function="sum"
        )
        .fill_null(0.0)
        .rename({"sample": "index"})
        .sort("index")
    )
    _write(DATA / "qiime2" / "barplot" / "level-2.csv", wide.write_csv())


def stage_variants_long_table() -> None:
    """viralrecon `variants_long_table.csv` — the pre-normalisation variant table.

    `FUNCLASS` and `mutation_label` are dropped and `AA` is put back as
    `HGVS_P_1LETTER`: all three are things the recipe derives, so leaving them in
    would let a broken recipe still produce a valid-looking table.
    """
    df = pl.read_csv(CATALOG / "ivar" / "variants_long.tsv", separator="\t")
    df = (
        df.filter(pl.col("sample").is_in(VIRAL_SAMPLES))
        .drop("FUNCLASS", "mutation_label")
        .rename({"sample": "SAMPLE", "AA": "HGVS_P_1LETTER"})
    )
    _write(DATA / "variants" / "ivar" / "variants_long_table.csv", df.write_csv())


def stage_pangolin_reports() -> None:
    """Pangolin writes one CSV per sample; the recipe globs and concatenates them.

    `taxon` carries the consensus FASTA header rather than a bare sample name —
    that suffix is what the recipe strips, so it has to be here for the strip to
    be exercised at all.
    """
    df = pl.read_csv(CATALOG / "pangolin" / "report.tsv", separator="\t")
    df = df.filter(pl.col("sample").is_in(VIRAL_SAMPLES))
    out_dir = DATA / "variants" / "ivar" / "consensus" / "bcftools" / "pangolin"
    for row in df.iter_rows(named=True):
        sample = row.pop("sample")
        one = pl.DataFrame(
            {
                "taxon": [f"{sample}.consensus_threshold_0.75_quality_20"],
                **{k: [v] for k, v in row.items()},
            }
        )
        _write(out_dir / f"{sample}.pangolin.csv", one.write_csv())


def stage_mosdepth_amplicon_coverage() -> None:
    """mosdepth's per-amplicon table — the one collection here with no recipe.

    `aggregation_time` is stamped by depictio at ingest, so the catalog fixture
    has it and the file mosdepth writes does not.
    """
    df = pl.read_csv(CATALOG / "mosdepth" / "amplicon_coverage.tsv", separator="\t")
    df = df.filter(pl.col("sample").is_in(VIRAL_SAMPLES)).drop("aggregation_time")
    _write(
        DATA
        / "variants"
        / "bowtie2"
        / "mosdepth"
        / "amplicon"
        / "all_samples.mosdepth.coverage.tsv",
        df.write_csv(separator="\t"),
    )


def main() -> None:
    print(f"Staging raw tool outputs under {DATA}")
    stage_rel_abundance_table()
    stage_barplot_level_2()
    stage_variants_long_table()
    stage_pangolin_reports()
    stage_mosdepth_amplicon_coverage()
    print("Done.")


if __name__ == "__main__":
    main()
