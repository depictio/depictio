---
name: nfcore-template-builder
description: Builds one nf-core pipeline template for Depictio (catalog tools, template.yaml, dashboards, docs) from a megatest run that is already on disk. Invoke with "<pipeline> <version>", e.g. "hic 2.0.0". Sonnet by design; the main session reviews the diff.
model: sonnet
tools: Read, Write, Edit, Glob, Grep, Bash
---

You build ONE nf-core template for Depictio. The pipeline and version are given in the
invocation. Everything you need is local; do not re-derive facts that are written below.

## Hard rules

- Work only in the worktree you are started in. No git write operations (`git log/show/diff`
  are fine). No docker except `docker logs`. No `uv sync`, `pnpm`, `npm`, `pip`.
- Edit only: `depictio/projects/nf-core/<pipeline>/<version>/**`,
  `depictio/projects/nf-core/<pipeline>/recipes/*.py`, and the catalog tools this pipeline
  owns (`depictio/catalog/<tool>/` for tools that do not exist yet, plus new
  `depictio/catalog/multiqc/<module>.yaml` panels). Never touch `depictio/models/**`,
  `packages/**`, `depictio/viewer/**`, `depictio/api/**`, another pipeline, or an existing
  catalog output. Shared files (`.gitignore`, `multiqc_stubs.py`, `TEMPLATE_BOTTLENECKS.md`,
  `MEGATEST_STATUS.md`, `VALIDATION_SCENARIOS.md`, `scripts/nfcore_showcase.py`): put the
  snippet in your final report, do not edit.
- Token budget. The data is at `~/Data/depictio-nfcore/<pipeline>/<version>/megatest/`
  (DATA_ROOT). Never list S3. Inspect with `find DATA_ROOT -type f | sed 's|.*/megatest/||' |
  sort | head -300`, `head -5`, `wc -l`, `zcat | head`. Never Read a real data file whole.
  Never Read a reference file over 300 lines whole: `grep -n` for the block you need, then
  `sed -n 'a,bp'`. The excerpts in this brief replace most reference reading.
- Run each validation command once per change, not repeatedly.

## Deliverables (the cutandrun 3.1 file set)

```
depictio/projects/nf-core/<pipeline>/<version>/
  template.yaml            megatest.yaml (already there; fix keys to the real layout)
  dashboards/base.yaml     docs/dashboards.md (narrative; image links added later)
  VALIDATION_REPORT.md     download_test_data.sh (3-line wrapper, copy cutandrun's)
  input/<samplesheet>      pipeline_info/software_versions.yml (copied from DATA_ROOT)
  .db_seeds/.gitkeep
```
Plus the catalog tools. Target: ~90% of dashboard tiles carry a `use:`.

## Catalog authoring contract

Flat layout: `depictio/catalog/<tool>/module.yaml` + one `<output>.yaml` per output + a
`<output>.tsv` fixture (10-20 rows cut from the real file with `head`, header identical to
the schema) + an optional `<output>.py` recipe. A recipe owns the schema, so its YAML has
NO `columns:`; a recipe-free output declares `columns:` instead.

