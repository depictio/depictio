"""Download real nf-core megatest output files as advanced-viz fixtures.

For each viz_kind we have a canonical-producer entry in the docs catalog
(`docs/features/components.md`), pull one concrete output from a recent
nf-core megatest result. The downloaded files double as:
  1. Manual-upload fixtures for poking at the React beta builder UI.
  2. Future CI fixtures for `validate_binding()` schema checks.

S3 source: https://nf-core-awsmegatests.s3.amazonaws.com/

Coverage (12 / 18 viz_kinds — the rest don't have a clean nf-core source):
    differentialabundance  → volcano, ma, qq, hierarchical_heatmap
    ampliseq               → da_barplot, rarefaction, stacked_taxonomy, phylogenetic
    viralrecon             → coverage_track, lollipop
    taxprofiler            → sunburst
    rnaseq                 → embedding

Not covered (no clean nf-core fixture available):
    enrichment, manhattan, dot_plot, upset_plot, sankey, oncoplot

Usage:
    python3 dev/advanced_viz_docs_screenshots/extract_nfcore_fixtures.py

Downloads land in dev/advanced_viz_docs_screenshots/fixtures/<viz>/.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

BUCKET = "nf-core-awsmegatests"
FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Recent megatest result hashes (looked up via `aws s3 ls s3://<bucket>/<pipe>/`).
# Bump these as pipelines re-run if you want fresher fixtures.
DA_RUN = "differentialabundance/results-f9bed37741dd5b9b67c9ef7b6d65af1122b69115"
AMPLI_RUN = "ampliseq/results-test-43b7746caa826135bf0d99a3cf855ee2a32a545e"
VIRAL_RUN = "viralrecon/results-fc9fece226061594208a25c8acdc05b0bf7c14d1/platform_illumina"
TAX_RUN = "taxprofiler/results-fa1aab03875c090c0594af7c2bbe22ada6c12391"
RNASEQ_RUN = "rnaseq/results-test-86c45b8e0e0213f055118ab23dcbcf262c9159da"


@dataclass(frozen=True)
class Fixture:
    viz_kind: str
    pipeline: str
    s3_key: str
    local_name: str  # filename only, lands under fixtures/<viz_kind>/
    notes: str  # one-liner describing header/format quirks


FIXTURES: list[Fixture] = [
    Fixture(
        "volcano",
        "differentialabundance",
        f"{DA_RUN}/tables/differential/Condition_treatment-Control-Treated.deseq2.results.tsv",
        "deseq2_results.tsv",
        "plain TSV from DESeq2 results() — first column is gene_id (rowname)",
    ),
    Fixture(
        "ma",
        "differentialabundance",
        f"{DA_RUN}/tables/differential/Condition_treatment-Control-Treated.deseq2.results.tsv",
        "deseq2_results.tsv",
        "same file as volcano — uses baseMean + log2FoldChange columns",
    ),
    Fixture(
        "qq",
        "differentialabundance",
        f"{DA_RUN}/tables/differential/Condition_treatment-Control-Treated.deseq2.results.tsv",
        "deseq2_results.tsv",
        "same file as volcano — uses pvalue column only",
    ),
    Fixture(
        "hierarchical_heatmap",
        "differentialabundance",
        f"{DA_RUN}/tables/processed_counts/Condition_treatment-Control-Treated.vst.tsv",
        "deseq2_vst_matrix.tsv",
        "wide TSV from DESeq2 vst() — rows=genes, cols=samples",
    ),
    Fixture(
        "da_barplot_lfc",
        "ampliseq",
        f"{AMPLI_RUN}/qiime2/ancombc/differentials/Category-mix8-ASV/lfc_slice.csv",
        "ancombc_lfc.csv",
        "ANCOM-BC LFC slice — needs join with q_val_slice on feature_id",
    ),
    Fixture(
        "da_barplot_qval",
        "ampliseq",
        f"{AMPLI_RUN}/qiime2/ancombc/differentials/Category-mix8-ASV/q_val_slice.csv",
        "ancombc_qval.csv",
        "ANCOM-BC q-value slice — join with lfc_slice for full DA barplot input",
    ),
    Fixture(
        "rarefaction",
        "ampliseq",
        f"{AMPLI_RUN}/qiime2/alpha-rarefaction/shannon.csv",
        "qiime2_alpha_rarefaction_shannon.csv",
        "QIIME2 alpha-rarefaction — WIDE table (sample × depth_iter cols); needs melt to (sample, depth, metric)",
    ),
    Fixture(
        "stacked_taxonomy",
        "ampliseq",
        f"{AMPLI_RUN}/qiime2/abundance_tables/feature-table.tsv",
        "qiime2_feature_table.tsv",
        "QIIME2 taxa table — `# Constructed from biom file` header line + `#OTU ID` column; comment_prefix=`#`",
    ),
    Fixture(
        "phylogenetic",
        "ampliseq",
        f"{AMPLI_RUN}/qiime2/phylogenetic_tree/tree.nwk",
        "qiime2_tree.nwk",
        "plain Newick string — feed the metadata DC separately (any TSV with `taxon` col joining tip labels)",
    ),
    Fixture(
        "coverage_track",
        "viralrecon",
        f"{VIRAL_RUN}/variants/bowtie2/mosdepth/genome/SAMPLE_01.mosdepth.coverage.tsv",
        "mosdepth_coverage.tsv",
        "mosdepth coverage TSV — chrom/start/end/depth columns",
    ),
    Fixture(
        "lollipop",
        "viralrecon",
        f"{VIRAL_RUN}/variants/ivar/SAMPLE_02.vcf.gz",
        "ivar_variants.vcf.gz",
        "ivar VCF (gzipped) — `##` metadata header + `#CHROM` column line; needs vcf2maf or bcftools query -H",
    ),
    Fixture(
        "sunburst",
        "taxprofiler",
        f"{TAX_RUN}/bracken/bracken-db/MOCK_001_Illumina_Hiseq_3000_bracken-db.bracken.tsv",
        "bracken_sample.tsv",
        "Bracken per-sample TSV — name, taxonomy_id, taxonomy_lvl, *_reads, fraction_total_reads",
    ),
    Fixture(
        "embedding",
        "rnaseq",
        f"{RNASEQ_RUN}/multiqc/star_salmon/multiqc_data/multiqc_star_salmon_deseq2_pca-plot.txt",
        "rnaseq_deseq2_pca.txt",
        "DESeq2 PCA from rnaseq MultiQC — small (~264B) TSV with sample × PC1/PC2",
    ),
]


def fetch(fx: Fixture) -> tuple[bool, str]:
    out_dir = FIXTURES_DIR / fx.viz_kind
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / fx.local_name
    if out_path.exists():
        return True, f"cached ({out_path.stat().st_size} bytes)"
    cmd = [
        "rtk",
        "proxy",
        "aws",
        "s3",
        "cp",
        f"s3://{BUCKET}/{fx.s3_key}",
        str(out_path),
        "--no-sign-request",
        "--quiet",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        return False, f"FAIL: {result.stderr.strip()[:120]}"
    if not out_path.is_file():
        return False, "FAIL: no file written"
    return True, f"{out_path.stat().st_size} bytes"


def main() -> int:
    print(f"Downloading {len(FIXTURES)} fixtures to {FIXTURES_DIR}\n")
    rows: list[tuple[str, str, str, str]] = []
    for fx in FIXTURES:
        print(f"  {fx.viz_kind:<22} {fx.pipeline:<20} ", end="", flush=True)
        ok, detail = fetch(fx)
        status = "OK  " if ok else "FAIL"
        print(f"{status}  {detail}")
        rows.append((fx.viz_kind, fx.pipeline, status, detail))

    print(f"\n{'Viz':<22} {'Pipeline':<22} {'Status':<6} Notes")
    print("-" * 100)
    for fx in FIXTURES:
        local = FIXTURES_DIR / fx.viz_kind / fx.local_name
        size = f"{local.stat().st_size:>7} B" if local.is_file() else " missing"
        print(f"{fx.viz_kind:<22} {fx.pipeline:<22} {size:<8}  {fx.notes}")

    return 0 if all(s == "OK  " for _, _, s, _ in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
