# nf-core/mag 5.5.0: Depictio dashboards

One dashboard: an **Overview**, then child tabs in three groups, read as a funnel from
the reads to one bin in full. The family rules are in `depictio/projects/nf-core/RULES.md`;
`ampliseq/2.18.0` is the reference implementation.

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | Did the reads survive trimming and host removal in every sample? |
| Assemblies | Assembly | Which assemblies are long and contiguous enough to bin? |
| Assemblies | Contigs | How are the contigs covered by each sample's reads? |
| Genomes | Bins | How complete and how clean is each recovered bin? |
| Genomes | Taxonomy | Which organisms are the bins, and how confidently are they named? |
| Genomes | Annotation | Do the bins carry the genes and RNAs of a genome? |
| Genomes | Bin detail | What do all four tools say about one bin? |

The unit is the bin, not the sample. Every assembler is crossed with every binner over
every sample, so the bins outnumber the samples by orders of magnitude, and the filters
that matter are the assembler, the binner, the phylum and the quality thresholds. The
template has no group variable: mag's own vocabularies (assembler, binner, MIMAG tier)
take the place of a design column.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the samples, assemblies and
  bins of the run and the shortest contig the binners were given (`min_contig_size`, read
  from the run parameters).
- **Pipeline**: six steps (clean, assemble, map back, bin, classify, annotate). Each step
  opens the parameters that drive it and the tab that shows its output.
- **Key figures**: four headline cards, each opening the tab that explains it. Bins (split
  by MIMAG tier), the median contig N50 of the assemblies (with its spread), the bins named
  down to a species (their share of all bins) and the median CheckM2 completeness. An
  assembler, a binner and a sample filter above them narrow these four only.
- **Findings**: result rows whose values are computed under the filters, each with a link
  to its tab: the binner that recovered the most bins of at least medium quality and its
  share, the assembler that put the most bases into contigs of 1 kbp or more, the phylum
  with the most named bins and its share, and the annotated bins that carry the RNAs of a
  high-quality draft. Below them, four figures in two rows, each linking its tab: the
  completeness against contamination plane beside assembled length against N50, then the
  GTDB lineage sunburst beside transfer against ribosomal RNAs. The bar of this section
  filters by assembler and binner.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (assembler, binner, then sample) sit in the collapsed left
panel and narrow every tab: the assembler and binner reach every per-assembly and per-bin
collection through the `bin_summary` links, the sample every collection through the sample
sheet. The `Sample sheet` section is pinned to the bottom of every child tab, collapsed,
and absent from the Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to
read the tab), then a strip of four key numbers, each card with its own colour and a
secondary that reads it, then at most three open sections; tables and details follow,
collapsed.

**MultiQC.** MultiQC panels only, and the only home of the read QC: fastp writes JSON and
NanoPlot free text, neither of which a table collection can read. Open: general statistics,
fastp reads kept and base quality, Bowtie 2 host and phiX removal, NanoStat long-read yield.
Collapsed: long reads by quality and short-read insert sizes, then the QUAST, CheckM2 and
GTDB-Tk panels that the next tabs draw in full. When a run publishes no `multiqc/`
directory, the report is re-generated with `depictio.dev_scripts.multiqc_reprocess` from
the run's raw outputs. Filter: the sample as the report names it.

