# nf-core/methylseq 2.3.0: Depictio dashboards

This template turns the Bismark route of [nf-core/methylseq](https://nf-co.re/methylseq) 2.3.0
into a single six-tab Depictio dashboard. methylseq trims bisulfite reads, aligns them with
Bismark against a bisulfite-converted genome, removes PCR duplicates, and extracts per-cytosine
methylation calls in three contexts (CpG, CHG, CHH). The dashboard follows that chain: the
reprocessed MultiQC report, the per-library QC floors, the coverage the calls rest on, whether
the extraction needs a read-position trim, the methylome as a whole, and the comparison the
cohort was sequenced for.

> **This template reads a REPROCESSED MultiQC report.**
> methylseq 2.3.0 published MultiQC 1.13, which writes `multiqc_data.json` and no parquet.
> Depictio reads only `multiqc.parquet` (MultiQC 1.31 and later), so the MultiQC tab is bound
> to a report this repository generates by re-running the pinned MultiQC 1.35 over the run's own
> raw tool outputs. Mandatory: without it the MultiQC tab is empty. See the Reproducing section
> below and `VALIDATION_REPORT.md`.

> **Bismark route only.** methylseq also publishes a `bismark_hisat/` and a `bwameth/` route
> for the same samples; this template covers the default `bismark/` route only. Every Bismark
> recipe here matches `bismark_[a-z0-9]+` rather than the literal `bismark_bt2`, so the sample
> ids parse identically on the hisat2 route once that route has a template.

---

## Variables

| Variable | Default | What it does |
| --- | --- | --- |
| `METADATA_FILE` | none | Design table (TSV): sample id in a `sample` column or the first column, one column per factor. Feeds the sample hub. Without it the design filter has nothing to offer and the Group comparison is pruned. |
| `GROUP_COL` | first factor of `METADATA_FILE` | The factor the dashboards colour and filter by. The group comparison tests it when it has exactly two levels, and otherwise the first factor that does. |
| `GROUP_COL_DISPLAY` | title-cased `GROUP_COL` | Label used in titles. |
| `GENOME` | `hg38` | Assembly of the locus tracks (contig axis and region search). |

The samplesheet methylseq takes carries no design column, and the template never parses one out
of sample names. A run's design is a table beside the run, the ampliseq convention.

---

## How the dashboard is built

- **One funnel, six tabs.** MultiQC, Run QC, Coverage, Bias and context, Global methylome,
  Group comparison. Each answers the question the previous one raises: is the report normal,
  which libraries fail a floor, is depth spread evenly enough for a site call, does the
  extraction need a trim, is each methylome bimodal and do the libraries group by the design,
  and where do the two groups differ.
- **The sample hub is the hub.** `samples` is one row per sample: the samplesheet id and FASTQ
  pair joined to the factors of `METADATA_FILE`, carried under their own names. A persistent
  `Sample filters` section (sample, `GROUP_COL`) is pinned to the top of every tab, and the
  project links fan a pick there out to the MultiQC panels and every per-library collection.
- **Pinned glance strip and sample sheet.** Four cards ride every tab (samples by the design
  factor, reads to CpG calls, CpG methylation, lowest conversion efficiency); none is repeated
  as a tab card. The sample hub table sits in a collapsed `Sample sheet` section pinned to the
  top. A collapsed `QC thresholds` section holds the mapping-efficiency, duplication and
  conversion sliders.
- **Every tab has its own filters.** Read and yield sliders on Run QC, contig and depth on
  Coverage, context, read and read position on Bias and context, CpG-density class and window
  methylation on Global methylome, call, effect size and adjusted p on Group comparison.
- **Detail tables are collapsed at the end of the tab that reads them.**
- **Catalog provenance.** Every panel outside the MultiQC tab carries a `use:` catalog
  reference (`bismark/*`, `qualimap/*`), or an explicit `viz_kind` for the locus tracks.
- **Everything matches on file name**, so a run published with a different `--outdir` layout
  still lands in the same collections.

---

## MultiQC

MultiQC panels only, every module the reprocessed report carries: general statistics, all ten
FastQC panels, the two Cutadapt panels, Bismark's five plots (alignment rates, strand, the
deduplication share, the per-context cytosine methylation and the six-panel M-bias picker) and
Qualimap BamQC. A bisulfite library legitimately fails the per-base sequence content and GC
checks, because converting unmethylated cytosines is the point, so the quality, length and
adapter panels are the ones to read. A tab-local `Glance scope` slider narrows the glance strip
by CpG methylation level.

---

## Run QC

Bismark's run summary (`bismark2summary`), its alignment report and its deduplication report,
one row per library.

`Alignment and duplication`: the share of reads aligned and duplicated per library (box plots),
then two floor cards on the worst library of the selection. Mapping efficiency passes at 70 %
and warns from 60 %; duplication passes up to 10 % and warns to 20 %. Bisulfite alignment
searches four converted genomes, so an efficiency in the seventies is the expected ceiling.

`Cytosine yield`: CHG and CHH methylation and the conversion rate per library. The template
reads conversion as `100 - %CHH`, which assumes a mammalian genome where non-CpG methylation is
near zero; below about 98 % the CpG calls inherit the same false-positive rate. Plants methylate
CHG and CHH for real, so on a plant run judge conversion on an unmethylated spike-in such as
lambda instead of this card.

`Library QC profile`: eight run-summary metrics on parallel axes, one line per library coloured
by the design factor. A library that crosses the others on the CHH axis is a conversion
problem; one that crosses them on the alignment and duplication axes together is a library
preparation problem.

`Library detail` (collapsed): the run summary, alignment and deduplication tables.

---

## Coverage