```yaml
# module.yaml
id: preseq
name: Preseq
nf_core_url: https://github.com/nf-core/modules/tree/master/modules/nf-core/preseq/lcextrap
homepage: https://github.com/smithlabcode/preseq
```
```yaml
# complexity_curve.yaml (recipe-backed, binds an advanced_viz kind + figure + cards + table)
id: preseq_complexity_curve
name: Library complexity curve
find:
  path_glob: "**/*.ccurve.txt"          # ** crosses directories; add path_glob_alt for variants
recipe: preseq/complexity_curve.py
fixture: complexity_curve.tsv
renders_as:
  - { id: complexity_ribbon, component: advanced_viz, kind: profile,
      roles: {series: sample, x: total_reads, y: expected_distinct, lower: lower_ci, upper: upper_ci} }
  - { component: figure, visu_type: line, dict_kwargs: {x: total_reads, y: expected_distinct, color: sample} }
  - { component: card, column: expected_distinct, aggregation: max,
      secondary_layout: top_n, breakdown_col: sample, top_n_count: 3 }
  - { component: table }
```
```python
# complexity_curve.py: the recipe contract
import polars as pl
from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.sample_ids import strip_stage_suffixes
RAW_DC_TAG = "preseq_ccurve_raw"
SOURCES = [RecipeSource(ref="curves", dc_ref=RAW_DC_TAG)]
EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {"sample": pl.Utf8, "total_reads": pl.Float64, ...}
def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame: ...
```
Rules: dtypes must match EXPECTED_SCHEMA exactly (`pl.len()` is UInt64, cast it: the TSV
round-trip hides this and ingestion does not); recover the sample id from the file name via
`include_file_paths: source_path` + `depictio/recipes/lib/sample_ids.py`; decimate inside
the recipe for `profile` (never sampled, keep <= 200 points per series); every render a
dashboard will `use:` carries an `id:`. Card secondary layouts must ship the config they
read: `top_n` -> `breakdown_col` + `top_n_count`; `box_plot` -> `aggregations: [box_plot_stats]`;
`donut` -> `breakdown_col`; `attrition` -> `attrition_cols`; `gauge` -> `coverage_max`.
Recipe-free example: `depictio/catalog/mosdepth/amplicon_coverage.yaml`. Attrition/gauge
cards: `depictio/catalog/enchantr/sequence_counts.yaml`.

MultiQC panel (one per module the pipeline needs that has no `depictio/catalog/multiqc/<module>.yaml`):
copy `depictio/catalog/multiqc/preseq.yaml` (origin_tool, path_glob + the 2 path_glob_alt,
the shared conformance parquet fixture, one `{component: multiqc, section: <module>}`).
Modules names: `depictio/catalog/_index/multiqc_modules.txt`. Coverage exemptions are
computed automatically; a stub is optional and goes in the report as a snippet.

## template.yaml contract (copy the shape of cutandrun/3.1/template.yaml)

```yaml
template:
  template_id: "nf-core/<pipeline>/<version>"
  description: "..."
  version: "1.0.0"                       # template schema version, not the pipeline's
  variables: [{name: DATA_ROOT, description: "...", required: true}]
  reference: {vars: {}}
  provenance: {sources: [{name, glob, format: yaml|tsv|csv, pick: latest, group}],
               groups: [{group: "Software versions", key_patterns: ["*"]}]}
  dashboards: ["dashboards/base.yaml"]
name: "<Project name>"                    # becomes the dashboard project_tag
project_type: "advanced"
is_public: true
workflows:
  - name: "<pipeline>"                    # becomes every component's workflow_tag
    version: "<version>"
    engine: {name: nextflow, version: "..."}
    catalog: {name: "nf-core", url: "https://nf-co.re"}
    repository_url: "https://github.com/nf-core/<pipeline>"
    data_location: {structure: flat, locations: ["{DATA_ROOT}"]}
    data_collections: [...]
links: [...]
```
Three DC kinds: scan (`config.scan.mode: recursive`, regex on the FILE NAME only, never on
directory names; `dc_specific_properties.polars_kwargs` with `include_file_paths:
"source_path"`, `infer_schema_length: 0` when needed), transformed (`source: "transformed"`,
`transform.recipe: "<tool>/<output>.py"` for catalog recipes or
`"nf-core/<pipeline>/<file>.py"` for pipeline-local ones), and MultiQC (`type: "MultiQC"`,
regex `multiqc/multiqc_data/multiqc.parquet`, `dc_specific_properties.modules: [...]` +
`plots:` naming MultiQC 1.35 titles). `metatype: Metadata|Aggregate`, `optional: true` for
collections a run may not write, `columns_description` for EVERY column. The raw-scan +
recipe two-step (`<x>_raw` feeding `<x>` via `dc_ref`) is the idiom when the sample name
lives only in the file name. `links:` entries: `source_dc_tag / source_column /
target_dc_tag / target_type: table|multiqc / link_config: {resolver: direct|pattern|
sample_mapping, ...}`, hub-to-everything from the sample sheet plus a couple of reverse
links. `use:` never appears in template.yaml, only in the dashboard.

## dashboards/base.yaml contract

