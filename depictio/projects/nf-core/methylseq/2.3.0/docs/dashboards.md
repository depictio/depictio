# nf-core/methylseq 2.3.0: Depictio dashboards

One dashboard for the Bismark route of [nf-core/methylseq](https://nf-co.re/methylseq): an
**Overview**, then child tabs in two groups, read as a funnel from the reads to the windows
whose methylation differs between groups. The layout follows the family rules in
`depictio/projects/nf-core/RULES.md`; `ampliseq/2.18.0` is the reference implementation.

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | Did the reads trim, align and deduplicate cleanly in every library? |
| Data & QC | Run QC | Which libraries fail the alignment, duplication or conversion floors? |
| Data & QC | Coverage | How deep and how evenly do the alignments cover the reference? |
| Methylome | Bias and context | Does the methylation extraction need a read-position trim? |
| Methylome | Methylation levels | Is each methylome bimodal, and are CpG-dense regions unmethylated? |
| Methylome | Cohort structure | Do the libraries group by the design? |
| Methylome | Group comparison | Which windows differ in methylation between the two groups? |

> **This template reads a REPROCESSED MultiQC report.**
> methylseq 2.3.0 published MultiQC 1.13, which writes `multiqc_data.json` and no parquet.
> Depictio reads only `multiqc.parquet` (MultiQC 1.31 and later), so the MultiQC tab is bound
> to a report this repository generates by re-running the pinned MultiQC 1.35 over the run's own
> raw tool outputs. Without it the MultiQC tab is empty. See Reproducing below and
> `VALIDATION_REPORT.md`.

> **Bismark route only.** methylseq also publishes a `bismark_hisat/` and a `bwameth/` route for
> the same samples; this template covers the default `bismark/` route. Every Bismark recipe
> matches `bismark_[a-z0-9]+` rather than the literal `bismark_bt2`, so the sample ids parse
> identically on the hisat2 route once that route has a template.

## Variables

| Variable | Default | What it does |
| --- | --- | --- |
| `METADATA_FILE` | none | Design table (TSV): sample id in a `sample` column or the first column, one column per factor. Feeds the sample hub. Without it there is no group to filter or colour by, and the group comparison is pruned. |
| `GROUP_COL` | first factor of `METADATA_FILE` | The factor the dashboards colour and filter by. The group comparison tests it when it has exactly two levels, and otherwise the first factor that does. |
| `GROUP_COL_DISPLAY` | title-cased `GROUP_COL` | Label used in titles and captions. |
| `GENOME` | `hg38` | Assembly of the locus tracks (contig axis, gene annotation and region search). |

The samplesheet methylseq takes carries no design column, and the template never parses one out
of sample names. The design is a table beside the run, the ampliseq convention. `samples` is the
hub: one row per sample, the samplesheet id and FASTQ pair joined to the factors of
`METADATA_FILE`, and the source of every sample link in `template.yaml`. A 2.3.0 run publishes no
`params.json`, so the run's only provenance is its software versions: the `params:` links of the
dashboard open those.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters (here, the software versions).
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the run's facts (samples, read
  pairs analysed, pairs aligned, CpG calls), read from the sample hub and Bismark's run summary.
- **Pipeline**: five steps (trim, align, deduplicate, extract, methylome). Each step opens the
  version of the tool behind it and the tab that shows its output.
- **Key figures**: four headline cards, each opening the tab that explains it. Samples (split by
  group), the median share of reads aligned and the median CpG methylation (each with its
  spread), and the lowest bisulfite conversion over the libraries (100 minus the CHH
  methylation). A group and a sample filter above them narrow these four only.
- **Findings**: result rows whose values are computed under the filters, each with a link to its
  tab: the median depth over the reference, the share of CpGs that are 98 to 100% methylated,
  the median methylation of CpG-dense windows against CpG-poor ones, and the number of windows
  called between the groups out of those tested. Below them, four figures in two rows, one per
  Methylome tab: the CpG M-bias curves (a summary of the Bias and context explorer, CpG only)
  beside the per-CpG methylation density, then the library PCA beside the Manhattan of the
  tested windows. The bar of this section filters by group and sample.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (group, then sample id, both on the hub) sit in the collapsed
left panel and narrow every tab through the project links. The `Sample sheet` section (the hub
table) is pinned to the bottom of every child tab, collapsed, and absent from the Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to read
the tab), then a strip of key numbers, each card with its own colour and a secondary that reads
it (a box plot, a gauge, a threshold, a ranking or a share), then at most three open sections;
tables, details and the locus view follow, collapsed. Each tab has its own filters in the left
panel, under the persistent sample filters.

**MultiQC.** MultiQC panels only. Open: general statistics, FastQC base quality and Cutadapt
reads kept, then Bismark's alignment rates, deduplication, cytosine methylation and six-panel
M-bias picker. Collapsed: the other FastQC panels with the trimmed read lengths, and Bismark's
strand alignment with the four Qualimap BamQC panels. A bisulfite library fails the FastQC
sequence content and GC checks by design, because converting unmethylated cytosines is the
point. Its own sample filter reads the MultiQC report.

