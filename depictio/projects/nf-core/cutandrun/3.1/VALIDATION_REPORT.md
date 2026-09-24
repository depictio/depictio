# nf-core/cutandrun 3.1: template ingestion validation report

**Date:** 2026-09-05
**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-lot1`
**Validator:** local depictio-cli (`depictio/cli/.venv`) against the local docker stack
(instance `feat-nfcore-templates-lot1`, API `:8101`, MinIO `:9101`,
config `~/.depictio/CLI.feat-nfcore-templates-lot1-101.yaml`).

## Goal

Build the cutandrun 3.1 template plus the `seacr` catalog tool it needs, reuse the `macs2`
tool the chipseq workstream built, and drive `depictio-cli run` against the real AWS megatest
output end to end. cutandrun is the third and last pipeline in this lot whose MultiQC report
predates the parquet era, and the only one that runs two peak callers over the same
fragments, which is what the template's middle tab is about.

## Data used

AWS megatest run
`s3://nf-core-awsmegatests/cutandrun/results-42502fb44975e930eec865353c5481f472bcf766/`
(the 3.1 release tag). Six samples: H3K4me3 and H3K27me3 in two replicates each, plus two IgG
controls. All six reach the read QC panels; the four target samples reach the peak
collections, because SEACR calls the targets against the controls and a control has no peaks
of its own.

```bash
python scripts/nfcore_megatest.py fetch --pipeline cutandrun --version 3.1 \
  --dest ~/Data/depictio-nfcore/cutandrun/3.1/megatest
# or, equivalently:
bash depictio/projects/nf-core/cutandrun/3.1/download_test_data.sh
```

The manifest (`megatest.yaml`) fetches 103 files, 89.8 MB: the samplesheet, the software
versions, the original MultiQC 1.14 report's provenance files, every raw MultiQC input
(FastQC zips, Trim Galore reports, bowtie2 logs for both the target genome and the spike-in,
samtools stats, flagstat and idxstats, deepTools fingerprint, PCA and correlation tables),
the SEACR stringent peak calls, the MACS2 peak calls, the per-target consensus peak counts
and the fragment-length tables. No BAM, no FASTQ, no bigWig.

## MultiQC was reprocessed: 1.14 to 1.35

cutandrun 3.1 published MultiQC 1.14, which writes `multiqc_data.json` and no parquet.
Depictio reads only `multiqc.parquet` (MultiQC 1.31 and later), so the QC tab is bound to a
report this repository generates:

```bash
python -m depictio.dev_scripts.multiqc_reprocess \
  --src  ~/Data/depictio-nfcore/cutandrun/3.1/megatest \
  --dest ~/Data/depictio-nfcore/cutandrun/3.1/megatest
```

102 inputs were staged. `REPROCESSED.json` records `source_version 1.14`, `reprocessed_with
1.35` and seven modules: `bowtie2`, `cutadapt`, `deepTools`, `fastqc`, `macs`, `samtools` and
the software-versions section.

Unlike chipseq and atacseq, whose reports predate the parquet by a whole major era, 1.14 is
close enough to 1.35 that the module set is unchanged by the upgrade: the reprocess here buys
the format, not new panels. `template.yaml`'s `dc_specific_properties.modules` and `plots` and
every `selected_module` / `selected_plot` in `dashboards/base.yaml` are nonetheless authored
against the 1.35 anchors and were verified against them, not against the published report.

## Ingestion result: 11 / 11 data collections processed, exit 0

```bash
depictio/cli/.venv/bin/python -m depictio.cli run \
  --CLI-config-path ~/.depictio/CLI.feat-nfcore-templates-lot1-101.yaml \
  --template nf-core/cutandrun/3.1 \
  --data-root ~/Data/depictio-nfcore/cutandrun/3.1/megatest
```

`--project-name` was deliberately left off, so the project carries the name the template
declares (`CUT&RUN Chromatin Profiling`, id `6a9c3854f6eeff965a1052d8`, dashboard
`6a9c386430851b3fe1718358`). Delta tables read back from MinIO after the run:

| Data collection | Rows | Columns |
|---|---|---|
| `multiqc_data` | 1 report, 7 modules | (MultiQC parquet, not Delta) |
| `samples` | 6 | 9 |
| `samplesheet` | 6 | 10 |
| `seacr_peaks_raw` | 433,629 | 9 |
| `seacr_peaks` | 433,629 | 12 |
| `seacr_peak_summary` | 4 | 11 |
| `macs2_peaks` | 17,486 | 11 |
| `seacr_consensus_peaks` | 274,445 | 16 |
| `seacr_fragment_lengths_raw` | 2,713 | 5 |
| `seacr_fragment_lengths` | 2,713 | 6 |
| `caller_agreement` | 8 | 13 |

