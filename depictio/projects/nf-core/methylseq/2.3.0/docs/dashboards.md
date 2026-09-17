# nf-core/methylseq 2.3.0: Depictio dashboards

This template turns the Bismark route of [nf-core/methylseq](https://nf-co.re/methylseq) 2.3.0
into a single three-tab Depictio dashboard. methylseq trims bisulfite reads, aligns them with
Bismark against a bisulfite-converted genome, removes PCR duplicates, and extracts per-cytosine
methylation calls in three contexts (CpG, CHG, CHH). The dashboard follows that chain: the
reprocessed MultiQC report first, then the exact Bismark counts behind its alignment and
deduplication plots, then the per-context methylation levels and the M-bias curve that says
whether the extraction window needed trimming.

Data comes from the AWS megatest run `results-93bc5811603c287c766a0ff7e03b5b41f4483895` (the
2.3.0 release tag), Bismark route: two human ESC lines from E-MTAB-6511, MShef11 under three
low-oxygen replicates (Q1-Q3) and MShef4 across a bulk sample and three passage/differentiation
conditions (J1-J3).

> **This template reads a REPROCESSED MultiQC report.**
> methylseq 2.3.0 published MultiQC 1.13, which writes `multiqc_data.json` and no parquet.
> Depictio reads only `multiqc.parquet` (MultiQC 1.31 and later), so the MultiQC tab is bound
> to a report this repository generates by re-running the pinned MultiQC 1.35 over the run's own
> raw tool outputs. Mandatory: without it the MultiQC tab is empty. See the Reproducing section
> below and `VALIDATION_REPORT.md`.

> **Bismark route only.** methylseq also publishes a `bismark_hisat/` and a `bwameth/` route
> for the same samples; this template covers the default `bismark/` route only. A run launched
> with `--aligner bismark_hisat` or `--aligner bwameth` needs a different template.

---

## How the dashboard is built

- **One funnel, three tabs.** MultiQC, then Alignment & deduplication, then Methylation
  profiling. Each tab answers the question the previous one raises: is the run clean overall
  (MultiQC), exactly how much of each library aligned and how many duplicates were removed
  (the two summaries a MultiQC bar plot only shows relative to each other), and what methylation
  the run actually measured, context by context, with the M-bias curve that says whether the
  extraction window needs a trim.
- **The sample hub is the hub.** `samples` is one row per sample with the cell line and
  condition parsed out of the AWS megatest's SRA/GEO-derived sample name
  (`<SRR>_<GSM>_<cell_line>_<condition>`). A persistent `Sample filters` section (sample, cell
  line, condition) is pinned to the top of every tab, and the template's links fan a pick there
  out to the MultiQC panels and all four Bismark summaries at once.
- **Pinned sample sheet, tables and thresholds.** The sample hub sits in a collapsed
  `Sample sheet` section pinned to the top of every tab, the alignment and deduplication
  summaries in a collapsed `Reference tables` section pinned to the bottom, next to a collapsed
  `QC thresholds` section holding the mapping-efficiency floor and the duplication-rate ceiling.
- **Selection.** The M-bias curve on the Methylation profiling tab carries `selection_enabled`
  on `sample`, so picking a sample there narrows the table underneath it and (through the
  project links) every other tab.
- **Catalog provenance.** Every panel on the two non-MultiQC tabs carries a `use:` catalog
  reference: `bismark/*` for the four Bismark summaries this template owns, and
  `multiqc/<module>` for the tool-module QC panels, including `multiqc/qualimap`: the same
  panel nf-core/eager binds.
- **Everything matches on file name.** No data collection or recipe glob spells out a directory
  prefix, so a run published with a different `--outdir` layout still lands in the same
  collections; only `megatest.yaml` knows the AWS run's own `bismark/` aligner-route prefix.

---

## MultiQC

The main tab, and the one reading the reprocessed report.

`Sample sheet`, collapsed at the top of every tab, holds the sample hub with a donut of the
sample count by cell line beside its intro.

`Run at a glance` opens the report with the general statistics table: one row per sample,
pooling the FastQC, Cutadapt, Bismark and Qualimap headline numbers.

`Read quality` carries FastQC sequence counts, quality histograms and GC content, then the
Cutadapt (Trim Galore) kept-reads plot.

`Bisulfite alignment` is Bismark's own four plots: alignment rates, which bisulfite strand each
read pair came from, the deduplication share, and the per-context cytosine methylation table.
The exact numbers behind the first two are on the Alignment & deduplication tab.

`Coverage` reads Qualimap BamQC: the coverage histogram, cumulative genome coverage, insert
size and the GC content of mapped reads. This panel is shared with nf-core/eager, not
recreated here.

---

## Alignment & deduplication

What the MultiQC bar plots draw relative to each other, read as exact numbers.

`Alignment summary` reads Bismark's own "Final Alignment report": four cards (mapping
efficiency and its spread, the mapping-efficiency floor, pairs analysed, pairs with no
alignment), a bar of mapping efficiency per sample, and the full table.

`Deduplication summary` reads `deduplicate_bismark`'s report the same way: duplication rate and
its spread, a duplication-rate ceiling, sequences kept, alignments examined, a bar of the
duplication rate per sample, and the full table. On this megatest one sample (the MShef4 bulk
library) carries a duplication rate over 36%, against 0.7-0.8% for every other sample, the
usual signature of a library sequenced well past its complexity.

---

## Methylation profiling

What the run actually measured.

`Methylation by context` reads the extractor's "Final Cytosine Methylation Report": a donut of
methylation share by context, the spread of % methylated across samples, methylated and
unmethylated cytosine counts, a bar of % methylated by sample and context, and the full table.
CpG sits far above CHG and CHH for every sample here, which is the expected mammalian pattern;
CHG/CHH near zero is the bisulfite-conversion sanity check, not signal.

`M-bias (CpG)` reads the per-position methylation bias Bismark writes beside the extraction
call, CpG context, read 1 and read 2 as separate lines. A curve that has not flattened out by
the end of the read is Bismark's own advice to add an `--ignore` / `--ignore_r2` trim and
re-extract; MultiQC draws the same curve as a static picture, this one is linkable through the
sample filter and the raw coverage behind each position stays queryable in the table underneath.

---

## Reproducing

```bash
# 1. Fetch the megatest subset
bash depictio/projects/nf-core/methylseq/2.3.0/download_test_data.sh \
  ~/Data/depictio-nfcore/methylseq/2.3.0/megatest

# 2. Regenerate the MultiQC report Depictio reads (the run wrote 1.13)
python -m depictio.dev_scripts.multiqc_reprocess \
  --src  ~/Data/depictio-nfcore/methylseq/2.3.0/megatest \
  --dest ~/Data/depictio-nfcore/methylseq/2.3.0/megatest

# 3. Dry run, then ingest
python -m depictio.cli run --template nf-core/methylseq/2.3.0 \
  --data-root ~/Data/depictio-nfcore/methylseq/2.3.0/megatest --dry-run
python -m depictio.cli run --template nf-core/methylseq/2.3.0 \
  --data-root ~/Data/depictio-nfcore/methylseq/2.3.0/megatest
```

Step 2 is mandatory, not optional: without it `multiqc_data` finds no parquet and the whole
MultiQC tab is empty. Keep the first `REPROCESSED.json` or delete `multiqc/multiqc_data/` before
re-running, because the source-version probe reads the parquet it just wrote.
