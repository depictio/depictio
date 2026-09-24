# nf-core/eager 2.4.5: Depictio dashboards

This template turns the output of [nf-core/eager](https://nf-co.re/eager) 2.4.5 into a
single six-tab Depictio dashboard. eager trims and collapses ancient-DNA reads, maps
them, deduplicates, profiles the misincorporation damage pattern that says whether the DNA
is really ancient, and genotypes what is left. The dashboard follows that chain; the
optional branches (sex determination, contamination, metagenomic screening) are folded
into the tab whose question they answer and appear only when the run enabled them.

The template was validated on the AWS megatest run
`results-42c9d5f8602e5e88fdcec28f194d2cd4cff61c75` (the 2.4.5 release tag; see
`megatest.yaml`). No dashboard text names that run's samples, organism or contigs.

> **This template reads a REPROCESSED MultiQC report.**
> eager 2.4.5 published MultiQC 1.13.dev0, which writes `multiqc_data.json` and no
> parquet. Depictio reads only `multiqc.parquet` (MultiQC 1.31 and later), so the MultiQC
> tab is bound to a report this repository generates by re-running the pinned MultiQC 1.35
> over the run's own raw tool outputs. See `VALIDATION_REPORT.md`.

> **Copy the run's `--input` TSV under `{DATA_ROOT}/input/`.**
> eager 2.x does not publish its samplesheet. The two recipes that read it
> (`eager/samples.py`, `eager/lane_stats.py`) take any `input/*.tsv`, so copy the TSV the
> run was launched with there. For the megatest, `input/benchmarking_vikingfish.tsv` in
> this template directory is a hand-reconstructed manifest against the six ENA runs the
> megatest fetched.

---

## How the dashboard is built

- **Six tabs, one question each.** MultiQC (the report), Run and library hub (which
  libraries, from how many lanes, compared on every tool), Reads and read fate (where every
  read stops, and what each lane returned), Mapping, endogenous DNA and duplication (how
  much of the extract is the organism, and what the rest is when a screen ran),
  Authentication (is it ancient, and how contaminated), Coverage, sex and genotyping (per
  contig, distribution, locus, variants).
- **The library hub is the hub.** `samples` is one row per eager LIBRARY (`Library_ID`).
  The pinned `Sample scope` filters (library, sample, UDG treatment) fan out through the
  template links to the MultiQC panels and every per-library table. The two bcftools
  collections key on `Sample_Name` (bcftools reads it from the VCF header), so the hub
  carries both ids and two links on `sample_name`.
- **QC thresholds reach every tab.** The pinned, collapsed `QC thresholds` section filters
  the Qualimap BamQC summary (coverage, duplication) and endorS.py (endogenous DNA). Both
  collections link back to the hub, so a floor narrows the hub and the hub fans the
  surviving libraries out (filters travel up to three links).
- **Glance strip: run size and design.** `Run at a glance` is pinned persistent on every
  tab: libraries (by UDG treatment), biological samples (by organism), lanes merged and
  reads sequenced (with the share AdapterRemoval kept). No tab repeats these as cards.
- **Pinned tables.** The library sheet (top, collapsed) and the BamQC summary (bottom,
  collapsed, the table the thresholds read). Neither is repeated in a tab.
- **MultiQC panels once.** The MultiQC tab holds only panels no tile redraws from a tool
  table: general statistics, FastQC, the AdapterRemoval collapsed-read length and the
  bcftools variant panels. Every MultiQC twin of a tile (flagstat, Picard, preseq,
  DamageProfiler, Qualimap, AdapterRemoval retained/discarded) was removed.
- **Every tab has local filters** (`<X> scope`, open): report sample on MultiQC, lane and
  run on the hub, trimming outcome, final fate and lane on read fate (the lane filter
  narrows the per-lane tiles only), filter stage, endogenous DNA after filtering and
  duplication on mapping, read end, position, strand and fragment length on
  authentication, relative depth, contig length, window depth and depth threshold on
  coverage. There is no chromosome filter on the locus tab: the navigator owns the region.
- **Optional branches as hidden tiles.** Sex.DetERRmine, MTNucRatio, ANGSD nuclear
  contamination, MaltExtract and Kraken are `optional: true` collections, each bound to one
  table tile. The import drops a tile whose collection is absent, so a run without the
  branch shows only the two-sentence note of its section.
- **Tab order inside a tab:** cards, distributions, detail, then a collapsed tables section.
- **Everything matches on file name, never on directory names.** `deduplication/<library>/`,
  `damageprofiler/<library>_rmdup/`, `qualimap/<library>_rmdup_stats/` and
  `adapterremoval/output/` encode the library or lane in the path; the catalog recipes
  parse them out of `source_path`, which keeps the template portable to eager 3.x.

### Template variables

| variable | default | use |
| --- | --- | --- |
| `DATA_ROOT` | required | eager output root, plus `input/*.tsv` and the reprocessed MultiQC parquet |
| `SHORT_FRAGMENT_BP` | `70` | short-fragment cut-off. The `damageprofiler/authenticity` recipe receives it as a param and counts the fragments shorter than it (the column keeps the name `fraction_under_70bp`); the Authentication tab names it in its texts |

The locus navigator's `default_region` opens on the first chromosome of the megatest
reference; on a reference without that contig the navigator falls back to the
whole-reference overview. A non-model reference has no GenomeSpy built-in assembly, so the
contig list comes from the data and there is no gene lane.

---

## Reproducing

```bash
bash download_test_data.sh                       # AWS megatest fetch, no input/
mkdir -p ~/Data/depictio-nfcore/eager/2.4.5/megatest/input
cp input/benchmarking_vikingfish.tsv ~/Data/depictio-nfcore/eager/2.4.5/megatest/input/

python -m depictio.dev_scripts.multiqc_reprocess \
  --src ~/Data/depictio-nfcore/eager/2.4.5/megatest \
  --dest ~/Data/depictio-nfcore/eager/2.4.5/megatest

depictio-cli run --template nf-core/eager/2.4.5 \
  --data-root ~/Data/depictio-nfcore/eager/2.4.5/megatest --dry-run
```

---

## MultiQC

The landing tab, MultiQC panels only. `MultiQC overview` holds the general statistics
table, including endorS.py's endogenous DNA percentage (general-stats-only custom content).
`Read quality and trimming` holds FastQC on the raw lanes (counts, per-base quality, GC,
adapter content, duplication levels) and the AdapterRemoval collapsed-read length
distribution. `Variant calling` holds the four bcftools panels (substitution types,
quality, indel lengths, depths) that no tile redraws.

## Run and library hub

`Library QC profile` pools every per-library number eager produces into one row per
library: the pipeline-local `eager/library_qc.py` recipe left-joins the tidied endorS.py,
Picard, Qualimap and DamageProfiler collections on the library id. A
`parallel_coordinates` tile draws one polyline per library across nine axes, each rescaled
to its own range, so the tick values carry the reading. `Library detail` holds the
pooled table with the `Library record` (record_card, no default record) beside it
(`linked_component`): the card stays a thin rail until a row is picked, then opens that
library's record. The per-lane AdapterRemoval
table sits in a collapsed section at the bottom.

## Reads and read fate

One sankey, five stages, and the reads that fall out at each. The pipeline-local
`eager/read_fate.py` recipe chains AdapterRemoval, samtools flagstat and Picard
MarkDuplicates into a single flow, and the accounting is exact rather than apportioned:
AdapterRemoval's identity `2 x total_read_pairs = retained + collapsed + discarded` holds
per lane, and summed over a library's lanes `retained_reads` equals the pre-filter flagstat
total, so the reports chain without a fudge factor. Collapsing is an outflow at the
trimming step: one read of each merged pair stops existing there, and no report says which
survivors were merged.

`Lane yield` (moved here from the hub) reads the pipeline-local `eager/lane_stats.py`
output: `adapterremoval/settings` joined to the samplesheet on a key rebuilt from the R1
file name plus the `Lane` column. Reads kept per lane, collapse rate against retained
length (`adapterremoval/collapse_vs_length`) and the discard share per lane.

## Mapping, endogenous DNA and duplication

`Endogenous DNA` binds `endorspy/endogenous` (the `*_endogenous_dna_mqc.json` files read
directly): before, after, the loss between them, and the reads given to the mapper. That
last card reads samtools flagstat scoped to `stage == pre-filter` (`filter_expr`), because
flagstat has one row per library and filter stage and an unscoped sum counts every read
twice. The before/after scatter puts the on-target signal lost to filtering below the
diagonal.

`Alignment` reads `samtools/flagstat` per library and stage. `Duplication and complexity`
binds `picard/markduplicates_metrics` next to `preseq/complexity_curve`, with the
screening plane (endogenous DNA against clonality, marker sized by depth) between them.

`Off-target screen` holds one table per optional screen (MaltExtract authentication
overview, Kraken report) under a two-sentence note; without a screen the section is the
note alone.

## Authentication

`damageprofiler/authenticity` reduces each library to its terminal deamination at both read
ends, the substitution background, and its fragment length statistics including the share
under the short-fragment cut-off. The plane separates what a single number cannot: short
and damaged is ancient, long and undamaged is modern contamination, short but undamaged is
usually over-sheared modern DNA. Below it, one misincorporation profile
(`damageprofiler/misincorporation`: `C>T`, `G>A` and the pooled background by position)
and one fragment-length profile. The earlier line figure and MultiQC twins of both were
removed. DamageProfiler 0.4.9 writes no length-binned damage table, so the profile is not
split by length.

`Contamination` holds one table per optional estimate (ANGSD nuclear contamination,
MTNucRatio) under a two-sentence note.

## Coverage, sex and genotyping

`Per-contig depth and sex` parses the `Coverage per contig` block of `genome_results.txt`
and normalises each contig by the library's own mean: the quantity a sex call (sex
chromosome against autosome depth) and an organelle ratio are made from. The
Sex.DetERRmine table appears here when the run enabled it.

