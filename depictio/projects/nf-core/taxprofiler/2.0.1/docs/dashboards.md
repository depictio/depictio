# nf-core/taxprofiler 2.0.1: Depictio dashboards

One dashboard: an **Overview**, then child tabs in three groups, read as a funnel from the
reads to the taxa the classifiers agree on. The family rules are in
`depictio/projects/nf-core/RULES.md`; `ampliseq/2.18.0` is the reference implementation.

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | Were the reads clean, and how much host was removed? |
| Data & QC | Sequencing depth | Did the sequencing reach enough of each metagenome? |
| Communities | Profiles | What does each classifier say the community is made of? |
| Communities | Diversity | How diverse is each profile, by each classifier? |
| Classifiers | Concordance | Where do the classifiers agree, and where does each stand alone? |
| Classifiers | Confidence | How close are the reads to the genomes sylph matched? |

[nf-core/taxprofiler](https://nf-co.re/taxprofiler) is a benchmarking pipeline as much as a
profiling one: it runs one set of reads through as many classifiers and reference databases
as asked, and standardises every result with [taxpasta](https://taxpasta.readthedocs.io) so
the answers can be put side by side. A profiling run is a sample plus a classifier plus a
database (`profiler_db`): kraken2 against two databases is two answers. The template has no
group variable; the classifier (`profiler`) and the sequencing platform take the place of a
design column.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the samples, classifiers and
  databases of the run and its read QC tools (`shortread_qc_tool`, `longread_filter_tool`,
  read from the run parameters).
- **Pipeline**: six steps (clean, depth, profile, standardise, compare, confirm). Each step
  opens the parameters that drive it and the tab that shows its output.
- **Key figures**: four headline cards, each opening the tab that explains it, all on the
  taxpasta collections every run writes. Profiling runs (split by classifier), the median
  reads assigned per run and the median Shannon diversity (each with its spread), and the
  median number of classifiers per taxon call (against 2, a shared call). A classifier and a
  sample filter above them narrow these four only.
- **Findings**: result rows whose values are computed under the filters, each with a link
  to its tab: the most abundant phylum of the species-level profiles and its share, the
  median Shannon diversity, the taxon calls two classifiers or more share, and the median
  identity of the reads to the genomes sylph matched. Below them, four figures in two rows,
  each linking its tab: the composition per profiling run beside richness against diversity,
  then the PCoA of the profiles beside sylph identity against abundance. The bar of this
  section filters by platform and sample.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (platform, sample, sequencing run) sit in the collapsed left
panel and narrow every tab: they read the sample sheet, and the template's links fan a pick
out to every taxpasta collection, both sylph tables, the Nonpareil collections and the
MultiQC panels. The sequencing-run filter is a MultiSelect: the sheet is read as text, so
numeric and ERR/SRR accessions behave the same. The `Sample sheet` and `Database sheet`
sections are pinned to the bottom of every child tab, collapsed, and absent from the
Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to
read the tab), then a strip of four key numbers, each card with its own colour and a
secondary that reads it, then at most three open sections; tables and details follow,
collapsed.

**MultiQC.** MultiQC panels only. Open: general statistics, fastp filtered reads, FastQC
quality before trimming, then the host alignment (Bowtie 2) and the share mapped to the host
(samtools). Collapsed: FastQC counts and the read lengths after trimming (taxprofiler runs
FastQC twice, and MultiQC labels the second run `fastqc-1`), nanoq's long-read summary and
Nonpareil's redundancy levels; then each classifier's own top-taxa panel (kraken2, bracken,
centrifuge, kaiju, metaphlan) and MALT's mappability. Its own sample filter reads the MultiQC
report, so it works on a run whose sample sheet was not found.

**Sequencing depth.** Strip: the median metagenome coverage (against 95%, Nonpareil's
target), the median Nonpareil diversity (with its spread), the median effort sequenced (its
distribution) and the depth still needed (how many times deeper the median library would
have to go, against 1). Then the coverage curve of each library and coverage against
diversity, the depth still needed as the point size. Collapsed: the Nonpareil table.
Filters: coverage and diversity ranges. taxprofiler publishes only six fitted numbers per
library, so the curve is rebuilt from the model (a gamma CDF over the log of the effort,
200 points per library); feeding each library's own effort back through it reproduces the
published coverage to within 0.05. Nonpareil runs on the short reads only.

**Profiles.** Strip: distinct species named (by classifier), the median reads per taxon call
(with its spread), the median unclassified share of a run (its distribution, for the
classifiers that report one) and the largest share one named taxon holds (by classifier,
unclassified reads left out). Then the composition: one bar per profiling run, so a bar
never mixes two naming vocabularies, species by default, the eight largest taxa and Other,
the classifier named on the axis and the rank in the tile's settings. Species, not genus:
kraken-style classifiers report direct counts, so their genus rows hold only the reads that
stopped at a genus, and classifiers that report species only have no genus rows. Then the Krona rings, one wedge per classifier with its domains, phyla
and classes fanning out, and sylph's containment composition (the same eight and Other).
Collapsed: melon's genome copies (a sunburst, the copies per species and the table, pooled
over the long-read samples) and the profile tables (the long cross-classifier table, its
lineage copy and the sylph clades). Filters: classifier, database, abundance range, domain
and the melon phylum, the only filter that reaches melon's pooled table.

