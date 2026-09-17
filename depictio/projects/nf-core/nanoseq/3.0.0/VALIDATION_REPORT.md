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
