# nf-core/mhcquant 3.2.0: Depictio dashboards

One dashboard: an **Overview**, then child tabs in three groups, read as a funnel from the
spectra to the peptides each sample presents. The template follows the family rules in
`depictio/projects/nf-core/RULES.md` (ampliseq 2.18.0 is the reference implementation).

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | Did the search identify peptides evenly across samples? |
| Data & QC | Reproducibility | Do the replicate injections of a sample quantify the same peptides? |
| Search | Identification | How many spectra became peptides, and at what FDR? |
| Search | Physico-chemical checks | Do the identified peptides elute and ionise as peptides should? |
| Immunopeptidome | MHC signature | Which MHC class do the peptide lengths and anchor motifs point to? |
| Immunopeptidome | Peptides and proteins | Which peptides do conditions share, and which proteins do they come from? |

mhcquant identifies MHC-presented peptides from immunopeptidomics mass-spectrometry runs:
Comet searches every raw file, MS2Rescore and Percolator rescore the matches, OpenMS filters
them at the requested FDR, links features across the replicates of a sample and writes one
peptide table per sample. The template reads that table, the Comet pin files that precede
rescoring, the fragment-ion annotations and the MultiQC report.

The design comes from the samplesheet (`samples`): one row per raw file with its sample, its
condition (`GROUP_COL`, `Condition` by default) and its search database. Every filter starts
there: the links carry a pick to every sample-level table by `sample_id` and to the Comet
tables by `run_id`.

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `samples` | the samplesheet (`METADATA_FILE`, default `input/samplesheet.tsv`) | raw file |
| `multiqc_data` | `multiqc/multiqc_data/multiqc.parquet` | MultiQC sample |
| `mhcquant_peptides` | `<Sample>_<Condition>.tsv` at the output root | sample and precursor |
| `mhcquant_fragment_ions` | `intermediate_results/ion_annotations/*_matching_ions.tsv` | sample and peptidoform |
| `mhcquant_replicate_intensity` | the `intensity_<k>` columns of the peptide tables | sample, peptidoform, replicate |
| `openms_comet_psms`, `openms_comet_fdr_curve` | `intermediate_results/comet/*_pin.tsv` | raw file |

mhcquant does not publish the samplesheet it ran on, so the template ships the test_full sheet
under `input/` and reads it by default; point `METADATA_FILE` at the sheet of another run.
Derived collections (sample summary, length distribution, composition, motif matrix, replicate
pairs and detection, source proteins, condition sharing) are recipes over the peptide table.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `METADATA_FILE` | `{DATA_ROOT}/input/samplesheet.tsv` | samplesheet read by `samples` |
| `METADATA_ID_COL` | `ID` | samplesheet id column |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | `Condition` | group filters, the Samples card and the group colours |
| `NO_QUANTIFICATION` | unset | set for runs without `--quantify`: drops the replicate collections |
| `NO_ION_ANNOTATION` | unset | set for runs without `--annotate_ions`: drops the fragment-ion collection |

The CLI's metadata auto-detection picks the first non-id sheet column as `GROUP_COL`, so pass
`--var GROUP_COL=Condition` (or keep `Condition` second in the sheet).

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the samples and raw files
  (from the samplesheet), the enzyme, the FDR threshold, the peptide length bounds and the
  rescoring engine (from the run parameters).
- **Pipeline**: six steps (search, rescore, filter, quantify, profile, compare). Each step
  opens the parameters that drive it and the tab that shows its output.
- **Key figures**: four headline cards, each opening the tab that explains it. Samples
  (split by condition), the PSMs that passed the FDR filter (the box shows the spread per
  sample), the distinct peptide sequences (split by length) and the median identification
  rate of the raw files (the box shows its spread). A condition and a sample filter above
  them narrow these four only.
- **Findings**: result rows computed under the filters, each with a link to its tab: the
  distinct sequences that passed the FDR filter, the median gap to the predicted retention
  time, the most common peptide length and its share, and the source proteins with the
  median number of peptides each gives. Below them, four figures in two rows: the accepted
  PSMs against the FDR threshold beside the observed against predicted retention time, then
  the length profile beside the source proteins. The FDR curves, the length profile and the
  protein scatter draw one series or colour per raw file or sample, so their highlights hide
  the legend; the protein scatter labels only the three proteins that give the most
  peptides, so the labels stay apart at half width. The bar of this section filters by condition and peptide length.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (condition, sample, raw file) sit in the collapsed left
panel and narrow every tab. The `Sample sheet` and `Reference tables` (the per-sample
summary) sections are pinned to the bottom of every child tab, collapsed, and absent from
the Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to read
the tab), then a strip of four key numbers, each card with its own colour and a secondary
that reads it, then at most three open sections; tables and record cards follow, collapsed.

**MultiQC.** MultiQC panels only. Open: identification counts, q-value and Xcorr
distributions, then precursor m/z, retention time and peptide intensity. Collapsed: the
total ion chromatograms, the fragment mass error and the Percolator feature weights. Its
own sample filter reads the MultiQC report.