**Run QC.** Bismark's run summary (`bismark2summary`), alignment report and deduplication report,
one row per library. Strip: read pairs analysed (with the share aligned, then kept after
deduplication), the worst mapping efficiency (passes at 70%, warns from 60%), the worst
duplication (passes up to 10%, warns to 20%) and the worst conversion on a gauge. A bisulfite
aligner searches four converted genomes, so an efficiency in the seventies is the expected
ceiling. Then conversion per library, coloured by group, and the per-library QC profile: five
run-summary metrics on parallel axes (read pairs, aligned, duplicated, CpG methylation and
conversion). A library that crosses the others on the conversion axis is a bisulfite problem;
one that crosses them on alignment and duplication together is a library preparation problem. Collapsed: the run summary, alignment and deduplication tables. Filters:
read pairs, CpG methylation, conversion, mapping efficiency, duplication and alignments kept.

Conversion is read as `100 - %CHH`, which assumes a mammalian genome where non-CpG methylation is
near zero; below about 98% the CpG calls inherit the same false-positive rate. Plants methylate
CHG and CHH for real, so on a plant run judge conversion on an unmethylated spike-in such as
lambda instead.

**Coverage.** Qualimap BamQC at full resolution. Strip: mean depth (with its spread), the share
of the reference covered at least once, Qualimap's duplicate estimate (with its distribution)
and the mean mapping quality on Bowtie 2's 0 to 42 scale. Mean depth counts the bases at zero, so
on a shallow run the breadth is the number to judge. Then the depth along the reference (one
lane per library, Qualimap's windows mapped back onto their contigs with the per-contig lengths
of the same `genome_results.txt`), and side by side the depth histogram and the share of the
reference covered at least X deep. Collapsed: the BamQC table. Filter: contig, in the left
panel. The depth threshold sits in the bar of the depth distribution section and narrows that
section only, so the 1X breadth card keeps its value.

**Bias and context.** Bismark's M-bias report and its per-context summary. Strip: CpG
methylation (with its spread), CHG methylation (with its distribution), the worst CHH
methylation against a 2% line (the 98% conversion floor, on a mammalian genome) and the
methylated calls split by context. Then one M-bias explorer over all six tables of the M-bias
file, its context and read picked in the bar of its section, the context opening on CpG. The bar
narrows the explorer only: in the left panel a context pick would also narrow the per-context
strip, whose CHG and CHH cards would then print "–". A CpG curve that has not flattened by the end of the
read is Bismark's own advice to add an `--ignore` / `--ignore_r2` trim and re-extract; a CHH
curve that climbs at one end is unconverted cytosine at those positions. Collapsed: the raw
M-bias positions and the per-context methylation counts. Filter: read position, in the left
panel.

**Methylation levels.** The methylome itself, out of the per-CpG bedGraph files. Strip: the share
of CpGs at 98 to 100% methylation (with its spread), the share at 0 to 2% (a gauge), the median
window methylation (with its distribution) and the median window per CpG-density class. Then
the per-CpG methylation density (2% buckets, one curve per library, log y) and window
methylation by CpG-density class. A healthy mammalian methylome is bimodal; a library whose low
peak drifted upward points to incomplete conversion or a depth too low for a site call.
Filters: CpG-density class and window methylation.

The windows are split into tertiles of their CpG count (CpG-poor, Intermediate, CpG-dense).
nf-core/methylseq bundles no CpG-island or TSS annotation, and CpG density is the property an
island is defined by, so this is the annotation-free stand-in, named as a proxy. With a bundled
island and TSS annotation, three panels would follow without a new pipeline run: methylation by
feature class (island, shore, shelf, open sea), a TSS metagene over the signed distance to the
transcription start site, and the same metagene as a signal matrix.

**Cohort structure.** The library-by-window matrix read three ways. Strip: the libraries placed
by the PCA (a ring by group) and the 150 most variable windows ranked by contig. Then the PCA
coloured by group (a lasso makes an analysis group) beside the pairwise Pearson correlation,
clustered. Collapsed below them, the heatmap of the 150 windows whose methylation varies most
(one column per library), too tall to open by default. A library that
lands with the wrong block in all three is a swap, a mislabelled sheet or a conversion failure.
Filter: contig, on the variable windows.

**Group comparison.** nf-core/methylseq ships no differential-methylation caller at any version,
so this is the screen the published files support, labelled as one. Strip: windows tested
(ranked by contig), windows called (split by direction), the median difference (with its
spread) and the strongest call against padj 0.05. Then the Manhattan of every tested window,
and side by side the volcano (its View switch draws a QQ plot of the raw p-values) and the
distribution of the differences by call. Collapsed: `Methylation at a locus`, a navigator on the
comparison (significance per window, a locus field and a brush) with two followers on the same
region, one lane per library from the binned collection and the group difference; it opens on a
documented default region (rationale in `VALIDATION_REPORT.md`). Collapsed too: the tested-window
table. Filters: call, difference and adjusted p.

