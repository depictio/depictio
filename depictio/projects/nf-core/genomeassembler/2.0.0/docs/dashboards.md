# nf-core/genomeassembler 2.0.0: Depictio dashboards

One dashboard: an **Overview**, then child tabs in three groups, read as a funnel from the
samples and the genome their reads describe to the contiguity, accuracy and gene
completeness of every assembly. The template follows the family rules in
`depictio/projects/nf-core/RULES.md`; `ampliseq/2.18.0` is the reference implementation.

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | Samples | Which samples reached assembly QC, and at which stages? |
| Data & QC | Genome profile | What genome do the reads describe, before any assembly? |
| Assemblies | Best assembly | Which assembly is best across contiguity, accuracy and genes? |
| Assemblies | Stages | What does each polishing and scaffolding step add? |
| Quality | Contiguity | How long and how fragmented is each assembly? |
| Quality | Accuracy | How accurate is each assembly against the read k-mers? |
| Quality | Gene completeness | How many conserved single-copy genes does each assembly hold? |

The pipeline writes no MultiQC report, so there is no MultiQC tab. The unit of every tile
is the assessed assembly, named `<sample>_<stage>` by every QC tool: the raw assembly, each
polishing step (medaka, dorado, pilon) and each scaffolder (LINKS, longstitch, RagTag). One
sample therefore contributes several rows. A sample whose assembly never reached QC stays
in the sample sheet as `No assembly QC` and appears in no other tile.

The design is the samplesheet, declared through `METADATA_FILE`, `METADATA_ID_COL` and
`GROUP_COL` (default `strategy`; `GROUP_COL_DISPLAY` is the reader label). The samplesheet's
`assembler`, `assembler_ont`/`assembler_hifi` and `scaffold_*` columns become
`assembler_used` and `scaffolders`; every other sheet column is passed through to
`assemblies` and `sample_status`, so any of them can be `GROUP_COL`.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the run's facts (samples,
  assessed assemblies, the BUSCO lineage and the k-mer size), read from the run parameters
  and the assessed assemblies.
- **Pipeline**: six steps (profile, assemble, polish, scaffold, measure, score). Each step
  opens the parameters that drive it and the tab that shows its output.
- **Key figures**: four headline cards, each opening the tab that explains it. Samples
  (split by group), the median N50 (with its spread), the median consensus QV (against
  QV 40, the Earth BioGenome Project floor) and the median share of complete BUSCOs
  (counting the assemblies at 90% or above). The three assembly cards read `assemblies`, which every route writes; a QC tool
  the run skipped leaves its card with a dash rather than a gap in the row. A group and a
  sample filter above them narrow these four only.
- **Findings**: result rows whose values are computed under the filters, each with a link
  to its tab: the best consensus QV and the assembly that reached it, the largest N50 fold
  change of a polishing or scaffolding step over the raw assembly, the best N50 and its assembly,
  and the best share of complete BUSCOs with its lineage. Below them, four figures in two
  rows: N50 against QV per assembly beside the QV along each route, then the Nx curves
  beside the BUSCO classes per assembly. The route and Nx highlights hide their legends,
  which list routes and assemblies. The bar of this section filters by group and stage
  class.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (group, then sample id) sit in the collapsed left panel
and narrow every tab through the samplesheet links. The `Sample sheet` section is pinned
to the bottom of every child tab, collapsed, and absent from the Overview: one row per
samplesheet sample with its design columns and how far its assembly QC got.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to
read the tab), then a strip of four key numbers, each card with its own colour and a
secondary that reads it (a box plot, a distribution, a gauge, a share or a ranking), then
at most three open sections; tables, details and comparisons follow, collapsed.

**Samples.** Strip: samples (a ring by QC status), assessed assemblies (split by stage
class), distinct stages assessed (ranked by stage class) and the mean number of QC tools
per assembly (a gauge out of samtools, Merqury, BUSCO and QUAST). Then the assessed stages
per sample, a code figure so the count axis steps by one (with Analysis mode's groups as
panels). Filters: QC status, stage class and assembler.

