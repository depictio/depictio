# nf-core/nanoseq 3.0.0: template ingestion validation report

**Date:** 2026-09-17
**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-lot2`
**Validator:** `uv run pytest` plus `depictio-cli run --template nf-core/nanoseq/3.0.0
--data-root ~/Data/depictio-nfcore/nanoseq/3.0.0/megatest --dry-run` (local `depictio/cli/.venv`,
no docker, no live server needed for `--dry-run`). Full 8/8 steps passed.

## Goal

Build the nanoseq 3.0.0 template on top of an already-fetched, already-MultiQC-reprocessed
megatest run: Nanopore direct-cDNA / cDNA RNA-seq QC (NanoStat, FastQC, samtools via MultiQC),
Bambu gene/transcript quantification, and the DESeq2 / DEXSeq differential results computed on
top of those counts. Only `megatest.yaml` existed before this session; its `keys:` list assumed
NanoPlot, pycoQC, JAFFAL fusion calls and a `variant_calling/` directory that the real run does
not carry, and got the depth of the NanoPlot/minimap2 paths wrong. See "Discrepancies" below.

## Data used

`~/Data/depictio-nfcore/nanoseq/3.0.0/megatest/`, an AWS megatest run
(`results-1e60482a2c4621234393a6eef8e9a104309c20ae`, the 3.0.0 release tag): SG-NEx A549 and
K562 cell lines, direct cDNA and cDNA Nanopore RNA-seq, 3 replicates each (6 samples). The real
layout:

```
bambu/counts_gene.txt              bambu/counts_transcript.txt
bambu/deseq2/deseq2.results.txt    bambu/dexseq/dexseq.results.txt
fastqc/<sample>_fastqc.zip                    (6 files)
minimap2/samtools_stats/<sample>.sorted.bam.{stats,flagstat,idxstats}   (18 files)
nanoplot/fastq/<sample>/NanoStats.txt         (6 files)
multiqc/minimap2/multiqc_data/*               raw MultiQC 1.11 inputs
multiqc/multiqc_data/multiqc.parquet          already reprocessed to 1.35 (REPROCESSED.json)
pipeline_info/{execution_trace_*.txt, samplesheet.valid.csv, software_versions.yml}
```

No FASTQ, no BAM, no bigWig. No `pipeline_info/params_*.json` (like cutandrun, this run
predates the nf-core params dump).

## MultiQC: already reprocessed before this session

`multiqc/multiqc_data/REPROCESSED.json` records `source_version 1.11`, `reprocessed_with 1.35`,
and four modules: `fastqc`, `multiqc_software_versions`, `nanostat`, `samtools`. No pycoQC
module, the run did not produce pycoQC output, only NanoPlot/NanoStat. `template.yaml`'s
`dc_specific_properties.modules` / `plots` and every `selected_module` / `selected_plot` in
`dashboards/base.yaml` were verified against the real parquet's `anchor` / `section_key`
columns (`nanostat_fastq_stats_table`, `nanostat_quality_dist`, the 9 standard FastQC anchors,
6 samtools anchors, no insert-size plot, expected for single-end long reads). Plot **section
names** (not anchors) were cross-checked against MultiQC's own module source
(`nanostat.py`, `samtools/stats.py`) via GitHub, the same convention `cutandrun/3.1` uses.

## Catalog work

New tools (neither existed before this session):

- **`bambu`** (`depictio/catalog/bambu/`): `counts_gene` / `counts_transcript`, Bambu's
  gene/transcript count matrices reduced to the top 50 features by total count, bound to
  `complex_heatmap`. `counts_gene.txt`'s header is one field short of every data row (the
  row-id column is unnamed); the recipe reads the header and the data as two separate
  `glob_pattern` passes (`truncate_ragged_lines: True` on the header pass) and stitches them
  back together, a normal `has_header` read raises `found more fields than defined in Schema`.
- **`dexseq`** (`depictio/catalog/dexseq/`): `results`, DEXSeq per-transcript usage statistics,
  bound to `volcano` / `qq`. The effect-size column is named after the two conditions compared
  (`log2fold_A549_K562`), not a fixed name; the recipe finds it by prefix and renames it.
- **`multiqc/nanostat.yaml`**: new MultiQC panel (module `nanostat` had no panel yet).

Referenced, not edited:

- **`deseq2/results.yaml`** (`deseq2_results`, `depictio/catalog/deseq2/`, pre-existing,
  pipeline-agnostic): nanoseq's `bambu/deseq2/deseq2.results.txt` is comma-separated R
  `write.csv` output with an unnamed row-id column, exactly the shape
  `deseq2/results_long.py`'s fallback column resolution already handles. Wired through a raw
  scan tagged `deseq2_results_raw` (the two-step idiom the recipe's own docstring documents),
  with `format: CSV` instead of the TSV other pipelines write. Only one comparison file exists
  (no per-contrast naming), so `include_file_paths` was left off deliberately: the recipe's
  fallback labels every row `contrast: "all"` rather than the ugly literal filename the path-
  based derivation would otherwise produce (see NS-D5).
- **`multiqc/fastqc.yaml`**, **`multiqc/samtools.yaml`**: pre-existing, used as-is.

`use:` coverage, counting every `table` / `card` / `advanced_viz` / `multiqc` tile (excludes
`text` and interactive filters): **32 of 34** carry `use:` (94%), the 2 without are the
`samples` card and table (no catalog tool for a pipeline-authored samplesheet-derived hub,
consistent with `samples.py` in every other template).

## Kinds bound

`complex_heatmap` (bambu counts_gene / counts_transcript), `volcano` / `ma` / `qq` (deseq2
results), `volcano` / `qq` (dexseq results). No lot-2 kind (`contact_map`, `knee_plot`,
`damage_profile`) applies to this pipeline's outputs.

## Manifest changes (megatest.yaml, real layout vs the pre-existing guess)

- `pipeline_info/params_*.json`: **removed**, not written by this run.
- `nanoplot/*.txt` / `nanoplot/*.tsv`: **fixed** to `nanoplot/fastq/*/*.txt` (one directory per
  sample, file is `NanoStats.txt`, not the top-level glob assumed).
- `pycoqc/*.json`: **removed**, the run did not produce pycoQC output.
- `minimap2/*.stats` / `*.flagstat` / `*.idxstats` / `*.txt`: **fixed** to
  `minimap2/samtools_stats/*.{stats,flagstat,idxstats}` (one directory level deeper than
  assumed; the bare `minimap2/*.txt` catch-all was dropped, nothing matches it).
- `bambu/*.txt` / `*.tsv` / `*.csv`: **narrowed** to the four files that actually exist
  (`counts_gene.txt`, `counts_transcript.txt`, `deseq2/deseq2.results.txt`,
  `dexseq/dexseq.results.txt`) rather than a pipeline-wide glob, since the wildcard
  `bambu/*.csv` would also have missed the nested `deseq2/` / `dexseq/` subdirectories.
- `featurecounts/*.txt` / `*.summary`: **removed**, the run did not write a featureCounts stage.
- `deseq2/*.txt` / `*.tsv` and `dexseq/*.txt` / `*.tsv`: **removed** as top-level globs (the
  real files are nested under `bambu/deseq2/` and `bambu/dexseq/`, now covered by the narrowed
  `bambu/...` keys above).
- `jaffal/*.csv` / `*.txt` and `variant_calling/*.txt` / `*.tsv`: **removed**, this run's
  parameters (`is_transcripts: 0`, no `nanopolish_fast5`) never triggered fusion calling or
  variant calling.

## Discrepancies

- **NS-D1** `megatest.yaml` assumed pycoQC output; the run only produced NanoPlot/NanoStat.
  Fixed (removed the `pycoqc/*.json` key; no pycoQC catalog panel needed).
- **NS-D2** `megatest.yaml` assumed a flat `nanoplot/*.txt` / `minimap2/*.stats` layout; the
  real run nests one directory deeper (`nanoplot/fastq/<sample>/`,
  `minimap2/samtools_stats/`). Fixed.
- **NS-D3** `megatest.yaml` assumed `featurecounts/`, `jaffal/` and `variant_calling/`
  directories; none exist for this run's parameter set. Fixed (keys removed).
- **NS-D4** `megatest.yaml` assumed `pipeline_info/params_*.json`; not written (pre-params-dump
  era, like cutandrun). Fixed (key removed); provenance collects only `software_versions.yml`.
- **NS-D5** Bambu's row-id column (and hence `deseq2_results.gene_id` / `bambu_counts_*.gene_id`
  after regex extraction) is a GTF-attribute string
  (`ccds_id CCDS...; exon_id ENSE...; exon_number N; gene_biotype X; ENSGxxxxx`), exon-granular
  rather than one row per gene, an artifact of the megatest's minimal test GTF. The `bambu`
  recipes extract a clean `ENSG…` / gene_biotype via regex for their own output; the reused
  `deseq2_results` collection (shared recipe, not editable here) keeps the raw descriptor string
  as `gene_id` verbatim. Cosmetic, not a validity issue: volcano/MA hover labels on the
  Differential expression tab are these long strings rather than clean gene ids.
- **NS-D6 (transient, not caused by this work, since resolved)** Early in this session the full
  catalog failed to load (`test_catalog.py::test_bundled_catalog_loads` and every downstream
  test, both `test_shipped_dashboard_yamls.py::test_advanced_viz_*` tests for every shipped
  dashboard in the repo) because `depictio/catalog/bcftools/stats_summary.yaml`: a parallel
  agent's in-progress work, owned by the sarek pipeline builder, briefly had a `figure` render
  with a `title:` key `CatalogOutput` rejects. Not specific to this template; not editable here.
  By the time this template's own suite was re-run it had cleared (see "What was actually run").
- **NS-D7 (found and fixed during validation)** The first draft of `dashboards/base.yaml` copied
  the `config: {x_title, y_title, color_col, selection_enabled, selection_column}` shape from
  the brief's `scatter_xy`-family example onto all 5 `volcano` / `ma` / `qq` tiles. Those three
  kinds have their own dedicated config models (`VolcanoConfig`, `MAConfig`, `QQConfig` in
  `depictio/models/components/advanced_viz/configs.py`, all `extra="forbid"`) with no such
  fields, `AdvancedVizLiteComponent.model_validate` rejected every one of them, which the union
  in `DashboardDataLite` swallows silently (degrades to an inert dict, no `viz_kind`, "Unknown
  advanced viz kind" at render time) rather than raising. Fixed by matching the real config shape
  already used by `deseq2/volcano` / `deseq2/ma` / `deseq2/qq` in `atacseq/1.2.2/dashboards/base.yaml`
  (`label_col`, `category_col`, `significance_threshold`, `effect_threshold` /
  `fold_change_threshold`, `top_n_labels`, `show_labels` for volcano/ma;
  `feature_id_col`, `category_col` for qq). Caught by
  `test_advanced_viz_components_validate` / `test_advanced_viz_survives_the_component_union`,
  confirmed fixed by both tests plus a live `--dry-run`.

## What was actually run

```bash
uv run pytest depictio/tests/models/test_catalog.py -q
# -> 97 passed, 2 failed: both test_committed_json_schema_is_current (catalog.schema.json /
#    output.schema.json stale against depictio/models/components/advanced_viz, a
#    depictio/models/ regeneration step, out of this template's edit scope and unrelated to
#    nanoseq's content; flag for the advanced-viz-kind-builder / lot-2 kinds agent).

uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py -q -k nanoseq
# -> 10 passed, 0 failed (all of test_every_tab_validates, test_advanced_viz_components_validate,
#    test_advanced_viz_survives_the_component_union, test_card_secondary_strips_have_the_config_
#    they_read, test_component_sections_are_declared_in_the_right_list, test_section_icons_and_
#    colors_are_bundled, test_text_tiles_are_tall_enough_for_their_body, test_multiqc_tabs_hold_
#    only_multiqc_panels, test_tables_are_full_width, for depictio/projects/nf-core/nanoseq/3.0.0
#    /dashboards/base.yaml).

depictio/cli/.venv/bin/depictio-cli run --template nf-core/nanoseq/3.0.0 \
  --data-root ~/Data/depictio-nfcore/nanoseq/3.0.0/megatest --dry-run
# -> 8/8 steps passed (template resolution, server/S3 checks, project-config validation and
#    sync, data scanning, data-collection processing incl. every recipe, table joins, dashboard
#    import). No server was actually reached; --dry-run stubs those steps.

uv run ruff format depictio/catalog/bambu/*.py depictio/catalog/dexseq/*.py \
  depictio/projects/nf-core/nanoseq/recipes/*.py
uv run ruff check depictio/catalog/bambu/*.py depictio/catalog/dexseq/*.py \
  depictio/projects/nf-core/nanoseq/recipes/*.py
# -> All checks passed! (one unused `import re` in bambu/counts_gene.py fixed)

pre-commit run --files <every new file>
# -> trailing-whitespace, end-of-file-fixer, check-yaml, check-added-large-files, ruff,
#    ruff-format, shellcheck: all passed. ty and the Helm/thumbnail/nbstripout hooks
#    correctly skipped (no matching files).
```

Every recipe (`bambu/counts_gene.py`, `bambu/counts_transcript.py`, `dexseq/results.py`,
`nf-core/nanoseq/recipes/samples.py`, and the reused `deseq2/results_long.py`) was also run
directly against the real megatest files before the dry-run, confirming schema and shape (see
each recipe's docstring for the exact commands / output columns).

## Not done

- Screenshots for `docs/dashboards.md` (no server / viewer to capture from).
- A real (non-dry-run) ingest against a live instance.

---

# Remediation pass, 2026-09-22

**Date:** 2026-09-22
**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-lot2`
**Instance:** PORT_OFFSET 112 (API `localhost:8112`, viewer `localhost:5612`), project `lot2-nanoseq`.
**Validator:** `uv run pytest`, a `--dry-run`, and one live wipe-and-re-ingest against that instance.

## Why

The lot 2 audit found this template the worst funnel of the seven: **one** link
(`samples -> multiqc`), because everything downstream of Bambu is a wide matrix with a column
per sample and no `sample` column to link on. Four Quantification cards were therefore constants
over a 50-row table, two rows carried 4 cards where 8 columns were available, the pinned
reference table was 208 722 rows in a four-row-high tile, DE labels were Bambu's exon-granular
GTF attribute strings, NanoStat and `samtools stats` sat on disk but were reachable only through
MultiQC, DEXSeq's 419 rows / 4 hits took two 8x7 tiles, and 8 MultiQC panels were unplaced.

## What changed

**New catalog outputs** (module-level, reusable by any pipeline that runs these tools):

| Output | Rows on this run | What it unlocks |
| --- | --- | --- |
| `bambu/counts_gene_long` | 159 138 | Melts the wide gene matrix to one row per sample and gene, with count / CPM / log CPM. This is the link that was missing. |
| `bambu/counts_transcript_long` | 415 356 | Same at transcript level (`MIN_TOTAL_COUNT = 5`). |
| `bambu/sample_pca` | 6 | numpy SVD on log CPM over the 500 most variable genes, plotPCA-style, plus per-library depth / complexity / concentration readings. |
| `bambu/sample_correlation` | 6 | Spearman on log CPM of expressed genes, one column per sample, for `complex_heatmap`. |
| `bambu/top_variable_genes` | 100 | Genes ranked by variance of log CPM rather than by total count. |
| `nanoplot/nanostats` | 6 | NanoStat's summary block read directly: N50, mean/median length and quality, yield, extremes. |
| `nanoplot/nanostats_quality` | 30 | The Q-cutoff ladder (reads, share, megabases above each Phred floor). |
| `samtools/stats_sections` | 3 155 | The SN summary plus the RL / COV / ID histograms `samtools stats` writes and MultiQC never surfaces, decimated to 200 geometric bins per library per section. |

`samtools/stats_sections` is a new **output** in an existing tool dir: `flagstat` and `stats`
were not touched, and its glob is narrowed to `**/*.bam.stats` so it cannot collide with
`flagstat.yaml`'s `**/*flagstat.stats`.

**New pipeline-local recipes** (`depictio/projects/nf-core/nanoseq/recipes/`):

- `samples.py` carries `protocol`, `source_replicate` and `run_id` beside the condition. The
  six libraries are not three replicates per cell line: they are one cDNA and two direct-cDNA
  preparations off three flow-cell runs, which the sheet's `<group>_R<n>` naming hides.
  `protocol` is a persistent filter as a result. (Wave 3 follow-up: these now come from the
  design table, not from the FASTQ name; see "Design from METADATA_FILE" below.)
- `deseq2_results.py` wraps the shared DESeq2 reader so `gene_id` is the Ensembl id extracted
  from Bambu's attribute string, `gene_biotype` is its own filterable column, the original
  descriptor survives as `feature_label`, and the contrast is named `A549 vs K562` from the
  samplesheet instead of `all`. 208 722 rows; the `use: deseq2/...` renders bind unchanged
  (resolution is catalog-side, verified through `catalog_source_for_use`).
- `deseq2_top_expressed.py` is the same table cut to its 200 best-measured rows, which is what
  the bottom-pinned reference tile now holds.

**Isoform structures bind the shared `gtf/transcripts` catalog output.** A pipeline-local
`transcript_structures.py` reading both GTF and BED12 was written first and then **deleted** in
favour of `depictio/catalog/gtf/transcripts.py`, which landed mid-session from the
`transcript_structure` kind work. The tile is `use: gtf/transcript_structures`; the raw DC is
`gtf_transcripts_raw`, scanning `bambu/extended_annotations.gtf` only rather than the catalog's
own `**/*.gtf` glob, so the reference annotation the run was quantified against is not drawn
beside the discovered models. BED12 support went with the deleted recipe (see NS-D11).

**Dashboard: 3 tabs to 7.** Run hub / Basecall and read QC / Run dynamics / Alignment and
coverage / Quantification and sample structure / DE and usage / Isoforms. Persistent pinned
`Sample filters` (sample, condition, protocol) on every tab, persistent collapsed
`Significance thresholds` (padj, log2fc), and a tab-local filter section on each tab
(flow-cell run and source replicate; q_cutoff; stats section and axis range; gene biotype and
log CPM; direction, biotype and mean expression). Every card row fills all 8 columns, cards use
`box_plot` / `top_n` / `donut` / `gauge` strips, and all 8 previously unplaced MultiQC panels
are placed in collapsed per-tab sections.

## Discrepancies found in this pass

- **NS-D8** The 4 Quantification cards read `bambu_counts_gene` (the top-50 wide matrix), so
  `nunique(gene_id)` was the constant 50 and `sum(count)` the constant total of those 50 rows on
  every filter state. Fixed: those cards now read `bambu_counts_gene_long` /
  `bambu_sample_pca`, which carry a `sample` column and move with the filters.
- **NS-D9** NS-D5 (unreadable DE labels) is now **fixed**, not just documented: the wrapper
  above replaces the attribute string with the Ensembl id on every Bambu-derived collection,
  DESeq2 included. `feature_label` keeps the original.
- **NS-D10** The pinned `Reference tables` tile held all 208 722 DESeq2 rows at `h: 4` on every
  tab. Fixed: 200 rows at `h: 7`; the full table is still what the DE tab's volcano, MA,
  barplot and QQ read.
- **NS-D11 (accepted limitation)** nanoseq's UCSC conversion route publishes the same transcript
  models as BED12, which `gtf/transcripts` does not read. Since that conversion runs on a BED12
  derived from `extended_annotations.gtf`, a run with the BED12 has the GTF, so nothing is lost
  in practice. Recorded here rather than kept as a second optional collection.
- **NS-D12 (environmental, not a template defect)** `multiqc_data` fails to process with the
  CLI's own venv (`depictio/cli/.venv`): `No module named 'multiqc'`, so
  `extract_multiqc_metadata` cannot read the parquet and the run aborts before steps 7 and 8.
  The repo venv carries MultiQC 1.35, so the live ingest was re-run as
  `.venv/bin/python -m depictio.cli run ...`. Anyone re-ingesting this template from
  `depictio/cli/.venv` needs `uv sync --extra multiqc` first.
- **NS-D13 (fixed during validation)** Three `description:` values in `base.yaml` began a plain
  scalar and then contained `": "`, which YAML reads as a nested mapping; `yaml.safe_load`
  raised `mapping values are not allowed here` and all 10 shipped-dashboard tests failed to even
  parse the file. Reworded rather than quoted, so the pattern does not come back on the next
  edit.

## What was actually run (2026-09-22)

```bash
uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py -q -k nanoseq
# -> 10 passed, 863 deselected.