Gated by `depictio/tests/models/test_shipped_dashboard_yamls.py` (read only its test names
and docstrings with `grep -n "def test_\|\"\"\"" -A2`). The invariants: the MultiQC landing
tab holds MultiQC panels only (text, interactive, `placement: floating` and pinned
persistent sections are exempt); `interactive` components live in `filter_sections`,
everything else in `grid_sections`; section `icon`/`color` come from
`SECTION_ICON_OPTIONS` in `depictio/viewer/src/components/sections/sectionIcons.ts`;
every `advanced_viz` `use:` resolves to a catalog render id; card secondary strips carry
their config; tables and every dense tile are `w: 8`; text bodies get ~1 grid row per 300
characters; UpSet palettes valid; tab models validate.

Header + main tab (then one `tabs:` entry per funnel step):
```yaml
version: 1
main_dashboard:
  title: nf-core/<pipeline>
  subtitle: "nf-core/<pipeline> <version> megatest: <what the cohort is>"
  project_tag: <template name:>
  main_tab_name: MultiQC
  tab_icon: /assets/images/logos/multiqc_icon_color.svg
  tab_icon_color: orange
  icon: /assets/images/workflows/nf-core.png      # on EVERY tab
  icon_color: green
  workflow_system: nf-core
  filter_sections: [...]
  grid_sections: [...]
  components: [...]
tabs:
- title: <Step>
  tab_order: 2
  tab_icon: mdi:<icon>
  tab_icon_color: <colour unique per tab>
  icon: /assets/images/workflows/nf-core.png
  icon_color: green
  workflow_system: nf-core
  grid_sections: [...]
  components: [...]
```
Layout: 8 columns. Text intro `w: 8, h: 1`. Cards `w: 2, h: 2`, four across, never 3 of 4.
Table / figure / advanced_viz `w: 8, h: 7` (contact maps h 9). Two pinned persistent
sections ride every tab: the sample sheet (`pin: top`, `collapsed: true`) and the reference
tables / thresholds (`pin: bottom`). Tabs are a funnel: MultiQC -> QC -> the pipeline's
core result -> comparisons; filters compose forward. Component tags use a 2-letter pipeline
prefix: `<xx>-<tab>-<what>`.

The multi-interactive grouped block (several `interactive` components sharing `section:`
and `group:` inside a persistent pinned filter_section):
```yaml
  filter_sections:
  - {name: Sample filters, icon: mdi:filter-variant, color: teal,
     description: Applies to every tab through the project links, persistent: true, pin: top}
  components:
  - component_type: interactive
    tag: xx-filter-sample
    index: xx-sample-filter
    section: Sample filters
    group: Sample scope
    workflow_tag: <pipeline>
    data_collection_tag: samples
    interactive_component_type: MultiSelect      # Select for single-choice, RangeSlider for thresholds
    column_name: sample_id
    column_type: object                           # float for RangeSlider
    display: {title_size: md, custom_color: '#00897B', icon_name: 'mdi:test-tube'}
    placement: left
    title: Sample
    layout: {x: 0, y: 0, w: 1, h: 3}
  - component_type: interactive                  # sibling: same section + group, y: 3
    ...
```
One advanced_viz tile:
```yaml
  - component_type: advanced_viz
    tag: xx-qc-av-fingerprint
    index: xx-qc-av-fingerprint
    section: Coverage concentration
    workflow_tag: <pipeline>
    data_collection_tag: deeptools_fingerprint_metrics
    use: deeptools/fingerprint_scatter            # catalog render id
    config: {x_title: ..., y_title: ..., color_col: sample, selection_enabled: true, selection_column: sample}
    title: "Coverage concentration per library"
    description: "What the reader learns from it, one or two sentences."
    title_size: h3
    layout: {x: 0, y: 1, w: 8, h: 7}
```
Text bodies use folded scalars (`body: >`), never `|`. No hardcoded colours outside the
`display.custom_color` of interactive components.

## Kinds you can bind (roles, required first)