**Diversity.** Diversity is computed per profiling run, so one sample has as many values as
classifiers that profiled it, and the spread between them is classifier disagreement. Strip:
the median Shannon diversity (with its spread), taxa observed (the richest classifiers
first), evenness (its distribution) and the top-taxon share (with its spread). Then richness
against diversity (one point per run, colour the classifier, symbol the platform), the dot
plot of each run's diversity and top-taxon share, and the rank-abundance accumulation over
the classified part of each profile (the unclassified row left out, the rest renormalised): a
curve that reaches one after a handful of taxa is a profile carried by a few organisms.
Collapsed: the per-run table. Filters: classifier, richness and evenness ranges.

**Concordance.** Strip: runs ordinated (a ring by classifier), classifiers per taxon call
(its distribution), detected taxa (by rank) and the phyla in the flow (by classifier). Then
the Bray-Curtis PCoA of every profiling run (axes PCo1 and PCo2, a lasso selects runs and
narrows the flow), the UpSet of the taxa each set of classifiers found, and the taxonomic flow
from the root to the phylum (the depth picker goes down to species), the unclassified reads as
a band of their own. Collapsed: the
taxon by run heatmap. Filters: classifier, platform, classifiers per taxon, domain and the
flow classifier.

**Confidence.** sylph reports, for every reference genome it detects, the adjusted ANI of the
match beside its abundance, so a high-abundance, low-identity genome reads as the divergent
relative it is. Strip: the median adjusted ANI (against 95%, the species boundary), distinct
genomes (over all detections), the median effective coverage (with its spread) and the
detections (the spread of their abundance). Then the ANI dot plot by genome and sample, and
identity against abundance beside the record card of the genome picked on it. Collapsed: the
containment table. Filters: ANI and abundance ranges.

## Routes and pruning

taxprofiler runs any subset of its classifiers. The taxpasta collections need only
`--run_profile_standardisation`, whatever classifiers ran, and carry the Overview's key
figures. Everything else is `optional: true`: a run that did not produce a collection loses
its tiles, a tab left without data is dropped, and so are the Overview rows and highlights
that pointed at it.

| Route | What changes |
|---|---|
| No `--run_sylph` | No Confidence tab, identity row or highlight, and no sylph composition on Profiles. |
| No `--run_melon` or no long reads | No genome copies section. |
| No `--perform_shortread_redundancyestimation` | No Sequencing depth tab. |
| No sample sheet found | No persistent filters, sample sheet or Findings bar; each tab keeps its own filters. |
| No kraken2, krakenuniq or centrifuge | Taxa keep a `taxid <id>` label: `taxon_names` reads the names from those reports. |

