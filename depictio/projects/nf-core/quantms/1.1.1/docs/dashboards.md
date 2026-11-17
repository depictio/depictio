# nf-core/quantms 1.1.1: Depictio dashboards

One dashboard: an **Overview**, then child tabs in two groups, read as a funnel from the
spectra to the proteins that change between conditions. The template follows the family rules
in `depictio/projects/nf-core/RULES.md` (ampliseq 2.18.0 is the reference implementation).

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | Acquisition | Were the runs acquired alike? |
| Data & QC | Identification | How many precursors did each run identify, and how clean are they? |
| Quantification | Proteins | Which protein groups were quantified, and how completely? |
| Quantification | Reproducibility | Do the runs of a condition agree, and do the conditions separate? |
| Quantification | Differential abundance | Which proteins change between conditions, and can the test tell? |

quantms quantifies proteins from mass-spectrometry runs in three modes: data-dependent
acquisition with label-free quantification, isobaric labelling, and data-independent
acquisition (DIA). This template reads the **DIA** route: every raw file is converted to
mzML, DIA-NN matches the spectra to a spectral library and quantifies the protein groups, and
MSstats tests the conditions against each other. The other two routes write other tables and
need their own template.

The design comes from the SDRF the run was started with, which quantms parses into
`sdrfparsing/` (runs, sample, MSstats condition, acquisition settings). The `samples` hub
reads those two files, so the template needs no SDRF to run; the SDRF named by
`METADATA_FILE` only adds its characteristics columns (organism, instrument and so on). The
condition (`GROUP_COL`, `condition` by default) is the MSstats condition, written as a
readable label. Every filter starts from the hub: the links carry a pick to every run-level
table by `run_id` and to the per-condition tables by the condition column.

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `samples` | `sdrfparsing/*_openms_design.tsv`, `sdrfparsing/*_config.tsv`, the SDRF (`METADATA_FILE`) | run |
| `quantms_precursors` | `diannsummary/diann_report.tsv` | run and precursor |
| `quantms_proteins` | `diannsummary/diann_report.pg_matrix.tsv`, joined to the precursors | run and protein group |
| `quantms_acquisition`, `quantms_acquisition_profile`, `quantms_ms2_peak_bins` | `mzmlstatistics/*_mzml_info.tsv` | run, run and minute, run and peak bin |
| `quantms_comparisons` | `msstats/*comparisons.csv` | contrast and protein group |

Derived collections are recipes over those tables: the run summary, the protein summary (one
0 or 1 column per run, the run-membership matrix), the per-condition protein statistics, the run
projection and correlation, and the replicate pairs. They are declared after the collections
they read, which is the order of ingestion.

There is no MultiQC collection. quantms 1.1.1 reports through pmultiqc custom content, which
has no MultiQC module and no `multiqc.parquet`; the plots of that report are rebuilt here from
the result tables.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `METADATA_FILE` | `{DATA_ROOT}/input/sdrf.tsv` | SDRF read by `samples` for its characteristics columns (optional) |
| `METADATA_ID_COL` | `run_id` | hub id column, recorded only |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | `condition`, `Condition` | group filters, the Runs card and the group colours |

Leave `GROUP_COL` at `condition`: the contrast means, the condition correlation and the
replicate pairs are built per condition, and the MSstats comparison compares MSstats
conditions whatever column the dashboard groups by.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the runs and conditions (from
  the design) and the acquisition method, enzyme, tolerances and search database (from the run
  parameters, a dash when the run published none).
- **Pipeline**: five steps (acquire, identify, quantify, compare runs, test). Each step opens
  the parameters that drive it and the tab that shows its output.
- **Key figures**: four headline cards, each opening the tab that explains it. Runs (split by
  condition), the protein groups per run (its spread), the median variation of a protein
  between replicates (a threshold at 20 %, a warning from 30 %; the strip counts the groups at
  20 % or less) and the significant proteins, split by direction. A condition and a run filter
  above them narrow the first three.