- **Every eligible window is tested.** `bismark_window_group_compare` re-bins the bedGraphs with
  the same eligibility rules as the binned collection but without its drawing stride, so
  Benjamini-Hochberg corrects over every eligible window. Drawing budgets are applied by the
  renderers (the Manhattan, volcano and navigator keep every window above padj 0.05 and sample
  the rest), never by the test.
- **The test.** A pooled two-sample t-test on the arcsine square-root transform of each window's
  methylation proportion, between the two levels of `GROUP_COL` when it has exactly two levels,
  else of the first design factor that does (at least two libraries a side). `group_a` and
  `group_b` in the table name the two levels in sorted order; `delta_methylation` is `group_a`
  minus `group_b` in percentage points. A window is called when padj is under 0.05 and the
  difference is at least ten points.
- **What it is not.** The unit is a window, not a CpG and not a called DMR. Without per-CpG
  coverage counts (a 2.3.0 run does not publish `methylation_coverage/` by default) there is no
  beta-binomial model, and with few libraries a side the screen is low-powered by construction.

## The binned methylome

Nothing reads the per-CpG bedGraphs into memory whole: each file is streamed through
`depictio/recipes/lib/genomic_bins.py` into 10 kb windows. A window counts once it holds at least
20 CpGs in **every** library, on a contig with at least 50 such windows (which drops unplaced
scaffolds without naming an assembly). For drawing and for the cohort panels,
`bismark_binned_methylation` keeps a uniform stride of those windows (at most 20,000); a uniform
stride, rather than the CpG-densest windows, keeps every panel a genome-wide view instead of a
CpG-island one.

## Routes and pruning

| Route | What changes |
|---|---|
| No `METADATA_FILE` | No group filter or group colours; the group breakdowns of the cards fall away and the captions read "Group". `bismark_window_group_compare` is pruned: no Group comparison tiles, no windows row in the Findings and no Manhattan highlight. Only the per-library lanes of the collapsed locus section remain on that tab. |
| A design without a two-level factor | The comparison recipe skips the collection, with the same effect as above. |

The import re-packs the Overview grid after a drop, so a lone highlight takes the full row.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: the group column is
coloured `auto` (each value takes a colour-blind-safe colour at import, kept on a re-import),
and three known vocabularies are written out: the cytosine context (CpG, CHG, CHH), the call of a
tested window (hypermethylated red, hypomethylated blue, not significant grey) and the
CpG-density class (light to dark blue, poor to dense). Code figures read the same map and follow
Analysis mode's groups when it has some.

## Cross-selection

A picked row or point becomes a dashboard filter that narrows the other tiles of its collection
and follows the project links to the collections they reach. The pinned sample sheet selects on
`sample_id`; the Bismark, Qualimap and M-bias tables and the per-library profiles select on
`sample`; the PCA on `sample_id` (a lasso makes an analysis group); the tested-window table and
the two window tracks on `window_id`, and the Manhattan on `chromosome`. The cohort-level
collections (correlation, variable windows, comparison) hold the libraries as columns or test
across them, so the sample filters do not narrow them; their own tab filters do.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top of a
narrower one. Nothing is set per tab or per tile.

## Reproducing

```bash
# 1. Fetch the megatest subset
bash depictio/projects/nf-core/methylseq/2.3.0/download_test_data.sh \
  ~/Data/depictio-nfcore/methylseq/2.3.0/megatest

# 2. Put the vendored design table beside the run
mkdir -p ~/Data/depictio-nfcore/methylseq/2.3.0/megatest/input
cp depictio/projects/nf-core/methylseq/2.3.0/input/sample_metadata.tsv \
  ~/Data/depictio-nfcore/methylseq/2.3.0/megatest/input/

# 3. Regenerate the MultiQC report Depictio reads (the run wrote 1.13)
python -m depictio.dev_scripts.multiqc_reprocess \
  --src  ~/Data/depictio-nfcore/methylseq/2.3.0/megatest \
  --dest ~/Data/depictio-nfcore/methylseq/2.3.0/megatest

# 4. Dry run, then ingest
depictio-cli ingest --template nf-core/methylseq/2.3.0 \
  --data-root ~/Data/depictio-nfcore/methylseq/2.3.0/megatest --dry-run \
  --var METADATA_FILE=~/Data/depictio-nfcore/methylseq/2.3.0/megatest/input/sample_metadata.tsv
depictio-cli ingest --template nf-core/methylseq/2.3.0 \
  --data-root ~/Data/depictio-nfcore/methylseq/2.3.0/megatest \
  --var METADATA_FILE=~/Data/depictio-nfcore/methylseq/2.3.0/megatest/input/sample_metadata.tsv
```

Step 3 is mandatory: without it `multiqc_data` finds no parquet and the MultiQC tab is empty.
Keep the first `REPROCESSED.json` or delete `multiqc/multiqc_data/` before re-running, because
the source-version probe reads the parquet it just wrote. The bedGraph recipes stream the per-CpG
files twice (binned windows and the group comparison), a few seconds each on the megatest.
