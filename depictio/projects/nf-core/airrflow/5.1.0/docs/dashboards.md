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

Wave 2b: the V gene composition (rank picker) and the richness against evenness scatter draw
their pickers as a header strip under the title
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
- **Persistent filters.** `Sample filters` (sample, subject, condition, sex) is pinned to the
  top of every tab's filter panel, sourced on the validated AIRR samplesheet the pipeline
  writes. The template's links fan a selection there out to every other collection, so one pick
  narrows the MultiQC panels, the funnel, the diversity profiles and the overlap matrix at once.
  Tab-local filter sections are open, not collapsed.
- **Design column (`GROUP_COL`).** The condition filter and the subject card breakdown read the
  samplesheet column named by the `GROUP_COL` template variable (default `treatment`, the
  condition column of airrflow's samplesheet schema), labelled `GROUP_COL_DISPLAY` (default
  "Condition"). A run whose samplesheet names the condition differently passes
  `--var GROUP_COL=<column>`; the nf-core `test` profile, for instance, uses `intervention`.
- **Pinned tables.** Two at most: the AIRR samplesheet (collapsed `Sample sheet` section at the
  top) and the repertoire summary (collapsed `Reference tables` section at the bottom), which
  both the Repertoire and the Clonal tabs read. The sequence counts table sits collapsed at the
  end of Sequence processing, the threshold and overlap tables at the end of Clonal analysis.
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
subject, subjects broken down by condition (`GROUP_COL`), subject age as a Tukey box plot and
the number of target loci. The samplesheet table itself stays in its own collapsed section, so
the numbers travel with the reader while the rows behind them stay one click away.

The persistent `Sample filters` section carries sample, subject, condition and sex. airrflow
keeps `treatment`, `tissue` and `population` as free submitter columns. On the megatest cohort
`treatment` holds the sampling site and `tissue` a single timepoint, which is why the default
`GROUP_COL=treatment` gives a useful contrast there; on another run, point `GROUP_COL` at the
column that carries the design.

![MultiQC](screenshots/quality-control.png)


## Sequence processing

`Funnel at a glance` carries four cards: total input reads with an attrition strip across the
six milestone steps, representative sequences broken down by subject, annotated sequences as a
Tukey box plot, and the median retention with its per-sample box plot. The retention card has
no gauge: its scale depends on the library design (UMI or not, assembled input), so a fixed
maximum would overflow on some runs.

`Where the reads go` is the signature panel: a Sankey of every read of every sample, following
each group to the step it stopped at. Several steps collapse reads rather than discard them
(UMI consensus, deduplication, the representative filter), so a low retention is expected and
its spread across samples is what matters. The depth control adds the Change-O steps after
IgBLAST annotation.

`Per sample` plots the same funnel as one line per sample on a log axis, next to a retention bar
chart. A sample whose line drops away from the rest at one step is the one to look at. The
per-step counts table closes the tab in a collapsed section.

![Sequence processing](screenshots/sequence-processing.png)


## Repertoire

The Repertoire tab reads gene usage only: which V families and genes, which V-J pairs and
which CDR3 lengths build each repertoire. Clonality and diversity moved to Clonal analysis
(wave 3).

`Repertoire at a glance`: V families used, V genes used (both with the per-sample count
beside them), the largest V family share (how skewed the usage is, per sample) and the
productive in-frame sequences behind the spectratype, broken down by subject.

`V gene usage` pairs a stacked composition of V family and V gene fractions (switchable between
the two resolutions in the tile header) with a clustered sample by V gene heatmap, column
standardised so rare genes stay visible, annotated by subject.

![Repertoire](screenshots/repertoire.png)


### CDR3 spectratype and V-J pairing (Repertoire tab)

`CDR3 spectratype` is one small bar panel per sample (`facet_col: sample_id`), the share of
the sample's productive in-frame sequences at each CDR3 length in amino acids, coloured by
donor. The CDR3 length is the IMGT junction length minus the two anchor codons, divided by
three. Where the bell of a polyclonal repertoire centres depends on the locus (heavy chain,
light chain, TCR beta...), so the dashboard texts do not state a range. A `CDR3 length (aa)`
slider in `Repertoire scope` narrows the panels.

`V-J pairing` is a `complex_heatmap` with one row per donor and V gene and one column per J
gene, each cell the share of the donor's productive sequences using the pair, with
`subject_id` as a row annotation. Rows cluster; J columns keep their genomic order. It is per
donor because clones are defined per donor, and the sample sheet reaches it through a
`subject_id` link.