- **Findings**: result rows computed under the filters, each with a link to its tab: the
  distinct precursors, the protein groups quantified, the protein groups quantified in every
  run, the median variation between replicates (under 20 % is tight) and the proteins that
  change significantly out of those tested. Below them, four figures in two rows: the run
  projection (the runs of a condition should sit together) beside the variation against
  abundance of every protein group, then the volcano beside the p-value histogram, each with a
  caption on how to read it (nothing beyond the cut-offs on the volcano and a flat histogram
  say that no protein changed enough and the test is calibrated). Acquisition and
  identification quality stay on their tabs. The bar of this section filters by condition and
  run; the significant-protein count reads the MSstats table, which the run filter does not
  reach.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (condition, run) sit in the collapsed left panel and narrow
every tab. The `Sample sheet` and `Reference tables` (the per-run summary) sections are pinned
to the bottom of every child tab, collapsed, and absent from the Overview.

## Child tabs

Each child tab opens with a short intro (what the step does and how to read the tab), then a
strip of four key numbers, each card with its own colour and a secondary that reads it, then
at most three open sections; tables and record cards follow, collapsed.

**Acquisition.** Strip: MS2 spectra (the spread per run), the gradient length, the median
peaks per MS2 spectrum and the MS2 rate per minute. Then the MS2 spectra per minute and the
median MS2 base-peak intensity per minute, one curve per run, and the share of MS2 spectra by
the number of peaks they hold. Runs of one experiment are expected within about 5% of the
median on the gradient and the MS2 rate. Collapsed: the spectra summary of every run. Filter: a
retention-time window for the two gradient profiles.