uv run pytest depictio/tests/unit/test_nfcore_megatest.py -q
# -> 72 passed, 2 failed. Both failures are other pipelines' manifests
#    (eager-2.4.5, scrnaseq-4.2.0), owned by other agents in the same wave.

depictio/cli/.venv/bin/depictio-cli run --template nf-core/nanoseq/3.0.0 \
  --data-root ~/Data/depictio-nfcore/nanoseq/3.0.0/megatest --dry-run
# -> 8/8 steps passed.

uv run ruff format / ruff check <every new and changed .py>
# -> 4 files reformatted, then All checks passed!

uv run pre-commit run --files <every new and changed file>
# -> trailing-whitespace, end-of-file-fixer, check-yaml, check-added-large-files,
#    ruff, ruff-format all pass; ty / Helm / thumbnails / nbstripout / shellcheck
#    skipped (no matching files).
```

Two cross-checks were scripted against the shipped YAML rather than run by hand, and both pass:
every `data_collection_tag` in `dashboards/base.yaml` exists in `template.yaml` (the only
collections not bound to a tile are the four raw two-step scans plus `samplesheet`), and every
column named by a card, figure, table, filter or advanced-viz config exists in the recipe's
`EXPECTED_SCHEMA` with the declared `column_type`.

### Live ingest: partial, blocked on the instance

`lot2-nanoseq` was deleted and re-ingested once against PORT_OFFSET 112. Result, read back from
Mongo (`mongodb://localhost:27112/depictioDB`, project `6ab2aea59c185131670a9f4a`):

