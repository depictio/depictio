# nf-core/atacseq 1.2.2: Depictio dashboards

This template turns the output of [nf-core/atacseq](https://nf-co.re/atacseq) 1.2.2 into a
single six-tab Depictio dashboard. atacseq trims and aligns ATAC libraries, filters out
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

- **One funnel, six tabs.** MultiQC, then Signal, then Peaks, then Locus, then Consensus,
  then Differential accessibility. Each tab answers the question the previous one raises: are
  the libraries clean, is the ATAC signal where it should be, what did MACS2 call in each
  library, what the calls look like on one region, which of those calls the libraries agree
  on, and which of the agreed intervals change between design groups.
- **Genome build is a variable.** `GENOME` (default `hg38`) feeds the `assembly` of every
  genome track on the Locus tab. The megatest was aligned against hg19, which
  `reference.vars` sets for the reference ingest; for any other hg19 run pass
  `--var GENOME=hg19`.
- **The design sheet is the hub.** `pipeline_info/design_reads.csv` becomes `sample_design`,
  one row per library with its protocol group and both spellings of its name. A persistent
  `Sample filters` section is pinned to the top of every tab and carries one control per real
  factor of the sheet: the ATAC sample, the transposition protocol (three values) and the
  biological replicate (a MultiSelect on the `replicate_label` column, `R1`, `R2` and
  so on, which the design recipe derives from the integer replicate). The template's links fan a pick there out to the MultiQC panels, the ataqv
  collections, the peak QC summary, the peak calls, the HOMER annotation and the two DESeq2
  QC collections at once; the protocol pick also reaches the DESeq2 contrasts, which are
  named after the two groups compared, through a prefix (`wildcard`) link. The consensus
  matrices cannot take that link: this pipeline version builds one consensus set across
  every library, so `consensus_set` holds a single value and the samples are its columns.
- **Every tab also filters on its own columns.** Beside the persistent sample scope, each tab
  declares a non-persistent section on the collections it actually shows: `Library scope`
  on the MultiQC tab, `Fragment windows` on Signal, `Peak filters` (significance, width,
  feature class, reference sequence) on Peaks, `Locus scope` on Locus, `Consensus scope` on
  Consensus and `Contrast` on Differential accessibility. Nothing rides
  a tab whose collections it cannot reach.
- **Two spellings, one filter.** atacseq calls the merged filtered library
  `<sample>.mLb.clN` and MACS2 stamps that into every peak name, while ataqv, the peak QC
  summary and MultiQC use the bare sample id. `sample_design` carries both columns and each
  link starts from whichever one its target uses, so one pick in the sample filter reaches
  every collection.
- **A glance strip on every tab.** `Cohort at a glance` is a pinned persistent four-card
  strip, never collapsed: libraries by group (donut), replicate depth (box plot), peaks
  called (top 3 by library) and mean FRiP (gauge). It is what makes a strip legal on the
  MultiQC tab, and it is the first row wherever the reader lands.
- **Pinned reference tables and thresholds.** The design sheet sits in a collapsed `Sample
  sheet` section pinned to the top of every tab, and the per-library peak QC rows in a
  collapsed `Reference tables` section pinned to the bottom, next to a collapsed
  `QC thresholds` section holding the TSS enrichment and FRiP floors and the peak count, so
  the design, the
  numbers behind the cards and the cut-offs applied to them are one click away everywhere.
- **Selection, both ways.** The signal-against-specificity scatter on the Signal tab
  carries `selection_enabled` on `sample` and the ataqv metrics table carries
  `row_selection_enabled` on the same column; both peak tables on the Peaks tab do the
  same on `peak_id`. Lassoing narrows the tables, ticking rows
  narrows the panels, and the project links carry the selection between the MACS2 and HOMER
  collections.
- **Catalog provenance.** Almost every renderable tile carries a `use:` catalog reference
  (the text intros and the left-rail filters never do), so
  the tile chrome says where the panel comes from: `ataqv/*` for the ATAC quality panels,
  `macs2/*` for the peak and consensus panels, `homer/annotated_peaks` for the annotation
  panels, `deseq2/*` for the differential accessibility and consensus QC panels and
  `multiqc/<module>` for the tool-module QC panels. The exceptions are the two MultiQC
  custom-content panels the catalog has no module for (AT-D9), the design table, the two
  genome-track tiles the MACS2 catalog has no render id for yet (AT-D16), and the FRiP and
  peak-count threshold filters (open in the Wave 3 section of `VALIDATION_REPORT.md`).
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
measures are on the Signal tab.

`Read quality` carries FastQC sequence counts and quality histograms and the cutadapt kept
reads. Every library appears here more than once, under its raw and trimmed read-pair names.

`Alignment and library complexity` pairs Picard insert sizes with Picard duplication, then
samtools percent mapped and per-contig distribution at both filtering levels the run
published, then the ataqv MAPQ distribution. The preseq curve is not repeated here: the
Signal tab carries it with its confidence band. The doubled samtools entries are the point of
that section: `mLb.mkD` is duplicate-marked but unfiltered, `mLb.clN` is what the peak caller
sees, and the pair says how much ATAC filtering removed.

`Accessibility signal` is the tab's conclusion: the deepTools fingerprint curve, the FRiP
scores, the peak counts per library and the featureCounts bars saying how many reads fall
inside the consensus peaks.

Every tile on this tab reads the report. The panels that read a tool's own tables instead of
MultiQC's rendering of them sit on the Signal tab, next to the collections they come
from. That is also why this tab alone opens on a table rather than on a card strip: a shipped
test keeps non-MultiQC tiles off a tab called MultiQC (AT-D11, AT-D17), and no card reads the
report.

The left rail carries the persistent sample scope, the persistent QC thresholds and, local to
this tab, `Library scope`: a library pick on the design sheet that narrows every MultiQC panel
through the `design_reads -> multiqc_data` link.

---

![MultiQC](screenshots/library-qc.png)

## Signal

The tab that exists because MultiQC 1.9 reported none of this and 1.35 only reports part of
it.

`Library quality at a glance` is eight cards on the ataqv collections, in two rows that each
fill the grid. The first row is the quartet a library is accepted or rejected on: mean TSS
enrichment, the lowest share of high-quality autosomal reads inside peaks, the median
mitochondrial fraction and the duplicate fraction. The second is what the library's fragments
look like: the per-library median fragment length (read-weighted over the ataqv histogram,
`ataqv/metrics.median_fragment_length`), the reads per fragment class, the short-to-mono
ratio and the properly paired share.

`Depth and coverage concentration` reads two tables the report renders as bare curves. `use:
preseq/complexity_ribbon` adds the 95% confidence band MultiQC drops, so a library whose
extrapolation is guesswork shows as a ribbon that fans out instead of a line that looks as
certain as any other; `use: deeptools/fingerprint_scatter` puts every library on one plane,
coverage concentration against divergence from a uniform library, which for ATAC is how much
of the signal sits in open chromatin. Clicking a curve or a point selects that library. The
fingerprint plane and the read-distribution dot plot carry `controls_placement: header`, so
their axis and sort pickers sit under the title instead of behind the settings icon.

`Signal at transcription start sites` holds the canonical ATAC enrichment curve, coverage
against distance to the TSS with one trace per library, next to a scatter placing each
library on TSS enrichment against the share of reads in peaks. Lassoing libraries on that
scatter narrows the ataqv table below. Under them, `use: deeptools/metagene_profile` draws
the `plotProfile` matrix as one curve per library with the TSS marked at bin 300 and the
scaled gene body shaded.

`Fragment length ladder` carries the template's own fragment-length figure, filtered by the
fragment-window controls in the left rail, then the reads-per-fragment-class bars. MultiQC's
rendering of the same curve is not repeated.

`Read distribution` carries the per-chromosome read matrix as a complex heatmap (the MAPQ
distribution moved to the MultiQC tab). The mitochondrial contig is the row to read first: a high `chrM`
share is the classic ATAC failure.

`ATAC quality tables`, collapsed, holds the per-library ataqv metrics with row selection on
`sample`.

---

![Signal](screenshots/atac-signal.png)

## Peaks

`Peaks at a glance` counts the calls in view, their width distribution as a Tukey box plot,
their fold enrichment and the strongest significance reached, against a q-value threshold of
1.3 (`-log10(0.05)`, warn at 1.0).

`Significance along the genome` is the manhattan panel over `-log10(q)` next to a width
histogram in UI mode. The per-library FRiP and peak-count bars are not repeated here: the
glance strip and the MultiQC tab already carry them.

`Where the peaks land` reads the HOMER annotation: four cards (feature classes, genes
reached, distance to TSS, peak score), then the feature-class share per library as a full
width percent-normalised histogram. Under it, `use: homer/tss_distance` draws the distance to
the nearest start site pre-binned by the recipe, one curve per library as a share of that
library's peaks, which is what lets libraries of different depth be compared.

`Peak tables`, collapsed, holds the MACS2 broad calls and the HOMER annotation, both with row
selection on `peak_id`, linked to each other in both directions. A peak record card
(`linked_component` on the HOMER table) sits beside the annotation table: it stays a thin
rail until a row is picked, then shows the call with its feature class, distance to TSS and
nearest gene.

The left rail filters on peak significance, peak width, feature class and reference sequence.
The two sliders draw the distribution of their column above the handles (`show_histogram`).
The interval view of the calls moved to the Locus tab: a
region filter narrows every tile of its collection on a tab, and this tab keeps its
genome-wide panels.

## Locus

Three collections on one genomic region and one axis. The navigator carries a
`default_region` chosen so that every library calls peaks there and no track opens empty.

`Region at a glance` counts what the libraries called on the region in view: calls per
library (top 3), libraries per consensus interval (box plot), the HOMER feature classes
(donut) and the nearest genes. The cards follow the region like the tracks do.

`Peaks on one axis` stacks three tiles:

- the navigator, a `genome_view` on `macs2_broad_peaks` (`mark: rect`, one lane per
  library, `controls_placement: header`), with `assembly: {GENOME}` for the chromosome
  sizes. A locus or a brush in its header moves the section. No gene lane: the bundled gene
  tables are hg38 and mm10 only, and the annotation field does not take a variable yet.
- `macs2_consensus_boolean` as a second `genome_view` (`mark: bar`,
  `follow_region_filter: true`): each merged consensus interval as high as the number of
  libraries calling a peak on it. GenomeSpy rather than a Plotly `coverage_track`: the table
  holds ~105k intervals, and a Plotly track that fetches before the default region lands
  draws all of them genome-wide.
- `homer_annotated_peaks` as a third `genome_view` with `follow_region_filter: true`,
  coloured by feature class with the nearest gene in the hover. It stands in for the gene
  lane.

Two region links in `template.yaml` (`resolver: region`, `columns: {chrom: chr, pos:
start}`) rename the navigator's chromosome and position filters onto the consensus and HOMER
collections. `coverage_track` and `genome_view` never share a collection on this tab, which
the shipped-YAML lint `test_no_double_track_binding` enforces.

The navigator reads its own collection without its own region (so a brush can widen again),
and the server caps that read at about 10k rows ranked by q-value, so at the default region
it draws only the strongest calls of each library. The two tracks under it read the region
exactly.

The value link `macs2_broad_peaks -> homer_annotated_peaks` on `peak_id` is disabled in
`template.yaml`: the API walks every filter on the peak table through it, and a range filter
(the navigator's position, the q-value and width sliders) resolves as two discrete peak ids
and empties the HOMER tiles. A lasso on the Peaks tab therefore no longer narrows the HOMER
tables; the reverse link (HOMER to MACS2) still works.

The `Locus scope` rail filters the consensus support (slider with its
histogram) and the HOMER feature class. The persistent sample filters reach the broad calls
and the HOMER track through the project links; the consensus matrix has libraries as
columns, so they do not narrow it.

---

![Peaks](screenshots/peaks.png)

## Consensus

`Consensus at a glance` counts the intervals in the merged set, how many libraries back each
one, how many per-library peaks were merged into them, and the support of the strongest.

`Replicate agreement` is the UpSet panel over the library columns of the consensus boolean
matrix: which combinations of libraries call the same interval. The group-specific
intersections are what to read.

`Signal at the strongest intervals` is the fold-enrichment heatmap over the 250 most
accessible intervals, clustered. It is a top-N view on purpose: the full set runs to
hundreds of thousands of intervals, which is not a heatmap. Selecting an interval elsewhere narrows this panel when
the interval is in the top set and clears it otherwise.

`Consensus tables`, collapsed, holds both consensus collections with row selection on
`peak_id`.

---

![Consensus](screenshots/consensus.png)

## Differential accessibility

DESeq2 over the consensus interval counts, one contrast per pair of design groups.

`Sample space` opens the tab. It reads the two QC tables nf-core's own `featurecounts_deseq2.r`
writes beside the contrast results, as data rather than as MultiQC custom-content images:
`use: deseq2/qc_pca_embedding` places every library on the two principal components of the
consensus count matrix, and `use: deseq2/qc_distance_heatmap` clusters the pairwise Euclidean
distances (ward linkage, `Blues` scale). Read together they say whether the contrasts below
are worth reading at all.

`Differential accessibility at a glance` counts the intervals tested per contrast, the
effect size distribution, the direction split as a donut and the strongest significance
against a threshold of 1.3.

`Volcano, MA and QQ` is one `deseq2/volcano` tile with `views: [volcano, ma, qq]` and
`controls_placement: header`: the view switch and the thresholds sit under the title, the
tab opens on the volcano, and the MA (`avg_log_intensity_col: log2_base_mean`) and QQ
(`p_value_col: pvalue`) readings of the same rows are one click away. `Direction of change`
adds the strongest differential intervals as a DA barplot and a code-mode bar of significant
intervals per contrast.

The `Contrast` filter is a single-choice `Select` rather than a MultiSelect. That is
deliberate: DESeq2 scores consensus intervals named `Interval_1 ... Interval_N` and the
numbering restarts per contrast, so a `gene_id` identifies an interval only in combination
with the selected contrast.

`Differential tables`, collapsed, holds the DESeq2 rows with row selection on `gene_id`, then
the PCA coordinates and the distance matrix behind `Sample space`.

---

![Differential accessibility](screenshots/differential-accessibility.png)

## Cross-selection

A picked row or point becomes a dashboard filter that narrows the other tiles of its
collection and follows the project links to the collections they reach. On top of the
selections described per tab, the pinned peak summary table selects on `sample`, and the
consensus and annotation tracks of the Locus tab select on `peak_id` like the navigator.
The TSS distance profile does not select: its collection has no outgoing link.

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
python -m depictio.cli run --template nf-core/atacseq/1.2.2 --var GENOME=hg19 \
  --data-root ~/Data/depictio-nfcore/atacseq/1.2.2/megatest --dry-run
python -m depictio.cli run --template nf-core/atacseq/1.2.2 --var GENOME=hg19 \
  --data-root ~/Data/depictio-nfcore/atacseq/1.2.2/megatest
```

Step 2 is mandatory, not optional: without it `multiqc_data` finds no parquet and the whole
MultiQC tab is empty. Step 2 is also not idempotent for its provenance record, so keep the
first `REPROCESSED.json` or delete `multiqc/multiqc_data/` before re-running (AT-D7).