**Identification.** Strip: precursors (split by charge), distinct peptides (split by
modification), protein groups per run and the identification yield per thousand MS2 spectra.
Then one per-run quality view, the weakest run on top: the deviation from the median of the
runs, in percent, of the precursors, yield per thousand MS2 spectra, modified share and
missed-cleavage share, each bar coloured by condition and a grey band within 10% of the median (a rule of thumb of this dashboard, named in the legend and the description) (the runs are
labelled by condition and replicate, from the hub's `run_label`); the gap between observed
and library-predicted retention time along the gradient, coloured by condition (a density view
above a point threshold); and the peptide length
(each of the unmodified and modified series as a share of its own total) and the DIA-NN
evidence score per run as a violin. Collapsed: the precursor table (the run summary is a pinned reference table).
Filters: modification, charge and peptide length.

**Proteins.** Strip: completeness (the median share of the runs that quantified a group, a
threshold at 100% with a warning from 80%; the strip counts the groups quantified in every
run), peptide support (a ring), peptides per group (its distribution) and the abundance of the
groups (a box). Then the variation between runs against abundance for every group: one series, a dashed line at a coefficient of variation of 20 % (the threshold of the Variation card) that dims the points under it, the eight most variable groups above it labelled by gene, and a density past 2000 groups. Collapsed:
the protein groups missed in some runs, by how many runs quantified them (stacked by peptide
support, with the groups seen in every run counted in a note) beside the abundance of those
groups, which show one bar on a complete experiment, and the protein-group table with its record card, which opens on the
selected row and links the UniProt entry. Filters: detection,
peptide support and a variation range.

**Reproducibility.** Strip: protein groups quantified per condition, the variation within a
condition, the variance the first component explains and the protein groups paired between
runs; the first component's card says it is high when the first axis is the condition. Then
the run projection (a lasso filters the linked panels), the difference between two runs
against their mean for every replicate pair (a dotted zero line and a grey band within a twofold
change, both labelled in the plot, coloured by condition), and the variation within each condition as a violin (with its
box), where under 20 is tight and over 30 noisy. Collapsed: the clustered run correlation
(replicates correlate above 0.95, so its colours differ little) and the per-condition table. Filters: replicate pair and a variation range.

**Differential abundance.** Strip: the median effect size, the smallest adjusted p-value (with
the distribution of all of them), the median standard error and the proteins called
significant, split by direction. Then the proteins called Up and Down in each contrast (grouped
bars with the number tested in brackets), the volcano with its MA and QQ views (a dashed line at an
adjusted p of 0.05 and two at log2 fold changes of -1 and 1, the usual significance level and the
usual minimum effect for label-free proteomics; both are the dashboard's cut-offs, MSstats reports
the adjusted p-value only), the p-value histogram (twenty bins; with one contrast the first one
is coloured as the proteins below 0.05, with several the bars are stacked and coloured by
contrast; a dashed line at the level a bin would hold if no protein changed, and a note with the
count below 0.05, the count expected by chance and the estimated share of unchanged proteins)
and the fold-change histogram. Collapsed: the MSstats table with its record card.
Filters: contrast, direction, effect size and missing values.

## Routes and pruning

| Route | What changes |
|---|---|
| DDA label-free or isobaric labelling | Not covered: those routes write other result tables. |
| One condition | No contrast: the MSstats table is empty, the Differential abundance tab shows empty panels, and the projection and correlation show a single group. |
| No replicates | The replicate pairs and the per-condition variation are empty. |

A run that made no significant call leaves the volcano, the calibration histograms and the
tables intact; only the significant-protein card and the Findings row read zero.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: the condition is
coloured `auto` (each value takes a colour-blind-safe colour at import, kept on a re-import);
the call direction, the modification state, the detection class, the peptide-support class
and the specificity are written out; charge states and replicate pairs are coloured `auto`.

## Cross-selection

Tables and scatters emit a selection on their entity column, and the selection narrows every
other tile that reads the same collection or a collection linked from it:

- The sample sheet selects on `run_id`, which the links carry to every run-level collection;
  the pinned run summary selects on `run_id` too.
- The protein tables and the variation scatter and the volcano select on `protein_group`;
  a protein picked in the MSstats table also reaches the protein summary.
- A record card sits beside the table that drives it and waits for a picked row or point.

## What the run publishes for differential abundance

Audit of the result folders of the DIA mode: `msstats/*_comparisons.csv` is the only test
output, one row per protein and contrast (log2 fold change, standard error, t value, degrees of
freedom, p-value, adjusted p-value, missing and imputed share, `issue`), and the template
reads all of it (`quantms_comparisons`). `diannconvert/*_msstats_in.csv` is the MSstats input
(precursor and fragment intensities per run, the long table behind the quantities) and
`*_triqler_in.tsv` the Triqler input; neither holds a test, and the run does not publish
Triqler results, so neither feeds the tab. The test run publishes a single contrast (two
conditions, four runs), so the per-contrast views read one contrast there: the calls-per-contrast
bars show one Up and one Down bar, and the p-value histogram keeps its single colouring. A run
with several contrasts gets one pair of bars per contrast and a histogram stacked by contrast
(the stacked path was exercised on a synthetic table, not on a live run). The volcano draws the
points of every contrast in view together, so a multi-contrast run is read one contrast at a time
through the Contrast filter; a facet per contrast needs a volcano option that does not exist yet.

## Methods and assumptions

- **Precursors.** The DIA-NN report has one row per precursor and run, kept at the precursor
  q-value DIA-NN was given. Peptide counts use distinct stripped sequences, precursor counts
  use distinct modified-sequence and charge pairs.
- **Missed cleavages** count a K or R inside the sequence that is not followed by P (the
  trypsin rule); the figure says little for another protease.
- **Protein quantities.** `quantms_proteins` takes the normalised protein-group matrix; its
  peptide and precursor counts come from the report. A group is quantified in a run when the
  matrix holds a value there.
- **Completeness.** `detected_pct` of the protein summary is the share of the runs that
  quantified a group, in percent; 100 is a group quantified in every run.
- **Variation.** The coefficient of variation is the standard deviation over the mean of the
  linear quantity, over the runs of a condition that quantified the group, in percent. It
  needs at least two runs.
- **Projection.** The run projection is a principal-component analysis of the log2 quantities
  of the protein groups quantified in every run; with few runs it has few components.
- **Correlation.** Pearson, over the protein groups both runs quantified.
- **Calls.** `direction` marks a protein Up or Down at an adjusted p-value below 0.05 and an
  absolute log2 fold change of at least one. MSstats flags proteins it could not test
  (`issue`); they carry no p-value and never get a call. The fold change is the first
  condition of the contrast over the second.
- **Retention time.** DIA-NN reports it in minutes; the mzML spectrum table reports seconds,
  which the acquisition recipes convert to minutes.
- **No mass error.** The DIA-NN version in this release does not report a mass error, so the
  Identification tab has no mass-accuracy view.