- **18 of 21 data collections written**, with the row counts the recipes were designed for:
  `samples` 6, `nanostats` 6, `nanostats_quality` 30, `nanoplot_nanostats_raw` 162,
  `samtools_stats_raw` 1 780 032, `samtools_stats_sections` 3 155, `bambu_counts_gene` 50,
  `bambu_counts_gene_long` 159 138, `bambu_counts_transcript` 50,
  `bambu_counts_transcript_long` 415 356, `bambu_sample_pca` 6, `bambu_sample_correlation` 6,
  `bambu_top_variable_genes` 100, `deseq2_results` 208 722, `deseq2_top_expressed` 200,
  `dexseq_results` 419, plus the two raw DESeq2 / samplesheet scans.
- `gtf_transcripts_raw` / `gtf_transcripts` skipped cleanly as designed: the optional gate did
  its job, no file on disk, no failure.
- `multiqc_data` failed on NS-D12 (no `multiqc` module in `depictio/cli/.venv`), which aborts
  the run before step 7, so **no dashboard was imported**. The retry through the repo venv,
  which does carry MultiQC 1.35, never reached step 1: the instance's API wedged at 18:45 on an
  unrelated uvicorn reload and only a container restart clears it.

**Outstanding, for whoever has the restarted instance:** re-run
`.venv/bin/python -m depictio.cli run --template nf-core/nanoseq/3.0.0 --data-root
~/Data/depictio-nfcore/nanoseq/3.0.0/megatest --project-name lot2-nanoseq --overwrite`, then
capture the seven tab screenshots. The dev viewer on 5612 additionally predates the
`@genome-spy/core` install and throws "Failed to fetch dynamically imported module" on every
advanced-viz tile until its image is rebuilt, so screenshots need that rebuild too. Neither is
caused by this template.