**Assembly.** Strip: assembled bases (by assembler), the median contig N50 (with its
spread), contigs of at least 1 kbp (the largest assemblers first) and the longest contig
(with each assembly's longest). Then assembled length against contig N50, one point per
assembly with no labels (hover names it), and the contig-length section: the share of each
assembly kept per QUAST minimum contig length beside the Nx curve, both without a legend
(one curve per assembly). The Nx lengths come from the depth tables with QUAST's 500 bp
floor, so the curve crosses 50 at the QUAST N50; an assembly without a depth table has no
curve. Collapsed: the assembly statistics and the ladder rungs. Filters: an N50 range, a
minimum contig length range (it narrows the curves and keeps each whole inside the window)
and the assemblies the Nx curve draws.

**Contigs.** Every contig of at least 1 kbp, once per sample whose reads were mapped back
onto its assembly. Strip: the median depth of a contig in a sample (box plot), the median
mean depth (its distribution), distinct contigs (the largest assemblers first) and the
median contig length. Then length against depth, the plot a binner reads (a server-side
hash sample, one colour per sample), the depth of each assembly in each sample's reads as
boxes, and the recruitment heatmap: one row per assembly, one column per sample mapped
back, coloured by the log of the length-weighted mean depth, full width because sample ids
label its columns. It stands in for the bin by sample depth heatmap, whose input
(`GenomeBinning/depths/bins/`) is not always published. Filters: the sample whose reads
cover the contigs, contig length and depth.

**Bins.** Strip: bins scored (a ring by CheckM2 band), the median completeness (with its
spread), the median contamination (against the 5% high-quality cut, warning past 10%) and
the best quality score (by binner). Then completeness against contamination, cut into
quadrants at 90% complete and 5% contaminated and coloured by binner, the contiguity
section (CheckM2 contig N50 against completeness beside QUAST bin length against N50) and
completeness per binner as a histogram. The QUAST collection is linked to CheckM2 by
`bin_id`, so the tab's quality filters reach it. Collapsed: the QUAST per-bin table.
Filters: completeness, contamination and the quality band.

**Taxonomy.** GTDB-Tk places only the bins that pass its own thresholds. Strip: bins named
(a ring by binner), distinct phyla (by assembler), distinct species (the richest
phyla) and the median identity to the closest reference (against the 95% species
boundary). Then the lineage sunburst beside identity against alignment fraction (no
legend: colour is the phylum, keyed by the sunburst), the community each binning run
recovered (phylum by default, the eight largest and Other, a binner strip on top, the rank
in the tile's settings) and the Sankey of assembler to binner to phylum, weighted by bins.
Collapsed: the taxonomy table. Filters: phylum and placement method.

**Annotation.** Prokka's per-bin feature counts. Strip: coding sequences (by assembler),
the median genes per Mbp (with its spread), the median transfer RNAs (against the MIMAG
floor of 18) and the bins carrying the MIMAG RNAs (by binner). Then gene density against
bin size, with the roughly 900 coding sequences per megabase of a prokaryotic genome as a
reference, gene density per assembler as a histogram, and transfer against ribosomal RNAs,
the half of the MIMAG standard a completeness estimate cannot see. Collapsed: the
annotation table. Filters: gene density and the two RNA counts.

**Bin detail.** Strip: bins by MIMAG tier (a ring), tools per bin (its distribution), the
best quality score (by assembler) and Prokka features (a ring by class). Then the locus map
of the bin picked in the left panel or in the bin table, and feature lengths by class. The
collapsed `Bin table` holds the four-way outer join of CheckM2, QUAST, GTDB-Tk and Prokka
(one row per bin; `sources_present` counts the tools that reported on it) with the record
card of the bin picked in it beside it (`linked_component`). The card has no default
record and waits for a row. The collapsed `Features` section lists every annotated feature.
Filters: MIMAG tier, the bin, and the feature classes the map draws.

## Routes and pruning

Every collection but the sample sheet and the MultiQC report is optional: a run that did
not produce one loses its tiles, a tab left without data is dropped, and so are the
Overview tiles and rows that pointed at it.

| Route | What changes |
|---|---|
| No binning | No Genomes tabs, no Bins, species or completeness card, and only the assembly row and highlight in Findings. The assembler and binner filters lose their data. |
| No GTDB-Tk | No Taxonomy tab, phylum row or lineage highlight. The bin table keeps its rows without a lineage. |
| No Prokka | No Annotation tab, RNA row or highlight, and no locus map or features on Bin detail. |
| No depth tables | No Contigs tab and no Nx curve. |

The import re-packs the Overview grid after a drop, so a lone highlight takes the full row.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab. The assemblers
and binners are pinned, so a run with another subset keeps its colours; the MIMAG tiers and
CheckM2 bands share one scale (green high, blue medium, yellow low, red contaminated, grey
unknown); domains and Prokka feature classes are written out. Phyla are coloured
`auto:bin_count`: the eight with the most bins take the palette, largest first, so the
sunburst, the stacked community and the Sankey give a phylum the same colour, and Other and
Unclassified are grey.

## Cross-selection

A picked row or point becomes a dashboard filter that narrows the other tiles of its
collection and follows the project links to the collections they reach. The sample sheet
selects on `sample_id`; the assembly table, the ladder rungs and the retained-share curves
on `assembly_id`; the length against N50 scatter on `assembler`; the length against depth
scatter on `read_sample`; the MIMAG plane on `binner`; every other per-bin scatter and table
on `bin_id`; the features table on `feature_id`. The Nx curve does not select: its
collection has no outgoing link.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top
of a narrower one. Nothing is set per tab or per tile.

## Reproducing

```bash
bash depictio/projects/nf-core/mag/5.5.0/download_test_data.sh
python -m depictio.dev_scripts.multiqc_reprocess --src <DATA_ROOT> --dest <DATA_ROOT>
depictio-cli ingest --template nf-core/mag/5.5.0 --data-root <DATA_ROOT>
```

The test data fetch pulls only a subset of the Prokka GFFs (see `megatest.yaml`), because
each GFF carries the bin's whole sequence; the locus map covers whichever bins have a GFF
under the data root.
