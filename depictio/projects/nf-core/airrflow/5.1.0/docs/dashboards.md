# nf-core/airrflow 5.1.0: Depictio dashboards

One dashboard: an **Overview**, then child tabs in three groups, read as a funnel from the
reads to the clones that expand and are shared. It follows the family rules in
`depictio/projects/nf-core/RULES.md`, with nf-core/ampliseq 2.18.0 as the reference.

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | Did trimming and read quality hold for every sample? |
| Data & QC | Sequence Processing | How many reads survive each pRESTO and Change-O step? |
| Repertoire | V Gene Usage | Which V families and genes build each repertoire? |
| Repertoire | CDR3 & Pairing | How long are CDR3 loops, and which V and J genes pair? |
| Clonality | Clonal Diversity | How many clones does each repertoire hold, and how diverse is it? |
| Clonality | Clonal Expansion | How strongly do the largest clones dominate each repertoire? |
| Clonality | Clone Sharing | Which clones do the samples of one subject share? |

[nf-core/airrflow](https://nf-co.re/airrflow) trims and assembles B or T cell receptor reads
with pRESTO, annotates them with IgBLAST through Change-O, groups the sequences into clones
and runs the [Immcantation](https://immcantation.readthedocs.io) enchantr report on top. The
design comes from the validated sample sheet the pipeline writes under `pipeline_info/`:
`GROUP_COL` names its condition column (default `treatment`, the column airrflow's schema
documents) and `GROUP_COL_DISPLAY` its reader label (default "Condition"). A run whose sample
sheet names the condition differently passes `--var GROUP_COL=<column>`.

Clones are defined within a subject, so `subject_id` is structural rather than cosmetic: it
colours the per-sample lines and scatters, annotates the heatmaps and zeroes the
cross-subject cells of the overlap matrix.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the run's facts (samples and
  subjects from the sample sheet, the library preparation, the clonal threshold setting and
  the input mode, from the run parameters).
- **Pipeline**: six steps (trim, assemble, annotate, translate, clone, compare). Each step
  opens the parameters that drive it and the tab that shows its output.
- **Key figures**: four headline cards, each opening the tab that explains it. Samples (split
  by condition), input reads and clones (each summed, with the spread per sample) and the
  sequences per clone (each sample's mean clone size, the median over samples). A condition
  and a sample filter above them narrow these four only. A route that loses one of them fills
  its slot with an alternate (see Routes and pruning), so every route keeps four.
- **Findings**: result rows whose values are computed under the filters, each with a link to
  its tab: the most used V family and its share of the sequences, the median effective number
  of clones (Hill diversity at q = 1, after rarefying), the clones seen in more than one
  sample (counted over all samples, as the clone sets are narrowed by sample column rather
  than by row) and the clone size class that holds most sequences. Below them, four figures in two rows, each linking
  its tab: the V family composition per sample beside the Hill diversity profile, then the
  clones by number of samples holding them beside the clonal homeostasis sunburst. The bar
  of this section filters by condition and subject.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (condition, sample id, subject, sex) sit in the collapsed
left panel and narrow every tab through the sample sheet's links. The `Sample sheet` section
is pinned to the bottom of every child tab, collapsed, and absent from the Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to read
the tab), then a strip of key numbers, each card with its own colour and a secondary that
reads it, then at most three open sections; tables and details follow, collapsed.

**MultiQC.** MultiQC panels only. Open: general statistics, fastp filtered reads and the
FastQC sequence counts, then fastp's per-base quality beside the FastQC quality histograms.
Collapsed: per-sequence quality, GC, length, duplication, adapter content and the status
checks. Amplicons of one receptor locus show high duplication and a narrow GC band by design.
Its own sample filter reads the MultiQC report.

**Sequence Processing.** Strip: input reads, with the share kept through each pRESTO step
(quality, pairing, UMI consensus, assembly, duplicates), and the reads per sample with their
spread. Then the read-fate Sankey (losses peel off into a Lost lane, flows coloured by the
step they reach; its depth control adds the Change-O steps), and per sample the sequences left
at each step (log scale, one line per sample) beside the sequences each sample keeps per
1,000 input reads. UMI consensus and duplicate collapsing merge many reads into one sequence,
so that ratio is no share of reads kept. The counts table is collapsed. Filters: input reads
and sequences per input read.

**V Gene Usage.** Strip: distinct V genes (ranked by family), annotated sequences split by V
family, the largest share one family takes in a sample (with every family's spread) and the
median share of a V gene (with its distribution). Then the stacked composition per sample (V
family by default, the eight largest named, gene resolution a switch away, a subject strip
below) and the sample by V gene heatmap (ward on correlation, standardised per gene, subject
annotation). Filters: V family and locus.

**CDR3 & Pairing.** Strip: productive sequences (with the share the three largest samples
hold) and the largest share one CDR3 length takes in a sample. Then the spectratype, one line
per sample (dashed by locus on a multi-locus run), and the V by J pairing heatmap per subject
(rows clustered, J genes in genomic order). Collapsed: the spectratype as one bar panel per
sample. Both collections read the AIRR rearrangement table through two version-local recipes
in `recipes/`, which load only the columns they need. Filters: CDR3 length and locus.

**Clonal Diversity.** Strip: clones (with the share the three largest samples hold) and the
median effective number of clones (Hill diversity at q = 1, the exponential of Shannon
entropy, on repertoires rarefied to a common depth) with its spread. Then the Hill diversity
profile (one curve per sample against the order q, with alakazam's bootstrap band), the
ranked Hill number at one named order beside richness against evenness, and clones against
sequencing depth on log axes (point size: mean clone size). Collapsed: the clone definition (the SHazaM distance threshold
and its sensitivity per subject, cards and table) and the per-sample repertoire summary.
Filters: a clone count range and the diversity order (default "q = 1, Shannon"), which narrows
the ranked bars only.

**Clonal Expansion.** Strip: clones as a ring by size class, sequences split by size class,
the median share of a sample's largest clone (as a percentage) and the size of the largest clone
with every clone's size as a histogram (most clones hold one sequence).
Then the rank-abundance curves with their bootstrap bands, and the clonal homeostasis sunburst
(subject, sample, size class). Filter: size class.

**Clone Sharing.** Strip: clones split by the number of samples holding them, and the
sequences in shared clones with the share the three largest carry. Then the clones by number
of samples (log scale), the shared-clone heatmap for every sample pair (diagonal zeroed) and
the UpSet of exact sample sets. Collapsed: the overlap matrix as a table. Filter: samples per
clone.

## Routes and pruning

airrflow's route flags are not read from `params.json` yet, so a run that skipped a step
passes the matching `--var`. A tab left without data is dropped, and so are the Overview
tiles and rows that pointed at it; the import re-packs the Overview grid after a drop.

| Route | What changes |
|---|---|
| `ASSEMBLED_MODE` (`--mode assembled`) | No Sequence Processing tab; the input reads Key figure becomes input sequences. |
| `SKIP_REPORT` | No V Gene Usage tab, V family row or V composition highlight, and no Sequence Processing tab either: airrflow parses the pRESTO logs inside its report step. The input reads Key figure becomes sequences. |
| `SKIP_CLONAL_ANALYSIS` | No Clonality tabs, diversity, sharing or size class rows, nor their highlights; CDR3 & Pairing goes too, as its tables come from the clonal analysis. The clones and sequences per clone Key figures become unique sequences and V genes. |
| `SKIP_THRESHOLD_REPORT` | No clone definition cards or table. |
| `SKIP_MULTIQC` | No MultiQC tab. |

No collection but the sample sheet survives every route, so each Key figure a route loses
has an alternate on the same grid slot, bound to a collection that exists on that route
only. The import keeps whichever card of a slot survives, and no route keeps two.

| Slot | Default card | Alternate | Collection, and the route it exists on | Opens |
|---|---|---|---|---|
| 2 | Input reads | Input sequences: assembled sequences that entered IgBLAST | `annotation_counts_assembled`, `ASSEMBLED_MODE` | V Gene Usage |
| 2 | Input reads | Sequences: unique annotated sequences that entered clonal assignment | `repertoire_summary_noreport`, `SKIP_REPORT` | Clonal Diversity |
| 3 | Clones | Unique sequences: annotated sequences after duplicate collapse | `annotation_counts_noclonal`, `SKIP_CLONAL_ANALYSIS` | V Gene Usage |
| 4 | Sequences per clone | V genes: distinct V genes, ranked by family | `v_gene_usage_noclonal`, `SKIP_CLONAL_ANALYSIS` | V Gene Usage |

The two `annotation_counts_*` collections read the Change-O table of the report
(`repertoire_comparison/Sequence_numbers_summary/Table_sequences_assembled.tsv`) through the
version-local recipe `recipes/annotation_counts.py`: it is the sequence count a run still
writes without pRESTO or without clones. An alternate keeps the colour of the card it
replaces, so no route repeats one. Combined routes keep four cards too (an assembled run
without clonal analysis shows input sequences, unique sequences and V genes), except a run
that skipped both the report and the clonal analysis: only its Samples card is left.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: the condition and
the subject are coloured `auto` (each value takes a colour-blind-safe colour at import, kept
on a re-import), the five clonal homeostasis size classes are written out (blues from rare to
medium, then orange and red for the expanded classes), and V families and genes are coloured
`auto:seq_count`, so the eight families with most sequences take the palette, largest first,
and Other is grey. Code figures read the same map and follow Analysis mode's groups when it
has some.

## Cross-selection

Tables select rows and scatters select points; a pick becomes a dashboard filter that the
project links carry to every collection they reach. Row selection is on `sample_id` in the
sample sheet, the counts table, the repertoire summary and the overlap table, and on
`subject_id` in the threshold table. The clones-against-depth figure and the richness against
evenness scatter select on `sample_id`.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top of a
narrower one. Nothing is set per tab or per tile.

## Catalog module

The recipes ship as one catalog module, `depictio/catalog/enchantr/` (enchantr is airrflow's
own R package rather than an nf-core module, so `module.yaml` declares its identity in full).
Every repertoire panel is a catalog render (`use: enchantr/...`) and every MultiQC tile names
its module (`use: multiqc/fastp`, `use: multiqc/fastqc`).

## Reproducing

```bash
python scripts/nfcore_megatest.py fetch --pipeline airrflow --version 5.1.0 --dest <DATA_ROOT>
depictio-cli ingest --template nf-core/airrflow/5.1.0 --data-root <DATA_ROOT>
```