profile (series, x, y | lower, upper), scatter_xy (x, y | label, color, size),
complex_heatmap (index; matrix columns inferred), upset_plot (value_columns list),
embedding (sample_id, dim_1, dim_2 | dim_3, cluster, color), stacked_taxonomy (sample_id,
taxon, rank, abundance), sunburst (abundance + ranks list), volcano, ma, da_barplot,
dot_plot (cluster, gene, mean_expression, frac_expressing), coverage_track (chromosome,
position, value | end, sample, category; config `mark: line|rect|point`, `facet_by_sample`),
signal_matrix (region_id, position, value | group), manhattan, lollipop, qq, oncoplot,
metric_ci_bars, pr_benchmark, roc_pr_curve, confusion_matrix, sankey, rarefaction.
New in lot 2 (built by the kinds agent; bind them by these names):
contact_map (chrom1, start1, chrom2, start2, count | sample, end1, end2),
knee_plot (sample, rank, umi_count | is_cell),
damage_profile (sample, end "5p"|"3p", position, base_change, frequency | lower, upper).
Do not bind `phylogenetic` (two-DC blocker) and do not propose `agreement_matrix` (policy).
Shared output ids other pipelines rely on: `samtools/stats`, `samtools/flagstat`,
`qualimap/bamqc_genome_results` (eager owns), `bcftools/stats_summary`, `bcftools/stats_tstv`
(sarek owns). Reference them; create them only if you are that owner.

## Validate (once each, after the writing is done)

```bash
uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py -x -q
uv run pytest depictio/tests/models/test_catalog.py -x -q
uv run python -c "..."   # run each recipe transform on the real files, print schema + shape
depictio/cli/.venv/bin/depictio-cli run --template nf-core/<pipeline>/<version> \
  --data-root ~/Data/depictio-nfcore/<pipeline>/<version>/megatest --dry-run
uv run ruff format <your .py> && uv run ruff check <your .py>
pre-commit run --files <your files>
```
A `use:` on a lot 2 kind may fail until the kinds agent lands: report it, do not work around.
Do NOT ingest (no server).

## Final report (under 60 lines)

Files created/modified. Catalog outputs (tool/output -> renders). `use:` coverage n/total.
Kinds bound. Manifest changes (real layout vs guess). Discrepancies as `<XX>-D<n>`.
Snippets for shared files: multiqc stub (if any), `.gitignore` lines, TEMPLATE_BOTTLENECKS
§10 row, MEGATEST_STATUS row, VALIDATION_SCENARIOS section, `nfcore_showcase.py` Scenario.
Open questions.

## Pitfalls found in lot 2 (read before writing any YAML)

- MultiQC `plots:` / `selected_plot:` take the bare section name (e.g. "Read Mapping"), never
  the plot's internal `title` config. Confirm with `multiqc.list_plots()` on the run's parquet.
- Catalog `roles:` may carry required AND optional roles (validated against the kind's full
  vocabulary in `catalog.py::Render._check_component`); a `use:` tile inherits all of them, so
  a dashboard `config:` is only for overrides and display settings.
- A render `id:` must differ from the output's short id (output id minus `<tool>_`), or
  `_load_tool_dir` raises.
- `nf_core_url` must be a `github.com/nf-core/modules/...` URL; pipeline-local modules use
  `source_url`.
- int64/float64 columns take Slider/RangeSlider only, never Select.
- Advanced-viz configs are `extra="forbid"` per kind, and a wrong key can silently degrade the
  component instead of raising. Copy the exact field names from `configs.py` (grep
  `class <Kind>Config`) or from a shipped template using the same kind; never reuse
  `scatter_xy` keys (`x_title`, `color_col`, `selection_*`) on another kind.
- Catalog loading is all-or-nothing across `depictio/catalog/`: when agents run in parallel, a
  red `test_catalog.py` may be another agent's half-written dir. Validate your own tool dirs
  in isolation before assuming your files are broken.
- Megatest guesses are often one directory level off (`nanoplot/fastq/<s>/`,
  `minimap2/samtools_stats/`, `hicpro/stats/<s>/`); `params_*.json` may be `params.json` or
  absent on older runs.
- Bundled `multiqc/multiqc_data/multiqc.parquet` fixtures need a `.gitignore` allowlist line:
  report it as a shared-file snippet.
- `--dry-run` does NOT execute scans or recipes. Recipes must be tested through the same raw scan
  the CLI builds (polars read with the DC's `dc_specific_properties`: blank lines come back as
  null in a one-column text scan), not by reading files by hand.
- Scan regexes are matched with `re.match` against the basename, then against the path relative
  to the run root: a path-qualified pattern must start at the run root or with `.*/`.
- Descriptions must not contain `<` or `>` (e.g. "C>T"): the model rejects them as HTML.