Two collections exist only so another can read them back through `dc_ref`
(`seacr_peaks_raw` -> `seacr_peaks`, `seacr_fragment_lengths_raw` ->
`seacr_fragment_lengths`): the sample id lives in the file NAME and only a scan carries the
path into the frame. Each referenced collection is declared **before** the collection that
reads it and ingestion stays sequential.

All four dashboard tabs imported (`Sequencing and enrichment QC` + `Peak calls` + `Caller
agreement` + `Consensus and reproducibility`, 35 + 20 + 13 + 13 = 81 components across 23
sections: 24 cards, 15 text tiles, 12 MultiQC panels, 11 interactive filters, 9 figures, 6
tables and 4 advanced visualisations). 41 of those tiles carry a `use:` catalog reference
that resolved (`seacr/*` 23, `multiqc/*` 12, `macs2/*` 6).

## Post-ingest verification

Every collection was read back from its Delta table in MinIO and every tile grounded against
the real frame. No FILTER MISMATCH, no 4xx, no 5xx.

**Components (81/81).** Every component resolved, all 122 named columns exist in the bound
collection, and the six catalog render roles bind columns that are present.

**Code-mode figures (4/4).** All four exec against their frame with the viewer's scope and
return a plotly `Figure`: fragment length distribution 4 traces, signal along the genome 3,
MACS2 against SEACR per sample 2, reproducible share per target 2. The other five figures are
UI mode, where a plain express call suffices.

**Cards (24/24).** `bulk_compute_cards` returns a non-null value for every card unfiltered
and a different value under the persistent sample filter, with one exception that was checked
and is genuine: `Best q-value` is `max(neg_log10_qvalue)` over the MACS2 calls and the
strongest peak (407.14) survives the filter. Headline numbers: 433629 SEACR regions, median
width 623 bp, 17486 MACS2 peaks, median MACS2 width 1069 bp, mean fold enrichment 10.9, 54.6 %
of calls reproduced by the other caller, 274445 consensus intervals, 1.37 replicates per
interval.

**Advanced visualisations (4/4).** All four project their bound columns through
`POST /advanced_viz/data`, unfiltered and with the sample filter applied: SEACR signal
manhattan 9800 of 433629 rows (sampled), MACS2 significance manhattan 8763 of 17486
(sampled), the caller dot plot 8 of 8 (not sampled), the consensus UpSet 274445 of 274445
(not sampled, as the kind demands).

**Unit tests.** `depictio/tests/models/test_catalog.py` and
`depictio/tests/models/test_shipped_dashboard_yamls.py` pass on the staged tree.
`python -m depictio.cli dev catalog validate`: 33 catalog tools valid.

## MultiQC overlap policy

| Signal | Decision |
|---|---|
| Read counts, quality, GC, adapters, trimming | **MultiQC** (`use: multiqc/fastqc`, `use: multiqc/cutadapt`) |
| Alignment to the target genome and to the spike-in | **MultiQC** (`use: multiqc/bowtie2`) |
| Mapping rate, insert size, per-contig distribution | **MultiQC** (`use: multiqc/samtools`) |
| Enrichment over the IgG control, sample PCA and correlation | **MultiQC** (`use: multiqc/deeptools`) |
| Per-region coordinates, width, total and maximum coverage | **Dedicated** (`seacr/peaks`): MultiQC has no SEACR module at all, in any version |
| Per-sample SEACR yield and coverage summary | **Dedicated** (`seacr/peak_summary`) |
| Consensus intervals and replicate support | **Dedicated** (`seacr/consensus_peaks`): MultiQC has no set-intersection view |
| Fragment length ladder | **Dedicated** (`seacr/fragment_lengths`): cutandrun writes `*.frags.len.txt` that no MultiQC module reads |
| MACS2 peak coordinates and significance | **Dedicated** (`macs2/peaks`, reused from chipseq): the MultiQC `macs` module exposes no plot, only general-statistics columns |
| Agreement between the two callers | **Dashboard-side** (`recipes/caller_agreement.py`): a composition across two collections, which the catalog policy keeps out of the catalog |

New catalog entries created here: the `seacr` tool (`peaks`, `peak_summary`,
`consensus_peaks`, `fragment_lengths`). All four are pipeline-agnostic and matched on file
name, so any CUT&RUN-family pipeline that runs SEACR lands in the same collections.

## Discrepancies

### CR-D1: the run root is a numbered stage tree, and the template pins it

cutandrun 3.1 publishes its output under `01_prealign/`, `02_alignment/`, `03_peak_calling/`
and `04_reporting/`. The manifest's keys spell those prefixes out, because the alternative
(matching on file name alone across the whole tree) would pull the spike-in alignment
statistics into the target-genome collections. Every recipe still matches on file NAME, so
the collections themselves are layout-independent; only `megatest.yaml` knows about the
numbering. A 3.2 or later run that reorganises the tree needs the manifest updated and
nothing else. This is the first thing to check before bumping the template version.

