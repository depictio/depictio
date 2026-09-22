# nf-core/eager 2.4.5: template ingestion validation report

**Date:** 2026-09-17
**Worktree / branch:** `feat-nfcore-templates-lot2` (`feat/nfcore-templates-lot2`)
**Validator:** `depictio/cli/.venv/bin/depictio-cli run --dry-run` against the local server
this worktree's config resolves; recipes also exercised directly against the real data with
`uv run python3` (no ingestion, see "Do NOT ingest" in the brief this was built against).

## Goal

Build the nf-core/eager 2.4.5 template: the ancient-DNA QC funnel from raw reads through
mapping, duplication and coverage to the DamageProfiler misincorporation signature that
authenticates the DNA as ancient, and the genotypes called from what survives. Own the
shared catalog outputs `samtools/flagstat` and `qualimap/bamqc_genome_results`, and bind a
DamageProfiler misincorporation recipe to the new `damage_profile` advanced-viz kind
(`sample, end, position, base_change, frequency`) the kinds workstream was adding in
parallel.

## Data used

`~/Data/depictio-nfcore/eager/2.4.5/megatest/`: already fetched and MultiQC-reprocessed to
the 1.35 parquet before this work started. Two Atlantic cod libraries, `COD076E1bL1` (three
lanes, ERR1943600/601/602) and `COD092E1bL1i69` (three lanes, ERR1943607/608/609), mapped
with BWA, deduplicated with Picard MarkDuplicates and damage-profiled with DamageProfiler.
`megatest.yaml` and `input/benchmarking_vikingfish.tsv` were refined before this task and
were not further edited.

```bash
bash depictio/projects/nf-core/eager/2.4.5/download_test_data.sh
```

fetches everything **except** the samplesheet, see the next section.

## The samplesheet is not part of the megatest fetch

Unlike ampliseq, rnaseq or cutandrun, eager's AWS test bucket carries no `input/` prefix and
no `pipeline_info/params.json` to recover the run's `--input` TSV from (eager 2.x predates
the nf-core params dump). `input/benchmarking_vikingfish.tsv` is therefore a
hand-reconstructed manifest against the six ENA runs the megatest fetched, it ships with
the template but is **not** copied into `DATA_ROOT` by `download_test_data.sh` or by the
megatest fetch. A real run needs it placed by hand:

```bash
mkdir -p "$DATA_ROOT/input"
cp depictio/projects/nf-core/eager/2.4.5/input/benchmarking_vikingfish.tsv "$DATA_ROOT/input/"
```

This was done against the local `~/Data/depictio-nfcore/eager/2.4.5/megatest/` copy before
running the commands below. **Discrepancy EA-D1** (see below).

Also unlike ampliseq/rnaseq, the samplesheet's `SAMPLESHEET_FILE` auto-detection
(`depictio/cli/cli/utils/templates.py`, `_auto_detect_metadata_columns` neighbourhood) only
recognises a filename containing the substring `samplesheet`: `benchmarking_vikingfish.tsv`
does not match it. The `samples` recipe therefore reads a **fixed** path
(`input/benchmarking_vikingfish.tsv`, matching the cutandrun `samples.py` convention of a
fixed `pipeline_info/samplesheet.valid.csv` rather than a `{SAMPLESHEET_FILE}` variable) so
no `--var` or auto-detection is needed, but this only works if the file keeps this exact
name. **Discrepancy EA-D2.**

## software_versions.csv, not .yml

eager 2.4.5 is DSL1: `pipeline_info/software_versions.csv` is a flat two-column
`tool<TAB>version` table (35 rows), not the DSL2 `CUSTOM_DUMPSOFTWAREVERSIONS` nested YAML
cutandrun's `pipeline_info/software_versions.yml` deliverable is. The bundled copy here keeps
the `.csv` name and the real layout; `template.yaml`'s `provenance.sources` reads it with
`format: "tsv"` (a 2-column key/value reader), which the model layer accepts natively, no
conversion needed. **Discrepancy EA-D3** against the brief's `pipeline_info/software_versions.yml`
deliverable name.

