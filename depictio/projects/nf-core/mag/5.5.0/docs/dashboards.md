# nf-core/mag 5.5.0: Depictio dashboards

One dashboard, seven tabs, read as a funnel: **MultiQC -> Assembly -> Contigs
-> Bins -> Taxonomy -> Annotation -> Bin detail**. Each tab narrows the one
before it, and the filters compose forward.

The unit here is the bin, not the sample. Every assembler is crossed with
every binner over every sample, so the bins outnumber the samples by orders of
magnitude and the controls that matter are the assembler, the binner, the
phylum and the quality thresholds. The sample filter is the widest of them.

A pinned strip of four cards (bins recovered with their MIMAG tiers, median
completeness, median contamination, binned bases) rides every tab and is never
repeated as a tab card.

## Tabs

**MultiQC.** The landing tab, MultiQC panels only. Read QC lives here because
fastp writes JSON and NanoPlot writes free text, neither of which a table data
collection can read, so there is no read-level table and no Reads tab. When a
run publishes no `multiqc/` directory, the report is re-generated with
`depictio.dev_scripts.multiqc_reprocess` from the run's raw outputs.

**Assembly.** One row per assembler and sample. Assembled length against contig
N50 separates binnable assemblies (long assemblies in long pieces) from
fragmented ones. The "Contig length" section holds the retained fraction of
each assembly per QUAST minimum contig length and the Nx curve, one curve per
assembly with the N50 marked. The Nx lengths come from the depth tables with
QUAST's 500 bp floor, so the curve crosses x = 50 at the QUAST N50; an assembly
without a depth table has no curve. The "Minimum contig length range" filter
is a RangeSlider on `min_contig_length`: it narrows the curves and the rung
table to a window of thresholds and keeps every curve intact inside it.

**Contigs.** Every contig of at least 1 kbp, once per sample whose reads were
mapped back onto its assembly. Length against depth is the plot a binner sees
before it decides anything; the scatter draws a server-side hash sample. Depth
per assembly and read sample is read as boxes. The recruitment heatmap is one
row per assembly and one column per read sample, coloured by the assembly's
length-weighted mean depth: the assembly-level stand-in for the bin by sample
depth heatmap, whose input (`GenomeBinning/depths/bins/`) is not always
published.

**Bins.** Completeness against contamination, cut into quadrants at the MIMAG
high-quality thresholds (90 percent complete, under 5 percent contaminated),
coloured by binner. Its cards carry the bin count by CheckM2 band, the median
bin contig N50, the median bin size and the best quality score. Contiguity
against completeness sits below. The QUAST section is linked to CheckM2 by
`bin_id`, so the tab's quality filters reach it too.

**Taxonomy.** GTDB-Tk only places the bins that pass its own thresholds. The
sunburst reads the lineage from domain outwards; the stacked bars show the
recovered community per binning run as percentages, top 12 taxa, genus by
default, sorted by abundance, with the rank picker in the tile header as the
only rank control. The one Sankey of the template traces assembler to binner
to phylum, weighted by bins.

**Annotation.** Prokka's per-bin feature counts. Gene density against bin size,
with the roughly 900 coding sequences per megabase of a prokaryotic genome as
a reference, and transfer against ribosomal RNAs, the half of the MIMAG
standard a completeness estimate cannot see.

**Bin detail.** Cards: high-quality MIMAG drafts, bins meeting the MIMAG RNA
criteria, tools per bin and the best score. The locus map draws the genes of
the bin picked in the left panel or in the bin table. The "Bin detail" section
at the end of the tab holds the four-way outer join of CheckM2, QUAST, GTDB-Tk
and Prokka (one row per bin, `sources_present` counts the tools that reported
on it) with the record card of the bin selected in that table beside it
(`linked_component`). The record card has no default record: it stays a thin rail until a
row is picked. Its sections open on Quality
and carry readable labels.

## Cross-selection

A picked row or point becomes a dashboard filter that narrows the other tiles of its
collection and follows the project links to the collections they reach. The pinned sample
sheet selects on `sample_id` and the assembly table on `assembly_id`; the length ladder
profile and table select on `assembly_id`; every per-bin scatter and table of the Bins,
Taxonomy, Annotation and Bin detail tabs selects on `bin_id`, except the MIMAG plane, which
selects on `binner`; the locus table selects on `feature_id`. The Nx curve does not select:
its collection has no outgoing link and no sibling tile.

## Filters

Two filter sections and three grid sections are persistent and pinned, so they
ride every tab: the sample scope, the assembler and binner scope, the run's
headline numbers, the samplesheet and the per-assembly reference table. Each
tab then adds its own filters on its own columns: the MIMAG tier of the pinned
bin strip on the MultiQC tab, the minimum contig length range, N50 and the Nx
curves on Assembly, the read sample, length and depth on Contigs,
completeness, contamination and the quality band on Bins, phylum and placement
method on Taxonomy, gene density and the RNA counts on Annotation, and the
MIMAG tier, the bin and the feature class on Bin detail. Every threshold slider
draws its column's distribution above it.

## Controls

`advanced_viz_controls: header` on every tab: the analysis controls of every
scatter, the rank of the stacked community bars and the view switches sit in
the tile header rather than behind the settings icon.

## Reproducing

```bash
bash depictio/projects/nf-core/mag/5.5.0/download_test_data.sh
python -m depictio.dev_scripts.multiqc_reprocess --src <DATA_ROOT> --dest <DATA_ROOT>
depictio-cli run --template nf-core/mag/5.5.0 --data-root <DATA_ROOT>
```

The megatest fetch pulls only a subset of the Prokka GFFs (see megatest.yaml),
because each GFF carries the bin's whole sequence; the locus map covers
whichever bins have a GFF under the data root.
