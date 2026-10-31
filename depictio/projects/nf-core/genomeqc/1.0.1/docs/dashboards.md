# nf-core/genomeqc 1.0.1: Depictio dashboards

One dashboard: an **Overview**, then eight child tabs in two groups, read as a funnel from the
assemblies as they are to the genes the genomes share. The template follows the family rules in
`depictio/projects/nf-core/RULES.md` (ampliseq 2.18.0 is the reference implementation).

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | What does the MultiQC report say about the assemblies? |
| Data & QC | Assembly | How contiguous is each assembly? |
| Data & QC | Contamination | Does any assembly carry foreign or adaptor sequence? |
| Genomes | Completeness | How much of the conserved gene set does each genome hold? |
| Genomes | Karyotype | Where do the conserved genes and telomeric repeats sit? |
| Genomes | Repeats | How much of each genome is repeats, and of which kinds? |
| Genomes | Annotation | How many genes does each annotation hold, and how are they built? |
| Genomes | Orthology | Which orthogroups do the genomes share? |

nf-core/genomeqc compares several genome assemblies, each with its annotation when it has one. It
measures contiguity (QUAST), screens for foreign and adaptor sequence (FCS-GX, FCS-adaptor, Tiara),
masks repeats (RepeatMasker, with `--te repeatmasker`), scores conserved genes in the assembly and in
its proteins (BUSCO), counts telomeric repeats along every sequence (tidk), summarises the gene
models (AGAT, and its own gene overlap step) and groups the genes of all genomes into orthogroups
(OrthoFinder). The template reads the summary tables of each step; it never reads the masked FASTAs,
the RepeatMasker `.out` tables or the tens of thousands of per-orthogroup files OrthoFinder writes.

The samplesheet (assembly, accession, taxid) is not published and has no design column, so the
design is an optional table (`METADATA_FILE`, the assembly name in a `sample` column, any other
column a factor). Every filter starts from the genome hub (`genomes`, one row per assembly): the
links carry a pick on a genome to every per-genome collection.

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `metadata` | the design table (`METADATA_FILE`, optional) | assembly |
| `multiqc_data` | `multiqc/multiqc_data/multiqc.parquet` (QUAST only) | MultiQC row |
| `quast_assembly_raw`, `quast_assembly_report` | `quast/<a>/<a>.quast/transposed_report.tsv` | assembly |
| `quast_length_ladder` | the same reports | assembly and minimum length |
| `busco_batch_raw`, `busco_batch_summary` | `busco/{genome,protein}/<a>/stats/*-busco.batch_summary.txt` | assembly and BUSCO mode |
| `busco_composition` | the summary | assembly, mode and BUSCO class |
| `tidk_search_windows` | `tidk/<a>/search/<kind>/<a>.tsv` (optional) | assembly, sequence and 10 kb window |
| `busco_karyotype` | `busco/<mode>/<a>/ideogram/*.csv` and the tidk lengths (optional) | assembly and sequence holding a BUSCO |
| `agat_statistics` | `agat/<a>/stats/<a>.stats.txt` (optional) | assembly, feature type, isoform view and metric |
| `agat_gene_models` | the same reports (optional) | assembly and transcript type |
| `gene_overlaps` | `gene_overlaps/<a>.counts.tsv` (optional) | assembly |
| `orthofinder_species_stats` | `Comparative_Genomics_Statistics/Statistics_PerSpecies.tsv` (optional) | assembly |
| `orthofinder_orthogroup_matrix` | `Orthogroups/Orthogroups.GeneCount.tsv` (optional) | orthogroup, a 0/1 column per genome |
| `orthofinder_orthologue_matrix` | `Comparative_Genomics_Statistics/OrthologuesStats_one-to-one.tsv` (optional) | assembly, a column per genome |
| `ortho_seq_count` | `ortho_seq_count/species_ortho_seq_count.tsv` (optional) | assembly |
| `fcsgx_contamination` | `fcsgx/fcs_table.tsv` (optional) | assembly |
| `fcsgx_actions` | `decontamination/fcs-gx/<a>.fcs_gx_report.txt` (optional) | flagged range, or one `none` row per clean assembly |
| `fcsadaptor_actions` | `decontamination/fcs-adaptor/<a>.fcs_adaptor_report.txt` (optional) | flagged range, or one `none` row |
| `tiara_classifications` | `decontamination/tiara/raw/<a>.txt` (optional) | sequence of 3 kb or more |
| `tiara_class_counts` | `tiara_classifications` | assembly and Tiara class |
| `repeatmasker_repeat_classes` | `repeatmasker/<a>/<a>.tbl` (optional) | assembly and class or family line |
| `repeatmasker_masking_summary` | the same tables (optional) | assembly |
| `genomes` | the collections above | assembly |