## 2026-09-22 review fixes

- `dashboards/base.yaml`: the `Significance thresholds` section (adjusted p-value and log2
  fold-change `RangeSlider`s on `deseq2_results`) is no longer pinned and persistent on the
  main tab; it now lives in the `DE and usage` tab's own `filter_sections`
  (`ns-de-filter-padj`, `ns-de-filter-log2fc`), the only tab that renders that DC.
- `template.yaml`: new link `samples.sample_id -> gtf_transcripts.sample` (the DC's own column
  name), so the `Isoforms` structures follow the persistent sample picker.
- `test_shipped_dashboard_yamls.py -k nanoseq` passes. `.db_seeds` not regenerated here.

# Wave 2b pass, 2026-09-23 (PR #1102)

## What changed
- **Nx ladder** (`Basecall and read QC`): new transformed DC `samtools_read_length_nx`
  (versioned recipe `recipes/read_length_nx.py`, reads the `samtools_stats_raw` scan) with
  N1..N99 per library from the exact `RL` histogram; bound as a `profile` with an N50 marker.
  It replaces the N50 bar (N50 is rung 50). Test: `depictio/tests/recipes/test_samtools_nx_ladder.py`.
- **DE views**: the DESeq2 volcano carries `views: [volcano, ma, qq]` with the MA and QQ
  bindings and `controls_placement: header`; the separate `deseq2/ma` and `deseq2/qq` tiles
  (legacy kinds) are gone. The DEXSeq volcano offers `views: [volcano, qq]` (no mean
  intensity, so no MA).