## Clonal analysis

`Clonal analysis at a glance` carries six cards: clones (sum, per-sample box plot), median
clone size (box plot), rarefied richness and evenness on the first row; the distance threshold
and its sensitivity, each with the per-subject values beside the median, on the second. The
threshold is fitted by shazam per subject (or set with `--clonal_threshold`); the card reports
it without a pass or fail verdict, since no fixed cut-off applies to every locus and design.

`Clones and depth` (moved here from Repertoire in wave 3) plots clones against sequencing depth
on log axes, point size the mean clone size: a repertoire that is simply deeper sits along the
diagonal, one that is genuinely more clonal sits below it. Beside it, richness against evenness
puts the two halves of a Hill profile on one plane. Selecting points narrows the rest of the tab.

`Diversity profiles` draws the Hill diversity profile, one curve per repertoire against the
order q, with alakazam's bootstrap confidence band (`d_lower` to `d_upper`) shaded per sample.
Below it, a ranked confidence-interval strip compares one Hill number per sample at a named
order. It reads the `diversity_orders` collection (q = 0, 1 and 2 only, one labelled row per
sample and order), so the `Diversity order` Select in `Clonal scope` (default "q = 1,
Shannon") narrows the bars without touching the profile curves.

`Clone abundance` opens with the rank-abundance curve alakazam bootstrapped: relative abundance
against rank on log axes, one curve per sample, with the bootstrap interval shaded. Two
repertoires whose heads look equally expanded stop looking different as soon as their intervals
overlap. Below it, a sunburst of subject to sample to clone size class, using the standard
clonal homeostasis bins from rare to hyperexpanded.

`Sharing between samples` pairs the shared-clone heatmap for every sample pair with an UpSet of
the higher-order intersections a pairwise view cannot show. The heatmap's diagonal is zeroed,
and samples from different subjects always read zero because clones are subject-private.

`Clonal tables` (collapsed) holds the fitted threshold per subject and the shared-clone matrix.

---

![Clonal analysis](screenshots/clonal-analysis.png)


## Cross-selection

Tables select rows and scatters select points; a pick becomes a dashboard filter that the
project links carry to every collection they reach. Row selection is on `sample_id` in the
pinned sample sheet and repertoire summary, in the sequence counts table and in the clonal
overlap table, and on `subject_id` in the clonal threshold table. The clones-versus-depth
figure and the richness-against-evenness scatter select on `sample_id`. The diversity
profile does not select: its collection has no outgoing link, so a pick would narrow nothing.
The clone abundance profile emits a selection but its collection has no outgoing link
either, so it only narrows itself out of the filter.

## Catalog module

The recipes ship as one catalog module, `depictio/catalog/enchantr/`, holding `module.yaml`
plus twelve `<output>.py` / `<output>.yaml` / `<output>.tsv` triples. enchantR is airrflow's own R
package rather than an nf-core module, so `module.yaml` declares its identity in full
(homepage, EDAM immunology and immunoproteins topics).

| Output | What it is | Renders as |
|---|---|---|
| `sequence_counts` | Sequences remaining after every pRESTO and Change-O step | 4 cards, table |
| `sequence_fates` | The same funnel as read groups, per milestone | Sankey, table |
| `repertoire_summary` | Clone counts, clone-size spread, rarefied Hill numbers | 4 cards, scatter, richness against evenness, table |
| `clonal_abundance` | Bootstrapped rank abundance of every clone with its confidence band | Profile with ribbon, 2 cards, table |
| `clonal_diversity` | Hill diversity profile with bootstrap CIs | Rarefaction, CI bars, table |
| `diversity_orders` | Hill diversity at q = 0, 1, 2 with bootstrap CIs, labelled | CI bars, order Select, table |
| `clonal_overlap` | Sample by sample shared clone matrix | Clustered heatmap, PCoA ordination, table |
| `clone_sizes` | Every clone with rank, frequency and size class | Sunburst, 2 cards, table |
| `clone_sets` | Clone by sample presence matrix | UpSet, card, table |
| `v_gene_usage` | V family and V gene fractions per sample | Stacked composition, card, table |
| `v_gene_matrix` | Sample by V gene fraction matrix | Clustered heatmap, table |
| `threshold_summary` | The shazam distance threshold per subject | 3 cards, table |

The MultiQC modules airrflow emits (`fastp`, `fastqc`) already exist under
`depictio/catalog/multiqc/`, which is what lets a MultiQC tile carry `use: multiqc/<module>`
and the catalog badge.
