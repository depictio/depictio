# nf-core/pairgenomealign 3.0.4: Depictio dashboards

One dashboard: an **Overview**, then five child tabs in two groups, read as a funnel from the
query assemblies to where the long alignments land on the target. The template follows the family
rules in `depictio/projects/nf-core/RULES.md` (ampliseq 2.18.0 is the reference implementation).

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | What does the MultiQC report say about the alignments? |
| Data & QC | Assemblies | How contiguous is each query assembly, and where are its gaps? |
| Genome alignment | Alignment | How much of the target does each genome cover, at what identity? |
| Genome alignment | Divergence | How far has each genome diverged from the target? |
| Genome alignment | Synteny | Where do the long alignments of each query land on the target? |

nf-core/pairgenomealign aligns every genome of its samplesheet (the queries) to one target genome
with LAST. It profiles each query assembly (assembly-scan, `seqtk cutN`), fits scoring parameters
for each pair (`last-train`), aligns the query to the target (`lastal`), reduces the alignment to a
one-to-one alignment (`last-split`) and writes small per-pair summaries next to the MAF files, which
are gigabytes per pair and are not read. With `--export_aln_to psl` it also writes a PSL export of
the one-to-one alignment. The template reads those summaries, the assembly reports, the poly-N BEDs
and the MultiQC report.

The pipeline samplesheet carries only the genome id and its FASTA, so the design is an optional
table (`METADATA_FILE`, the genome id in a `sample` column, any other column a factor). Every filter
starts from the genome hub (`genomes`, one row per query genome): the links carry a pick on a genome
to every per-pair and per-assembly collection, and a selection made on an alignment or assembly tile
narrows the hub, and through it every other tab.

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `metadata` | the design table (`METADATA_FILE`, optional) | query genome |
| `last_split_identity` | `alignment/*.o2o.tsv` | genome pair |
| `last_split_matrix` | `alignment/*.o2o.matrix.txt` | genome pair |
| `last_train_params` | `alignment/*.train.tsv` | genome pair |
| `last_synteny_links` | `alignment/*.psl.gz` (optional) | alignment, up to 2000 per pair |
| `assemblyscan_stats` | `assemblyscan/*.json` | query assembly |
| `seqtk_cutn_gaps` | `cutn/*.bed` | query assembly |
| `seqtk_cutn_gap_lengths` | `cutn/*.bed` | query assembly and log10 length bin |
| `genomes` | the collections above | query genome |
| `multiqc_data` | `multiqc/multiqc_data/multiqc.parquet` | MultiQC row |

Every per-pair output is named `<target>___<query>`, the target from `--targetName` and the query
from the samplesheet; the query is the key every table joins on. A genome whose BED is empty has no
gap and no row in the gap collections: the hub reads its absence as zero.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `DATA_ROOT` | required | root of one run (`alignment/`, `assemblyscan/`, `cutn/`, `multiqc/`) |
| `METADATA_FILE` | unset (the bundled reference reads `{DATA_ROOT}/input/genome_metadata.tsv`) | design table; without it the group filter, group colours and group splits fall away |
| `METADATA_ID_COL`, `GROUP_COL`, `GROUP_COL_DISPLAY` | `sample`, first factor column | the group the filters, the Query genomes card and the colours use |
| `SKIP_ASSEMBLY_QC` | unset | set for runs with `--skip_assembly_qc`: drops the assembly-scan collection and what reads it |

## Routes

Three collections are optional, and the import prunes what depends on them (RULES section 13):

- **No PSL export** (`--export_aln_to` left at `no_export`, as in the megatest): no
  `last_synteny_links`. Every component of the Synteny tab reads it, so the tab is dropped at
  import. The pipeline step and the findings row that cite its links go with it, and its tile in
  the tab list draws nothing. The other tabs are untouched.
- **`--skip_assembly_qc`**: no `assemblyscan_stats`. The Assemblies strip, the contiguity scatter
  and the statistics table go; the gap matrix and the gap table, read from the BEDs, stay. The
  Overview loses the Check step, the N50 findings row and the contiguity tile.
