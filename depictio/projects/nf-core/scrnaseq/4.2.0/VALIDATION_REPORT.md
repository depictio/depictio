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
