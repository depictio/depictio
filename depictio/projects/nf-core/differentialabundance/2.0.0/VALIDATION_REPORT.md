# nf-core/differentialabundance 2.0.0: Depictio template validation report

Template for [nf-core/differentialabundance](https://github.com/nf-core/differentialabundance)
**2.0.0**, mirroring the `ampliseq` / `variantbenchmarking` template structure. Introduces
the pipeline-agnostic `deseq2` catalog tool.

## Data source (AWS megatest)

```
s3://nf-core-awsmegatests/differentialabundance/results-30ed7741fc392127156c2fb10cfa3d69d216b54b
```

The 2.0.0 release run (`results_sha` == the release `tag_sha`). 24 mouse RNA-seq samples
from a featureCounts matrix, two contrasts, no MultiQC. Fetched subset: **11 files,
38.3 MB** (see `megatest.yaml`; `bash download_test_data.sh` reproduces it).

Layout quirk: the run was launched with two parameter sets, so every table sits under
`tables/<kind>/deseq2_rnaseq_gsea,deseq2_rnaseq_gprofiler2/` (comma in the directory
name) instead of `tables/<kind>/` directly. The template is depth-agnostic: recursive
scans match on the file **name** (`os.walk` + `re.match` on the basename) and the recipe
globs use `**`.

Samplesheet and contrasts are not part of the results prefix. `pipeline_info/params.json`
names them as public URLs; `post_fetch_help` in `megatest.yaml` carries the two `curl`
lines that mirror them into `<DATA_ROOT>/input/`, where `SAMPLESHEET_FILE` auto-resolves.
A copy of both is committed under `2.0.0/input/`.

## Data collections (8)

| Tag | Source | Rows x cols ingested | Notes |
|---|---|---|---|
| `samples` | recipe `nf-core/differentialabundance/samples.py` | 24 x 14 | hub; sheet normalised to `sample_id` / `group` / `size_factor` |
| `deseq2_results_raw` | recursive scan `*.deseq2.results.tsv` | 62,634 x 9 | plumbing, see below |
| `deseq2_results_annotated_raw` | recursive scan `*_deseq2.annotated.tsv` | 62,634 x 33 | plumbing, optional (needs `--gtf`) |
| `deseq2_results` | recipe `deseq2/results_long.py` | 62,634 x 11 | volcano / MA / QQ / DA-barplot |
| `deseq2_results_annotated` | recipe `deseq2/results_annotated.py` | 55,486 x 15 | manhattan / lollipop / volcano; optional |
| `deseq2_vst_pca` | recipe `deseq2/vst_pca.py` | 24 x 16 | embedding |
| `deseq2_vst_heatmap` | recipe `deseq2/vst_top_variable.py` | 500 x 26 | complex heatmap |
| `deseq2_sample_distance` | recipe `deseq2/vst_sample_distance.py` | 24 x 26 | complex heatmap |

### Why the two `_raw` collections exist

The contrast id lives **only in the file name**
(`Condition_genotype_WT_KO_study.deseq2.results.tsv`), never in a column. The recipe glob
loader (`depictio/recipes/__init__.py::_resolve_glob_source`) reads each matched file with
`pl.read_csv` and concatenates them **without a per-file label**, and `pl.read_csv` has no
`include_file_paths` parameter (only `scan_csv` does). A data-collection scan does use
`pl.scan_csv`, so the path can be carried in as a column there.

So the per-contrast files are scanned into a raw collection with
`polars_kwargs: {include_file_paths: source_path, infer_schema_length: 0}`, and the tidy
collection reads it through `dc_ref`. `infer_schema_length: 0` is load-bearing: DESeq2
writes `NA` in numeric columns and `chromosome` mixes `1..19` with `MT`/`X`/`Y`, so
per-file type inference disagrees between contrasts and the concatenation fails
(`could not parse 'MT' as dtype i64`). Every column arrives as text and the recipes recast.

`dc_ref` collections are resolved from the referenced collection's Delta table, so the raw
collections are declared **before** the tidy ones and ingestion must stay sequential
(`DEPICTIO_INGEST_DC_WORKERS` unset, the default).

## Catalog tool `deseq2` (new)

`nf_core_url: modules/nf-core/deseq2/differential` (present in
`_index/nf_core_modules.txt`). Five outputs, all pipeline-agnostic: no differentialabundance
path appears in a recipe:

| Output | Recipe | Renders |
|---|---|---|
| `deseq2_results` | `results_long.py` | volcano, ma, qq, da_barplot, 4 cards, histogram figure, selectable table |
| `deseq2_results_annotated` | `results_annotated.py` | manhattan, annotated_volcano, annotated_da_barplot, chromosome_lollipop, 3 cards, bar figure, selectable table |
| `deseq2_vst_pca` | `vst_pca.py` | embedding, 2 cards, table |
| `deseq2_vst_heatmap` | `vst_top_variable.py` | complex_heatmap |
| `deseq2_sample_distance` | `vst_sample_distance.py` | complex_heatmap |

`results_long.py` is written for reuse by nf-core/chipseq, whose
`consensus/<antibody>/deseq2/<contrast>/*.deseq2.results.txt` differ in three ways it
tolerates: `.txt` instead of `.tsv` (a collection declaring `format: TSV` still gets a tab
separator for `.txt`, see `read_single_file_lazy`), CRLF/CR line endings (string columns
are stripped of stray `\r`), and older column naming (`baseMean`/`base_mean`,
`log2FoldChange`/`log2fc`/`lfc`, `pvalue`/`p_value`, `padj`/`fdr`/`qvalue`, matched
case-insensitively, plus an unnamed R row-name column as the feature id). The contrast is
derived from the file name and falls back to the parent directory name, which is what the
chipseq layout needs. `find.path_glob_alt` covers that nested layout.

## MultiQC overlap decisions

The pipeline runs no MultiQC at all, so there is nothing to defer to: every panel here is a
dedicated catalog render. No `multiqc/<module>.yaml` was created and no
`multiqc_stubs.py` builder is needed.

## Validation

| Check | Result |
|---|---|
| `depictio dev recipe run` on the three vst recipes + `samples.py` | 4 checkpoints pass each |
| `results_long.py` / `results_annotated.py` | not runnable standalone (`dc_ref`); validated through a scan-path simulation and the real ingest |
| catalog checks on the `deseq2` entry | 5 outputs, 25 renders, every role bound to an `EXPECTED_SCHEMA` column present in the fixture; `nf_core_url` module in `_index/nf_core_modules.txt` |
| `test_shipped_dashboard_yamls.py` assertions on `base.yaml` | 6/6 pass (tabs, `use:` expansion, card strips, section lists, icons and colours, text tile heights) |
| CLI dry run | 8/8 steps |
| CLI real ingest (project `Differential Abundance Analysis`) | 8/8 steps, 8/8 collections populated, 0 skipped, 0 failed |
| API smoke | all 10 `use:` renders resolve with every bound column present in the collection; the one code-mode figure returns a plotly Figure with 2 traces; the UI-mode figure binds; all 4 links overlap (24/24 samples, 27,743/31,317 genes), no FILTER MISMATCH |
| Dashboard import (step 8 of the same run) | 4 tabs, 58/58 components stored, nothing dropped by `_filter_unresolved_components`; all 10 advanced_viz tiles kept their catalog bindings |

Ingested contrast counts match the recipe output exactly: 31,317 features per contrast,
520 significant in WT/KO, 0 in Control/Treated. Those two numbers also match the
pipeline's own `*.deseq2.results_filtered.tsv` on disk (520 data rows and 0 data rows),
so the recipe's `significant` call reproduces the pipeline's thresholds.

This run kept the name the template declares (`Differential Abundance Analysis`), which is
what a later standalone import needs. `depictio-cli run` itself is not bound to that name:
step 8 resolves the project it has just created by its own name and hands the id to
`import_dashboards_from_template`, so `--project-name` is safe there. The standalone
`depictio dashboard import` is the bound path: `validate_schema_online` in
`depictio/cli/cli/commands/dashboard.py` looks the project up by the dashboard's
`project_tag`, and `--project` does not override that lookup, so re-importing an edited
dashboard into a renamed project fails with `Cannot resolve project ...: HTTP 404`.

## Known limits

* Only the DESeq2 route is bound (`--differential_method deseq2`). `_introspect_pipeline_params`
  sets no flag for the differential method, so there is no conditional to prune the
  collections on a limma / propd / dream run; such a run simply has no matching files and
  every collection fails rather than being pruned.
* `deseq2_results_annotated{,_raw}` are `optional: true`: a run given no `--gtf` writes no
  annotated table, and the Expression and Genome view tabs then have no data.
* `_col_annotations_json` (the sample-sheet annotation strips the two heatmap recipes
  compute) is read by the `visu_type: heatmap` figure path only. The `advanced_viz`
  complex_heatmap worker takes its `col_annotations` from the component config, so on these
  tiles the column is currently inert. That is harmless (it is a string column, excluded from the
  value matrix) but not yet drawn.
* No `.db_seeds`, no `STATIC_IDS`, no `db_init` registration: deferred for the whole lot.
* The seven screenshots under `docs/screenshots/` were captured from the live stack
  after this report was first written; `docs/dashboards.md` references all of them.

---

## 2026-09-22: lot 1 remediation pass

### What changed

| Area | Change |
|---|---|
| `recipes/samples.py` | Publishes `factor_2`, `factor_3`, `factor_4` and their source names, so a shipped filter can bind to a sheet factor without knowing its name |
| `template.yaml` | New collections `deseq2_vst_distribution`, `gsea_report_raw`, `gsea_report`; new `NO_GSEA` variable and conditional |
| `template.yaml` | Five new links: the sample hub and the PCA now reach the variance-stabilised heatmap and the distributions, and the contrast reaches the GSEA report |
| `megatest.yaml` | GSEA report key added, and the sibling-prefix fetch the tables actually came from is documented |
| `dashboards/base.yaml` | Three more persistent factor filters; the per-sample distribution panel; a fifth tab, Enrichment |
| `depictio/catalog/gsea/` | New module and the `report` output |
| `depictio/catalog/deseq2/` | New `vst_distribution` output |

### Verification

```bash
uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py -q -k differentialabundance
# 10 passed
```

Recipes run directly against `~/Data/depictio-nfcore/differentialabundance/2.0.0/megatest`:

| Recipe | In | Out |
|---|---|---|
| `recipes/samples.py` | 24-row sheet, 12 columns | 24 rows, 20 columns; `factor_2/3/4` resolve to the sheet's treatment (2 levels), time (2) and batch (3) |
| `deseq2/vst_distribution.py` | 31317 features by 24 samples | 1440 rows (24 samples by 60 bins); density sums to 1.0 per sample; 30.2 percent of features at the matrix floor |
| `gsea/report.py` | 4 report tables, 100 rows | 100 rows, 13 columns, across 2 contrasts by 2 poles (16 / 34 / 24 / 26) |

### Decisions

#### DA-C4: the factors are aliased, not named

Binding the new filters to `Condition_treatment`, `Condition_time` and `batch` would have
worked on this run and broken on the next: the pipeline's `--input` sheet is free-form, and
the only thing a template can rely on is that some columns are factor-like. The recipe
already aliased the leading one as `group`; this pass extends the same ranking to the next
three. A column with more than six levels is skipped rather than aliased, because a control
listing two dozen values is a control nobody uses, and the source name travels with the
alias so a panel can tell the reader which sheet column it is filtering.

#### DA-C5: a distribution panel, not a second correlation matrix

The exploratory set shinyngs draws includes both a sample-distance view and per-sample
distributions. The distance view was already here (`deseq2_sample_distance`, Euclidean over
the most variable features), so the gap was the distribution, which answers a different
question: not which libraries differ, but whether a library is shaped like the others.
A second, correlation-based matrix would have restated the first one in another metric and
is deliberately not added.

#### DA-C6: the GSEA pole is a column, because the file name is the only place it lives

GSEA writes one report per pole and encodes the contrast and the pole in the file name
only. Binding the four tables as four collections would have made the dashboard's shape
depend on how many contrasts a run has. The raw scan carries the path in, and the recipe
turns both into ordinary columns, so one collection covers any number of contrasts and the
panels split on them.

### Discrepancies

#### DA-D3: the pinned megatest prefix publishes no enrichment tables at all

The prefix's parameter-set directory is named `deseq2_rnaseq_gsea,deseq2_rnaseq_gprofiler2`,
which reads like both enrichment steps ran. They did not: that string is only the two
parameter-set NAMES the run was launched with, and the prefix contains no `tables/gsea/`
and no `tables/gprofiler2/`. The GSEA reports the Enrichment tab is built on were fetched
from a sibling prefix of the same pipeline that did run the step
(`47e3d923bbf2311ace0b9dea12d756287798275e`), and `megatest.yaml` records both the key and
the exact fetch command.

#### DA-D4: no prefix publishes gprofiler2 tables, so there is no gprofiler2 collection

Every published prefix of this pipeline was checked. The one that does run gprofiler2
(`3dd360fe`) crashed with only `pipeline_info/` written, and no other prefix carries
`tables/gprofiler2/`. A gprofiler2 catalog tool would therefore ship with a fixture and no
way to validate it against a real run, so it is not built. The `enrichment` kind the GSEA
dot plot uses is the same one a gprofiler2 output would render through, so adding it later
is a recipe, not a kind.

#### DA-D5: no `gsea_running_score` tile, because the per-set data is not published

The `gsea_running_score` kind needs a per-set ranked series (gene set, rank, running
enrichment score). The pipeline publishes only the report tables, one row per set; the
running scores exist only inside the GSEA HTML output. The NES bars stand in for that view.

#### DA-D6: the vst heatmap link is nominal, like every other wide matrix here

`deseq2_vst_heatmap` is features by samples, so the sample names are its COLUMN names and
not values in any column. `target_field: sample_id` names a column the matrix does not
have, which is deliberate: an absent column makes the row filter be skipped, leaving
`_narrow_wide_matrix_columns` to mirror the selection onto the column set. Pointing it at
a real column of the matrix (`gene_id`) would apply the row filter instead, comparing
sample names against gene identifiers, and empty the panel.

## 2026-09-22 review fixes

Second pinned persistent scope `Contrast scope` on `deseq2_results.contrast`, reaching the
four analysis tabs: the annotated table through a new
`deseq2_results.contrast -> deseq2_results_annotated.contrast` link (the existing pair on
`gene_id` carries selections, not contrasts) and the GSEA report through the existing link.
The four tab-local contrast multi-selects were removed so no tab shows two contrast
controls; each tab keeps its own local controls (direction, biotype, chromosome, pole,
thresholds). The contrast-vs-contrast description now says which two contrasts it pairs
(the first two by id) instead of the run's count.

## 2026-09-23: wave 2b (switchable DE views, diagnostics, gene record)

What changed:

- Differential expression: the `deseq2/volcano` and `deseq2/ma` tiles are one volcano tile
  with `views: [volcano, ma]`, `avg_log_intensity_col: log2_base_mean` and the view switch in
  the header. The QQ tile is the same render opened on `view: qq` (`views: [qq]`); the
  retired `deseq2/qq` and `deseq2/ma` renders are no longer used. New raw p-value histogram
  (`figure` histogram on `pvalue`, one facet per contrast). New `record_card` under the
  annotated table (`default_record` Uchl1, `ENSMUSG00000029223`, one card per contrast,
  Ensembl link template `https://www.ensembl.org/id/{value}`), driven by the table's row
  selection and by the contrast-against-contrast figure.
- Samples: PCA `controls_placement: header`. Genome view: the annotated volcano offers
  `views: [volcano]` with header controls. Enrichment: the GSEA dot plot spells
  `view: enrichment`, `views: [enrichment]`, header controls.
- `show_histogram: true` on all eight RangeSliders. GSEA running score stays unbound
  (incubating).

Commands and results:

- Shipped-YAML tests: 30 passed (shared run with rnaseq). Dry run and full `run` on
  `megatest/`: 8/8 steps; `deseq2_results` 62,634 rows, `deseq2_results_annotated` 55,486,
  `gsea_report` 100, `samples` 24, `deseq2_sample_distance` 24 x 26.

Discrepancies:

- DA-D1: `gsea/gsea_dotplot` is still declared `kind: enrichment` in the catalog, so the tile
  resolves through the alias table even though the dashboard spells the view. Flipping the
  catalog render to `kind: dot_plot` + `view: enrichment` belongs to the gsea catalog owner.
  Likewise `deseq2/ma` and `deseq2/qq` still exist as alias renders, now unused here.
- DA-D2: no parallel-coordinates QC profile: the pipeline runs no MultiQC, and the samples
  sheet has one numeric column (size factor).

## 2026-09-23: Wave 3 (bulk RNA family rework)

What changed:

- The DE tile is one `deseq2/volcano` with `views: [volcano, ma, qq]` and
  `p_value_col: pvalue`. The separate QQ tile and the Genome view annotated volcano are
  deleted.
- `da-de-card-signal` is a median with a Tukey box plot; `da-de-card-tested` is gone
  (features tested moved to the pinned `Run at a glance`); new `da-de-card-padj` (min
  adjusted p-value, 0.05 threshold, warning at 0.1).
- Enrichment NES card reads the new `gsea/report` column `abs_nes` and is titled
  "Strongest NES (absolute)"; the leading-edge card is a median with a box plot.
- `samples.py` always emits `factor_2..4` and their `_name` columns: missing factors are
  null with the name `none`, so one-factor sheets ingest against the same schema.
- The Expression tab is folded: the VST heatmap moved to a new `Top variable features`
  section on Samples, the biotype views and filter moved to Differential expression.
- Pinned, persistent `Run at a glance` (samples, contrasts, features tested, size factor)
  and `Sample sheet` (renamed from `Observation sheet`, collapsed). Filter sections renamed
  to `Sample scope`, `Library scope`, `Call scope`; the other scopes are open by default.
- Prose made generic (no gene named, no default record); `forbidden_terms` added to
  `megatest.yaml`.

Verified (offline): template lint clean except a warn-only `no_mean_of_percentages` hint on
the leading-edge card (it is a median of a percentage); shipped YAML and template
convention tests pass; `samples.py` checked on the full sheet and on a one-factor sheet;
`gsea/report` recipe tests pass; CLI dry run on the megatest 8/8.

Still open:

- No default contrast is set, so the DE volcano pools both contrasts until one is picked in
  `Contrast scope`.
- Volcano labels still read `gene_id`, not `gene_name` (S1 not done).
- Live render not checked in this wave; screenshots are stale.
- Conformance fixtures and `.db_seeds` need regenerating (main session).