## Three raw-scan-plus-recipe two-step DCs, not the freeform-text norm

`samtools/flagstat.py` and `qualimap/bamqc_genome_results.py` read genuinely freeform text
reports (`samtools flagstat`'s twelve fixed-label lines; Qualimap's `key = value` sections)
that never name the sample inside the file, only the path does. Both follow the
`preseq/complexity_curve.py`-documented idiom (raw DC scan with `include_file_paths`, then a
`dc_ref` recipe) but had no tabular structure to scan, so the raw DC reads one LINE per row
(`separator` set to `\x1f`, the same trick `catalog/ataqv/metrics.py` uses for JSON) and the
recipe reassembles + regex-parses each file's lines. `damageprofiler/misincorporation.py`'s
raw file IS a real TSV (three `#`-prefixed comment lines then a header), so its DC is a plain
TSV scan with `comment_prefix: "#"`; only the sample (parent directory) and the read end
(filename) needed recipe-side parsing. All three verified against the real files (see
Commands run).

## preseq recipe override

`depictio/catalog/preseq/complexity_curve.py`'s sample-id helper
(`strip_stage_suffixes`) does not know eager's `<library>.filtered.preseq` naming (`filtered`
and `preseq` are not in its stage-token list), so it would return the whole file stem
unchanged. `depictio/projects/nf-core/eager/recipes/complexity_curve.py` is a pipeline-local
override with the identical output schema (`use: preseq/complexity_curve` in the dashboard
is unaffected); see `docs/dashboards.md` for the full rationale. eager's `lc_extrap` run also
wrote no bootstrap CI, so `lower_ci`/`upper_ci`/`ci_width` are present but always null.
**Discrepancy EA-D4** (not a bug, documents why the recipe path differs from the catalog's).

## damage_profile: a lot-2 kind

`damageprofiler/misincorporation.yaml` binds `kind: damage_profile`
(roles: `sample, end, position, base_change, frequency`). At the time this template was
built, `depictio/models/components/advanced_viz/{configs,schemas,types}.py` already declared
the kind, its `DamageProfileConfig` (default column names `sample`/`end`/`position`/
`base_change`/`frequency`, matching this recipe's output exactly, no `config:` overrides
needed on the dashboard tile) and its `ROLE_NAMES`/`CANONICAL_SCHEMAS`/`KIND_METADATA`
entries, the kinds workstream had landed its models before this template's validation pass.
`uv run pytest depictio/tests/models/test_catalog.py -q` and
`test_shipped_dashboard_yamls.py -q -k eager` both pass with the binding live; no fallback
or workaround was needed. If a future rebase reverts the kind ahead of this template's own
merge, the `use: damageprofiler/misincorporation` advanced-viz tile
(`ea-dmg-av-profile` in `dashboards/base.yaml`) is the one to watch, everything else on that
tab (the figure, the card, the table, the two MultiQC panels) is kind-independent.

## bcftools: referenced, not owned

nf-core/sarek owns `bcftools/stats_*` (its `depictio/catalog/bcftools/` was present,
mid-build, in this shared worktree throughout, not edited). The Genotyping tab therefore
binds only the `multiqc/bcftools` MultiQC panels (Substitution types, Variant quality, Indel
distribution, Variant depths); no `bcftools/stats_summary` or `_tstv` table is referenced
from this template, to avoid depending on an output that may not exist yet when this
template's own tests run standalone.

### EA-D7: a de-anchored scan pattern swallowed MultiQC's own summary table

Caught by the first live ingest, not by any offline check. Widening the Qualimap
`genome_results.txt` scan from `.*_stats/genome_results\.txt$` to
`.*genome_results\.txt$` (so the template stops depending on the `_rmdup_stats/`
directory name and ports to eager 3.x) also matched
`multiqc/multiqc_data/multiqc_qualimap_bamqc_genome_results.txt`, MultiQC's own flattened
summary of the same data. The raw collection picked up 3 files instead of 2, and
`qualimap/bamqc_genome_results.py` failed on the third with
`pattern not found: 'number of reads = ([\d,]+)'`.

Fixed by anchoring the pattern at the start of the basename: `genome_results\.txt$`. The
scan regex is `re.match`ed against the basename first, so a leading `.*` is never needed and
actively harmful next to a MultiQC report directory whose files are all named
`multiqc_<module>_<table>.txt`. Every scan pattern in this template was then replayed
against the real data root and checked for the same collision; the other seventeen are
clean, and the five optional collections correctly match nothing.

Worth noting beyond this template: any nf-core template whose scan pattern for a tool's own
output starts with `.*` is one MultiQC module name away from the same failure.

## Commands run

```bash
# Catalog validation (whole catalog was briefly broken mid-build by a concurrent
# agent's in-progress depictio/catalog/bcftools/; retried after it stabilised, see
# "Cross-agent worktree note" below)
uv run pytest depictio/tests/models/test_catalog.py -q
# 97 passed, 2 failed: test_committed_json_schema_is_current[catalog.schema.json/output.schema.json]
#, pre-existing, unrelated to this template (see Discrepancy EA-D5).

uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py -q
# 809 passed, 4 failed, all pre-existing/unrelated to eager:
#   test_advanced_viz_components_validate / _survives_the_component_union
#     [nf-core/nanoseq/3.0.0/dashboards/base.yaml]              (nanoseq workstream, in progress)
#   test_section_icons_and_colors_are_bundled
#     [projects/init/advanced_viz_showcase/dashboards/{contact_map,knee_plot}.yaml]
#                                                                  (kinds workstream, in progress)
uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py -q -k eager
# 10 passed, 0 failed.

# Each recipe's transform() run directly against the real DATA_ROOT files (not through
# the CLI loader), schema + shape printed and spot-checked against the source reports:
#   samtools/flagstat.py            -> 4 rows (2 libraries x 2 stages)
#   qualimap/bamqc_genome_results.py -> 2 rows (one per library)
#   damageprofiler/misincorporation.py -> 180 rows (2 libraries x 2 ends x 15 positions x 3 classes)
#   nf-core/eager/recipes/samples.py -> 2 rows (one per library)
#   nf-core/eager/recipes/complexity_curve.py -> 399 rows total across both libraries, thinned

mkdir -p ~/Data/depictio-nfcore/eager/2.4.5/megatest/input
cp depictio/projects/nf-core/eager/2.4.5/input/benchmarking_vikingfish.tsv \
   ~/Data/depictio-nfcore/eager/2.4.5/megatest/input/

depictio/cli/.venv/bin/depictio-cli run --template nf-core/eager/2.4.5 \
  --data-root ~/Data/depictio-nfcore/eager/2.4.5/megatest --dry-run
# ✅ Depictio-CLI run completed successfully! (8/8 steps), server accessibility, S3, project
# validation, config sync, scan, process, joins and dashboard import all passed. No ingestion.

uv run ruff format <5 recipe .py files> && uv run ruff check <same>       # clean
pre-commit run --files <every file this template touched>                  # all hooks passed
```

## Cross-agent worktree note

`depictio/catalog/bcftools/` (nf-core/sarek's, untracked) briefly failed
`CatalogOutput` validation (`renders_as.0.title: Extra inputs are not permitted`) while that
agent's work was mid-flight in this shared worktree; it was not edited from here, and a later
retry of the full `test_catalog.py` run found it fixed. Flagging in case the timing differs
on a rebuild: a global `load_catalog_entries()` failure with `bcftools` in the traceback is
not this template's bug.

## `use:` coverage

36 of 38 dense (non-text, non-interactive) dashboard tiles carry a `use:`: 94.7%, above the
brief's ~90% target. The two without one are the library-hub card and table (no catalog
module owns a pipeline's own sample sheet, the convention every other nf-core template
here follows).

## Open questions

- Whether `EA-D2`'s fixed-path samplesheet convention should instead grow a
  `SAMPLESHEET_FILE` variable + auto-detection support for non-`samplesheet`-named files, so
  a future ancient-DNA template with a differently-named manifest does not need its own
  special case.
- Whether `endorS.py`'s endogenous-DNA percentage (currently reachable only through the
  MultiQC general-stats panel, since it is `generalstats`-only custom content with no
  dedicated MultiQC section) deserves a small dedicated `endorspy/` catalog tool and card ,
  out of scope for this pass since the brief only named `samtools/flagstat`,
  `qualimap/bamqc_genome_results` and the damage-profile binding.

