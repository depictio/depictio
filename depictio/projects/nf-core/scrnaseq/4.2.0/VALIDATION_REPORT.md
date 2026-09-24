# nf-core/scrnaseq 4.2.0: template validation report

**Date:** 2026-09-17
**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-lot2`
**Validator:** local recipe execution (agents A/B) + shipped-dashboard/catalog pytest suites +
`depictio-cli run --dry-run` against the real AWS megatest data (agent C). No local server was
started and nothing was ingested (out of scope for this pass, see "Not done" below).

This report supersedes the original single-route (Cell Ranger only) version of this template.
The dashboard was redesigned around a per-cell QC hub, a MAD-based QC flag, and an optional
aligner-concordance comparison against simpleaf/alevin-fry and kallisto|bustools.

## Data layout change (v1 -> v2)

**v1**: `DATA_ROOT` was the Cell Ranger aligner route's own output directory
(`aligner_cellranger/`), i.e. one route only.

**v2 (current)**: `DATA_ROOT` is the megatest RESULTS ROOT itself (`run_root: ""` in
`megatest.yaml`), holding one subdirectory per `--aligner` route the pipeline supports:
`aligner_cellranger/` (required), `aligner_simpleaf/` and `aligner_kallisto/` (optional, feed
the Aligner concordance tab). `aligner_star/` publishes nothing this template reads and is not
fetched. Every scan pattern in `template.yaml` is path-qualified from that root (`.*/` where any
route could satisfy it, or an explicit `aligner_<x>/` prefix where the route matters), because
scan regexes are `re.match`-ed against the basename first, then against the path relative to
`DATA_ROOT`: an unqualified pattern that matched under `aligner_cellranger/` alone no longer
matches once that prefix becomes part of the relative path. Two patterns inherited from v1
needed this fix:

- `cellranger_metrics_raw` (`metrics_summary.csv`): was `cellranger/count/[^/]+/outs/...`, fixed
  to `.*/cellranger/count/[^/]+/outs/...`.
- `multiqc_data` (`multiqc.parquet`): was `multiqc/multiqc_data/...`, fixed to the explicit
  `aligner_cellranger/multiqc/multiqc_data/multiqc\.parquet$` (not `.*/`, since only the Cell
  Ranger route's parquet is fetched, see "Aligner routes" below).

Verified by walking the real megatest tree and `re.match`-ing every fixed/new pattern against
every file's basename and DATA_ROOT-relative path: each of the 6 CellBender-adjacent patterns
(`cellranger_metrics_raw`, `cellbender_metrics_raw`, `cellranger_cellbender_barcodes_raw`,
`simpleaf_cellbender_barcodes_raw`, `kallisto_cellbender_barcodes_raw`, `multiqc_data`) matches
exactly the one file it is meant to, with zero cross-route collisions.

## Shared-tag deduplication

Agent A's `cellranger/cell_qc.py` and agent B's `nf-core/scrnaseq/{cell_calls_by_method,
aligner_summary}.py` both need CellBender's Cell Ranger-route cell-barcode list. A declared it
as `cellranger_cellbender_cells_raw`; B declared the same scan as
`cellranger_cellbender_barcodes_raw`. Declared once in `template.yaml` under B's tag (2 recipe
files reference it vs. A's 1), and `cellranger/cell_qc.py`'s `CELLBENDER_CELLS_DC_TAG` constant
(and its docstring) updated to match.

## `cellbender_metrics_raw` collision (A's flag, fixed here)

`cellbender_metrics_raw` (pre-existing, `depictio/catalog/cellbender/`) had pattern
`.*/cellbender_removebackground/[^/]+_metrics\.csv$` with no tool qualifier. Under the v2 layout
this now also matches `aligner_simpleaf/` and `aligner_kallisto/`'s identically-named
`*_metrics.csv` files (both fetched by agent B), silently pulling all three routes' CellBender
metrics into one "sample". Fixed by qualifying the pattern to the Cell Ranger route only
(`.*/cellranger/[^/]+/cellbender_removebackground/[^/]+_metrics\.csv$`), mirroring the
qualification already used for the cell-barcode list. The simpleaf and kallisto routes get their
own separately-declared, route-qualified `*_cellbender_metrics_raw` scans (agent B), both
consumed via the shared `cellbender/metrics.py` recipe.

## New outputs (this redesign)

**Cell Ranger route** (`depictio/catalog/cellranger/`, agent A):
- `cell_qc`, the cell hub: one row per called cell, UMI/gene counts, mito/ribo/hb/top-20
  fractions, graph-based + k-means clusters, UMAP/t-SNE/PCA coordinates, CellBender agreement,
  the MAD-based QC flag.
- `cluster_summary`, one row per graph-based cluster, aggregated from `cell_qc`.
- `marker_expression` / `marker_matrix`, mean expression + detection rate of the top cluster
  marker genes, long and wide (for the dot plot and heatmap).
- `diffexp` extended with `cluster_label` and `rank_in_cluster` (id kept).
- `metrics_summary` extended with `_frac` (0-1) twins of the `_pct` columns (id kept).
- `library_metrics_long`, the 5 headline metrics 10x's QC guidance bands, thresholded.
- `mapping_breakdown`, exonic/intronic/intergenic/antisense/unmapped read shares.

**Aligner concordance** (agent B, all `optional: true`):
- `depictio/catalog/simpleaf/`: `barcode_rank`, `mapping_metrics`.
- `depictio/catalog/qcatch/`: `metrics_summary`.
- `depictio/catalog/kallisto/`: `run_metrics`.
- `depictio/projects/nf-core/scrnaseq/recipes/{cell_calls_by_method,aligner_summary}.py`
  (pipeline-local): line every route's cell calls up on one normalised 16-mer barcode
  (`barcode_core`), and translate each route's own headline numbers onto one common schema.

## The MAD rules

Computed per sample, on log1p values (sc-best-practices convention), by `cellranger/cell_qc.py`:
- `mad_low_umi` / `mad_low_genes`: log1p(n_umi) or log1p(n_genes) more than 5 MAD below the
  sample median.
- `mad_high_top20`: the top-20 genes' share of a cell's counts (`pct_top20`) more than 5 MAD
  above the sample median.
- `mad_high_mito`: `pct_mito` more than 3 MAD above the sample median, OR above 8% outright.
- `qc_status` = "flagged" when any of the four is true, else "pass"; `qc_reason` names the first
  failing criterion; `qc_flagged` is the 0/1 form of `qc_status` (so a card can `average` it into
  a "% flagged" reading, the same trick doesn't exist for the 4 individual Boolean criteria,
  whose dashboard cards use `sum`/raw counts instead, see "Discrepancies").

## The no-mito reference finding

The pbmc8k GRCh38 reference bundled with this megatest carries **zero genes named `MT-*`**
(verified: 0 matches in `filtered_feature_bc_matrix/features.tsv.gz`; ribosomal and
hemoglobin genes ARE present, 134 and 4 respectively). `pct_mito` is therefore 0, and
`mad_high_mito` false, for every one of the 8 767 cells on this specific megatest. This is a
property of the reference, not a recipe bug: the column and the MAD rule are unchanged and will
activate against a reference that does carry mitochondrial genes. The dashboard's reading was
adjusted accordingly rather than built around an empty signal:
- `umap_qc` (Embeddings tab) colours by `log10_n_genes`, not `pct_mito`.
- `umi_vs_genes` (Cell QC tab) colours by `qc_status`, not `pct_mito` (also required: `scatter_xy`'s
  optional `color` role only accepts a String column, and `pct_mito` is Float64).
- The Cell QC tab's box plots show `pct_ribo` and `log10_n_umi` by cluster, not `pct_mito`.
- The Cell QC tab's intro text says explicitly why the mito panels read 0/false here.
- `cluster_qc_heatmap`'s `value_columns` drops `median_pct_mito` (constant 0 across every
  cluster on this reference, which the heatmap's row-z-score normalisation cannot handle).

## Aligner routes

nf-core/scrnaseq's `--aligner` flag selects one of 4 quantification routes; this megatest run
published 3 of them (`cellranger` the default, `simpleaf`/alevin-fry, `kallisto`|bustools;
`star`/STARsolo publishes nothing this template reads and was not fetched). Only the Cell Ranger
route is required, it is the only one with matrices, secondary analysis (clustering,
projections, differential expression) and a MultiQC report, so every tab except Aligner
concordance depends on it alone. The simpleaf and kallisto routes are tables-and-JSON only (no
matrices: `af_quant/featureDump.txt`, `map_info.json`, `quant.json`, QCatch's
`metrics_summary.csv` for simpleaf; `run_info.json`, `inspect.json`,
`counts_filtered/cells_x_genes.barcodes.txt` for kallisto), plus CellBender's metrics + cell list
on both, all declared `optional: true`. Neither route's own `multiqc.parquet` is fetched or
scanned: both were inspected and carry only the same sample's FastQC data the Cell Ranger route's
parquet already has, nothing Cell Ranger's MultiQC panel doesn't already show. Barcodes across
routes are normalised to the bare 16-mer (`barcode_core`) before comparison, since Cell Ranger's
own barcodes (and CellBender's on that route) carry a `-1` GEM-well suffix the other two routes
do not. **A Cell Ranger-only run (the pipeline default) leaves the entire Aligner concordance tab
empty**, verified by agent B running `cell_calls_by_method` and `aligner_summary` with every
non-Cell-Ranger source omitted: both still produce a valid (reduced) table rather than erroring.

## Dashboard: tabs, components, links

Rewritten `dashboards/base.yaml`: MultiQC (unchanged shape) + 7 tabs, Library QC, Cell calling,
Cell QC, Embeddings, Clusters, Markers, Aligner concordance (optional). Global cell-level filters
(cluster, QC status, mito %, genes detected, all on `cellranger_cell_qc`) are pinned on every
tab; 3 new `cluster_label` cross-DC links (`cellranger_cell_qc` -> `cellranger_cluster_summary` /
`cellranger_marker_expression` / `cellranger_diffexp`) let a cluster picked anywhere narrow every
downstream tile without leaving the tab. See the accompanying report for the exact per-tab
component counts, kinds used and validation results.

## Automated checks

```bash
uv run pytest -q depictio/tests/models/test_catalog.py
# 99 passed

