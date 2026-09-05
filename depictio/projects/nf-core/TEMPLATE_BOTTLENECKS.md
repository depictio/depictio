# What blocks and limits nf-core templating in Depictio

Companion to `MEGATEST_STATUS.md`. That file records what the **AWS megatest bucket**
publishes. This one records what **Depictio itself** lacks, found while building the
lot-1 templates (differentialabundance 2.0.0, funcscan 4.0.0, airrflow 5.1.0,
rnafusion 4.1.3, rnaseq 3.26.0, taxprofiler 2.0.1, chipseq 1.2.0, atacseq 1.2.2 and
cutandrun 3.1) against real runs.

Every item below was hit in this lot, not predicted. Each says what happened, why it
costs, and the smallest fix that would remove it. Items are ordered by how much they
cost to work around.

## 1. Recipes cannot see which file a row came from

`_resolve_glob_source` in `depictio/recipes/__init__.py` reads each file a glob matches
and concatenates them with `pl.concat(..., how="diagonal_relaxed")` **without a
per-file label**, and `pl.read_csv` has no `include_file_paths` parameter. A data
collection **scan** does not have this problem, because it uses `pl.scan_csv`, which
does.

So any pipeline output whose sample identity lives in the **path** rather than in a
column cannot be attributed inside a recipe:

- run_dbCAN writes `cazyme_annotation/<sample>/<sample>_overview.tsv`. The funcscan
  recipes recover the sample from the assembly-accession prefix of the gene id. That is
  correct for funcscan only, and is a per-pipeline workaround, not a mechanism.
- DESeq2 writes `<contrast>.deseq2.results.tsv`, with the contrast **only** in the file
  name. differentialabundance works around it by declaring a `_raw` collection scanned
  with `polars_kwargs: {include_file_paths: source_path}` and a tidy collection that
  reads it through `dc_ref`. That doubles the collection count and adds an ordering
  constraint (item 3).

**Smallest fix:** a `file_column` option on `RecipeSource`, or have
`_resolve_glob_source` always add a path or stem column. One change removes two
workarounds and the extra collections.

## 2. `optional: true` is not honoured on a glob source

`RecipeSource(optional=True)` is respected for `path` and `dc_ref` sources.
`_resolve_glob_source` raises unconditionally when nothing matches. A recipe whose
optional inputs are globs therefore hard-fails instead of degrading, so optionality has
to be pushed up to the template level (prune the whole collection) even when the recipe
could have produced a smaller frame.

## 3. `dc_ref` makes declaration order load-bearing, silently

A `dc_ref` source is resolved by reading the referenced collection back from **its Delta
table in S3** (`depictio/cli/cli/utils/deltatables.py`), which exists only once that
collection has been processed. Two consequences, neither visible in the schema:

- the referenced collection must be declared **before** the one that reads it;
- ingestion must stay sequential (`DEPICTIO_INGEST_DC_WORKERS` unset).

funcscan hit this with its `screening_summary` hub and had to move it last in
`data_collections`. The failure message names the reading collection, not the ordering.

**Smallest fix:** topologically order the collections by their `dc_ref` edges at ingest
time, or fail validation with an explicit ordering error.

## 4. Catalog loading is all-or-nothing

`load_catalog_entries()` raises `ValueError: invalid catalog entry
depictio/catalog/<tool>` when a folder holds recipes but no `module.yaml`. There is no
per-folder skip, so **one** half-written tool makes every `use:` in **every** shipped
dashboard unresolvable at once. During this lot that broke ampliseq, viralrecon,
variantbenchmarking and three in-flight templates simultaneously, with an error naming
only the unrelated folder.

**Smallest fix:** skip and warn on an incomplete folder instead of raising, or validate
folders independently so one bad tool cannot take the catalog down.

## 5. `find` is one glob per output, and `**` is one segment

`PurePosixPath.match` treats `**` as a single path segment, and `full_match` (which does
not) is Python 3.13 only while CI runs 3.12.9. The shipped
`**/multiqc/multiqc_data/multiqc.parquet` globs therefore cannot match rnaseq's
`multiqc/star_salmon/multiqc_report_data/multiqc.parquet`.

This lot added `CatalogFind.path_glob_alt`, a list of alternates tried in turn. It works,
but it means every new nesting depth a pipeline invents is another literal alternate in
sixteen YAML files.