QUAST and MultiQC label an assembly after its FASTA (the RefSeq file name); every other tool uses
the assembly name of the samplesheet. The hub reads the name from the QUAST report's directory and
keeps the FASTA label as `assembly_label`, which links it to the QUAST tables and the MultiQC panels.

genomeqc publishes BUSCO's summaries and its own per-sequence count of complete BUSCOs, but not
BUSCO's full table (the gene positions) and no table of sequence lengths. The karyotype therefore
shades whole sequences by their BUSCO density, and takes each length from tidk, whose last window of
a sequence ends at its length. Without tidk there is no karyotype.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `DATA_ROOT` | required | root of one run (`quast/`, `busco/`, `tidk/`, `agat/`, `orthofinder/`, `decontamination/`, `multiqc/`) |
| `METADATA_FILE` | unset (the bundled reference reads `{DATA_ROOT}/input/genome_metadata.tsv`) | design table; without it the group filter, group colours and group splits fall away |
| `METADATA_ID_COL`, `GROUP_COL`, `GROUP_COL_DISPLAY` | `sample`, first factor column | the group the filters, the Genomes card and the colours use |

## Routes

Every tool collection but QUAST is optional, and the import prunes what depends on it (RULES
section 13):

- **Genome-only run** (no annotation in the samplesheet): no AGAT, gene overlaps, OrthoFinder, ortho
  seq count or protein BUSCO. The Annotation and Orthology tabs are dropped, with the Annotate and
  Compare steps, the orthology findings row and the two highlights; the karyotype reads
  `busco/genome/<a>/ideogram/` instead. On Completeness, the "Complete in the proteins" card prints a
  dash and the genome-against-annotation scatter has no points (both read the BUSCO proteins mode).
- **`--skip_tidk`**: no sequence lengths, so neither karyotype: the Karyotype tab and its findings
  row are dropped.
- **No FCS-GX database** (`--gxdb` and `--gxdb_manifest` unset): no decontamination; the
  Contamination tab and the Screen step are dropped.
- **No `--te repeatmasker`** (unset, or `--te hite`, whose output no recipe reads): the Repeats tab
  and the Mask step are dropped.
- **`--skip_busco`**: no BUSCO and no karyotype; the Completeness and Karyotype tabs, the Complete
  step, two findings rows and the completeness highlight are dropped, and the BUSCO key figure prints
  a dash.
- **No design table**: the group filters and the group split of the Genomes card fall away; the
  scatters draw in one colour.

## Overview

The landing page, at compact width with the filter panel collapsed (21 of 24 rows):

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: the first says what the dashboard shows and how to move
  through it; the second lists the genome count, the BUSCO lineage, the annotation validator, the
  OrthoFinder version and the repeat annotation (from the run parameters).
- **Pipeline**: six steps (measure, screen, mask, complete, annotate, compare). Each step opens the
  parameters that drive it and the tab that shows its output; a step whose tool did not run is
  removed with its value.
- **Key figures**: four headline cards on the genome hub, each opening the tab that explains it: the
  genomes (split by group), the N50 (a histogram), the complete BUSCOs (a threshold at 95%, failing
  below 90%) and the N bases per 100 kb (the box shows the spread). A group and a genome filter above
  them narrow these four only.
- **Findings**: four result rows computed under the filters, each with a link to its tab: the median
  N50 with the L50, the complete BUSCOs of the assemblies and of their proteins, the sequences that
  carry the BUSCOs with the share of the busiest, and the orthogroups every genome shares with those
  of a single genome. Below them, four figures in two rows: the contiguity scatter beside the BUSCO
  classes, then the gene models beside each genome's genes by the orthogroups they fall in (shared,
  genome-specific or none).
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (group, genome) sit in the collapsed left panel and narrow every
tab. The `Sample sheet` (the genome hub) is pinned to the bottom of every child tab, collapsed.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to read the
tab), then a strip of four key numbers, each card with its own colour and a secondary that reads it,
then at most three open sections; tables follow, collapsed.

