# nf-core/epitopeprediction 3.2.0: Depictio dashboards

One dashboard: an **Overview**, then child tabs in two groups, read as a funnel from the
alleles the peptides bind to the peptides that bind and the tools behind the calls. The
template follows the family rules in `depictio/projects/nf-core/RULES.md` (ampliseq 2.18.0 is
the reference implementation).

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | How many peptides does each tool call a binder? |
| Neoepitopes | Predictions | Which alleles do the peptides bind, sample by sample? |
| Neoepitopes | Peptides | Which peptides bind, and which variant or protein do they come from? |
| Neoepitopes | Predictors | How far do the prediction tools agree on the binders? |

epitopeprediction predicts which peptides bind a sample's MHC molecules. A sample is one of
three inputs: a VCF of somatic variants (annotated with Ensembl VEP, then cut by pVACseq into
every peptide of the requested lengths that overlaps a mutation, with `--wild_type` adding
the wild-type peptide of each missense mutant), a protein FASTA (digested into peptides of
the requested lengths) or a peptide table. Each tool of `--tools` (MHCflurry, MHCnuggets,
MHCnuggets II, NetMHCpan, NetMHCIIpan, MixMHCpred, MixMHC2pred) scores every peptide against
every allele of the sample, and `MERGE_PREDICTIONS` writes one table per sample,
`predictions/<sample>.tsv`.

The design comes from the samplesheet (`samples`): one row per sample with its alleles, its
MHC class and its input file. `input_type` (Variants, Proteins or Peptides, from the input
file's extension) is derived by the hub recipe and is the default `GROUP_COL`. Every filter
starts there: the links carry a pick to every collection by `sample`, and to the MultiQC
panels by sample mapping (the report names its rows `<sample>_<tool>` and `<sample>.prep`).

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `samples` | the samplesheet (`METADATA_FILE`, default `input/samplesheet.csv`) | sample |
| `multiqc_data` | `multiqc/multiqc_data/multiqc.parquet` | MultiQC sample (sample and tool) |
| `epitopeprediction_predictions` | `predictions/<sample>.tsv` | sample, peptide, allele and tool |
| `epitopeprediction_peptides` | the same | sample and peptide |
| `epitopeprediction_allele_summary` | the same | sample and allele |
| `epitopeprediction_predictor_summary` | the same | sample and tool |
| `epitopeprediction_predictor_agreement` | the same (optional) | sample, peptide, allele and tool pair |
| `epitopeprediction_wildtype_pairs` | the same (optional) | sample, mutant peptide, allele and tool |
| `epitopeprediction_variant_peptides` | `variant_peptides/<sample>_length_<k>.tsv` (optional) | sample and peptide |

epitopeprediction does not publish the samplesheet it ran on in this release, so the template
ships the test_full sheet under `input/` and reads it by default; point `METADATA_FILE` at the
sheet of another run. The per-tool directories (`mhcflurry/`, `mhcnuggets/` ...) hold the same
scores as `predictions/`, split by chunk, and are not read; neither is `variant_fasta/`, a
search database for proteogenomics.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `METADATA_FILE` | `{DATA_ROOT}/input/samplesheet.csv` | samplesheet read by `samples` |
| `METADATA_ID_COL` | `sample` | samplesheet id column |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | `input_type`, `Input type` | group filters, the Samples card and the group colours |
| `NO_VARIANT_INPUT` | unset | set for a sheet with no VCF: drops the variant peptides and the mutant / wild-type pairs |
| `NO_WILD_TYPE` | unset | set for a run without `--wild_type`: drops the mutant / wild-type pairs |
| `SINGLE_PREDICTOR` | unset | set for a run with one tool per MHC class: drops the tool agreement |

The three optional collections are also marked `optional` and their recipes fail with a named
reason when they find nothing to pair, so an ingest that meets no input skips them and the
import prunes their tiles even when the variable is not set.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the samples (from the
  samplesheet), the alleles scored (from the predictions), the tools and the class I and
  class II peptide lengths (from the run parameters).
- **Pipeline**: five steps (peptides, lengths, predict, call, compare). Each step opens the
  parameters that drive it and the tab that shows its output; the compare step cites the
  peptides two tools scored and goes with the agreement collection.
- **Key figures**: four headline cards, each opening the tab that explains it. Samples (split
  by input type), peptides (split by binder call), alleles (ranked by locus) and predicted
  binders (split by length). An input-type and a sample filter above them narrow these four
  only.
- **Findings**: result rows computed under the filters, each with a link to its tab: the
  allele called the binder of the most peptides and its share of the binder calls, the share
  of peptides that bind an allele, the mutant peptides that bind where their wild type does
  not, and the share of peptides two tools scored that get the same call from both. Below
  them, four figures in two rows: the allele by sample dot plot beside the length histogram
  stacked by call, then IC50 against percentile rank beside one tool's IC50 against the
  other's. The bar of this section filters by input type and allele.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (input type, sample, MHC class) sit in the collapsed left
panel and narrow every tab. The `Sample sheet` section is pinned to the bottom of every child
tab, collapsed, and absent from the Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool or its
documentation, and how to read the tab), then a strip of four key numbers, each card with its
own colour and a secondary that reads it, then at most three open sections; tables and record
cards follow, collapsed.