**Smallest fix:** a matcher where `**` spans segments, applied to a single `path_glob`.

## 6. Every new MultiQC section needs a hand-written stub

The conformance project synthesises a MultiQC report covering every `section` the
catalog declares, from `STUB_BUILDERS` in
`depictio/projects/init/catalog_conformance/scripts/multiqc_stubs.py`. A section with no
stub is not fatal, but it is recorded as an **exemption** and stops being covered. This
lot adds fifteen MultiQC catalog entries (bracken, centrifuge, deeptools, dupradar,
featurecounts, kaiju, metaphlan, nanoq, nonpareil, picard, preseq, qualimap, rseqc,
salmon, star) against fifteen pre-existing builders, so the stub file must roughly
double for coverage to keep up.

## 7. Depictio has no MultiQC version gate, only a filename regex

Depictio reads `multiqc.parquet` and nothing else. That name is MultiQC >= 1.31 (1.30
wrote `BETA-multiqc.parquet`, older releases wrote none). The template's scan regex is
the **only** gate, so a run from an older MultiQC surfaces as a missing data collection
with no diagnosis. chipseq 1.2.x published MultiQC 1.9 and had to be reprocessed with
the pinned 1.35 before it could be templated at all.

Two follow-on hazards:

- a reprocessed report's **anchors and plot names differ** from the original, so
  `dc_specific_properties.modules` / `plots` authored against the old report silently
  mismatch. `multiqc.reprocess: true` in the manifest is what makes this visible.
- a run can publish a parquet that is technically valid but **empty**: funcscan 4.0.0
  writes a single `run_metadata` row with no general-stats table and no module sections,
  because the pipeline feeds MultiQC nothing but software versions.

**Smallest fix:** read the parquet's `multiqc_version` at ingest and report a too-old or
module-less report as a named condition rather than as an absent file.

## 8. The standalone dashboard import is bound to the project name

`validate_schema_online` in `depictio/cli/cli/commands/dashboard.py` resolves the
dashboard's `project_tag` through `/projects/get/from_name/{name}`, and `--project/-p`
does **not** override that lookup. So a project created under any other name cannot take
a re-imported dashboard, and the error is a bare `HTTP 404` naming the tag.

`depictio-cli run` step 8 does not have this problem: it passes the id of the project it
just created. The two paths disagree, which is what makes the failure confusing.

A smaller wart in the same command: the import summary prints the component count of the
**main** dashboard only ("Components: 14") while it actually writes every tab in the
file.

## 9. Seeding is not part of templating yet

None of the seven templates ships `.db_seeds`, `STATIC_IDS` or `db_init` registration, so
none of them appears on a fresh deployment. The export-then-remap flow that would produce
those seeds is the one variantbenchmarking still lacks, and export-derived seeds churn
component indices on every re-import. This is the single largest gap between "the
template ingests" and "the template ships".

## 10. Visualisation kinds the life-science outputs actually wanted

Bound with a code-mode figure in this lot because no kind exists:

- diversity profile with confidence ribbons (airrflow Hill profiles)
- fusion protein-domain track (rnafusion FusionInspector)
- **metagene / reference-point signal profile**: mean signal against position
  relative to a TSS or across a scaled gene body, one line per sample, classically
  paired with a heatmap of every region sorted by signal. This is the strongest
  candidate for the next kind, because it recurs across four pipelines in this lot
  alone: cutandrun `04_reporting/deeptools_heatmaps/*/*.plotHeatmap.mat.tab`,
  atacseq ataqv TSS enrichment and deepTools plotProfile, chipseq deepTools
  plotProfile, rnaseq RSeQC gene body coverage.

  `coverage_track` is the closest existing kind and does not fit: it requires a
  `chromosome` column, treats `position` as an absolute coordinate rather than a
  signed offset from a reference point, and stacks one subplot per sample where
  this figure needs the samples overlaid to be read at all. The parts that justify
  a kind rather than a code-mode line are the reference-point axis (a labelled
  marker at 0, scaled-body ticks) and the paired per-region heatmap; a plain
  `px.line` covers the rest, which is why the lot ships code mode for now.

Wanted by pipelines not in this lot, and still missing:

- V-to-J pairing heatmap (airrflow, full rearrangement tables)
- 96-context mutational signature, and circos (oncoanalyser)
- knee plot (scrnaseq), isomiR ladder (smrnaseq), jplace reader (phyloplace),
  assembly graph (bacass)