- **No design table**: the group filters and the group split of the Query genomes card fall away;
  the identity scatter draws in one colour.

## Overview

The landing page, at compact width with the filter panel collapsed (21 of 24 rows):

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the genome count and target, the
  seed and soft-masking, the strand, the mismap limit and the export format (from the run
  parameters).
- **Pipeline**: six steps (check, train, align, compare, link, report). Each step opens the
  parameters that drive it and the tab that shows its output.
- **Key figures**: four headline cards, each opening the tab that explains it. The query genomes
  (split by group), their size (the box shows the spread), the share of the target covered (a
  histogram) and the percent identity (the box shows the spread). A group and a genome filter above
  them narrow these four only.
- **Findings**: result rows computed under the filters, each with a link to its tab: the median
  identity with the target coverage, the K80 distance with the transition bias, the N50 with the
  share of sequences over 1 Mb, and the links of the synteny ring with their matching bases. Below
  them, four figures in two rows: the contiguity scatter beside the identity and coverage scatter,
  then the fitted gap costs beside the saturation scatter. The identity scatter is coloured by the
  group, so its highlight hides the legend.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (group, genome) sit in the collapsed left panel and narrow every
tab. The `Sample sheet` (the genome hub) is pinned to the bottom of every child tab, collapsed, and
absent from the Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to read the
tab), then a strip of four key numbers, each card with its own colour and a secondary that reads it,
then at most three open sections; tables and record cards follow, collapsed.

**MultiQC.** MultiQC panels only: the one-to-one identity and the fitted parameters of every genome
pair, then the contig length statistics and the base content of every query assembly. The report
holds custom content only. The `Report scope` filter narrows the panels to selected report rows, and
the pinned sample filters narrow them too (the pair id reaches the alignment sections by prefix, the
genome the assembly sections directly).

**Assemblies.** Strip: the N50 (its spread), the share of sequences over 1 Mb (a histogram: complete
and fragmented assemblies make two groups), the assembly length (its spread) and the GC content (its
spread). Then the sequences against N50 of each assembly on log axes, sized by length, and the gap
length matrix: one row per assembly, the lengths of its runs of N on a log10 scale across, the share
of its runs in each bin as the colour. A fixed scaffolding filler is one dark cell; a dotted line
marks the common 100 bp one. Collapsed: the assembly statistics and the gap summary. Filters: N50 and
sequence count.

**Alignment.** Strip: the percent identity (its spread), the share of the target covered (a
histogram), the aligned length (its spread) and the fitted gap opening cost (a histogram). Then every
genome by target coverage and identity, with the record of the picked genome beside it (alignment,
divergence and assembly in one card), and the gap opening cost last-train fitted against the
identity of its training alignments. Collapsed: the one-to-one alignment and the fitted parameters
per pair. Filters: identity and target coverage.

**Divergence.** Strip: the K80 distance (its spread), the transitions over transversions (its
spread), the alignment blocks (a histogram) and the deletions in the query (its spread). Then the
transition bias against the raw distance, one point per pair sized by its blocks, and the
substitution spectrum, the share of each of the 12 directed substitutions per genome, scaled per
column and clustered by row. Collapsed: the substitution counts and the five distance estimates.
Filter: K80 distance.

**Synteny.** Only with a PSL export. Strip: the links kept (split by orientation), the matching
bases (the target sequences with most), the identity of the links (its spread) and their span (its
spread). Then the ring: target and query sequences share it, a chord joins the two loci of an
alignment, its width the matching bases and its colour the orientation. The ring reads one query
genome: the left panel's picker is `always_selected`, so it holds the first query of the list until
another is picked.
Collapsed: the alignments behind the chords. Filters: query genome and orientation.

## Colours

`category_colors` is declared once on the Overview and read by every tab. The group (the first
design column, `clade` for the reference dataset) takes the palette, so the identity scatter, the
Query genomes card and the filter chips agree. The palette has eight colours and the reference
design has eight clades; a design with more groups falls back to the dashboard's colorway.