The import re-packs the Overview grid after a drop, so a lone highlight takes the full row.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab. The classifiers
are pinned, so a run with another subset keeps its colours; the platforms and the domains
(`unclassified` and `unresolved` grey) are written out. Phyla, genera and species are coloured
`auto:rel_abundance`: the eight most abundant of the run take the palette, largest first,
so both stacked compositions, the rings and the flow give a taxon the same colour, and Other
is grey. The accumulation curve reads the classifier colours through
`depictio_category_colors`.

## Cross-selection

A picked row or point becomes a dashboard filter that narrows the other tiles of its
collection and follows the project links to the collections they reach. The sample sheet
selects on `sample` (every collection and the MultiQC panels); the PCoA, the diversity
scatter and the per-run table on `profiler_db`; the Nonpareil scatter and table on
`library`; the profile and lineage tables on the taxon `name`; the sylph clades on
`clade_name`; the melon table on `species`; the sylph scatter and table on `genome`, the
scatter feeding the record card beside it. The database sheet selects nothing: no other tile
reads it.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top
of a narrower one. Nothing is set per tab or per tile.

## Catalog modules

| Module | Output | What it is |
|---|---|---|
| `taxpasta` | `taxpasta_profiles` | Every standardised table melted into one long classifier x database x sample x taxon frame |
| `taxpasta` | `taxpasta_lineage` | The same rows with the NCBI ranks widened into columns, the ancestry read back out of the indented kraken-style reports |
| `taxpasta` | `taxpasta_matrix` | The top taxa as a wide taxon by run matrix |
| `taxpasta` | `taxpasta_embedding` | Bray-Curtis PCoA over every profiling run |
| `taxpasta` | `taxpasta_presence` | Per sample and taxon, a 0/1 detection column for every classifier |
| `taxpasta` | `taxpasta_sample_summary` | Taxa reported, reads assigned, top-taxon share, Shannon and evenness per run |
| `sylph` | `sylph_ani` | Per-genome containment: adjusted ANI against abundance and coverage |
| `sylph` | `sylph_profile` | The sylph-tax merged report as a long sample x rank x taxon composition |
| `melon` | `melon_ranks` | Genome-copy composition, seven ranks wide, pooled over the long-read samples |
| `nonpareil` | `nonpareil_summary` | Coverage, projected effort and diversity index per sequencing library |
| `nonpareil` | `nonpareil_curves` | The coverage curve each library's fitted model describes |

One recipe is project-local rather than catalog: taxprofiler runs taxpasta without names,
so the standardised tables identify taxa by NCBI id only, and
`depictio/projects/nf-core/taxprofiler/recipes/taxon_names.py` reads the names and ranks back
out of the kraken2, krakenuniq and centrifuge reports the pipeline also writes. MultiQC has
no Bracken or Centrifuge module, so nf-core/taxprofiler runs the `kraken` module three times
with different `path_filters`; their catalog entries find kraken-style reports.

## Reproducing

```bash
bash depictio/projects/nf-core/taxprofiler/2.0.1/download_test_data.sh
# fetches the test data subset and the sample and database sheets into <DATA_ROOT>/input/
depictio-cli ingest --template nf-core/taxprofiler/2.0.1 --data-root <DATA_ROOT>
```

No `--var` is needed: the `run_*` and `perform_*` flags come from
`pipeline_info/params.json`, and every classifier-specific collection is optional, so a run
with a different classifier set ingests unchanged and shows fewer tiles. Leave
`--project-name` off: `dashboard import` resolves `project_tag: Taxprofiler Metagenomic
Profiling` by name, so a renamed project cannot take a re-imported dashboard later.
