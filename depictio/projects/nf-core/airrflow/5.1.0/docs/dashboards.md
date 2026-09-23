# nf-core/airrflow 5.1.0: Depictio dashboards

This template turns the output of [nf-core/airrflow](https://nf-co.re/airrflow) 5.1.0 into a
single four-tab Depictio dashboard. airrflow processes B and T cell receptor amplicon
libraries into an AIRR rearrangement repertoire: it trims and assembles the reads, collapses
them by UMI, annotates V(D)J genes with IgBLAST, groups the sequences into clones and then runs
the [Immcantation](https://immcantation.readthedocs.io) enchantR report on top. The template
surfaces that report, and the sequence funnel that feeds it, next to the pipeline's own MultiQC.

Data comes from the AWS megatest run
`results-e69d49e3f23f11a3391755b5fb7aa4283c0a2471` (the 5.1.0 release tag), a ten-sample,
two-subject multiple sclerosis B cell study of cervical lymph node and brain lesion tissue.

---

## How the dashboard is built

Wave 2b: the V gene composition (rank picker), the richness against evenness scatter and the
overlap MDS draw their pickers as a header strip under the title
(`controls_placement: header`), and the processing and repertoire threshold sliders show the
column's distribution (`show_histogram: true`). The Repertoire tab also carries the two
figures the AIRR literature expects that the report tables cannot give: a CDR3 spectratype
per sample and a V by J pairing grid per donor. Both read the AIRR rearrangement table the
repertoire analysis starts from (`*__repertoire-pass.tsv`, about 310 MB on the megatest)
through two version-local recipes in `recipes/`, which read only the six or seven columns
they need, so the raw table never reaches Delta. Both collections are optional.

- **One funnel, four tabs.** MultiQC, then Sequence processing, then Repertoire, then
  Clonal analysis. Each tab answers the question the previous one raises: are the reads good,
  how many survive, what repertoire do the survivors make, and how is that repertoire
  structured.
- **Persistent filters.** `Sample filters` (sample, subject, tissue, sex) is pinned to the top
  of every tab's filter panel, sourced on the validated AIRR samplesheet the pipeline writes.
  The template's links fan a selection there out to every other collection, so one pick narrows
  the MultiQC panels, the funnel, the diversity profiles and the overlap matrix at once.
- **Pinned reference tables.** The rows behind every tile sit in a collapsed
  `Reference tables` section pinned to the bottom of every tab, alongside a pinned, collapsed
  `Sample sheet` section at the top.
- **Catalog provenance.** Every repertoire panel is a catalog render (`use: enchantr/...`) and
  every MultiQC tile names its module (`use: multiqc/fastp`, `use: multiqc/fastqc`), so the tile
  chrome shows where the panel comes from.
- **Subject is structural, not cosmetic.** airrflow defines clones within a subject, so
  `subject_id` colours the diversity profiles, annotates both heatmaps and zeroes the
  cross-subject cells of the overlap matrix. It is not a display choice: a clone id under two
  subjects is two different clones.

---

## MultiQC

The main tab. `Read QC at a glance` carries the MultiQC general statistics table, the fastp
filtered-read bars and the FastQC sequence counts. `Base quality` pairs fastp's per-base quality
curves with FastQC's quality histograms and per-read score distribution. `Read content`
(collapsed) holds GC, length, duplication, adapter content and the FastQC status grid.

airrflow runs FastQC twice, on the raw reads and again after the mate pairs are assembled, so
MultiQC labels the second run `fastqc-1` and the panels carry both the `<sample>` and
`<sample>_ASSEMBLED` series. Amplicon libraries are expected to look duplicated and to sit at a
narrow GC and length range, so most FastQC warnings here are normal.

A `Read QC scope` filter narrows the panels to selected report samples, independently of the
persistent sample filter, because the MultiQC sample ids carry the `_ASSEMBLED` suffix.

`Cohort at a glance` is pinned above all of it and rides every tab: samples broken down by
subject, subjects broken down by sampling site, subject age as a Tukey box plot and the target
loci. The samplesheet table itself stays in its own collapsed section below, so the numbers
travel with the reader while the rows behind them stay one click away.

The persistent `Sample filters` section carries sample, subject, sampling site and sex. airrflow
keeps `treatment`, `tissue` and `population` as free submitter columns, and this cohort used them
for sampling site, timepoint and sorted cell type in that order, so the filter that reads
`Sampling site` is bound to `treatment`. `tissue` holds one value for every sample here and is
deliberately not offered as a filter.

![MultiQC](screenshots/quality-control.png)


## Sequence processing

`Funnel at a glance` carries four cards: total input reads with an attrition strip across the
six milestone steps, UMI representatives broken down by subject, annotated sequences as a Tukey
box plot, and the median retention on a gauge.

`Where the reads go` is the signature panel: a Sankey of every read of every sample, following
each group to the step it stopped at. Three of the steps collapse reads rather than discard
them, since UMI consensus, deduplication and the representative filter each fold many reads onto
one sequence, so a retention of about one percent is expected and its spread across samples is
what matters. The depth control adds the Change-O steps after IgBLAST annotation.

`Per sample` plots the same funnel as one line per sample on a log axis, next to a retention bar
chart. A sample whose line drops away from the rest at one step is the one to look at.

![Sequence processing](screenshots/sequence-processing.png)


## Repertoire

`Repertoire at a glance`: clone counts as a box plot, mean clone size against a threshold,
median evenness on a gauge, and the repertoire count broken down by subject. Clone counts scale
with sequencing depth, so the Hill numbers behind the evenness card are rarefied to a common
depth by alakazam.

`V gene usage` pairs a stacked composition of V family and V gene fractions (switchable between
the two resolutions) with a clustered sample by V gene heatmap, column standardised so rare
genes stay visible, annotated by subject. A stacked bar of the family level alone sits below.

`Clones and depth` plots clones against sequencing depth on log axes, point size the mean clone
size: a repertoire that is simply deeper sits along the diagonal, one that is genuinely more
clonal sits below it. Beside it, richness against evenness puts the two halves of a Hill profile
on one plane, sized by the sequences behind each point, so a repertoire that is large but carried
by a few clones separates from one that is both large and flat. Selecting points in either, or
rows in the table below, narrows the clonal tab.

![Repertoire](screenshots/repertoire.png)


### CDR3 spectratype and V-J pairing (Repertoire tab)

`CDR3 spectratype` is one small bar panel per sample (`facet_col: sample_id`), the share of
the sample's productive in-frame sequences at each CDR3 length in amino acids, coloured by
donor. The CDR3 length is the IMGT junction length minus the two anchor codons, divided by
three. The seven deep samples draw the expected bell around 14 to 16 residues; the three
shallow brain-lesion sections are spikier, and SRR1383456 (27 sequences) is a handful of
bars rather than a distribution. A `CDR3 length (aa)` slider in `Repertoire scope` narrows
the panels.

`V-J pairing` is a `complex_heatmap` with one row per donor and V gene (`M4 IGHV3-23`) and
one column per J gene, each cell the share of the donor's productive sequences using the
pair, with `subject_id` as a row annotation. Rows cluster; J columns keep their genomic
order. It is per donor because clones are defined per donor, and the sample sheet reaches it
through a `subject_id` link.

## Clonal analysis

`Clonal analysis at a glance` puts the distance threshold on the card row, because clones are
called by nearest-neighbour distance and every number on the tab rests on the threshold shazam
fitted per subject. Beside it: rarefied richness, clones by homeostasis size class, and the
threshold's sensitivity.

`Diversity profiles` shows the Hill diversity profile, one curve per repertoire, against the
order q. At q of 0 every clone counts once; as q rises the large clones dominate, so a curve
that falls steeply is a repertoire carried by a few expanded clones. The panel below it is a
`profile` tile that draws the same curves with alakazam's bootstrap confidence band
(`d_lower` to `d_upper`) shaded per sample, and a ranked confidence-interval strip below
compares one Hill number per sample once a q is picked. The ribbon panel used to be a
hand-written Plotly figure with its own palette; the `profile` kind draws the band natively
and follows the theme.

`Clone abundance` opens with the rank-abundance curve alakazam bootstrapped: relative abundance
against rank on log axes, one curve per sample, with the bootstrap interval drawn as a shaded
band. The band is the point of the panel. Two repertoires whose heads look equally expanded stop
looking different as soon as their intervals overlap, which is exactly what happens to the three
brain-lesion sections here, each estimated off a few hundred sequences. Below it, the same clones
as a rank-abundance scatter (top 500 per sample, selection enabled on sample) and a sunburst of
subject to sample to clone size class, using the standard clonal homeostasis bins from rare to
hyperexpanded.

`Sharing between samples` pairs the shared-clone heatmap for every sample pair with an UpSet of
the higher-order intersections a pairwise view cannot show. The heatmap's diagonal is zeroed, so
the colour scale spans the real sharing rather than each sample's own repertoire size, and
samples from different subjects always read zero. A third panel reads the same square matrix as
an ordination: each sample is a row of shared-clone counts, and a Bray-Curtis PCoA over those
rows places samples that share clones next to each other, which is the repertoire-overlap MDS
immunarch and VDJtools draw. The coordinates are computed at render time rather than stored, so
narrowing the sample scope re-runs the ordination on what is left instead of showing a stale
layout.

---

![Clonal analysis](screenshots/clonal-analysis.png)


## Catalog module

The recipes ship as one catalog module, `depictio/catalog/enchantr/`, holding `module.yaml`
plus eleven `<output>.py` / `<output>.yaml` / `<output>.tsv` triples. enchantR is airrflow's own R
package rather than an nf-core module, so `module.yaml` declares its identity in full
(homepage, EDAM immunology and immunoproteins topics).

| Output | What it is | Renders as |
|---|---|---|
| `sequence_counts` | Sequences remaining after every pRESTO and Change-O step | 4 cards, table |
| `sequence_fates` | The same funnel as read groups, per milestone | Sankey, table |
| `repertoire_summary` | Clone counts, clone-size spread, rarefied Hill numbers | 4 cards, scatter, richness against evenness, table |
| `clonal_abundance` | Bootstrapped rank abundance of every clone with its confidence band | Profile with ribbon, 2 cards, table |
| `clonal_diversity` | Hill diversity profile with bootstrap CIs | Rarefaction, CI bars, table |
| `clonal_overlap` | Sample by sample shared clone matrix | Clustered heatmap, PCoA ordination, table |
| `clone_sizes` | Every clone with rank, frequency and size class | Sunburst, 2 cards, table |
| `clone_sets` | Clone by sample presence matrix | UpSet, card, table |
| `v_gene_usage` | V family and V gene fractions per sample | Stacked composition, card, table |
| `v_gene_matrix` | Sample by V gene fraction matrix | Clustered heatmap, table |
| `threshold_summary` | The shazam distance threshold per subject | 3 cards, table |

The MultiQC modules airrflow emits (`fastp`, `fastqc`) already exist under
`depictio/catalog/multiqc/`, which is what lets a MultiQC tile carry `use: multiqc/<module>`
and the catalog badge.