### CR-D2: MultiQC 1.14 is above the reprocess floor for modules but below it for the parquet

1.14 already parses every module 1.35 does for this run, so unlike chipseq (which gained
nothing but the format) and atacseq (which gained a whole `ataqv` module), the reprocess here
changes only the on-disk format. It is still mandatory: without it `multiqc_data` finds no
parquet and the whole QC tab is empty. Recorded because it is the counter-example that keeps
"reprocessing adds panels" from being read as a general rule.

### CR-D3: `macs2_peaks` is the only optional collection, and the agreement tile is not covered by it

`--peakcaller seacr` is a legitimate cutandrun run and produces no `macs2/` tree, so
`macs2_peaks` is declared `optional: true` and its four cards, its manhattan panel and its
table prune cleanly. `caller_agreement` is different: it is a join of the two callers per
sample, and with one caller present it degrades to a table saying each caller agrees with
itself, which reads as 100 % agreement rather than as missing data. The optional flag covers
the collection but not the derived comparison. A run with `--peakcaller seacr` is the
scenario to check (see `VALIDATION_SCENARIOS.md`, C2).

### CR-D4: SEACR's schema is not MACS2's, which is why it needed its own tool

SEACR calls regions from fragment coverage rather than from a background model, so a SEACR
row carries a total signal, a maximum signal and the sub-interval where that maximum was
reached, and no p-value and no fold enrichment at all. `macs2/peaks` cannot read it and a
shared output would have to make half its columns nullable. The `seacr` tool therefore
declares its own schema, and the two callers meet only in `caller_agreement`, which joins
them on `sample`.

That difference is also why the two manhattan panels on the Peak calls tab bind different
scores: the SEACR panel plots `log10(total signal)` at the maximum-signal position, the MACS2
panel plots `-log10(q)`. They are not comparable on the y axis and the tab's text tiles say
so.

### CR-D5: the IgG controls are samples everywhere except in the peak collections

`samples` and `samplesheet` hold six rows; `seacr_peak_summary` holds four. The two IgG
controls are what SEACR calls the targets *against*, so they have no peaks of their own. The
persistent sample filter is on the hub, which carries all six, and the `Role` control in the
left rail is a single-choice `Select` so that picking `control` visibly empties the peak
panels rather than silently showing the targets.

### CR-D6: two thirds of the consensus intervals are called by one replicate only

174048 of the 274445 consensus intervals (63 %) have `support = 1`. That is a property of
this megatest, not of the template: H3K27me3 is a broad mark and its two replicates overlap
poorly. It matters when reading the dashboard, because the consensus cards average over a set
that is mostly single-replicate, and it is why the `Replicate support` filter defaults to
showing all values rather than to the reproducible subset. The UpSet panel is the tile that
shows the split directly.

### CR-D7: the UpSet compute is asynchronous and can answer empty on first read

`POST /advanced_viz/data` returns the projected columns for the consensus UpSet immediately
(274445 of 274445 rows), but the intersection computation itself is a background job:
`/compute_upset` answered `upset job pending: 0 intersections` on the first probe after
ingest. Re-reading once the job completes returns the intersections. Nothing to fix in the
template, but a verification script that asserts on the intersection count has to wait for
the job rather than read once.

### CR-D8: no `params.json`, so nothing is auto-detected from the run

