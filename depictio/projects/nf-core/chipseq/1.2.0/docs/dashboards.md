# nf-core/chipseq 1.2.0: Depictio dashboards

This template turns the output of [nf-core/chipseq](https://nf-co.re/chipseq) 1.2.0 into a
single six-tab Depictio dashboard. chipseq aligns ChIP and input libraries, filters and
deduplicates them, calls peaks per sample with MACS2, annotates those peaks with HOMER, merges
them into one consensus peak set per antibody and finally tests each consensus interval for
differential binding with DESeq2. The dashboard follows that chain from left to right.

Data comes from the AWS megatest run
`results-048fd6854fcc85b355c61dfc2e21da0bcc6399ea` (the 1.2.0 release tag): sixteen human
libraries, EZH2 ChIP in NTKO and TKO cells and FOXA1 ChIP in E2 and VEH treated cells, two
replicates each, every ChIP against its own input control.

> **This template reads a REPROCESSED MultiQC report.**
> chipseq 1.2.0 is a DSL1 pipeline and this run published MultiQC 1.9, which writes
> `multiqc_data.json` and no parquet. Depictio reads only `multiqc.parquet` (MultiQC 1.31 and
> later), so the MultiQC tab is bound to a report this repository generates by re-running the
> pinned MultiQC 1.35 over the run's own raw tool outputs. The published 1.9 report is not
> used. Its anchors and plot names differ from the 1.35 ones the template is authored
> against, so never copy a `selected_plot` out of the published HTML report: read it from
> `multiqc.list_plots()` on the regenerated parquet. See the Reproducing section below and
> `VALIDATION_REPORT.md`.

---

## How the dashboard is built

- **One funnel, five tabs.** MultiQC, then Signal, then Peaks, then Consensus, then
  Differential binding. Each tab answers the question the previous one raises: are the
  libraries good, is each ChIP enriched over its own input, what did MACS2 call in each
  sample, which of those calls the replicates agree on, and which of the agreed intervals
  change between conditions.
- **The hub is every library, with its factors as columns.** `pipeline_info/design_controls.csv`
  names the eight ChIPs, their input controls and their antibodies, and nothing else: the
  conditions the run exists to compare live only inside the sample names, and the eight input
  libraries appear in no row at all although every QC collection carries them. The `design`
  collection is therefore a recipe (`nf-core/chipseq/design_factors.py`) rather than a plain
  scan. It emits one row per library, sixteen in this run, with `role` (ChIP or input control),
  `antibody`, `condition` and `replicate` parsed out of the names. The persistent
  `Sample filters` section pinned to the top of every tab exposes all four, role included,
  so NTKO against TKO and E2 against VEH are selections rather than facts buried in a string
  and the input controls can be dropped or kept with one pick.
- **The persistent filters reach every tab.** The project links fan a pick out to the MultiQC
  panels, the peak table, the peak QC summary, the HOMER annotation and the signal
  collections on the sample name. The consensus sets and the DESeq2 contrasts have no sample
  column by construction, so the antibody filter reaches them through a `wildcard` resolver
  instead: `EZH2` matches the `EZH2_IP` consensus set and the `EZH2_IP_NTKOvsEZH2_IP_TKO`
  contrast.
- **A glance strip on every tab.** `Cohort at a glance` is a pinned persistent four-card strip:
  libraries split by role, conditions as a top-4 breakdown, peaks called with a top-3
  breakdown by sample, and the FRiP score as a Tukey box plot. Four different breakdowns on
  purpose. Every other tab opens on its own four-card strip below it, and the collapsed
  `ChIP design` and `Reference tables` sections follow the viewer from tab to tab.
- **Peak-level selection, both ways.** The manhattan panel on the Peaks tab carries
  `selection_enabled` on `peak_id`, and both peak tables carry `row_selection_enabled` on the
  same column. Lassoing peaks there narrows the tables, ticking rows in a table narrows the
  panels, and the project links carry the selection between the MACS2 and HOMER collections.
  A consensus interval carries the same way to and from its DESeq2 row.
- **Catalog provenance.** 62 of the 65 panel tiles carry a `use:` catalog reference, so the
  tile chrome says where the panel comes from: `macs2/*` for the peak and consensus panels,
  `homer/annotated_peaks` for the annotation panels, `deseq2/*` for the differential binding
  and sample-space panels and `multiqc/<module>` for the QC panels, including the four
  pipeline custom-content sections that had no catalog stub. The three without one read the
  `design` hub, which is a pipeline-local recipe and has no catalog module.
- **Everything matches on file name.** No data collection or recipe glob spells out the
  `bwa/mergedLibrary/macs/narrowPeak/` prefix, so a run aligned with a different aligner lands
  in the same collections. The one remaining path-qualified glob, the HOMER annotation
  override, anchors on `mergedLibrary` alone, which is the aggregation level every chipseq
  1.2.0 run publishes, and not on the `bwa/` this particular run happened to write.

---

## MultiQC

The main tab, and the one reading the reprocessed report.

`Run summary` is the MultiQC General Statistics table: one row per library, pooling the
FastQC, Trim Galore, samtools, Picard, MACS2 and phantompeakqualtools headline numbers. It is
the one panel in the report that speaks for the run rather than for a single tool, so it is
what the tab opens on, and the sections below take it apart module by module.

`Read quality` carries FastQC sequence counts and quality histograms and the cutadapt filtered
read bars. Every library appears here under its `<sample>_T<n>` technical-replicate name, so a
sample shows up once per library rather than once per sample.

`Alignment and library complexity` pairs samtools percent mapped with Picard duplication, then
the preseq complexity curve full width, then the featureCounts assignment bars that say how
many reads fall inside the consensus peaks.

`ChIP enrichment` is the tab's point: the deepTools fingerprint curve, which separates an
enriched ChIP from a flat input, next to the FRiP scores, then the strand cross-correlation
plot with the NSC and RSC coefficients derived from it. Those last four are the pipeline's own
custom content rather than a MultiQC module, and they now have catalog stubs
(`multiqc/frip_score`, `multiqc/strand_shift_correlation`, `multiqc/nsc_coefficient`,
`multiqc/rsc_coefficient`), so they carry a `use:` badge like every other panel.

Every tile on this tab reads the report, apart from the pinned `Cohort at a glance` strip and
the pinned design and reference tables, which ride every tab. The panels that read a tool's own
tables instead of MultiQC's rendering of them are on the Signal tab, next to the collections
they come from.

The left panel adds a collapsed, tab-local `Library scope` filter. The FastQC and Trim Galore
panels are keyed on the sequencing library (`<sample>_T<n>`), a finer grain than the merged
sample every other tab works in, so `design_reads` reaches the report on its own key.

![MultiQC](screenshots/sequencing-qc.png)

## Signal

preseq, plotFingerprint and plotProfile each write a per-sample table beside the curve MultiQC
renders. This tab reads those tables.

`Signal at a glance` is a four-card strip on them: coverage concentration as a Tukey box plot,
the mean divergence from the input on a gauge, the share of the genome called enriched as a
histogram, and the strongest metagene signal with a top-3 breakdown by sample.

`Library complexity` is `use: preseq/complexity_ribbon`, which adds the 95% confidence band
MultiQC drops, so a library whose extrapolation is guesswork is visible as a ribbon that fans
out rather than as a line that looks as certain as any other.

`Coverage concentration` is `use: deeptools/fingerprint_scatter`, deepTools' own QC scatter:
the share of the genome called enriched against the Jensen-Shannon distance to the input,
point size the differential enrichment and colour how concentrated the coverage is against a
uniform library of the same depth. Both axes need `--JSDsample`, so only the IP libraries
carry a point; the inputs are the reference each IP is compared against.

`Metagene signal` is `use: deeptools/metagene_profile`, the `plotProfile` matrix as one curve
per library with the TSS marked at bin 300 and the scaled gene body shaded.

Clicking a curve or a point on any of those three panels filters the dashboard to that
library. The tab-local `Signal scope` filter adds two range sliders on the tab's own
collections: the share of the genome called enriched, and the extrapolated sequencing depth.

## Peaks

`Peak yield` is a four-card strip on the peak table: peaks in view with a top-3 breakdown by
sample, peak width as a box plot, fold enrichment as a histogram, and median -log10 q against
a threshold. Under it, `use: macs2/peak_summary` draws the FRiP score per sample as a bar
chart, the fraction of each library's mapped reads that fall inside its own peaks.

`Significance along the genome` puts every peak at its summit position with -log10 of the
MACS2 q-value as height, coloured by sample. It is the tab's selection source: lasso a region
and the peak ids travel to the tables below and, through the project links, to the HOMER
annotation. Beside it, a volcano of the same significance against fold enrichment over input,
with the q 1e-10 and five-fold lines drawn and the peaks past both drawn large (`views:
[volcano]`: a peak call has no mean abundance and no uniform null, so the MA and QQ views are
not offered); and a
peak-width histogram per sample, which is what separates a sharp transcription-factor profile
from a broad histone mark.

`Around the summits` binds the `macs2/summit_profile` catalog output (added in wave 2b). The
canonical ChIP figure here is a read-coverage metagene around the summits, and it cannot be
built from this run: `computeMatrix` is not published as a table and the bigWigs are not in
the megatest mirror. What the narrowPeak files do carry is every call's interval and summit,
so the recipe sets each summit at 0 and aggregates the calls themselves in 50 bp bins across
4 kb. The first profile counts the summits the OTHER samples called around each summit, per
anchor and per kb, on a log axis: replicates of a sharp factor pile their summits onto each
other (FOXA1 here, a spike about a hundred times the flanks), while a broad mark agrees far
less sharply (EZH2, a few-fold spike). The second is the share of the sample's own calls
still covering each offset, the average footprint of a call; where it crosses one half is the
median half-width. Neither is a coverage signal, and the tile text says so.

The genome view and coverage track that used to sit in a `Peak landscape` section here moved
to the Locus tab: binding both on `macs2_peaks` on one tab is what the
`test_no_double_track_binding` lint forbids, and the locus navigator's region filters would
have narrowed this tab's genome-wide cards and Manhattan to one locus.

`Where the peaks land` reads the HOMER annotation: cards for annotated peaks by feature class
(donut), genes touched (composition by class), distance to TSS (box plot) and peak score
(histogram); the feature-class composition of each sample as a percentage stacked bar
(`barnorm: percent`, so libraries with 7 000 and 66 000 peaks compare directly); and a code-mode histogram of the
signed distance to the nearest TSS, clipped to a 10 kb window and split by feature class, with
the TSS marked. The raw column runs to several hundred kb, so without the window the peak at
zero flattens out. Under it, `use: homer/tss_distance` reads the same distances pre-binned
by the recipe, one curve per sample as a share of that sample's peaks: the histogram pools
samples and splits by class, the profile does the opposite, and being a share rather than a
count is what lets libraries of different depth be compared.

`Peak tables` (collapsed) holds the HOMER annotation table and the MACS2 call table, both with
row selection on `peak_id`.

The left panel adds a `Peak scope` group (q-value, fold enrichment and width range sliders,
plus a chromosome multi-select) and a collapsed `Annotation scope` group (feature class,
distance to TSS). Every range slider on the dashboard draws the distribution of its column
above the handles (`show_histogram: true`).

![Peaks](screenshots/peaks.png)

## Locus

The locus section: one navigator, and the tracks under it follow its region. The navigator
(`use: macs2/peak_genome_view`, controls in the tile header) draws every MACS2 call as a
rectangle, one lane per library, and opens on `default_region: chr21:43,600,000-44,000,000`,
the TFF1 neighbourhood, where all eight libraries called peaks and both consensus sets hold
intervals. TFF1 is the textbook FOXA1 and oestrogen target, so the FOXA1 E2 lanes are dense
at its enhancer and promoter. A locus typed in the header or a brush on the axis emits a
chromosome and a position filter on `macs2_peaks`; two `region` links in `template.yaml`
rename that pair onto `macs2_consensus_boolean` and `homer_annotated_peaks`, so the tracks
below show the same region:

- `Consensus intervals per antibody`: a `coverage_track` on the consensus boolean matrix, one
  lane per consensus set, height the number of libraries calling the interval.
- `Peaks by nearest gene and feature class`: a second `genome_view` on the HOMER annotation,
  `follow_region_filter: true`, coloured by feature class with the nearest gene on hover.

The run is hg19 (HOMER places the TFF1 promoter peak at -173 bp from the hg19 TSS), and the
bundled gene lane exists only for hg38 and mm10, so the navigator sets `assembly: hg19` and
draws no gene lane; gene-symbol search in the locus field is therefore unavailable, only
coordinates. The HOMER track stands in for the gene lane. There is no read-coverage track:
the bigWigs are not in the megatest mirror.

`Region at a glance` recounts the region in view on every move: peaks with a top-3 by
library, their mean fold enrichment, the consensus support of the intervals as a box plot and
the number of distinct nearest genes split by feature class. The tab-local `Locus scope`
carries the chromosome, a q-value slider, the consensus support and the HOMER feature class.

This is a tab of its own rather than a section of Peaks because the navigator's region
filters narrow every tile of the tab they sit on.

![Locus](screenshots/locus.png)

## Consensus

`Consensus at a glance`: intervals per consensus set with a top-3 breakdown, samples per
interval as a box plot, peaks merged as a histogram, and the reproducibility tiers of the
strongest intervals as a donut. The fourth card used to break down by consensus set as well,
which made three of the four say the same thing.

`Replicate agreement` is an UpSet of the eight per-sample presence columns: each bar is a
combination of samples calling exactly the same set of intervals. Pick a single antibody in
the left panel first, because the combinations of one consensus set never meet those of the
other and reading both at once is meaningless.

`Signal at the strongest intervals` is a clustered complex heatmap of MACS2 fold enrichment,
log1p scaled, rows annotated by consensus set and support. It plots the 250 most strongly
bound intervals of each consensus set rather than all 153891, because a heatmap draws one row
per interval. A cell is zero where that sample called no peak, so condition-specific binding
reads as a block rather than as scattered gaps.

`Consensus tables` (collapsed) holds the boolean matrix and the fold-enrichment matrix, both
with row selection on `peak_id`, linked to each other in both directions and, on
`interval_id`, to the DESeq2 rows on the next tab.

The tab-local `Consensus scope` filter carries the consensus set, the number of samples backing
an interval and the chromosome.

![Consensus](screenshots/consensus.png)

## Differential binding

`Differential binding at a glance`: intervals tested broken down by contrast, direction of
change as a donut, log2 fold change as a box plot, and the strongest -log10 padj against a
significance threshold. The first card used to break down by direction as well, which the
second one already answers.

`Sample space` comes before any interval is read. `deseq2_qc.r` writes the principal components
and the sample-to-sample distance matrix of the count matrix it tested, and the published
MultiQC report renders both as pictures; here they are data. `use: deseq2/qc_pca_embedding`
places every library in the space of the consensus counts, coloured by consensus set, and
`use: deseq2/qc_distance_heatmap` clusters the Euclidean distances on DESeq2 rlog values.
Where the replicates of a condition sit together and the two conditions sit apart, the contrast
below is measuring the condition; where they interleave, it is measuring the batch.

chipseq publishes one count matrix, and therefore one PCA and one distance matrix, PER
ANTIBODY. The distance matrix is consequently block diagonal, because a pair drawn from two
different antibodies was never compared. The PCA needs a pipeline-local recipe
(`nf-core/chipseq/deseq2_qc_pca.py`) for the same reason: the catalog recipe maps component
columns to the embedding axes by position on the concatenated frame, and the two files spell
different variance percentages into their headers, so a plain concatenation spreads two
matrices over four columns and leaves half the cohort off the plotted axes. The local recipe
resolves the components per matrix and keeps the catalog output's column names, so the tile
still binds the catalog render.

`Volcano, MA and QQ` is one `volcano` tile with the view switch in its header (`views:
[volcano, ma, qq]`, `controls_placement: header`). The volcano puts -log10(padj) against log2
fold change with the padj 0.05 and two-fold lines drawn; the MA view puts effect size against
log2 mean normalised count, where the low-count intervals fan out on the left; the QQ view
compares the observed p-values with the uniform null. These were three tiles on the retired
`ma` and `qq` kinds.

`Direction` is a ranked bar chart of the 25 intervals with the largest significant effect.

The PCA tile carries its colour-by and axis pickers in the tile header.

`Differential tables` (collapsed) holds the DESeq2 rows with row selection on `gene_id`.

Pick a single contrast in the left panel before reading any of these panels. DESeq2 names
consensus intervals `Interval_1 ... Interval_N` and the numbering restarts in each consensus
set, so `gene_id` identifies an interval only together with its contrast; the `Contrast`
filter is a single-choice `Select` for that reason.

---

![Differential binding](screenshots/differential-binding.png)

## Catalog modules

| Module | Outputs | Renders as |
|---|---|---|
| `depictio/catalog/macs2/` | `peaks`, `broad_peaks`, `peak_summary`, `consensus_boolean`, `consensus_fc`, `summit_profile` | manhattan, genome view, coverage track, volcano, UpSet, complex heatmap, 2 profiles, 3 figures, 5 tables, 16 cards |
| `depictio/catalog/homer/` | `annotate_peaks`, `tss_distance_profile` | profile, 3 figures, 7 cards, table with row selection |
| `depictio/catalog/preseq/` | `complexity_curve` | profile with a confidence ribbon, figure, 4 cards, table |
| `depictio/catalog/deeptools/` | `fingerprint_metrics`, `plot_profile` | scatter (X/Y), profile, 2 figures, 7 cards, 2 tables |
| `depictio/catalog/deseq2/` (reused) | `results`, `qc_pca`, `qc_sample_dists` | volcano, MA, QQ, DA barplot, embedding, complex heatmap, 4 cards, figure, 3 tables |
| `depictio/catalog/multiqc/` | `frip_score`, `nsc_coefficient`, `rsc_coefficient`, `strand_shift_correlation` (added here) | one panel each |

`macs2` and `homer` both map to nf-core modules (`macs2/callpeak`, `homer/annotatepeaks`), so
their `module.yaml` carries `nf_core_url` and leaves the rest of the identity to the nf-core
`meta.yml`. `deseq2` comes from the differentialabundance workstream and is used unchanged.

The MultiQC modules this pipeline emits already have catalog entries: `fastqc`, `cutadapt`,
`samtools`, `picard`, `featurecounts` existed, and `preseq` and `deeptools` were added here.
`preseq` and `deeptools` have a standalone tool as well as a MultiQC entry, and the two do
not overlap: the panels are the curves MultiQC redraws from its parquet, the tools read the
tables nf-core publishes beside them, which carry the preseq confidence bounds and the
per-sample fingerprint metrics the panels leave out. See `TEMPLATE_BOTTLENECKS.md`, "What
MultiQC parses but never publishes as data".

`macs` and `phantompeakqualtools` are parsed by MultiQC but expose no plot, only
general-statistics columns, so they get no catalog entry and no panel of their own; they
reach the dashboard through the General Statistics table alone.

chipseq's own custom-content sections are not MultiQC modules, but four of them are written
identically by every pipeline in the nf-core ChIP family and so have catalog stubs now:
`frip_score`, `nsc_coefficient`, `rsc_coefficient` and `strand_shift_correlation`. The last
three come from phantompeakqualtools, which MultiQC parses without exposing a plot, so the
pipeline writes the coefficients itself. The remaining custom-content sections are bound
without a `use:` badge on purpose: `peak_count` and `peak_annotation` duplicate panels the
Peaks tab draws from the peak tables directly, and the DESeq2 PCA and clustering sections
carry a per-antibody numeric suffix the run assigns itself (`deseq2_pca_1`,
`deseq2_pca_2`, …), which is not a portable module name. Those two are bound as DATA instead,
on the Differential binding tab's `Sample space` section.

---

## Reproducing

```bash
# 1. Fetch the megatest subset (399 files, 213 MB, no credentials needed).
bash depictio/projects/nf-core/chipseq/1.2.0/download_test_data.sh
#    -> ~/Data/depictio-nfcore/chipseq/1.2.0/megatest

# 2. REQUIRED. Regenerate the MultiQC report with the pinned MultiQC 1.35.
#    The run published MultiQC 1.9, which ships no parquet, so without this step
#    the multiqc_data collection finds nothing and the MultiQC tab is empty.
python -m depictio.dev_scripts.multiqc_reprocess \
  --src  ~/Data/depictio-nfcore/chipseq/1.2.0/megatest \
  --dest ~/Data/depictio-nfcore/chipseq/1.2.0/megatest
#    -> multiqc/multiqc_data/multiqc.parquet + REPROCESSED.json
#    Check REPROCESSED.json: source_version 1.9, reprocessed_with 1.35, 20 modules.
#    Do not re-run this over a directory that already holds the regenerated
#    parquet: the source-version probe would then read 1.35 back off it.

# 3. Dry run, then the real ingest.
python -m depictio.cli run --template nf-core/chipseq/1.2.0 \
  --data-root ~/Data/depictio-nfcore/chipseq/1.2.0/megatest --dry-run
python -m depictio.cli run --template nf-core/chipseq/1.2.0 \
  --data-root ~/Data/depictio-nfcore/chipseq/1.2.0/megatest
```

Do not pass `--project-name`: the dashboard's `project_tag` is resolved by project name, so
renaming the project breaks a later standalone `depictio dashboard import`. Re-ingesting
accumulates dashboards, so delete the project before repeating a run rather than renaming it.

To check which module and plot names the regenerated report actually offers:

```python
import multiqc

multiqc.parse_logs(
    "~/Data/depictio-nfcore/chipseq/1.2.0/megatest/multiqc/multiqc_data/multiqc.parquet"
)
multiqc.list_plots()
```

This is the list `template.yaml`'s `dc_specific_properties.plots` and every `selected_plot` in
`dashboards/base.yaml` are authored against. It is a MultiQC 1.35 list, and it is not the same
as the section list in the 1.9 HTML report the pipeline published.
