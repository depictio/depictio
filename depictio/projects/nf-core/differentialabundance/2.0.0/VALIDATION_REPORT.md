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