- **DEXSeq usage**: new transformed DC `dexseq_usage` (recipe `recipes/dexseq_usage.py`,
  DEXSeq results + Bambu transcript counts), per-library transcript share of the six genes with
  the smallest gene-level q-value; bound as a stacked, faceted `figure bar`.
- **Header controls** on the length-vs-quality `scatter_xy`, the PCA `embedding`, the
  depth-vs-complexity `scatter_xy`, both volcanoes and the `transcript_structure` tile.
- **`show_histogram: true`** on every threshold `RangeSlider` (quality cutoff, both log CPM
  floors, log2 mean expression, adjusted p-value, log2 fold change). The two distribution-axis
  sliders (`bin`) keep the plain slider.
- Links: `samples.sample_id` to `samtools_read_length_nx.sample` and `dexseq_usage.sample`.

## Discrepancies
- **NS-D14 (input not published)** Read length against quality as a per-read density cannot be
  drawn: nanoseq publishes no per-read table (NanoPlot runs without `--raw`, pycoQC needs
  `sequencing_summary.txt`, absent on this FASTQ-started run). The scatter stays one point per
  library, without `density: true`. samtools stats `FFQ` is quality by cycle, not by read length.
- **NS-D15 (check passed)** The recomputed N50 rung equals NanoStat's N50 for all six
  libraries (919, 1961, 1257, 1326, 1400, 1402).