Also: the `phylogenetic` kind has no catalog output binding it, and `upset_plot` and
`sankey` can only be bound through a dashboard `config:` block because their roles are
list-valued rather than required.

## 11. List-valued render roles were never actually validated

`test_all_recipe_output_roles_resolve_against_the_recipe` did `set(r.roles.values())`,
which raises `TypeError: unhashable type: 'list'` on exactly the roles `_LIST_ROLES`
declares: sankey `steps`, sunburst `ranks`, complex_heatmap `value_columns` and
`row_annotation_cols`. The first such render the loader reached made the whole test
error out, so the assertion had never checked those roles at all. Six shipped renders
across four tools now use them. Fixed in this lot by flattening before comparing.

## 12. Large fan-in inputs have no pre-aggregation story

A template can only bind what a recipe can read in one pass. crisprseq publishes 6195
files, airrflow's per-sample `*_db-pass.tsv` set is 227 MB, funcscan's raw per-tool
outputs are 2.8 GB against 6.5 MB of aggregated reports. Every template in this lot
binds the aggregated report and leaves the per-sample corpus alone, which is why
airrflow's V-to-J pairing and rnafusion's per-read evidence are unbound.

## 13. A stale API catalog cache corrupts imports silently

`load_catalog_entries()` is `@lru_cache(maxsize=1)` and nothing in the shipped code
ever calls `cache_clear()`. The API process answers from whatever `depictio/catalog/`
held the first time it was asked, so a tool added while the stack runs stays invisible
until the container restarts.

The damage is not confined to lookups. When the API cannot expand a `use:` handle the
component does not raise, it degrades to a raw dict: `viz_kind` and `catalog_source`
are stored as null, the inherited role bindings and config defaults are lost, and the
import still reports success. `AdvancedVizDispatch.tsx` dispatches on `viz_kind`, so
the viewer renders `Unknown advanced viz kind: ""` for a dashboard that every
CLI-side check passed.

The split across this branch is exactly whether the tool folder existed at API start:

| project | advanced_viz tiles with a resolved kind |
|---|---|
| ampliseq, viralrecon, funcscan, airrflow, differentialabundance | all of them |
| chipseq | 4 of 7 |
| rnafusion | 0 of 9 |
| taxprofiler | 0 of 8 |
| rnaseq | 0 of 2 |

Two probe imports through the same endpoint isolate it: `fusionreport/caller_upset`
stores null, `hamronization/arg_upset` stores `upset_plot` with a 14-key config.

Recovering needs a container restart AND a re-ingest, because the null is persisted;
restarting alone leaves the stored dashboards broken. Declaring a redundant `viz_kind:`
in the YAML would hide the symptom while still losing the config defaults and the
catalog badge, so no template in this lot does that.

## 14. A long annotation label can collapse a complex_heatmap to nothing

Binding `row_annotation_cols` to a field whose labels are long silently
destroys the plot. Plotly sizes the strip's margin from the longest label and
nothing clamps it against the tile, so on funcscan's ARG heatmap a 517 px tile
got a 346 px right margin and a plot area 284 px wide NEGATIVE: the colour bar
and a few tick labels drew, and not one cell did.

Nothing catches this before a human looks. The data is correct, the recipe is
correct, the roles resolve, every bound column exists, the server returns rows,
and `test_shipped_dashboard_yamls.py` is satisfied. Only the rendered pixels
are wrong, which is why the browser pass exists.

The template-side fix is to bind a short form of the field and keep the long
one on the row for the table, which is what `hamronization/gene_matrix.py` now
does. The platform-side fix, not attempted here, is for the complex_heatmap
renderer to clamp annotation margins to a fraction of the tile and truncate
labels with a hover, so that no binding can produce a negative plot area.

Worth checking wherever a field is free text rather than a controlled
vocabulary: taxonomy lineages, GO terms and drug classes are all candidates.

## Pipelines considered and not templated in this lot

| pipeline | why not |
|---|---|
| crisprseq | screening arm never published a megatest; 6195-file fan-in needs pre-aggregation |
| smrnaseq | isomiR views need a kind that does not exist |
| scrnaseq | nested `aligner_*` run roots plus a missing knee plot |
| oncoanalyser | signature and circos kinds missing; run root `HCC1395/` |
| methylseq, raredisease, quantms, bacass | no usable megatest run at all |