The fetched `pipeline_info/` carries the software versions (both
`software_versions.yml` and the pipeline's own `local_versions.yml`) but no `params*.json`,
so `_introspect_pipeline_params` sets no template variable and the template exposes
`DATA_ROOT` alone. Provenance is collected from the two version files. Nothing degrades:
there is no metadata-gated conditional in this template.

### CR-D9: the MultiQC tab's opening strip was four non-MultiQC cards, and three of them were duplicates

`Run at a glance` opened the MultiQC tab with four cards that no MultiQC module feeds: three
read `seacr/peak_summary` and one read `samples`. A tab named MultiQC holds MultiQC panels
only, so all four left the section.

The three SEACR cards were not moved to the Peak calls tab, they were deleted. That tab's
`SEACR peak yield` row already carries the same four statements over `seacr/peaks`, the
per-region collection the summary is an aggregate of, and with the same secondary layouts:
`SEACR regions called` (sum of `num_peaks`, top 3 by sample) restates `Regions in view`
(count of `peak_id`, top 3 by sample); `Median region width` box-plots four per-sample
medians where `Region width` box-plots every region; and `Coverage per base` was duplicated
verbatim, same title, same `threshold_value: 50` and `threshold_warn: 25`. Moving them would
have put two identically titled cards on one tab and made the row ragged at seven cards. The
per-sample summary itself is not lost: `cr-ref-table-summary` carries it in the pinned
`Reference tables` section on every tab, and the two `QC thresholds` sliders still read it.

`Samples by role` moved into the pinned `Sample sheet` section, which is the section that
owns the `samples` collection, so the donut now rides along on every tab instead of only the
MultiQC one. A lone `w: 2` card would have left six empty columns, so it sits beside the
section intro (`w: 6`) rather than on a row of its own; the intro grew to `h: 2` to keep its
prose inside the narrower tile.

What is left in `Run at a glance` is the `General statistics` panel, moved up from
`Read quality`. The section keeps the tab's opening orientation without being empty, its
content is a MultiQC panel, and `Read quality` is four FastQC and cutadapt panels in two full
rows. The text tiles on both sections were rewritten: the old opener announced "four cards
for the peak yield", and the `Reference tables` opener pointed at "the QC cards" that no
longer exist.

Still stale after this change: `docs/dashboards.md` describes `Run at a glance` as a
four-card strip.

---

# 2026-09-22: remediation pass

**Date:** 2026-09-22
**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-lot2`
**Validator:** local depictio-cli against the lot 2 docker stack (port offset 112: API
`:8112`, MinIO `:9112`, dev viewer `:5612`), against the same megatest data as above.

## What changed

The version pin is unchanged and deliberately so (CR-D10). The template went from 11 to 18
data collections and from 4 to 5 tabs, and the two recipes that used to live inside the
project moved into the catalog.

| Added | Home | Rows on the megatest |
|---|---|---|
| `bowtie2_logs_raw` | raw scan of `*.bowtie2.log`, both log sets in one collection | 72 |
| `bowtie2_spikein_factors` | new catalog tool `bowtie2` (`spikein_factors.py`) | 6 |
| `seacr_fragment_classes` | new output on the existing `seacr` tool | 16 |
| `frip` | new catalog tool `cutandrun` (`frip.py`) | 8 |

`samples.py` and `caller_agreement.py` moved out of
`depictio/projects/nf-core/cutandrun/recipes/` and into the new `cutandrun` catalog tool.
That directory is now empty: the template owns no code of its own, and every tile on it has
a catalog home.

New tab `Signal` (tab 2) takes the fragment ladder and the deepTools tables off the QC tab
and hosts the two new signal sections, `Nucleosome classes` and `Spike-in normalisation`.

Fixed from the audit, in the order the findings were raised:

* the lone card at the old `base.yaml:336` is gone; every tab now opens with a four-card
  strip (`w: 2`, `h: 2`, at `x` 0 / 2 / 4 / 6), multi-metric, over the tab's own collection;
* both ragged rows on the `Caller agreement` tab (old `:1272` and `:1337`) fill their eight
  columns, and every `y` below them was recomputed;
* `seacr_peak_summary` is a four-row table, so its tile is `h: 3` rather than `h: 4`;
* `replicate` is exposed as a persistent factor filter beside `sample` (CR-D15);
* every tab carries filters on two levels: the pinned persistent sample and threshold
  sections, plus a tab-local section on the tab's own collections. No tab has an empty
  `filter_sections` any more;
* `megatest.yaml` is de-anchored from the numbered stage tree (CR-D17), which supersedes
  CR-D1.

## Post-ingest verification (2026-09-22)

`depictio-cli run --template nf-core/cutandrun/3.1 --data-root
~/Data/depictio-nfcore/cutandrun/3.1/megatest`: 18 / 18 data collections processed, 8 / 8
steps, exit 0. No pre-existing "CUT&RUN Chromatin Profiling" project needed deleting.
Project `6ab2aa3ad486f8485e1a87ed`; dashboards `6ab2aa58fbe776a1a573e2a1` through
`...e2a5`, one document per tab.

Row counts read back from the Delta tables through `GET /deltatables/specs/{id}`:

```
samples                    6      seacr_peaks              433629
samplesheet                6      seacr_peak_summary            4
bowtie2_logs_raw          72      macs2_peaks               17486
bowtie2_spikein_factors    6      seacr_consensus_peaks    274445
seacr_fragment_lengths  2713      seacr_fragment_classes       16
frip                       8      caller_agreement              8
```

Headline numbers on the three new collections, from the same specs:

* spike-in factors: alignment rate to the target genome 75.73 % to 88.92 % (mean 84.96),
  spike-in reads 179 to 62845 per library, spike-in fraction 0.006 % to 3.06 %, scale factor
  0.1591 to 55.8659 (median 14.66). Six rows, one per library, IgG controls included;
* nucleosome classes: 7051185 fragments over four classes and four target samples, class
  fractions 6.36 % to 56.31 %, class medians 59 bp to 573 bp, mononucleosome to
  sub-nucleosome ratio 3.14 to 8.47;
* FRiP: eight rows, two per target sample, `In peaks` and `Outside peaks`. Coverage in peaks
  1958573070 bp in total, FRiP 0.6745 to 0.8599 (median 0.7766). The two rows of a sample
  sum to 1.0 by construction, which the `fraction` sum of 4.0 over four samples confirms.

Layout: a checker over all five tabs found 0 overlapping tiles, 0 vertical gaps, and every
row filling exactly eight columns.

Catalog coverage: 118 components, of which 24 text tiles and 19 interactive filters. All 75
remaining tiles carry a `use:` reference and all 75 resolve through `catalog_source_for_use`
(`seacr` 28, `cutandrun` 22, `multiqc` 13, `macs2` 6, `bowtie2` 5, `deeptools` 3). Two of the
interactive filters bind catalog renders as well, so 77 references in total. The audit
measured 80 % before this pass.

Commands run once each:

```bash
uv run pytest depictio/tests/recipes/test_bowtie2_spikein_factors.py \
              depictio/tests/recipes/test_cutandrun_frip.py \
              depictio/tests/recipes/test_seacr_fragment_classes.py   # 15 passed
uv run pytest depictio/tests/models/test_catalog.py                   # 93 passed, 6 failed
depictio-cli run --template nf-core/cutandrun/3.1 --data-root <megatest>   # 8/8 steps, exit 0
```

None of the six `test_catalog.py` failures names `bowtie2`, `cutandrun` or `seacr`: four are
card strip requirements on `cellbender` / `kallisto` / `qcatch` / `simpleaf`, two are the
`funcscan_software_versions` glob tests, one is the committed JSON schema lagging the
`genomespy_track` to `genome_view` rename, and `test_cli_validate_exits_zero_on_bundled_catalog`
fails because catalog loading is all or nothing (see CR-D18). All three tools here load
cleanly through `load_catalog_entries()`.

Screenshots (1600 x 1000, dev viewer), four of five: `1-multiqc.png`, `2-signal.png`,
`3-peak-calls.png` and `4-caller-agreement.png` under `/tmp/claude-502/shots-cutandrun/`.
The fifth tab is CR-D16.

## Discrepancies (2026-09-22)

### CR-D10: 3.1 stays pinned although 3.2.2 exists, and `--peakcaller macs2` would empty three tabs

3.2.2 is the current release, so this template is one minor and two patches behind. It is
pinned anyway: every cutandrun 3.2.x prefix in the megatest bucket is an empty or failed run
(CR-D1's note still holds), so bumping would mean pinning a version with no validated data
behind it. Recorded here so that the staleness is a decision rather than an oversight.

The route that is not covered is `--peakcaller macs2` alone. SEACR is cutandrun's default and
this template is built on it: with MACS2 as the only caller, `seacr_peaks`,
`seacr_peak_summary`, `seacr_consensus_peaks`, `seacr_fragment_classes` and `frip` are all
empty, which empties the `Signal`, `Peak calls` and `Consensus` tabs and degrades
`Caller agreement` to the self-comparison CR-D3 already describes. There are 0 route variants
for it in `VALIDATION_SCENARIOS.md` and none could be built from the bucket. The opposite
route, `--peakcaller seacr`, is covered: `macs2_peaks` is `optional: true` and prunes.

### CR-D11: the spike-in scale factor is recomputed here, not read from a published table

The run publishes no scale-factor table. All 104 fetched files were checked for one before
the recipe was written. cutandrun computes the factor inside the pipeline and applies it to
the bedGraph without writing it out, so `bowtie2/spikein_factors.py` recovers it from the two
Bowtie 2 log sets as `normalisation_c / spikein_aligned_pairs` with cutandrun's default
`normalisation_c = 10000`.

Two independent checks say the recovery is right. First, dividing the recovered factor back
out of the SEACR signal collapses four raw signal-to-fragment ratios spanning 2.3 to 48 into
the band 0.67 to 0.86, which a wrong formula or a reads-instead-of-pairs reading would not
do. Second, that band is a plausible FRiP for a CUT&RUN library, which the raw ratios (above
1, therefore not fractions at all) are not.

A run launched with a different `--normalisation_c` would need that value threaded through.
It is a module constant today, `NORMALISATION_C` in `bowtie2/spikein_factors.py`, because no
`params.json` is published to read it from (CR-D8).

### CR-D12: FRiP here is a fraction of fragment coverage, not a fraction of reads

The name is the field's, the denominator is not. SEACR reports no read count anywhere, so
`cutandrun/frip.py` works in base pairs on both sides: the denominator is
`sum(fragment_length * count)` over the fragment-length histogram, and the numerator is
SEACR's `total_signal` summed over the sample's regions, de-scaled by CR-D11's factor. For a
uniform read length the two definitions agree; for a library with a wide fragment ladder they
differ, and this one is the more faithful of the two for CUT&RUN, where fragment length is
the signal.

The ratio is clipped at 1 with `min_horizontal`. An imperfect factor then shows as a
saturated split (`Outside peaks` at 0) rather than as a fraction above 1. No sample on the
megatest hits the clip.

### CR-D13: the SEACR manhattan was dropped from `Signal along the genome`

That section now carries a `genome_view` tile (`mark: rect`, `end_col: end`, so a region is
drawn at its true width) and a `coverage_track` tile on the same `seacr/peaks` collection.
Keeping the old manhattan would have put three genome-axis views of one table in one section,
two of them saying the same thing less precisely: the manhattan plots one point per region at
the maximum-signal position, which the `genome_view` rect supersedes.

The `coverage_track` tile is deliberate redundancy and not a duplicate: it is the fallback if
the GenomeSpy renderer is unavailable (CR-D16), and it reads the same columns through a
renderer with no WebGL dependency. The MACS2 manhattan on `MACS2 alongside` is untouched:
it plots a different score (`-log10(q)`) that CR-D4 explains is not comparable.

### CR-D14: the glance strip on the MultiQC tab lives in the pinned section

"Every tab opens with a four-card strip" and "a tab named MultiQC holds MultiQC panels only"
(`test_multiqc_tabs_hold_only_multiqc_panels`) cannot both be satisfied by a section on the
MultiQC tab itself, which is what CR-D9 resolved by emptying `Run at a glance` of cards.

The strip therefore sits in the pinned persistent `Sample sheet` section, which the test
exempts explicitly and which rides every tab. One consequence worth knowing when reading a
screenshot: the first strip on the QC tab is the sample-sheet strip, identical on all five
tabs, and the tab's own opening content starts below it.

### CR-D15: `replicate` is an integer, so the factor filter binds a second column

`replicate` is a real samplesheet factor with two distinct values on this run, but it is
`Int64`, and an integer column takes a `Slider` or a `RangeSlider` and never a `MultiSelect`.
A slider over the values 1 and 2 is not a factor control.

`cutandrun/samples.py` therefore carries the same value a second time as
`replicate_label` (`Utf8`, `R1` / `R2`), which is also how the run names its own files, and
the persistent `Replicate` filter is a `MultiSelect` on that. The integer column stays in the
collection for the cards that aggregate it. A reader who edits the dashboard has to know that
the two columns are the same factor.

### CR-D16: the `Consensus` tab could not be screenshotted, for an environment reason

Four of the five tabs were captured clean. The fifth kept failing with
`Failed to fetch dynamically imported module: .../AdvancedVizDispatch.tsx`, which is the
error boundary every `advanced_viz` tile falls into on this stack: the lot 2 dev viewer
container predates the `@genome-spy/core` install and needs an image rebuild that only the
maintainer can run. The dependency is declared and present on the host
(`packages/depictio-react-core` and `depictio/viewer`, 0.88.1), and tabs 2, 3 and 4 did
render their advanced visualisations once it landed, but the failure recurs and is not
something a reload clears.

Nothing in the template is implicated: the tab's YAML is unchanged from the version that
imported and rendered before this pass except for one text intro and one added filter, and
its UpSet panel resolved its columns server side. Validation for this pass was therefore done
through the API (row counts and shapes per collection, dashboard and tab listing) rather than
through the rendered page, and the fifth tab should be screenshotted after the rebuild:

| Tab | Dashboard id | Title |
|---|---|---|
| 0 | `6ab2aa58fbe776a1a573e2a1` | nf-core/cutandrun (the MultiQC tab) |
| 1 | `6ab2aa58fbe776a1a573e2a2` | Signal |
| 2 | `6ab2aa58fbe776a1a573e2a3` | Peak calls |
| 3 | `6ab2aa58fbe776a1a573e2a4` | Caller agreement |
| 4 | `6ab2aa58fbe776a1a573e2a5` | Consensus and reproducibility |

### CR-D17: `megatest.yaml` no longer spells out the numbered stage directories

This supersedes CR-D1. Every key is now anchored on the tool directory or on the file name
that identifies the output, never on `01_prealign/`, `02_alignment/`, `03_peak_calling/` or
`04_reporting/`, which are this run's publishing layout and not part of any file's identity.
Lint rule F7 is satisfied and a run published with a different `--outdir` structure is
matched.

The de-anchored manifest matches exactly the same 102 of the 104 fetched files as the pinned
one did; the two unmatched files are the locally produced MultiQC reprocess artefacts, which
are created after the fetch and are not meant to be matched.

The concern CR-D1 raised, that matching on file name alone would pull the spike-in alignment
statistics into the target collections, is handled rather than avoided: one key,
`*.bowtie2.log`, now collects both log sets on purpose, and `bowtie2/spikein_factors.py`
tells them apart by the `.spikein.` infix in the file name. Three keys keep a directory
segment (`*markdup/*.stats` and its two siblings) because there the directory names the BAM
the statistics describe, which is what excludes the duplicate dedup/ twin of the IgG
controls.

### CR-D18: catalog loading is all or nothing, so a broken tool elsewhere fails this one too

`python -m depictio.cli dev catalog validate` and
`test_cli_validate_exits_zero_on_bundled_catalog` exit non-zero on the tree this pass was
validated on, because another tool being built in parallel in the same shared worktree has a
recipe without a `module.yaml`. `load_catalog_entries()` refuses the whole catalog rather
than skipping the offending directory.

The three tools added or changed here were checked individually through
`load_catalog_entries()` and load cleanly, and the end-to-end `depictio-cli run` above went
through the same loader successfully. This is a property of the shared tree at validation
time, not of the template, but it means the bundled-catalog gate cannot be read as green
until every tool in the lot lands.

## 2026-09-22 review fixes

`collapsed: true` dropped from the pinned `Sample sheet` section and the four cards moved
to its first row (intro text below, hub table last), so the glance strip is on screen at
first paint on every tab. Run-specific prose reworded (`The eight rows ...` and the spike-in
scatter description now describe the mechanism). Not done: rebinding the tab-local
`Alignment scope` (`bowtie2_spikein_factors`). The MultiQC tab renders only the report plus
the pinned `samples` and `seacr_peak_summary` tables, both already filtered, and `samples`
has no numeric column for the two sliders; the `bowtie2_spikein_factors -> multiqc_data`
link is what makes them narrow the report, so the binding is functional as declared.

## 2026-09-23 wave 2b: locus section, fragment pile-up, duplication

What changed:

- Peak calls: `Signal along the genome` became the `Peak calls locus` section. The SEACR
  navigator (`genome_view`, `controls_placement: header`, `region_filter_enabled`,
  `default_region: chr9:130,850,000-131,350,000`) drives three tracks through three new
  `region` links in `template.yaml`: the fragment pile-up (`coverage_track`,
  `views: [track, locus]`), the MACS2 calls and the consensus intervals with the hg38 gene
  lane (`genome_view`, `follow_region_filter`). The `coverage_track` on `seacr_peaks` was
  removed (it doubled the navigator: `test_no_double_track_binding`). The width histogram and
  the total-against-maximum scatter moved to the yield section.
- New catalog output `seacr/frags_profile` (recipe, fixture, renders `frags_pileup_matrix`
  signal_matrix and `frags_pileup_track` coverage_track) over two new optional collections,
  `seacr_frags_raw` (scan of `*.frags.cut.bed`) and `seacr_frags_profile`. Bound on the Signal
  tab (`Fragment pile-up around the peaks`: signal_matrix + a code-mode mean profile) and on
  the locus section. New render `seacr/seacr_consensus_track` (genome_view) in
  `consensus_peaks.yaml`.
- Signal: `Library duplication` section on two new collections, `samtools_flagstat_raw`
  (scan anchored on `markdup/`, the IgG `dedup/` twin would double-count) and
  `samtools_flagstat` (shared `samtools/flagstat` recipe): duplicate share per library and
  against depth.
- `controls_placement: header` on the navigator, the fragment track, the fingerprint
  scatter, the PCA and the caller dot plot; `show_histogram: true` on all 11 RangeSliders.
- `megatest.yaml`: new key `*.frags.cut.bed` (4 files, 168 MB, fetched with
  `scripts/nfcore_megatest.py fetch --key`).

Discrepancies:

### CR-D19: the navigator carries no `assembly`

SEACR calls regions on alt and unplaced contigs (`chr17_GL000205v2_random`, `chrUn_*`).
With `assembly: hg38` GenomeSpy threw `Unknown chromosome/contig` on the first such row and
the tile failed (`Cannot read properties of undefined (reading 'subscribeMarkEvent')`). The
navigator derives its axis from the rows, so gene-symbol search in its locus field is off;
the gene lane rides the consensus track, whose rows arrive already narrowed to chr9. A
renderer-side fix (drop rows on contigs the assembly does not list) would restore both.

### CR-D20: the fragment BEDs are large, so the pile-up keeps 500 regions per sample

`*.frags.cut.bed` holds every fragment (7.05 M rows over the four targets). The raw scan
keeps them (a glob source cannot carry the file path: `pl.read_csv` has no
`include_file_paths` in the pinned polars), and the recipe keeps, per sample, the 500
strongest SEACR regions whose 6 kb windows do not overlap (122 000 rows, 4 s). The locus
fragment track is therefore drawn only inside those windows; the tile description says so.

### CR-D21: the pile-up matrix sits on the Signal tab, not under the navigator

The navigator's region reaches `seacr_frags_profile` through its region link, which on the
Peak calls tab narrowed the matrix to the 20 regions on screen. On the Signal tab the matrix
shows all 2 000.

### CR-D22: the navigator draws a sample of the SEACR calls

`seacr_peaks` has 433 629 rows and the navigator is not narrowed by its own region, so it
shows a sample of them at the default region; the tracks under it are narrowed and complete.

Commands and results:

- `uv run pytest -q depictio/tests/models/test_shipped_dashboard_yamls.py -k cutandrun`:
  10 passed; `test_no_double_track_binding --runxfail` no longer lists cutandrun.
- `uv run pytest -q depictio/tests/models/test_catalog.py depictio/tests/recipes/test_seacr_frags_profile.py`:
  102 passed.
- Recipe on the real megatest files: 122 000 rows, 0 duplicate genomic bins; mean fragments
  per million at the summit against 3 kb: H3K4me3 140.5 / 59.3 against 2.2 / 2.6, H3K27me3
  15.0 / 5.9 against 4.3 / 1.8.
- `depictio.cli run --dry-run`: 8/8 steps.
- Ingest on the lot 2 stack: 22/22 collections, `seacr_frags_raw` 7 051 185 rows,
  `seacr_frags_profile` 122 000, `samtools_flagstat` 6 (targets 1.0 to 6.5 % duplicates, IgG
  35 and 86 %). The three new `use:` tiles were stored without `viz_kind` because the backend
  catalog cache predated them (last StatReload 09:05 UTC); patched in place through
  `/dashboards/save` for the live check, which showed the MACS2, consensus and fragment tracks
  following the default region (33, 34 and 1 220 rows) and the matrix rendering.
- Re-ingest on fresh containers (project 6ab3d8499aabb660c9aec0c2, tabs
  6ab3d88930116ab0896e41e5..e9): 22/22 collections with the same row counts, and every stored
  advanced_viz carries a `viz_kind` (Signal: signal_matrix, scatter_xy, embedding,
  complex_heatmap; Peak calls: genome_view x3, coverage_track, manhattan). Typing
  `chr9:131,000,000-131,200,000` in the navigator moved every track: fragment pile-up 1 220 to
  702 rows, MACS2 33 to 18, consensus 34 to 7, each echo line on the new region, axes
  rescaled. The navigator itself stays at 9 920 rows (its chr9 rows, not narrowed by its own
  position filter) and its axis zoomed to about chr9:130.3-133.0 Mb rather than the exact
  window typed (CR-D22 reading: the navigator shows its chromosome, the tracks the region).

## Wave 3 (2026-09-23)

What changed:

- `GENOME` template variable (default `hg38`, matching the megatest). The navigator, the
  MACS2 and consensus tracks read `assembly: "{GENOME}"`, the fragment track
  `locus_assembly: "{GENOME}"`.
- New `Locus` tab (tab 5): four region cards, the four locus tiles moved out of Peaks, and a
  `Locus scope` rail (SEACR coverage per base, MACS2 q-value, replicate support). Tabs renamed
  `Peak calls` to `Peaks` and `Consensus and reproducibility` to `Consensus`.
- `Cohort at a glance` (role, target, peaks called, FRiP) split from a collapsed `Sample
  sheet`; replicate and role filters are MultiSelects.
- New catalog column `seacr/fragment_classes.sample_median_length`, a fragment-weighted
  median over the whole sample; the fragment-length card reads it. Fragment vrects are now the
  0 to 120 and 120 to 250 bp windows, labelled.
- FRiP card reads `frip` ("Lowest FRiP"); FRiP table moved to `Peak tables`; the fragment
  pile-up moved to Peaks. SEACR density card is a histogram; width histograms use a log x
  axis. MACS2 q threshold 1.3 (warn 1.0).
- Removed the three MultiQC deepTools twins, the caller dot plot, the divergence share figure,
  the class-share card and several redundant FRiP tiles. Every advanced viz has
  `controls_placement: header`. Texts are generic; megatest names are `forbidden_terms`.

Verified: lint clean (top_n and text_intro xpass), recipe tests including the new weighted
median test, CLI dry run 8/8.

Still open:

- Conformance seeds for `seacr_fragment_classes` need regenerating (new column).
- The gene lane stays `annotation: hg38` (the field is a Literal and rejects `{GENOME}`).
- With a built-in assembly, alt and unplaced contigs are not drawn, and a locus typed on a
  contig the assembly does not list can fail the GenomeSpy spec.
- The region cards paint genome-wide until the navigator's default region lands (platform).
- Live rendering not verified in this wave.