- **NS-D16 (input not published)** No sashimi: nanoseq publishes no splice-junction table and the
  megatest mirror holds no BAM. No `transcript_structure` data either: `bambu/extended_annotations.gtf`
  is absent (quantification-only run), so the optional `gtf_transcripts` DCs skip and that tile
  stays empty, as before. No genomic coordinates exist anywhere in the run's tables, so there is
  no locus section.
- **NS-D17** Facet order of the usage figure follows Plotly's order of appearance, not the
  q-value ranking; the q-value is in each facet title.

## What was run (2026-09-23)
```
uv run pytest -q depictio/tests/models/test_shipped_dashboard_yamls.py      # 853 passed, 1 xfailed
uv run pytest -q depictio/tests/models/test_catalog.py                      # 99 passed
uv run pytest -q depictio/tests/recipes/test_samtools_nx_ladder.py          # 2 passed
python -m depictio.cli run --template nf-core/nanoseq/3.0.0 --data-root ... --dry-run   # 8/8
.venv/bin/python -m depictio.cli run ... --project-name lot2-nanoseq        # 8/8, live
```
Live rows: samtools_read_length_nx 594, dexseq_usage 84, samtools_stats_sections 3 155,
deseq2_results 208 722, dexseq_results 419, bambu_counts_transcript_long 415 356; the
optional GTF pair skipped. Screenshots: `/tmp/claude-502/shots-nanoseq/` (7 tabs + tile shots,
volcano MA and QQ views clicked live).

