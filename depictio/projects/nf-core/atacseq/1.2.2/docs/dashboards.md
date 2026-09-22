# nf-core/atacseq 1.2.2: Depictio dashboards

This template turns the output of [nf-core/atacseq](https://nf-co.re/atacseq) 1.2.2 into a
single five-tab Depictio dashboard. atacseq trims and aligns ATAC libraries, filters out
duplicates and mitochondrial reads, measures the ATAC-specific quality signals with ataqv,
calls accessible regions per library with MACS2, annotates them with HOMER, merges them into
one consensus peak set and finally tests each consensus interval for differential
accessibility with DESeq2. The dashboard follows that chain from left to right.

Data comes from the AWS megatest run
`results-f327c86324427c64716be09c98634ae0bc8165f6` (the 1.2.2 release tag): six GM12878
libraries across three transposition protocols, FAST, OMNI and STD, two biological replicates
each.

> **This template reads a REPROCESSED MultiQC report.**
> atacseq 1.2.2 is a DSL1 pipeline and this run published MultiQC 1.9, which writes
> `multiqc_data.json` and no parquet, nested at `multiqc/broadPeak/multiqc_data/`. Depictio
> reads only `multiqc.parquet` (MultiQC 1.31 and later), so the MultiQC tab is bound to a report
> this repository generates by re-running the pinned MultiQC 1.35 over the run's own raw tool
> outputs. Here the upgrade is not only a format change: MultiQC 1.35 gained an `ataqv`
> module that 1.9 had no idea about, so the reprocess adds four ATAC-specific QC panels
> outright. Never copy a `selected_plot` out of the published HTML report; read it from
> `multiqc.list_plots()` on the regenerated parquet. See the Reproducing section below and
> `VALIDATION_REPORT.md`.

> **This is the broad-peak route, and only that route.** The run was called with
> `--narrow_peak false`, so the peak files are `*_peaks.broadPeak` (BED6+3, no summit column)
> and are read by the catalog's `macs2/broad_peaks` rather than by `macs2/peaks`, which reads
> the narrowPeak shape. The two outputs glob on different file names, so a run matches exactly
> one of them. Release 1.2.1 is the narrowPeak twin of the same run.
>
> There is deliberately no narrowPeak route variant in the template. The mechanism exists
> (`template.conditional` with `override_dcs`), but broad reports a `midpoint` column where
> narrow reports a `summit`, and the dashboard binds the broad catalog renders, so a narrow
> route would also need a second copy of `dashboards/base.yaml`. See AT-D15. Every other
> collection already takes both routes: the HOMER, consensus and DESeq2 globs match
> `macs/*/`, not `macs/broadPeak/`.

---

## How the dashboard is built

- **One funnel, five tabs.** MultiQC, then ATAC signal, then Peaks, then Consensus, then
  Differential accessibility. Each tab answers the question the previous one raises: are the
  libraries clean, is the ATAC signal where it should be, what did MACS2 call in each
  library, which of those calls the libraries agree on, and which of the agreed intervals
  change between transposition protocols.
- **The design sheet is the hub.** `pipeline_info/design_reads.csv` becomes `sample_design`,
  one row per library with its protocol group and both spellings of its name. A persistent
  `Sample filters` section is pinned to the top of every tab and carries one control per real
  factor of the sheet: the ATAC sample, the transposition protocol (three values) and the
  biological replicate (two values, an integer column, so a range control rather than a
  select). The template's links fan a pick there out to the MultiQC panels, the ataqv
  collections, the peak QC summary, the peak calls, the HOMER annotation and the two DESeq2
  QC collections at once; the protocol pick also reaches the DESeq2 contrasts, which are
  named after the two groups compared, through a prefix (`wildcard`) link. The consensus
  matrices cannot take that link: this pipeline version builds one consensus set across
  every library, so `consensus_set` holds a single value and the samples are its columns.
- **Every tab also filters on its own columns.** Beside the persistent sample scope, each tab
  declares a non-persistent section on the collections it actually shows: `Peak QC scope`
  (peaks called, median peak width) on the MultiQC tab, `Fragment windows` on ATAC signal,
  `Peak filters` (significance, width, feature class, reference sequence) on Peaks,
  `Consensus scope` on Consensus and `Contrast` on Differential accessibility. Nothing rides
  a tab whose collections it cannot reach.
- **Two spellings, one filter.** atacseq calls the merged filtered library
  `<sample>.mLb.clN` and MACS2 stamps that into every peak name, while ataqv, the peak QC
  summary and MultiQC use the bare sample id. `sample_design` carries both columns and each
  link starts from whichever one its target uses, so one pick in the sample filter reaches
  every collection.
- **A glance strip on every tab.** `Cohort at a glance` is a pinned persistent four-card
  strip, never collapsed: libraries by protocol (donut), replicate depth (box plot), peaks
  called (top 3 by library) and mean FRiP (gauge). It is what makes a strip legal on the
  MultiQC tab, and it is the first row wherever the reader lands.
- **Pinned reference tables and thresholds.** The design sheet sits in a collapsed `Sample
  sheet` section pinned to the top of every tab, and the per-library peak QC rows in a
  collapsed `Reference tables` section pinned to the bottom, next to a collapsed
  `QC thresholds` section holding the TSS enrichment and FRiP floors, so the design, the
  numbers behind the cards and the cut-offs applied to them are one click away everywhere.
- **Selection, both ways.** The signal-against-specificity scatter on the ATAC signal tab
  carries `selection_enabled` on `sample` and the ataqv metrics table carries
  `row_selection_enabled` on the same column; the enrichment scatter on the Peaks tab and
  both peak tables do the same on `peak_id`. Lassoing narrows the tables, ticking rows
  narrows the panels, and the project links carry the selection between the MACS2 and HOMER
  collections.
- **Catalog provenance.** 68 of the 73 renderable tiles carry a `use:` catalog reference
  (93%; the other 49 tiles are the text intros and the left-rail filters, which never do), so
  the tile chrome says where the panel comes from: `ataqv/*` for the ATAC quality panels,
  `macs2/*` for the peak and consensus panels, `homer/annotated_peaks` for the annotation
  panels, `deseq2/*` for the differential accessibility and consensus QC panels and
  `multiqc/<module>` for the tool-module QC panels. The five that do not are the two MultiQC
  custom-content panels the catalog has no module for (AT-D9), the design table, and the two
  genome-track tiles the MACS2 catalog has no render id for yet (AT-D16).
- **Everything matches on file name, or on the part of the path that carries meaning.** No
  data collection or recipe glob spells out the `bwa/` aligner directory or the `broadPeak/`
  route: the HOMER and DESeq2 QC globs anchor on `**/mergedLibrary/macs/*/`, which is the
  merge level the template binds, and the MultiQC scan regex takes both
  `multiqc/multiqc_data/` and the `multiqc/<route>/multiqc_data/` a real run writes.

---

## MultiQC

The main tab, and the one reading the reprocessed report.

`Run at a glance` is the MultiQC General Statistics table: one row per library, pooling the
FastQC, Trim Galore, samtools, Picard, MACS2 and ataqv headline numbers. It is the one panel
in the report that speaks for the run rather than for a single tool, so it is what the tab
opens on, and the sections below take it apart module by module. The ATAC-specific ataqv
measures are on the ATAC signal tab.

`Read quality` carries FastQC sequence counts and quality histograms and the cutadapt kept
reads. Every library appears here more than once, under its raw and trimmed read-pair names.

`Alignment and library complexity` pairs Picard insert sizes with Picard duplication, then
samtools percent mapped and per-contig distribution at both filtering levels the run
published, then the preseq complexity curve. The doubled samtools entries are the point of
that section: `mLb.mkD` is duplicate-marked but unfiltered, `mLb.clN` is what the peak caller
sees, and the pair says how much ATAC filtering removed.

`Accessibility signal` is the tab's conclusion: the deepTools fingerprint curve, the FRiP
scores, the peak counts per library and the featureCounts bars saying how many reads fall
inside the consensus peaks.

Every tile on this tab reads the report. The panels that read a tool's own tables instead of
MultiQC's rendering of them sit on the ATAC signal tab, next to the collections they come
from. That is also why this tab alone opens on a table rather than on a card strip: a shipped
test keeps non-MultiQC tiles off a tab called MultiQC (AT-D11, AT-D17), and no card reads the
report.

The left rail carries the persistent sample scope, the persistent QC thresholds and, local to
this tab, `Peak QC scope`: the peaks called and the median peak width of each library, which
narrow the peak QC rows pinned under the panels.

---

![MultiQC](screenshots/library-qc.png)

## ATAC signal

The tab that exists because MultiQC 1.9 reported none of this and 1.35 only reports part of
it.

`Library quality at a glance` is eight cards on the ataqv collections, in two rows that each
fill the grid. The first row is the quartet a library is accepted or rejected on: mean TSS
enrichment, the share of high-quality autosomal reads that fall inside peaks, the median
mitochondrial fraction and the duplicate fraction. The second is what the library's peaks and
fragments look like: the peaks ataqv scored with a breakdown by library, the median fragment
length and the spread of reads over the fragment classes.

`Depth and coverage concentration` reads two tables the report renders as bare curves. `use:
preseq/complexity_ribbon` adds the 95% confidence band MultiQC drops, so a library whose
extrapolation is guesswork shows as a ribbon that fans out instead of a line that looks as
certain as any other; `use: deeptools/fingerprint_scatter` puts every library on one plane,
coverage concentration against divergence from a uniform library, which for ATAC is how much
of the signal sits in open chromatin. Clicking a curve or a point selects that library.

`Signal at transcription start sites` holds the canonical ATAC enrichment curve, coverage
against distance to the TSS with one trace per library, next to a scatter placing each
library on TSS enrichment against the share of reads in peaks. Lassoing libraries on that
scatter narrows the ataqv table below. Under them, `use: deeptools/metagene_profile` draws
the `plotProfile` matrix as one curve per library with the TSS marked at bin 300 and the
scaled gene body shaded.

`Fragment length ladder` puts the template's own fragment-length figure next to MultiQC's
rendering of the same signal, then the reads-per-fragment-class bars. The pair is
deliberate: the figure is filtered by the fragment-window controls in the left rail, the
MultiQC panel is the unfiltered reference.

`Read distribution` carries the per-chromosome read matrix as a complex heatmap and MultiQC's
MAPQ distribution beside it. The mitochondrial contig is the row to read first: a high `chrM`
share is the classic ATAC failure.

`ATAC quality tables`, collapsed, holds the per-library ataqv metrics with row selection on
`sample`.

---

![ATAC signal](screenshots/atac-signal.png)

## Peaks

`Peaks at a glance` counts the calls in view, their width distribution as a Tukey box plot,
their fold enrichment and the strongest significance reached.

`Significance along the genome` is the manhattan panel over `-log10(q)`, next to a code-mode
scatter of enrichment against significance carrying `selection_enabled` on `peak_id`, and a
width histogram in UI mode.

`Peak intervals on the genome` draws the same calls as intervals rather than as points. A
broad call is a region, and the manhattan panel above collapses it to its midpoint, which is
the one thing a broad run should not be read as. The `genome_view` tile binds `chr / start /
end / neg_log10_qvalue` with `mark: rect` and `facet_by_sample`, so each library gets its own
lane on a shared, chromosome-aware genome axis: scroll to zoom into a locus, drag to pan,
brush a region to narrow the tab to it and click an interval to select the peak. A
`coverage_track` tile under it reads the same rows through the Plotly renderer, so the
section still answers the question if the GenomeSpy renderer is unavailable. Neither tile
pins an assembly: the contig list is derived from the data, so the pair works on a run
aligned against any reference rather than only against a human one.

`Where the peaks land` reads the HOMER annotation: four cards (feature classes, genes
reached, distance to TSS, annotated peaks), the annotation bar per library, and a code-mode
histogram of the distance to the nearest start site inside a 10 kb window. Under it, `use:
homer/tss_distance` reads the same distances pre-binned by the recipe, one curve per library
as a share of that library's peaks: the histogram pools libraries and splits by class, the
profile does the opposite, and being a share rather than a count is what lets libraries of
different depth be compared.

`Peak tables`, collapsed, holds the MACS2 broad calls and the HOMER annotation, both with row
selection on `peak_id`, linked to each other in both directions.

The left rail filters on peak significance, peak width, feature class and reference sequence.
The last one is what the two genome tiles are read with: one chromosome at a time keeps the
track legible and the region brush meaningful.

---

![Peaks](screenshots/peaks.png)

## Consensus

`Consensus at a glance` counts the intervals in the merged set, how many libraries back each
one, how many per-library peaks were merged into them, and the support of the strongest.

`Replicate agreement` is the UpSet panel over the six library columns of the consensus
boolean matrix: which combinations of libraries call the same interval. With three protocols
in two replicates each, the protocol-specific intersections are what to read.

`Sample space` reads the two QC tables nf-core's own `featurecounts_deseq2.r` writes beside
the contrast results, as data rather than as the MultiQC custom-content images the report
renders them as: `use: deseq2/qc_pca_embedding` places every library on the two principal
components of the consensus count matrix, and `use: deseq2/qc_distance_heatmap` clusters the
pairwise Euclidean distances. Read together they say whether the contrasts on the next tab
are worth reading at all: on this run the two replicates of a protocol sit at distance 32 to
91 of each other and 101 to 119 from any other protocol, so the protocols separate cleanly.
These two collections are also the only sample-keyed rows on the consensus level, which makes
them what carries the left-rail sample scope onto this tab at all (AT-D18).

`Signal at the strongest intervals` is the fold-enrichment heatmap over the 250 most
accessible intervals, clustered. It is a top-N view on purpose: the full set is 104657
intervals, which is not a heatmap. Selecting an interval elsewhere narrows this panel when
the interval is in the top set and clears it otherwise.

`Consensus tables`, collapsed, holds both consensus collections with row selection on
`peak_id`, then the PCA coordinates and the distance matrix behind the `Sample space` panels,
with row selection on the library.

---

![Consensus](screenshots/consensus.png)

## Differential accessibility

DESeq2 over the consensus interval counts, three contrasts: FAST against OMNI, FAST against
STD and OMNI against STD.

`Differential accessibility at a glance` counts the intervals tested, the effect size
distribution, the direction split as a donut and the strongest significance.

`Volcano and MA` are the catalog's `deseq2/volcano` and `deseq2/ma` panels. `Calibration and
direction` adds the QQ plot, the strongest differential intervals as a DA barplot, and a
code-mode bar of significant intervals per contrast.

The `Contrast` filter is a single-choice `Select` rather than a MultiSelect. That is
deliberate: DESeq2 scores consensus intervals named `Interval_1 ... Interval_N` and the
numbering restarts per contrast, so a `gene_id` identifies an interval only in combination
with the selected contrast.

`Differential tables`, collapsed, holds the DESeq2 rows with row selection on `gene_id`.

---

![Differential accessibility](screenshots/differential-accessibility.png)

## Reproducing

```bash
# 1. Fetch the megatest subset (147 files, 215 MB)
bash depictio/projects/nf-core/atacseq/1.2.2/download_test_data.sh \
  ~/Data/depictio-nfcore/atacseq/1.2.2/megatest

# 2. Regenerate the MultiQC report Depictio reads (the run wrote 1.9)
python -m depictio.dev_scripts.multiqc_reprocess \
  --src  ~/Data/depictio-nfcore/atacseq/1.2.2/megatest \
  --dest ~/Data/depictio-nfcore/atacseq/1.2.2/megatest

# 3. Dry run, then ingest
python -m depictio.cli run --template nf-core/atacseq/1.2.2 \
  --data-root ~/Data/depictio-nfcore/atacseq/1.2.2/megatest --dry-run
python -m depictio.cli run --template nf-core/atacseq/1.2.2 \
  --data-root ~/Data/depictio-nfcore/atacseq/1.2.2/megatest
```

Step 2 is mandatory, not optional: without it `multiqc_data` finds no parquet and the whole
MultiQC tab is empty. Step 2 is also not idempotent for its provenance record, so keep the
first `REPROCESSED.json` or delete `multiqc/multiqc_data/` before re-running (AT-D7).