`Depth distribution`: `qualimap/coverage_histogram` (bases at each depth) and
`qualimap/genome_fraction_coverage` (share covered at least that deep).

`Depth along the reference` is a locus section. `qualimap/coverage_across_reference` maps
Qualimap's windows (written on one concatenated axis) back onto their contigs with a
per-sample `join_asof` against the per-contig lengths. The navigator is a `genome_view` on
those windows; a `coverage_track` under it draws mean mapping quality from the
pipeline-local `eager/mapq_across_reference.py`, and a `region` link carries the
navigator's chromosome and position onto that collection, so a brush or a typed locus
moves both tracks and the cards together.

`Variant calls` binds `bcftools/stats_summary` and `bcftools/stats_tstv` (keyed on
`Sample_Name`). The Ts to Tv expectation lives in its card's description: deamination read
as variation pushes the ratio up.

---

## Cross-selection

A picked row or point becomes a dashboard filter that narrows the other tiles of its
collection and follows the project links to the collections they reach. The pinned sample
sheet selects on `sample_id` and the Qualimap reference table on `sample`; the lane table and
the lane yield scatter select on `lane_id`; every per-library table and scatter of the
mapping, authentication and coverage tabs selects on `sample`, as do the fragment length
and genome fraction profiles. Not selectable: the complexity curve and depth histogram
profiles and the coverage track (no outgoing link and no sibling tile to narrow), and the
raw MaltExtract, Kraken, contamination and Sex.DetERRmine tables, whose columns are not
declared. The endogenous-against-clonality scatter emits a selection, but its collection
has no outgoing link, so it narrows no other tile.

## Note: the preseq recipe here is pipeline-local, not the shared catalog one

`depictio/catalog/preseq/complexity_curve.py` recovers the library name from the file name
via `depictio.recipes.lib.sample_ids.strip_stage_suffixes`, which strips known
dot-separated stage tokens (`ccurve`, `mkd`, `sorted`, ...). eager's own `preseq lc_extrap`
step writes `<library>.filtered.preseq`: `filtered` and `preseq` are not in that shared
list, so the helper would hand back the file stem unchanged rather than the library id.
Rather than widen a list shared by every other pipeline that reuses it on behalf of one
pipeline's naming, `depictio/projects/nf-core/eager/recipes/complexity_curve.py` matches
eager's fixed suffix directly and keeps the rest of the catalog recipe's contract,
including the `profile` kind's decimation rule (<= 200 points per library, never sampled),
unchanged. The dashboard still binds `use: preseq/complexity_curve`: the output schema is
byte-identical, only the file that produces it differs. eager's own `lc_extrap` run also
wrote no bootstrap confidence interval, so `lower_ci`/`upper_ci`/`ci_width` are present
(the `profile` kind's optional band roles need the columns to exist) but always null.