**MultiQC.** MultiQC panels only. Open: the pipeline's binding-prediction statistics
(binders, non-binders and unsupported peptides per sample and tool), the rank and affinity
distributions and the binder length distribution, all custom content. Collapsed: the general
statistics and the bcftools panels of the VCF inputs (substitution types, indel lengths,
variant quality, depths), which a run without variant input does not have. The pinned sample
filters narrow its panels.

**Predictions.** Strip: the predictions (split by IC50 band), the binder calls (split by
peptide length), the alleles scored (ranked by locus) and the median IC50 against the 500 nM
binder line. Then the allele by sample dot plot (thirty alleles, those whose median affinity
differs most between samples, every allele on demand; dot size is the binder share, colour
the median affinity score), the log10 IC50
histogram by tool and the predictions per sample stacked by IC50 band. Collapsed: the
per-allele table and every prediction. Filters: allele, HLA locus, tool and a log10 IC50
range; the allele pick reaches the allele summary, the agreement and the mutant / wild-type
pairs through the project links.

**Peptides.** Strip: the peptides (split by binder call), the predicted binders (split by the
IC50 band of their best prediction), alleles per binder (its distribution) and the median
best IC50 against the 500 nM line. Then the peptides by length stacked by call, and the
mutant against wild-type IC50 of every missense mutant whose wild type was predicted (below
the diagonal the mutation strengthens binding; colour is the outcome, a mutant binder whose
wild type does not bind first). Collapsed: the candidate peptides cut from the variants (by
consequence and length, and their table), and the peptide table with its record card (best
prediction, source variant or protein, wild type). Filters: binder call, peptide length and
origin; the length pick reaches the predictions and the variant peptides.

**Predictors.** Strip, read from the per-tool summary (the numbers of the MultiQC statistics
table): binders per tool (a ring by tool), the binder share per sample and tool (its spread),
the peptides a tool could not score (by tool) and the most alleles a tool scored in one
sample. Then the binder share per sample and tool, IC50 against percentile rank for every
prediction (one colour per tool, a line at 500 nM), and one tool's IC50 against the other's
for the peptides both scored against the same allele (colour is who calls a binder).
Collapsed: the per-tool table and the paired predictions. Filters: tool and agreement.

## Routes and pruning

| Route | What changes |
|---|---|
| No VCF row (`NO_VARIANT_INPUT`) | No variant peptides and no mutant / wild-type pairs: the Peptides tab loses its Mutant against wild type and Variant peptides sections, the Overview its neoepitope row. The MultiQC bcftools panels are absent from the report and pruned. |
| No `--wild_type` (`NO_WILD_TYPE`) | No mutant / wild-type pairs: the Mutant against wild type section and the neoepitope row go. |
| One tool per class (`SINGLE_PREDICTOR`) | No agreement: the Agreement section, its filter and table, the compare step, the agreement row and its highlight go; the Predictors tab keeps its per-tool strip and figures. |

The Overview's Key figures read collections every route writes, so a route never leaves a gap
in the strip.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: the group column
is coloured `auto`; the binder call, the IC50 bands, the peptide origin, the MHC class, the
tool agreement, the mutant / wild-type outcome and the variant consequence are written out;
tools, HLA loci and peptide lengths are coloured `auto`.

## Cross-selection

- The sample sheet selects on `sample`, which the links carry to every collection and to the
  MultiQC panels.
- The allele filter of Predictions (and of the Overview's Findings bar) works on the
  normalised allele (`HLA-A*02:01`), which every collection shares; a later HLA typing
  template can drive it (`TODO(wave4c)` in the dashboard and the template).
- The peptide table selects on `peptide_key` (sample and sequence) and opens its record card;
  the scatters select on `sequence`.

## Methods and assumptions

- **Two shapes.** `predictions/<sample>.tsv` is read in either shape the pipeline writes:
  long (the default) or `--wide_format_output`. The wide shape is melted file by file; a
  sample screened against every supported allele (`HLA-all`) has tens of thousands of columns,
  so the files are read as raw lines and never concatenated column-wise.
- **IC50.** The pipeline writes a 0-1 affinity score, `BA = 1 - log10(IC50) / log10(50000)`;
  the template derives the IC50 in nM back from it. MixMHCpred and MixMHC2pred give no IC50.
- **Rank.** `percentile_rank` is the tool's rank as written. MHCnuggets' rank is experimental
  and is a fraction of the human proteome (0 to 1), not a percentage, which the affinity
  against rank scatter shows as its own band.
- **Binder.** The binder call is the pipeline's, per tool: rank of 2 or less for MHCflurry,
  NetMHCpan and MixMHCpred, 5 or less for NetMHCIIpan, IC50 of 500 nM or less for MHCnuggets.
  A peptide is a binder when at least one tool calls it a binder of at least one allele, and
  unsupported when no tool scored it.
- **Wild types.** The per-tool summary leaves wild-type peptides out, as the MultiQC table
  does; the other collections keep them, with `origin` saying which is which.
- **Alleles.** Alleles are normalised to two-field `HLA-<gene>*<f1>:<f2>` (a class II
  heterodimer keeps both chains, `HLA-DPA1*01:03/DPB1*02:01`); a non-HLA allele is kept as
  written. `hla_locus` groups the class II chains by locus (`HLA-DR`, `HLA-DQ`, `HLA-DP`).
- **Screens.** A sample run against every supported allele (`HLA-all`) contributes thousands
  of alleles, each seen in that sample only: the dot plot's cap keeps the alleles whose
  affinity varies most between samples, so alleles shared by several samples come first, and
  the binder calls and allele counts of such a run are dominated by that sample.
