# nf-core/nanoseq 3.0.0: Depictio dashboards

This template turns the output of [nf-core/nanoseq](https://nf-co.re/nanoseq) 3.0.0 into a
single three-tab Depictio dashboard. nanoseq QCs Nanopore long reads, aligns them with
minimap2, quantifies gene and transcript expression with Bambu, and (when the samplesheet asks
for it) runs DESeq2 and DEXSeq on top of those counts. The dashboard follows that chain
left to right: MultiQC, then quantification, then differential expression.

Data comes from the AWS megatest run `results-1e60482a2c4621234393a6eef8e9a104309c20ae` (the
3.0.0 release tag): SG-NEx A549 and K562 cell lines, direct cDNA and cDNA Nanopore RNA-seq,
3 replicates each.

> **This template reads an ALREADY-REPROCESSED MultiQC report.**
> nanoseq 3.0.0 published MultiQC 1.11, which writes `multiqc_data.json` and no parquet.
> Depictio reads only `multiqc.parquet` (MultiQC 1.31 and later); the megatest data directory
> this template was built against already carries the reprocessed report
> (`multiqc/multiqc_data/multiqc.parquet` + `REPROCESSED.json`), produced by re-running the
> pinned MultiQC 1.35 over the run's own raw tool outputs. See `VALIDATION_REPORT.md` if you
> need to reproduce that step from a fresh fetch.

---

## How the dashboard is built

- **One funnel, three tabs.** MultiQC, then Quantification, then Differential expression. Each
  tab answers the question the previous one raises: are the reads clean and did they align,
  what did Bambu count per gene and transcript, and which genes / transcripts moved between
  A549 and K562.
- **The sample hub reaches MultiQC only.** `samples` is one row per sample with its condition
  (A549 / K562), replicate number and reference build. A persistent `Sample filters` section is
  pinned to the top of every tab and the template's one link fans a pick there out to the
  MultiQC panels. Quantification and Differential expression carry no `sample` column of their
  own: Bambu's counts are one row per feature with a column per sample (a wide matrix, not a
  long per-sample table), and DESeq2 / DEXSeq collapse the whole run into a single A549-vs-K562
  comparison.
- **Pinned sample sheet and DESeq2 reference table.** The sample hub sits in a collapsed
  `Sample sheet` section pinned to the top of every tab, and the full DESeq2 gene-results table
  in a collapsed `Reference tables` section pinned to the bottom, next to a collapsed
  `Significance thresholds` section (adjusted p-value and log2 fold-change sliders) that
  narrows that same table and the volcano / MA / QQ plots on the Differential expression tab.
- **Bambu, not a genome aligner's per-region output.** nanoseq's megatest run is a
  transcript-quantification run (minimap2 against a transcriptome/genome, Bambu counting), not
  a variant-calling or fusion-detection run, the samplesheet's `is_transcripts` and
  `nanopolish_fast5` columns are empty for every sample here, so no JAFFAL fusion calls and no
  nanopolish methylation output exist to show. See `VALIDATION_REPORT.md` for what the real
  megatest layout does and does not carry.
- **Feature ids are Bambu's GTF-attribute strings, not clean Ensembl ids.** The megatest's
  minimal test GTF makes Bambu's "gene" rows exon-granular
  (`ccds_id CCDS...; exon_id ENSE...; gene_biotype X; ENSGxxxxx`) rather than one row per gene.
  The `bambu` catalog tool's own recipes extract a clean `ENSG…` id and biotype for the
  Quantification tab; the DESeq2 results reused from the pipeline-agnostic `deseq2` catalog
  tool keep the raw descriptor string, so volcano / MA hover labels on the Differential
  expression tab are the long form. Cosmetic, not a correctness issue, see NS-D5 in
  `VALIDATION_REPORT.md`.

## Tabs

### MultiQC

General statistics, then FastQC read quality, NanoStat's long-read summary (mean/median read
length and quality, N50, yield above each quality cutoff, and the reads-by-quality
distribution) and samtools alignment stats (percent mapped, flagstat, mapped reads per contig).
No insert-size plot: nanoseq's Nanopore reads are single-end.

### Quantification

Bambu's gene- and transcript-level count matrices, each reduced to the 50 features with the
highest total count across the six samples (208k gene-level and 215k transcript-level rows is
neither readable nor useful as a heatmap) and rendered as a clustered heatmap next to the full
top-50 table.

### Differential expression

DESeq2 gene-level results (volcano, MA and QQ plots) next to DEXSeq per-transcript usage
results (volcano and QQ). DESeq2 tests whether a gene's total Bambu count differs between A549
and K562; DEXSeq tests whether one of a gene's transcripts is used more or less relative to
that gene's other transcripts, holding the gene's total expression constant. The Differential
expression tab's significance thresholds (bottom-pinned) act on the DESeq2 table; the DEXSeq
volcano reads its own `padj` (the gene-level adjusted q-value DEXSeq itself reports).

## Reproducing

```bash
python scripts/nfcore_megatest.py fetch --pipeline nanoseq --version 3.0.0 \
  --dest ~/Data/depictio-nfcore/nanoseq/3.0.0/megatest
# or, equivalently:
bash depictio/projects/nf-core/nanoseq/3.0.0/download_test_data.sh

# MultiQC reprocess (skip if multiqc/multiqc_data/multiqc.parquet + REPROCESSED.json already exist):
python -m depictio.dev_scripts.multiqc_reprocess \
  --src  ~/Data/depictio-nfcore/nanoseq/3.0.0/megatest \
  --dest ~/Data/depictio-nfcore/nanoseq/3.0.0/megatest

depictio-cli run --template nf-core/nanoseq/3.0.0 \
  --data-root ~/Data/depictio-nfcore/nanoseq/3.0.0/megatest --dry-run
```