## Wave 3 conventions (read before editing any dashboard)

Gated by `depictio/tests/models/test_template_conventions.py` (one test per rule, one
parameter per template; a template listed in its `KNOWN_VIOLATIONS` is xfail until fixed,
then removed from the list so the rule turns strict).

### Genericity
- A template answers the pipeline's questions for ANY run. No megatest sample names, loci,
  genes, organisms, counts, results or run-specific thresholds in titles, subtitles, bodies,
  descriptions, defaults or filters.
- Every `megatest.yaml` carries `forbidden_terms: [...]` (the megatest's sample ids, genes,
  organisms and loci). The lint fails when one appears in any dashboard text (tab title /
  subtitle, section name / description, component title / description / body), matched
  case-insensitively on word boundaries.
- Intros: 2 sentences (`h: 2`), what to look at, not what was found. The lint caps a text
  body at 3 sentences; methods go to docs/dashboards.md.
- `default_record`: absent or data-derived. `default_region`: allowed, documented in one
  sentence ("opens on a documented default, change it in the header").
- Design metadata: variables `METADATA_FILE`, `METADATA_ID_COL`, `GROUP_COL`
  (+ `GROUP_COL_DISPLAY`), as in ampliseq 2.18.0. Dashboards reference `{GROUP_COL}` /
  `{GROUP_COL_DISPLAY}`; never parse the design out of sample names in a recipe.
- Genome build: declare a defaulted variable and reference it wherever an assembly or an
  annotation is set (genome_view / coverage_track `assembly`, `annotation`, template.yaml):
  ```yaml
  variables:
    - {name: GENOME, description: "Genome build of the run (UCSC name)", required: false, default: "hg38"}
  ```
  Any declared variable with a `default` resolves `{NAME}` in template.yaml and in the
  dashboard YAMLs (`--var GENOME=mm10` overrides it). A default does not count as provided
  for `if_var_present` conditionals. Mirror the default in `reference.vars` for the seeded
  reference project.
- Sample ids a file's content lacks: a scan DC uses `polars_kwargs.include_file_paths`; a
  recipe source declares `RecipeSource(..., source_path="source_path")` and derives `sample`
  from that column (never hardcode a sample list).
- MultiQC to hub: do not hand-write a `mappings:` list of run sample names. The generic
  canonicalisation (`depictio/cli/cli/utils/sample_mapping.py::canonicalize_to_hub`) joins a
  MultiQC name to the hub id it equals once read / lane / trimming / stage suffixes are
  stripped, or to the hub id that prefixes it at a `.` `_` `-` boundary.

### Family conventions
- Tab 1 = MultiQC when the pipeline has one (MultiQC panels only), else an Overview tab.
- Pinned persistent glance strip: exactly 4 cards (run size + design), on every tab, no text,
  never repeated as a tab card.
- "Sample sheet" section: pinned top, collapsed, 2-sentence intro, declared on the main tab.
- At most 2 pinned tables; never pin a table a tab also shows (lint: same DC + same `use:`).
- Remove a MultiQC panel when a tile reads the same table; the others go in a collapsed
  section at the bottom.
- Card secondary: `box_plot` for per-library measures; `top_n` only under `sum` or `count`
  (lint). Never average percentages across contexts (lint, warn level: an
  `average` / `median` card over a `*_pct` / `*percent` / `*_frac` column needs a
  `filter_expr` scoping it to one context). Never histogram-strip a one-row-per-sample table.
- `threshold_warn` sits on the failing side of `threshold_value` (lint): below it for
  `threshold_direction: min`, above it for `max`.
- Order inside a tab: cards, distributions, detail, collapsed tables. Every tab has filters
  (pinned persistent + a tab-local section, open). One `record_card` per key (no hardcoded
  default) in a "<unit> detail" section at the tab end.
- A single-value `Slider` filters `>=` (a threshold); use `RangeSlider` for a band.
- Composition bars: percentages, `top_n: 12`, sorted by abundance. One sankey per template.
- Locus: a dedicated tab (or a section on the comparison tab when the navigator reads that
  DC); never the same tracks on two tabs; no lateral chromosome filter.
- Distance heatmaps: `ward` + `Blues`. Replicate / role filters: MultiSelect.
  `advanced_viz_controls: header`.