# Wave 3

**Date:** 2026-09-23. Offline only (no ingest, no live check): the stack belongs to the main
session.

## What changed

- **Tabs 7 -> 6, MultiQC first.** Run hub became the `MultiQC` tab (general statistics, FastQC,
  samtools flagstat/idxstats, pinned sample sheet). Run dynamics folded into `Reads and read
  length` (the aligned read-length profile plus a 2-sentence pycoQC note). `DE and usage` split:
  DESeq2 is `Gene expression (DESeq2)`; the DEXSeq section moved to the top of `Isoform usage
  and expression`.
- **Glance strip.** Pinned persistent, 4 cards on every tab (libraries by condition, reads,
  gigabases, N50); the hub copies and `ns-sheet-card-condition` are gone.
- **Blockers.** Q-ladder cards (`ns-rq-card-pct/-ladder-reads/-mb`) scoped to the Q10 rung
  with `filter_expr`, Q10 in the title. Recomputed on the megatest: 1 788 362 reads and
  2 187.1 Mb at Q10 or above (against 9 627 631 basecalled; the old sum over all rungs gave
  16.8 M). The dead `section` / `bin` filters on Run dynamics and Alignment are removed. The
  biotype claim on the DE tab is dropped together with the DE copies of the Quantification
  counts, so no `deseq2_results -> bambu_counts_gene_long` link was added. top_n on
  `max` cards replaced by `box_plot`; `ns-is-card-genes` keeps top_n (nunique shows per-library
  values since wave 3a) but is scoped to `count > 0`.