**MultiQC.** MultiQC panels only: QUAST's assembly statistics, the sequences in QUAST's length bins,
and the general statistics. The `Report scope` filter narrows the panels to report rows; the pinned
genome filters reach them through the FASTA label.

**Assembly.** Strip: N50 (a histogram), L50 (a histogram), assembly length and GC content (their
spread). Then the sequences against N50 of every assembly on log axes, sized by length and coloured
by group, with the record of the picked genome beside it, and the share of each assembly kept above
QUAST's minimum lengths. Collapsed: the QUAST statistics and the length ladder. Filters: N50 and
sequence count.

**Contamination.** Strip: the highest foreign share FCS-GX reports (a threshold at genomeqc's 0.5%,
failing above 2%), the bases FCS-GX flags (by action), the adaptor bases (by action) and the
sequences Tiara classified (by class). Then the foreign share per genome beside Tiara's classes per
genome, both stacked bars whose axis starts near the smallest bottom share (a `//` marks the cut;
the Zoom switch shows the whole bar). Collapsed: the FCS-GX calls, the FCS-adaptor calls and Tiara's class per sequence. Filters:
Tiara class and FCS-GX action.

**Completeness.** Strip: complete BUSCOs in the assembly (a threshold at 95%), complete in the
proteins (their spread), duplicated (a histogram) and the four classes summed (a composition). Then
one stacked bar per BUSCO run, each assembly beside its proteins (the axis starts above the complete
share every run shares, marked `//`; Zoom off shows the whole bar), and the assembly score against the
protein score per genome. Collapsed: the BUSCO scores per run. Filter: complete BUSCOs.

**Karyotype.** Strip: the sequences holding a BUSCO (by genome), the BUSCOs placed (by genome), the
BUSCOs per Mb (a histogram) and the 10 kb windows holding the tidk repeat (by genome). Then two
ideograms, one karyotype per genome each, the 24 longest sequences drawn to their length: the first
shaded by complete BUSCOs per Mb, the second by the copies of the searched repeat per 10 kb window.
The ideograms draw on canvas: a genome picker above the chart, a click on a bar (or Ctrl+wheel)
opens it zoomed with an overview strip, and the detail view's Filter dashboard action emits a
sequence or range filter on the tile's collection. Collapsed: the BUSCOs per
sequence. Filter: sequence length.

**Repeats.** Strip: the masked share (a gauge), the interspersed share (its spread), the simple
repeats (a histogram) and the elements found (by class). Then the share of each assembly every
repeat class takes; the rank switch opens the families. Collapsed: the masking summary and every
class and family line. Filter: repeat class.

**Annotation.** Strip: protein-coding genes (by genome), exons per mRNA (their spread), single-exon
genes (a histogram) and overlapping genes (their spread). Then every transcript type of every
annotation by genes and exons per transcript, then the genes per type beside each annotation's genes split by overlap
(overlapping none, overlapping another, nested on the opposite or the same strand), both stacked
bars. Collapsed: the gene models per type and every AGAT statistic. Filters (on the AGAT
statistics table): feature type and isoform view.

**Orthology.** Strip: the orthogroups (by copy class), the core every genome shares, the share of
genes placed for the genome with the fewest (its spread) and the orthogroups of one genome. Then each
genome's genes in shared, genome-specific or no orthogroups (a stacked bar, the Overview's
highlight), the UpSet of the genomes each orthogroup reaches and the one-to-one orthologues of every pair of genomes.
Collapsed: the orthogroup assignment per genome and the sequences carrying orthologues. Filter: copy
class.

## Colours

`category_colors` is declared once on the Overview and read by every tab: the group (the first
design column, `family` for the reference dataset) takes the palette; the BUSCO classes, BUSCO modes,
orthogroup copy classes and Tiara classes are written out; the RepeatMasker classes take the palette
by their share of the genomes (`auto:genome_pct`), with Unclassified grey.