**Genome profile.** Strip: GenomeScope's haploid genome size, heterozygosity, repeat share
and the lowest model fit over the read sets. Then the jellyfish k-mer spectrum
GenomeScope fits, one line per read set. The GenomeScope table is collapsed. Filter: read
set.

**Best assembly.** Strip: the best N50, QV, share of complete BUSCOs and k-mer completeness
over the assemblies in view, each with every assembly's spread. Then the parallel
coordinates over N50, sequence count, length, QV and k-mer completeness (coloured by group;
brush an axis to keep a range). BUSCO stays off it: the plot drops a line that misses an
axis, and BUSCO scores fewer assemblies than Merqury, and N50 against QV coloured by
assembler with the assembly record card beside it (`linked_component`: it waits for a
picked point). The assembly table is collapsed. Filters: stage class, assembler and a QV
range.

**Stages.** Routes from each sample's raw assembly through polishing to each scaffolder
(`stage_steps`). Strip: routes (ranked by the stage they end on), the largest QV gain, the
largest N50 fold change and the lowest share of complete BUSCOs over the steps. Then the
QV and the N50 fold change along each route. Collapsed: the comparison of two stage
classes metric by metric (a screen, not a verdict, with few assemblies per class) and the
route table. Filters: final stage and route.

**Contiguity.** Strip: the median assembled length, N50, L50 and sequence count. Then the
Nx curves computed from the samtools idxstats sequence lengths of every assessed assembly,
and QUAST's reference-free view (N50 against assembled length beside the length kept above
each contig length, its legend below). Collapsed: QUAST against a reference (written only when the run had
one) and the QUAST tables. Filters: stage and an N50 range.

**Accuracy.** Strip: the median consensus QV, k-mer completeness, the sequences Merqury
scored (a ring, error-free or not) and the median error k-mers per assembly. Then QV
against k-mer completeness (a line at Q40, the points under it dimmed, no legend of
assemblies) and the copy number of the read k-mers in each assembly (classes in name
order).
Collapsed: the per-sequence QV scatter and the Merqury table. Filters: a QV range and
error-free sequences.

**Gene completeness.** Strip: the median share of complete BUSCOs (counting the
assemblies at 90% or above), the highest duplicated share, the median fragmented and
missing shares, each with its spread. Then the BUSCO classes
per assembly and complete against duplicated BUSCOs. The BUSCO table is collapsed.
Filters: lineage and a complete range.

## Routes and pruning

Every QC data collection is optional. A run that skipped a tool, or an assembly a tool never
reached, prunes that tool's collections: a tab left without data is dropped, with the
Overview rows and highlights that pointed at it.

| Route | What changes |
|---|---|
| No Merqury | No Accuracy tab or QV row; the QV cards print a dash. |
| No BUSCO | No Gene completeness tab, BUSCO row or BUSCO highlight. The BUSCO cards print a dash. |
| No QUAST | No QUAST sections on Contiguity. |
| No reference | No QUAST reference view or table. |
| No k-mer profiling (GenomeScope, jellyfish) | No Genome profile tab. |

The import re-packs the Overview grid after a drop, so a lone highlight takes the full row.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: the group
column is coloured `auto` (each value takes a colour-blind-safe colour at import, kept on a
re-import), the assembler too. The stage classes, the stages, the BUSCO classes, the
k-mer copy-number classes, the QC status and the error-free flag are written out, so a
class keeps its colour on every tab.

## Cross-selection

A picked row or point becomes a dashboard filter that narrows the other tiles of its
collection and follows the project links to the collections they reach. Every per-assembly
tile (the Best assembly scatter and table, the QUAST, Merqury and BUSCO scatters and
tables, the Nx curves) selects on `assembly_id`, the per-sequence QV scatter on `sequence`,
the stage profiles and route table on `route`, the GenomeScope table on `read_set` and the
pinned sample sheet on `sample`.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top
of a narrower one. Nothing is set per tab or per tile.

## Reproducing

```bash
python scripts/nfcore_megatest.py fetch --pipeline genomeassembler --version 2.0.0 --dest <DATA_ROOT>
depictio-cli ingest --template nf-core/genomeassembler/2.0.0 --data-root <DATA_ROOT>
```