- **Redundancies removed.** Ladder x4 -> ladder AV + table (`ns-rq-fig-ladder`,
  `ns-rd-mqc-readsbyquality` dropped). NanoStat x3 -> DC table only (`ns-rq-mqc-nanostat-table`,
  `ns-rd-mqc-lengthdist` dropped). `ns-de-fig-distribution`, `ns-de-table-counts`,
  `ns-qt-av-topcount`, `ns-is-av-heatmap`, `ns-hub-fig-depth`, the Run dynamics samtools cards
  (except supplementary alignments, now on Alignment) and samtools `Percent mapped` / `Alignment
  stats` panels dropped. The wide `bambu_counts_gene` / `bambu_counts_transcript` DCs are no
  longer bound and were removed from template.yaml.
- **Reference table.** The DESeq2 top-200 table is no longer pinned; it is a collapsed table on
  the DESeq2 tab. Pinned tables: the sample sheet only.
- **Genericity.** No A549 / K562 / SG-NEx / gene id / run numbers in any dashboard text;
  "the run's contrast" in titles; `coverage_max: 60` gauge removed. `forbidden_terms` added to
  megatest.yaml. Median log-CPM cards scoped to detected features (`count > 0`); samtools
  percentage cards scoped to the SN row. Correlation heatmap: ward + Blues.
- **Filters.** Every tab has an open tab-local section: Run scope (MultiQC), Read QC scope
  (mean-quality Slider `gte` + N50 range on NanoStat), Alignment scope (library), Feature scope,
  DE scope (5 filters in one section), Isoform scope.

## What was run

```
uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py \
  depictio/tests/models/test_template_conventions.py -q -k nanoseq -rxX
python -m depictio.cli run --template nf-core/nanoseq/3.0.0 --data-root ... --dry-run   # 8/8
```

## Design from METADATA_FILE (wave 3 genericity follow-up)

`samples.py` no longer parses `input_file`. The design comes from an optional table declared
through `METADATA_FILE` / `METADATA_ID_COL` / `GROUP_COL` (the ampliseq convention; the
`group_col` and `id_col` values reach the recipe through the transform `params` channel),
joined on the sample name or on the samplesheet group. `condition` is the `GROUP_COL` column,
the design-table columns `protocol`, `source_replicate` and `run_id` feed the hub columns of
the same name (`unknown` when absent), and other factors ride along as extra columns. Without
a table, `condition` is the samplesheet group recovered from the pipeline-built
`<group>_R<replicate>` name. The megatest's table is vendored as `input/sample_metadata.tsv`
(built once from the source dataset's library annotations, the values the old FASTQ-name
parse produced) and set in `reference.vars`. Checked on the megatest: the hub with the
vendored table is frame-identical to the previous parse; without it the confounders read
`unknown`. Output schema unchanged (9 columns; extra factors are optional columns).

## Still open

- Without `METADATA_FILE` the library preparation, source replicate and flow-cell run filters
  and the two `Sample structure` donuts show a single `unknown` value. They stay bound (the hub
  columns always exist); pruning them per variable would need a component-level conditional.
- `ns-qt-card-top50` (median of a per-library percentage) still raises the rule-f warning; the
  collection has one row per library, so there is no context to scope.
- `ns-is-av-structures` has no gene picker source besides its header; not bound to the DEXSeq
  table selection.
- Not checked live: the new filter_expr cards, the Slider `gte` filter and the new layout.