**Reproducibility.** Strip: replicates per peptide (its distribution), peptide detections
split by replicate (a ring), the median log10 intensity (its spread) and the peptides
quantified in both replicates of a pair, split by pair. Then the intensity scatter for
every replicate pair and the UpSet of the replicate combinations each peptide was
quantified in. Collapsed: the replicate membership table. Filters: replicate pair and the
number of replicates a peptide was detected in. The per-sample replicate correlations and
completeness are columns of the pinned per-sample summary.

**Identification.** Strip: spectra searched, as a funnel to the target matches and the PSMs
accepted at 5% and 1% FDR; the identification rate per raw file (its distribution); the PSMs
that passed the pipeline's filter (their spread per sample); the accepted precursors, split
by modification. Then the accepted target PSMs against the q-value threshold, one curve per
raw file, and the score of the accepted peptides by sample. Collapsed: the Comet search
table. Filters: a peptide score range and a PSMs-per-peptide range.

**Physico-chemical checks.** Strip: the retention-time error per sample, the precursor mass
error per raw file, the correlation with the MS2PIP-predicted spectrum and the precursors
split by charge. Then the observed against DeepLC-predicted retention time, with the record
of a picked peptide beside it, and, side by side, retention time against Kyte-Doolittle
hydropathy and precursor m/z over the gradient by charge. Collapsed: the fragment-ion cards
(mass error, matched ions) and table, absent on a run without `--annotate_ions`. Filters:
precursor charge and a retention-time range.

**MHC signature.** Strip: the 9-mer share per sample, the median peptide length (its spread
over the peptides, since every sample of a class I run has the same median), and the distinct
sequences ranked by their P2 and C-terminal residues, the two class I anchors. Then the
length profile with the class I (8 to 12) and class II (13 to 25) ranges shaded, the
composition per sample by length (switchable to charge and modification; the eight largest
categories), and the positional amino-acid heatmap per sample and length for reading
anchor motifs, bound to the twenty residue columns only (the matrix's `peptides` count
would flatten the frequency scale). Collapsed: the length table. Filters: peptide length and modification, which
also narrow the length profile and the motif heatmap through the project links.

**Peptides and proteins.** Strip: the distinct sequences split by condition sharing,
peptides per source protein (its distribution), the protein intensity (its spread) and the
source proteins per peptide (the precursors mapping to one protein against the shared
ones). Then the UpSet of the conditions each sequence was identified
in, and the source proteins by the peptides they give against their intensity (a click
selects the protein). Collapsed: the peptide table with its record card, and the protein
table with its record card; each card opens on the selected row. Filters: condition sharing
and a peptides-per-protein range.

## Routes and pruning

| Route | What changes |
|---|---|
| No `--quantify` (`NO_QUANTIFICATION`) | No Reproducibility tab: every tile of it binds a replicate collection. The replicate columns of the per-sample summary stay empty. |
| No `--annotate_ions` (`NO_ION_ANNOTATION`) | No Fragment ions section on Physico-chemical checks. |
| One condition | The sharing split and the UpSet of Peptides and proteins show a single set. |

The Overview's Key figures read collections every route writes, so a route never leaves a
gap in the strip. An unresolved tab link in the steps (Reproducibility, without
`--quantify`) is drawn as plain text.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: the condition
is coloured `auto` (each value takes a colour-blind-safe colour at import, kept on a
re-import); peptide lengths are coloured `auto:peptides`, the most common lengths first;
the length windows, the modification state and the condition sharing are written out;
charge states, replicates and replicate pairs are coloured `auto`.

## Cross-selection

Tables and scatters emit a selection on their entity column, and the selection narrows every
other tile that reads the same collection or a collection linked from it:

- The sample sheet selects on `sample_id`, which the links carry to every collection and to
  the MultiQC panels; the pinned per-sample summary selects on `sample`.
- The Comet table selects raw files (`run_id`), the replicate membership table peptides.
- The peptide table and the three scatters of Physico-chemical checks select on `sequence`,
  which also reaches the condition-sharing collection. The source-protein scatter and table
  select on `protein`; the fragment-ion table on `peptide`.
- A record card sits beside the table or scatter that drives it and waits for a picked row
  or point.

## Methods and assumptions

- **Peptide rows.** The peptide table has one row per precursor (peptidoform and charge).
  Counts of peptides use distinct sequences or peptidoforms; replicate intensities are
  summed over the charge states of a peptidoform.
- **Replicate order.** The `intensity_<k>` columns carry no file name. The template assumes
  column `k` is the raw file ranked `k+1` by samplesheet `ID` within its sample, the order
  the files enter feature linking. Pair and replicate labels follow that assumption.
- **Comet FDR.** `openms_comet_*` apply target-decoy competition on Xcorr to the pin files,
  before MS2Rescore and Percolator, so they describe the raw search, not the final FDR. The
  identification rate is the PSMs at 1% FDR over the spectra searched.
- **Length windows.** Class I is 8 to 12 residues and class II 13 to 25. The pipeline's own
  length filter (`peptide_min_length`, `peptide_max_length`) bounds what can appear.
- **Motifs.** Frequencies are over distinct sequences of one length in one sample; lengths
  with fewer than 20 sequences are left out.
- **No binding predictions.** 3.2.0 no longer runs MHCflurry or other binders, so there is
  no binder-rank view.