---

# 2026-09-22: lot 2 remediation pass

**Worktree / branch:** `feat-nfcore-templates-lot2` (`feat/nfcore-templates-lot2`, PR #1102)
**Stack:** API `http://localhost:8112`, viewer `http://localhost:5612`, Mongo `localhost:27112`
**Run:** `~/Data/depictio-nfcore/eager/2.4.5/megatest`, two Atlantic cod libraries,
six sequencing lanes, reprocessed MultiQC 1.35 report.

## What the audit found

The 2026-09-17 pass built five tabs and 52 components on six data collections, and left
most of what eager publishes unread. Specifically:

- The Genotyping tab was one text tile and four MultiQC panels: the GATK HaplotypeCaller
  VCF statistics on disk (`bcftools/stats/*.vcf.stats`) were bound to nothing.
- No tab filled a card row, and only 2 of 8 cards carried a `box_plot` secondary strip.
- `endorspy/*_endogenous_dna_mqc.json`, the headline ancient-DNA number, was reachable
  only through MultiQC's general-statistics table.
- `damageprofiler/*/lgdistribution.txt` (fragment length), `deduplication/*_rmdup.metrics`,
  `adapterremoval/*.settings` and ten raw Qualimap tables per library (including the
  627-row `coverage_across_reference.txt`) were all unread.
- The hub carried filters on constants: `ea-filter-udg` was a `Select` with one value, and
  organism, sequencing type and strandedness were likewise single-valued.
- eager's only genuine multi-value factor, the sequencing lane, was invisible, because the
  hub collapses six lanes onto two libraries.

## What this pass added

### New catalog outputs (five tools)

| Output | Rows on this run | Notes |
| --- | --- | --- |
| `qualimap/coverage_across_reference` | 1252 (626/library) | windowed depth, mapped back onto contigs |
| `qualimap/coverage_histogram` | 289 | bases at each depth |
| `qualimap/genome_fraction_coverage` | 102 | share of the reference at each depth threshold |
| `qualimap/coverage_per_contig` | 454 (227 contigs x 2) | depth per contig, relative to the library mean |
| `damageprofiler/lgdistribution` | 688 | fragment length per library and strand |
| `damageprofiler/authenticity` | 2 | second-order: deamination against fragment length |
| `endorspy/endogenous` | 2 | endogenous DNA before and after filtering |
| `picard/markduplicates_metrics` | 2 | `## METRICS CLASS` block of `*_rmdup.metrics` |
| `adapterremoval/settings` | 6 (one per lane) | `[Trimming statistics]` block |

`depictio/catalog/picard/` and `depictio/catalog/adapterremoval/` and
`depictio/catalog/endorspy/` are new tool directories; `qualimap/` and `damageprofiler/`
gained outputs beside the ones they already had. All five parse the library or lane id out
of `source_path` rather than matching directory names in a scan regex, so the scan patterns
stay file-name-only and the template ports to eager 3.x's layout.

`depictio/recipes/lib/qualimap_raw.py` is a new shared helper: the four Qualimap recipes all
need the same sample-id recovery, which has to tolerate both `raw_data_qualimapReport/` and
`raw_data/` layouts and strip the `_stats` / `_rmdup` / `_bamqc` stage tails Qualimap's
output directory carries.

### New pipeline-local recipes

- `eager/lane_stats.py` (6 rows): joins the AdapterRemoval reports to the samplesheet on a
  key rebuilt from the R1 file name plus the `Lane` column
  (`pl.format("{}_L{}", r1_stem, Lane)`), with a run-accession fallback for a hand-written
  samplesheet whose R1 spelling differs. This is what makes lane (4 distinct values) and
  run accession (6) real filter factors, replacing the dead constant filters.
- `eager/read_fate.py` (12 rows): the five-stage flow, chained exactly, see EA-V1 below.

### Dashboard

Eight tabs, 151 components. Every tab opens with a four-card row that fills the eight-column
width; 21 of 40 cards carry a `box_plot` strip, the rest `top_n`, `donut` or `attrition`.
Three persistent sections (the four-card run strip, the library sheet, the BamQC reference
table) are pinned to every tab including MultiQC, which the MultiQC-only rule exempts pinned
persistent sections from. Every tab declares its own local filter section on the factor that
tab varies over.

Dropped: `ea-filter-udg` and the organism / sequencing-type / strandedness filters, all
single-valued on this run. They remain as columns in the hub table.

Two tabs are gated on branches this megatest did not enable. `Contamination and sex` and
`Metagenomic screening` each open with a text tile saying which modules did not run, and
then show the data that is on disk and answers the nearest question: per-contig relative
depth for the first, the off-target fraction for the second. Their collections
(`sexdeterrmine`, `mtnucratio`, `nuclear_contamination`, `maltextract_heatmap`,
`kraken_report`) are declared `optional: true` with the globs the eager output docs publish,
so a run that does enable them ingests with no template edit.

## Verifications

### EA-V1: the read-fate flow closes exactly, with no apportioning

AdapterRemoval's own identity holds per lane:

```
2 x total_read_pairs = retained_reads + collapsed_pairs + discarded_reads
```

and, summed over a library's lanes, `retained_reads` equals the pre-filter flagstat total to
the read: 71 388 991 on COD076E1bL1, 69 615 709 on COD092E1bL1i69. The remaining stages
chain exactly too: mapped 25 154 106, passed the quality filter 16 801 402 (which is also
MarkDuplicates' `UNPAIRED_READS_EXAMINED`), duplicates 4 682 948, unique 12 118 454.

Collapsing is modelled as an outflow at the trimming step, not a stage of its own. One read
of each merged pair stops existing there, and no report says which of the survivors were
merged, so a collapse stage would have to apportion the mapped reads between collapsed and
uncollapsed. As an outflow it is exact.

### EA-V2: the coverage track's contig mapping is correct

Qualimap reports window centres on a single concatenated reference axis with no contig
column. `qualimap/coverage_across_reference.py` takes the same run's `genome_results.txt` as
an *optional* second source, builds a running sum of the `Coverage per contig` lengths and
maps each window with a per-sample `join_asof(strategy="backward")`. Checked against the
reference: 626 windows per library, maximum global position 669 958 061 against a genome of
669 966 409, 227 contigs recovered, and the mitochondrion `NC_002081.1` lands at local
position 8348, exactly half of its 16 696 bp length, which is the single window that fits
it. With the optional source absent the recipe falls back to one pseudo-contig, `genome`.

### EA-V3: the bcftools join key is `Sample_Name`, not `Library_ID`

`bcftools stats` reads its sample name from the VCF header (`COD076`), not the BAM's library
id (`COD076E1bL1`). The hub therefore carries a second `Sample` filter on `sample_name`, and
the template two extra links with `source_column: sample_name` for `bcftools_stats_summary`
and `bcftools_stats_tstv`. Without them the genotyping tiles silently filter to nothing.

### EA-V4: the mitochondrial signal is real

`qualimap/coverage_per_contig` puts `NC_002081.1` at 53.1X against a 0.89X nuclear mean, a
relative depth of 59.4. That is the mitochondrial-to-nuclear ratio MTNucRatio would have
reported had it run, and it is why the `Contamination and sex` tab can answer the nearest
question despite the branch being off.

## Commands run

```bash
uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py -q -k eager
# 10 passed, 863 deselected

uv run pytest depictio/tests/models/test_catalog.py -q
# 95 passed, 4 failed, none in this template's tools; see "Cross-agent" below

uv run python -m depictio.cli run --template nf-core/eager/2.4.5 \
  --data-root ~/Data/depictio-nfcore/eager/2.4.5/megatest --dry-run
# ✅ 8/8 steps

uv run ruff format <12 recipe .py files> && uv run ruff check <same>   # clean
uv run pre-commit run --files <every file this pass touched>           # all hooks passed
```

Every recipe was additionally run against the real megatest files, building the raw frame
the way each DC's `polars_kwargs` will, and asserting both the dtype of every column in
`EXPECTED_SCHEMA` and the column order. Every `use:` in the dashboard was resolved through
`catalog_source_for_use` (88 refs, 0 unresolved) and every column the dashboard names
(`column_name`, `breakdown_col`, `attrition_cols`, `step_cols`, `dict_kwargs`, and every
advanced-viz role) was checked to exist in the frame its data collection will hold, with
`column_type` checked against the frame's real dtype. 0 mismatches.

## Live ingest, 2026-09-22

```bash
curl -X DELETE .../projects/delete?project_id=<previous lot2-eager>
nohup uv run python -m depictio.cli run \
  --CLI-config-path ~/.depictio/CLI.feat-nfcore-templates-lot2-112.yaml \
  --template nf-core/eager/2.4.5 \
  --data-root ~/Data/depictio-nfcore/eager/2.4.5/megatest \
  --project-name lot2-eager > /tmp/claude-502/ingest-eager2.log 2>&1 &
# ✅ Depictio-CLI run completed successfully! (8/8 steps)
# 31 data collections processed, 5 optional skipped (sexdeterrmine, mtnucratio,
# nuclear_contamination, maltextract_heatmap, kraken_report)
```

Project `6ab2b00b2a5cbf9bc537a7e1`. Every non-optional collection has rows:

| Collection | Rows | Collection | Rows |
| --- | --- | --- | --- |
| `samples` | 2 | `qualimap_bamqc_genome_results` | 2 |
| `adapterremoval_settings` | 6 | `qualimap_coverage_per_contig` | 454 |
| `eager_lane_stats` | 6 | `qualimap_coverage_across_reference` | 1252 |
| `samtools_flagstat` | 4 | `qualimap_coverage_histogram` | 289 |
| `endorspy_endogenous` | 2 | `qualimap_genome_fraction_coverage` | 102 |
| `picard_markduplicates_metrics` | 2 | `preseq_complexity_curve` | 399 |
| `eager_read_fate` | 12 | `damageprofiler_misincorporation` | 180 |
| `bcftools_stats_summary` | 2 | `damageprofiler_lgdistribution` | 688 |
| `bcftools_stats_tstv` | 2 | `damageprofiler_authenticity` | 2 |

All 8 tabs imported, 151 components, matching the YAML exactly:

| Tab | Dashboard id | Components |
| --- | --- | --- |
| MultiQC (main) | `6ab2b02f1b869aaa995ec18c` | 22 |
| Run and library hub | `6ab2b02f1b869aaa995ec18d` | 13 |
| Reads and read fate | `6ab2b02f1b869aaa995ec18e` | 14 |
| Mapping, endogenous DNA and duplication | `6ab2b0301b869aaa995ec18f` | 26 |
| Damage authentication | `6ab2b0301b869aaa995ec190` | 22 |
| Contamination and sex | `6ab2b0301b869aaa995ec191` | 12 |
| Coverage and genotyping | `6ab2b0301b869aaa995ec192` | 30 |
| Metagenomic screening | `6ab2b0301b869aaa995ec193` | 12 |

All 13 `advanced_viz` tiles landed with their kind and catalog provenance intact
(`scatter_xy` x5, `profile` x4, `sankey`, `damage_profile`, `coverage_track`,
`genome_view`), checked in Mongo rather than the viewer, which is the known
`use:`-import silent-no-kind failure mode and did not occur here.

Every row count and dashboard id above was read back a second time straight from Mongo
(`mongodb://localhost:27112/depictioDB`), because the lot 2 API wedged shortly after the
ingest finished. The 30 non-MultiQC, non-optional collections each have a `deltatables`
document whose latest aggregation carries the expected column count, and the row counts
match the API's to the row. The seven tab documents hang off the main one by
`parent_dashboard_id`, and 22 + 13 + 14 + 26 + 22 + 12 + 30 + 12 = 151 components, which is
exactly what `dashboards/base.yaml` declares. Six collections have no deltatable, which is
correct: `multiqc_data` is a MultiQC collection, and the five gated ones were skipped.

No screenshots were taken in this pass. The lot 2 dev viewer predates the
`@genome-spy/core` install and fails any advanced-viz tile with
"Failed to fetch dynamically imported module" until the image is rebuilt; that is a
stack issue, not a template one.

## Cross-agent worktree notes

Two `test_catalog.py` failures are outside this template's partition and are recorded here
only so a rebuild does not attribute them to it:

- `test_committed_json_schema_is_current` for `catalog.schema.json` and `output.schema.json`
  is stale because the advanced-viz kind registry gained `genome_view` in this same lot.
  Those files are on the shared do-not-edit list; the kind agent or the main session
  regenerates them with `depictio dev catalog schema`.
- `test_every_bundled_card_declares_a_secondary_strip` and
  `test_cli_validate_exits_zero_on_bundled_catalog` fail on `cellbender`, `kallisto`,
  `qcatch`, `simpleaf`, `cellranger`, `cooltools` and `gtdbtk`, all other agents' tools.

Catalog loading is all-or-nothing, so any one tool's breakage fails every catalog test. An
earlier run of this pass failed 30 tests purely because `depictio/catalog/bismark` still
declared the pre-rename `genomespy_track` kind; that resolved on its own once the other
agent landed the rename.

## `use:` coverage

88 of 104 dense (non-text, non-interactive) dashboard tiles carry a `use:`: 84.6%. The 16
without one all read this pipeline's own tables: the library hub, the per-lane trimming
ledger (`eager_lane_stats`) and the read-fate flow (`eager_read_fate`). No catalog module
owns a pipeline's sample sheet, its lane ledger, or a flow assembled from four different
tools' reports, so those stay pipeline-local, as in every other nf-core template here.

## Open questions

- No per-caller dot plot on the genotyping tab. This run genotyped with one caller, so the
  comparison would have a single column. `bcftools/stats_summary` already carries the
  `caller` column a multi-caller run would need, so adding it later is a dashboard change
  only.
- `damageprofiler/authenticity`'s `fraction_under_70bp` uses a fixed 70 bp threshold
  (`SHORT_FRAGMENT_BP`). It is the conventional ancient-DNA cutoff but it is a constant in
  the recipe, not a template variable; a study working on a different fragment regime would
  want it configurable.
- The `Contamination and sex` and `Metagenomic screening` optional collections have never
  been exercised against a run that enables them. Their globs come from the eager output
  documentation, not from data, so the first real run of either branch may need the scan
  patterns adjusted.
- EA-D2 (the hand-reconstructed samplesheet at a fixed path) is unchanged from the previous
  pass and still applies: `input/benchmarking_vikingfish.tsv` must be copied into the
  `--data-root` by hand.

## 2026-09-22 review fixes

- `dashboards/base.yaml`: tab-local, non-persistent `Glance scope` section on the main tab, a
  `RangeSlider` on `damageprofiler_authenticity.ct_5p_first` (the DC behind the pinned damage
  card), so the MultiQC tab has its own control beside the pinned ones.
- No new pinned samplesheet factor: `organism` (`Gadus_morhua`), `seq_type` (`PE`) and
  `udg_treatment` (`none`) each carry a single value across the six rows of
  `input/benchmarking_vikingfish.tsv`, so a filter on any of them would be dead on the
  reference run. They stay in the hub table.
- `test_shipped_dashboard_yamls.py -k eager` passes.