uv run pytest -q depictio/tests/models/test_catalog.py depictio/tests/models/test_shipped_dashboard_yamls.py \
  -k "scrnaseq or cellranger or simpleaf or kallisto or cellbender or qcatch"
# 10 passed (all from test_shipped_dashboard_yamls.py; test_catalog.py's ids don't carry these
# keywords, so it was additionally run unfiltered, see above)

uv run pytest -q depictio/tests/models/test_shipped_dashboard_yamls.py
# 813 passed, full suite, no -k filter

DEPICTIO_CONTEXT=cli uv run python -m depictio.cli run --template nf-core/scrnaseq/4.2.0 \
  --data-root ~/Data/depictio-nfcore/scrnaseq/4.2.0/megatest --dry-run
# 8/8 steps passed

# Strict advanced_viz config check: every advanced_viz component in base.yaml
# (main_dashboard + all 7 tabs), constructed as AdvancedVizLiteComponent(use=..., viz_kind=...,
# config=..., workflow_tag=..., data_collection_tag=...) under DEPICTIO_CONTEXT=cli.
# 15/15 components: config resolves to a pydantic BaseModel, not a dict.

uv run ruff format --check depictio/catalog/cellranger/cell_qc.py   # already formatted
uv run ruff check depictio/catalog/cellranger/cell_qc.py            # all checks passed
pre-commit run --files <every file this pass touched>               # all hooks passed
```

## Discrepancies found while wiring the dashboard (`SC-D<n>`, this pass)

- **SC-D6, `use:` mismatch on the simpleaf knee render.** `simpleaf/barcode_rank.yaml`'s
  `knee_plot` render carries `id: simpleaf_barcode_rank_knee` (the full output id, not the
  output-id-minus-tool-prefix short form `barcode_rank_knee` that `cellranger/barcode_rank.yaml`
  uses for the same kind). Not a rule violation, a render id only has to differ from its own
  output's short id, and `simpleaf_barcode_rank_knee` != `barcode_rank`, just an inconsistent
  naming choice between the two catalog dirs. Fixed on the consumer side: the Aligner concordance
  tab's `use:` reads `simpleaf/simpleaf_barcode_rank_knee`. Not edited in B's catalog YAML (small
  binding fix on my side, not a recipe rewrite).
- **SC-D7, boolean columns have no supported interactive filter.**
  `depictio/models/components/constants.py::INTERACTIVE_COMPATIBILITY["bool"] = []` (Checkbox/
  Switch are commented out as "not yet implemented in frontend"). The spec's global-filter list
  asked for a `cellbender_cell` Select filter on `cellranger_cell_qc`; dropped it entirely rather
  than working around a platform gap. See "Could not do" below.
- **SC-D8, boolean columns only take `count`/`sum`/`min`/`max` aggregations, not `average`.**
  4 cards (3 individual MAD criteria on the Cell QC tab, the CellBender-agreement card on Cell
  calling) were designed as `average` + `gauge` (a "% of cells" reading, the same trick A's
  `qc_flagged` Int64 column uses for the *overall* flag). Since the 4 individual MAD criteria and
  `cellbender_cell` stayed Boolean (not Int64), switched these 4 cards to `aggregation: sum` (a
  raw cell count) with the `gauge` secondary layout removed; titles/descriptions adjusted to read
  as counts, not percentages.
- **SC-D9, `cluster_qc_heatmap`'s `median_pct_mito` dropped pre-emptively.** Per the Amendments
  ("drop median_pct_mito if the heatmap rejects an all-zero column") and SC-D-adjacent to the
  no-mito finding above: since `median_pct_mito` is known constant-0 on this reference (every
  cluster), it was dropped from `value_columns` before ever hitting a runtime failure, rather
  than discovered by trial and error.

## Could not do (from the spec)

- **`cellbender_cell` Select filter** (one of the 5 spec'd global cell filters): the platform has
  no interactive component for Boolean columns (`INTERACTIVE_COMPATIBILITY["bool"] == []`, see
  SC-D7). Not a catalog/recipe fix, a `depictio/models/components` change, out of scope for this
  worktree's "no `depictio/models/**`" rule (that rule applies to the template-builder agent
  contract this pass followed throughout). The remaining 4 filters (cluster, QC status, mito %,
  genes detected) are wired and pinned on every tab as specified.
- **"CellBender cells found" card wording as a fraction.** Same Boolean-aggregation gap (SC-D8):
  the "Cell Ranger cells CellBender keeps" card and the 3 individual MAD-criterion cards read as
  raw cell counts rather than the percentages the spec's wording implied. The overall
  `qc_flagged` card (Int64) does still read as a true percentage/gauge.
- **A literal merged Cell-Ranger-vs-simpleaf knee curve.** The spec's "knee curves Cell Ranger +
  simpleaf (knee_plot with sample = aligner)" would need one DC unioning both routes' rank
  tables; no such output exists (out of scope to add, would mean writing a new recipe, which
  this pass's brief reserves for agents A/B). Shipped instead as two half-width `knee_plot` tiles
  side by side, same log-log axes, directly comparable.

## Not done (out of scope for this pass)

- No `depictio-cli run` without `--dry-run` (no server started, no ingestion, per the brief).
- No `.db_seeds/*.json` generated (only `.gitkeep`: needs a real ingested run to export from).
- No dashboard screenshots (`docs/dashboards.md` has no image links yet).
- No git writes, no docker, no `uv sync`/`pnpm`/`npm`/`pip` (per the worktree's hard rules).

---

# 2026-09-22: lot 2 remediation pass

Scope: portability of the scan regexes, the grid/card/table audit findings, the unread
`analysis/` files, and a keystone per-cell expression matrix with a two-group comparison.

## Portability (the finding that mattered most)

12 scan regexes and 2 provenance globs were anchored on `aligner_cellranger/`, a directory that
exists only because the megatest publishes all three `--aligner` routes side by side. An ordinary
run writes one route and its results root IS that directory, so every one of those scans matched
nothing. All 31 `pattern:` / `glob:` lines are now `(?:.*/)?`-anchored or route-agnostic; the
three CellBender scans stay separated by the tool directory in the path (`cellranger/`,
`simpleaf/`, `kallisto/`), which is what actually distinguishes them.

## New data collections

Two raw scans (`cellranger_dispersion_raw`, `cellranger_features_selected_raw`) and six
transformed collections, all authored as catalog outputs under `depictio/catalog/cellranger/`:

| Output | Rows on pbmc8k | Notes |
| --- | --- | --- |
| `cell_expression` | 8 767 x 127 (121 genes) | panel = top-5 markers per graph-based cluster, the curated PBMC panel, top-30 dispersion; CD3D detected in 55.96% of cells, median 1.11 |
| `cell_expression_long` | 70 686 | curated panel only, 150 cells per cluster; `box` is not in `figure_builder._SAMPLABLE_PLOT_TYPES`, so the cap has to live in the recipe |
| `hvg_dispersion` | 22 835 | 20 785 selected / 2 050 not selected; top HVGs PPBP, PF4, IGJ, GNG11, SDPR |
| `cell_cycle` | 8 767 | 43 S genes and 54 G2/M genes present in the reference; G1 5 290 / G2M 1 867 / S 1 610 |
| `cell_funnel` | 1 | 499 387 barcodes, 8 767 called (1.76%), 8 743 CellBender, 8 645 QC pass (98.61%) |
| `diffexp` (widened) | 6 800 | graphclust 1 400 plus kmeans_2..kmeans_10; graphclust labels byte-identical to the cell hub's |

`cell_calls_by_method` and `aligner_summary` moved from `recipes/` into the catalog; only
`samples.py` stays pipeline-local.

## Audit findings, all closed

- 6 grid rows that did not fill the 8-column grid: now 0 partial rows across the 9 tabs
  (audited by summing `layout.w` per (section, y)).
- 11 bare cards: every card now carries a secondary strip. 20 `box_plot` cards with
  `aggregations: [box_plot_stats]` were added, on a hub that previously had none.
- 19 tiles without `use:`: now 2, both on the pipeline-local `samples` collection, which has no
  catalog tool by design.
- 6 over-tall tables for 1-10 rows trimmed (h4-6 to h3-5).
- `sc-cc-fig-hist` histogrammed the geometrically thinned barcode-rank collection, so its bar
  heights were off by roughly 40x. Dropped, replaced by the honest `attrition` waterfall on
  `cell_funnel`.
- The pinned filter section was described as "mito %" while the control is `n_umi`; wording fixed
  in `base.yaml` and `docs/dashboards.md`.
- Dot plot: `max_genes` 100 to 40 and `h` 7 to 12 (14 clusters x 5 markers is 70 rows in an
  h7 tile).
- Embeddings: 4 stacked 8x7 tiles to a 2x2 grid at w4.
- `analysis/pca/*/dispersion.csv` and `features_selected.csv` were fetched and never read; they
  now back the Feature selection section.
- Only the graph-based `differential_expression.csv` was scanned while 9 k-means files sat on
  disk; the scan is widened and a tab-local Clustering resolution Select exposes them.

## Discrepancies (`SC-D<n>` continued)

- **SC-D9** `cellranger/marker_expression` was already taken by the per-cluster (gene x cluster)
  dot-plot table, so the keystone wide matrix is named `cellranger/cell_expression` and its melt
  `cellranger/cell_expression_long`.
- **SC-D10** `group_compare` infers its feature columns from the numeric columns of the bound
  collection, so `umap_1` / `umap_2` are tested alongside the 121 genes. Duplicating an 8 MB
  table to drop two columns is worse than the artefact; the tile's text says to read a hit named
  after an axis as an artefact of the layout. A feature-exclusion list on the kind would fix it.
- **SC-D11** The MultiQC tab carries the two pinned persistent filter sections but no tab-local
  one: the purity test forbids non-MultiQC tiles there, and the MultiQC parquet is filtered by
  sample mapping rather than by column.
- **SC-D12** A `threshold` card with `threshold_value: 0.0` fails the shipped-dashboard gate,
  which tests the value for truthiness rather than for being set. The cell-cycle card uses 0.05.
- **SC-D13** Six bundled cards in `cellbender/`, `kallisto/`, `qcatch/` and `simpleaf/` had no
  secondary strip (pre-existing at HEAD, newly caught by
  `test_every_bundled_card_declares_a_secondary_strip`). Fixed with `secondary_layout: histogram`;
  these four tools are used by this template only.
- **SC-D14** The catalog validator rejects `aggregation: sum` on a Boolean column, so the bundled
  `cellbender_cell` card render is `count` + `composition`. The dashboard-level Boolean sum cards
  are pre-existing and left as they are (polars sums a Boolean fine).

## Commands run

```bash
uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py -q -k scrnaseq
# 10 passed

uv run pytest depictio/tests/models/test_catalog.py -q
# 95 passed, 4 failed: 2 stale *.schema.json (regenerated by the main session, not editable here)
# and 2 from other agents' catalog dirs (cooltools_insulation, gtdbtk_summary).
# Every cellranger / simpleaf / cellbender / qcatch / kallisto failure is fixed.

uv run python -m depictio.cli run --template nf-core/scrnaseq/4.2.0 \
  --data-root ~/Data/depictio-nfcore/scrnaseq/4.2.0/megatest --dry-run
# 8/8 steps passed
```

## Not done

- **No re-ingest and no screenshots.** The API on port 8112 stopped answering
  (`curl /utils/status` times out) after the dry run, and the brief says not to restart anything;
  the lot 2 dev viewer also needs an image rebuild before any advanced_viz tile renders. The
  project `lot2-scrnaseq` (`6aabc8dc19d44b8c1b14191e`) was therefore NOT deleted and NOT
  re-ingested: it still holds the pre-remediation dashboard.
- `.db_seeds/*.json` is still only `.gitkeep`; it needs an ingested run to export from.

## 2026-09-22 review fixes

- `dashboards/base.yaml` main tab: opens with a four-card glance strip in `Run at a glance`
  (`persistent: true, pin: top`): cells called (top-n by sample), median genes per cell (box
  plot), sequencing saturation and reads in cells (gauges), all on `cellranger_metrics` via
  `cellranger/metrics_summary`. The MultiQC intro and general statistics panel moved to a new
  `MultiQC general statistics` section. Tab-local, non-persistent `Glance scope`: a
  `RangeSlider` on `cellranger_metrics.estimated_cells`.
- `Cell calling` tab: `Calling funnel` is now the first grid section and opens with four
  `w: 2, h: 2` cards (waterfall attrition, cells called, called cells passing QC, and a new
  `sc-cc-card-pctcalled` box plot on `pct_called`); the intro text and funnel table follow at
  `y: 2` and `y: 4`. The knee-plot section comes second.
- `sc-cl-av-sankey` description no longer contains `>` ("graphclust, then kmeans_6, then
  kmeans_10").
- `test_shipped_dashboard_yamls.py -k scrnaseq` passes. `.db_seeds` not regenerated here.

## 2026-09-23 wave 2b (header controls, violin, record card, parallel coordinates)

What changed, all in `dashboards/base.yaml` (no template, catalog or recipe change):
- `controls_placement: header` on the analysis tiles: Cell QC UMI-vs-genes scatter, the four
  Embeddings maps + gene UMAP + HVG scatter, the cell-cycle scatter, the Markers dot plot and
  volcano, the Compare UMAP and `group_compare`, the aligner-agreement scatter.
- `show_histogram: true` on every QC threshold `RangeSlider` (UMIs, genes, UMIs per barcode,
  top-20 share, dispersion, cells per cluster, marker expression, methods agreeing). Not on
  `Cells called`: `cellranger_metrics` has one row.
- Markers: `sc-mp-fig-bycluster` is now `visu_type: violin` (`box: true, points: false`);
  the volcano carries `views: [volcano]` and sits at `w: 5` beside a new `record_card`
  (`sc-mk-av-record`, `id_col: gene`, `default_record: FCER1A`, follows the marker-table row
  selection); a text tile opens the Differential expression section.
- Clusters: new `parallel_coordinates` (`sc-cl-av-pcoords`) on `cellranger_cluster_summary`,
  one line per cluster, six axes (`median_pct_mito` left out: constant 0).
- Compare selections: `group_compare` opens on `C1 VPREB3/OSBPL10` vs `C2 FCAR/CLEC4E` with
  `auto_run: true`.

Discrepancies:
- **SC-D15** `record_card` and `parallel_coordinates` tiles carry `viz_kind` + `config` rather
  than `use:`: the `cellranger` catalog outputs have no render for these kinds and the catalog
  was outside this pass's partition. Adding `{id: gene_record, kind: record_card}` to
  `diffexp.yaml` and `{id: cluster_profile, kind: parallel_coordinates}` to
  `cluster_summary.yaml` would restore the `use:` ratio.
- **SC-D16** `cellranger_diffexp.gene_id` holds the gene symbol, not an Ensembl id, so the card
  links to an Ensembl search on the symbol rather than a gene page.
- **SC-D17** The `sc-mp-fig-bycluster` figure keeps `use: cellranger/marker_by_cluster`, whose
  catalog render still says `visu_type: box`; the dashboard's own `visu_type: violin` wins.
- **SC-D18** No locus section: scrnaseq publishes no genomic-coordinate collection.

Commands and results:
```bash
uv run pytest -q depictio/tests/models/test_shipped_dashboard_yamls.py -k scrnaseq   # 10 passed
uv run pytest -q depictio/tests/models/test_catalog.py                              # 99 passed
uv run python -m depictio.cli run --template nf-core/scrnaseq/4.2.0 \
  --data-root ~/Data/depictio-nfcore/scrnaseq/4.2.0/megatest --dry-run              # 8/8 steps
uv run python -m depictio.cli dashboard import <base.yaml with project_tag lot2-scrnaseq> \
  --config ~/.depictio/CLI.feat-nfcore-templates-lot2-112.yaml --api http://localhost:8112 --overwrite
# updated in place, dashboard 6ab3742e84fc1ee30ed7ea05 (tabs ...ea06 to ...ea0d)
```
Data were not re-ingested (no DC changed); every DC of `lot2-scrnaseq` answers
`/deltatables/shape` with rows (diffexp 6 800, cluster_summary 14, cell_expression 8 767 x 127).
Live checks (headless Playwright, 1600x1000, `/tmp/claude-502/shots-scrnaseq/`): the record
card opens on FCER1A (graphclust Cluster 8, rank 1, log2fc 7.72), the comparison opens with a
result (C1 n=1249 vs C2 n=1189, 9 up, 22 down, 90 not significant), the violin and the
parallel coordinates (14 lines, 6 axes) render, header chips are visible without hover.

## Wave 3 (2026-09-23): genericity, blockers, redundancy

What changed:
- **Marker panel.** `MARKER_PANEL` (optional template variable, comma list) replaces the
  hardcoded PBMC panel. `depictio/recipes/lib/scrnaseq_panels.py` now holds
  `parse_marker_panel` / `resolve_marker_panel` and no tissue panel; `cellranger/cell_expression.py`
  puts the reader's panel first, then the top 5 markers per cluster, then the most dispersed genes;
  `cellranger/cell_expression_long.py` keeps `MARKER_PANEL`, else the top 2 markers per cluster
  from `cellranger_diffexp` (new optional `dc_ref`), else the wide table's first gene columns, at
  most 24 genes. It no longer raises on a mouse or non-blood run. Both recipes read the panel
  from a `params` keyword the platform does not pass yet (see Open).
- **CellBender per route.** `simpleaf_cellbender_metrics` and `kallisto_cellbender_metrics` ran
  `cellbender/metrics.py`, whose fixed `dc_ref` is the Cell Ranger route's raw scan, so all three
  routes reported the Cell Ranger CellBender numbers (8 805 cells). Two pipeline-local recipes
  (`recipes/simpleaf_cellbender_metrics.py`, `recipes/kallisto_cellbender_metrics.py`) reuse the
  catalog transform on each route's own scan: 8 805 / 8 821 / 8 765 now.
- **Blockers:** cluster QC heatmap `col_z`; "Significant markers" counts rows with
  `adjusted_pvalue < 0.05` by `cluster_label`; the per-cell violin is faceted by gene; "Cycling
  cells" counts barcodes with `g2m_score >= 0.05`; the found/expected ratio has no one-sided
  threshold (median + box plot); the HVG text and the `Kept for the PCA` filter are fixed/removed;
  glance strip and threshold cards read `_frac` and show the lowest library; the five threshold
  cards lost their passing-side `threshold_warn` (P17).
- **Genericity:** no gene name, sample, tissue or cluster label in any text or default
  (`color_col: CD3D` / `MS4A1`, `default_record: FCER1A`, `default_group_a/_b` removed);
  the Ensembl link is `Multi/Search`; the mito rule has its cards and box plot back
  (`sc-cq-card-mito`, `sc-cq-card-box-mito`, `sc-cq-fig-mito-box`); `forbidden_terms` in
  `megatest.yaml`.
- **Redundancy removed (42 tiles, 182 to 141 with the new mito card):** Library QC 8 cards + 1 intro, MultiQC knee, Cell calling
  4 ambient cards + rank table, Cell QC 2 histograms + top-20 box card, Embeddings 2 UMAPs,
  4 HVG cards, HVG table, selection filter, 2 embedding cards, variance table, Clusters sizes
  bar, parallel coordinates, cell-cycle table, Markers heatmap, faceted barplot, 6 cards, per-cell
  table, and the `Glance scope` slider. `sc-ref-table-metrics` is no longer pinned (collapsed
  at the end of Library QC). New tag: `sc-mk-card-counts` (was `sc-mk-card-resolutions`),
  `sc-cq-card-box-mito` (was `-box-ribo`), `sc-cq-fig-mito-box` (was `-ribo-box`), `sc-cq-card-mito`.
- **Conventions:** cards before figures on every tab, intros at most 2 sentences,
  `advanced_viz_controls: header` on every tab, the gene record in a closing "Gene detail"
  section, Markers resolution filter `default_value: graphclust`.

Verified:
```bash
uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py \
  depictio/tests/models/test_template_conventions.py -q -rxX -k scrnaseq   # 13 passed, 3 xpassed
uv run python -m depictio.cli run --template nf-core/scrnaseq/4.2.0 \
  --data-root ~/Data/depictio-nfcore/scrnaseq/4.2.0/megatest --dry-run      # 8/8 steps
```
The recipe chain (scans, `cell_qc`, `cell_expression`, `cell_expression_long`, `cell_cycle`,
`aligner_summary`) was re-run in process on the local megatest: the long table holds 24 genes
x 2 079 capped cells (49 896 rows) without a panel and exactly the 3 present genes of a
`CD3D, MS4A1;LYZ NOTAGENE` panel; a synthetic mouse-cased wide table falls back to its own
genes instead of raising.

Open:
- `MARKER_PANEL` reaches the recipes only once the platform forwards a transform `params`
  mapping (snippet in the wave 3 report: `TransformConfig.params`, `execute_recipe(params=)`,
  CLI pass-through). Until then the variable is declared and documented, and the recipes use
  the data-derived fallback.
- The UpSet still has no simpleaf own-call set: the megatest fetch has no per-barcode simpleaf
  (QCatch) cell list, only its metrics summary.
- Nothing re-ingested or checked live in this pass; `.db_seeds` not regenerated.