Qualimap BamQC at full resolution. `Depth summary`: mean depth, duplication, mapping quality and
GC of mapped bases per library. Mean depth counts the bases at zero, so on a shallow run the
genome-fraction curve is the number to judge; a low GC share is the conversion itself.
`Depth along the reference` maps Qualimap's windows back onto their contigs with the per-contig
lengths of the same `genome_results.txt`. `Depth distribution` holds the depth histogram and the
share of the reference covered at least X deep. `Coverage detail` (collapsed) is the BamQC table.

---

## Bias and context

One M-bias explorer over all six tables of the M-bias file, the context filter opening on CpG.
A CpG curve that has not flattened by the end of the read is Bismark's own advice to add an
`--ignore` / `--ignore_r2` trim and re-extract. A CHH curve that climbs at one end is unconverted
cytosine at those positions, on a mammalian genome. `Context detail` (collapsed) holds the raw
M-bias positions and the per-context methylation counts.

---

## Global methylome

The methylome itself, out of the per-CpG bedGraph files. Nothing is read into memory whole:
each file is streamed through `depictio/recipes/lib/genomic_bins.py` into 10 kb windows. A window
counts once it holds at least 20 CpGs in **every** library, on a contig with at least 50 such
windows (which drops unplaced scaffolds without naming an assembly). For drawing and for the
cohort panels, `bismark_binned_methylation` keeps a uniform stride of those windows (at most
20,000); a uniform stride, rather than the CpG-densest windows, keeps every panel a genome-wide
view instead of a CpG-island one.

`Per-CpG methylation`: the distribution of methylation over every covered CpG, 2 % buckets, one
curve per library, with two cards on the share of CpGs at 98 to 100 % and at 0 to 2 %. A healthy
mammalian methylome is bimodal; a library whose low peak drifted upward points to incomplete
conversion or a depth too low for a site call.

`CpG density`: the windows split into tertiles of their CpG count (CpG-poor, Intermediate,
CpG-dense). nf-core/methylseq bundles no CpG-island or TSS annotation, and CpG density is the
property an island is defined by, so this is the annotation-free stand-in, named as a proxy.
With a bundled island and TSS annotation, three panels would follow without a new pipeline run:
methylation by feature class (island, shore, shelf, open sea), a TSS metagene over the signed
distance to the transcription start site, and the same metagene as a signal matrix.

`Cohort structure`: the library-by-window matrix read three ways, a PCA coloured by the design
factor, the pairwise Pearson correlation and the 150 windows that vary most.

---

## Group comparison

nf-core/methylseq ships no differential-methylation caller at any version, so this is the screen
the published files support, labelled as one.

- **Every eligible window is tested.** `bismark_window_group_compare` re-bins the bedGraphs with
  the same eligibility rules as the binned collection but without its drawing stride, so
  Benjamini-Hochberg corrects over every eligible window. Drawing budgets are applied by the
  renderers (the Manhattan, volcano and navigator keep every window above padj 0.05 and sample
  the rest), never by the test.
- **The test.** A pooled two-sample t-test on the arcsine square-root transform of each window's
  methylation proportion, between the two levels of `GROUP_COL` when it has exactly two levels,
  else of the first design factor that does (at least two libraries a side). `group_a` and `group_b` in the table name the two
  levels in sorted order; `delta_methylation` is `group_a` minus `group_b` in percentage points.
  A window is called when padj is under 0.05 and the difference is at least ten points.
- **What it is not.** The unit is a window, not a CpG and not a called DMR. Without per-CpG
  coverage counts (a 2.3.0 run does not publish `methylation_coverage/` by default) there is no
  beta-binomial model, and with few libraries a side the screen is low-powered by construction.
- **No design, no tab.** Without `METADATA_FILE`, or without a two-level factor, the collection
  is skipped and its tiles are pruned.

`Window comparison`: the difference, the number of called windows, the windows tested and the
strongest call, then the Manhattan (genome-wide, opening the funnel) and the volcano with a QQ
view in its header. `Effect size distribution`: the per-window difference by call.
`Methylation at a locus`: a navigator on the comparison (significance per window, a locus field
and a brush in its header) with two followers on the same region, one lane per library from the
binned collection and the group difference. It opens on a documented default region; the
rationale for the shipped default is in `VALIDATION_REPORT.md`. `Window detail` (collapsed) is
the tested-window table.

---

## Cross-selection

A picked row or point becomes a dashboard filter that narrows the other tiles of its
collection and follows the project links to the collections they reach. The pinned sample
sheet selects on `sample_id`; the Bismark, Qualimap and M-bias tables and the per-library
profiles select on `sample`; the group comparison table and the two window tracks select on
`window_id`, and the manhattan panel on `chromosome`. The methylation-by-context table, the
binned methylation track and the depth histogram do not narrow anything: their collections
have no outgoing link and no sibling tile. The cohort PCA emits a selection but reaches no
other tile for the same reason.

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
python -m depictio.cli run --template nf-core/methylseq/2.3.0 \
  --data-root ~/Data/depictio-nfcore/methylseq/2.3.0/megatest --dry-run \
  --var METADATA_FILE=~/Data/depictio-nfcore/methylseq/2.3.0/megatest/input/sample_metadata.tsv
python -m depictio.cli run --template nf-core/methylseq/2.3.0 \
  --data-root ~/Data/depictio-nfcore/methylseq/2.3.0/megatest \
  --var METADATA_FILE=~/Data/depictio-nfcore/methylseq/2.3.0/megatest/input/sample_metadata.tsv
```

Step 3 is mandatory: without it `multiqc_data` finds no parquet and the MultiQC tab is empty.
Keep the first `REPROCESSED.json` or delete `multiqc/multiqc_data/` before re-running, because
the source-version probe reads the parquet it just wrote. The bedGraph recipes stream the per-CpG
files twice (binned windows and the group comparison), a few seconds each on the megatest.
