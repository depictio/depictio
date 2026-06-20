# nf-core/variantbenchmarking 1.4.0 — Depictio template validation report

Template for [nf-core/variantbenchmarking](https://github.com/nf-core/variantbenchmarking)
**1.4.0**, mirroring the `ampliseq` / `viralrecon` template structure. Benchmarks variant
callers (precision / recall / F1) against truth sets.

## Data source (AWS megatest)

```
s3://nf-core-awsmegatests/variantbenchmarking/results-8b21c01749c4447b285d242a198127736f3ffe51
```

The most recent release-line run (pipeline_info dated 2026-04-22). It is the **only** megatest
covering both categories; earlier runs (`results-55e33f…`, `results-68a3209…`) only contain
`small/`. **No megatest contains `sv/`, `cnv/`, or `multiqc/`.**

| Category | Truth set | Tools | Final tables |
|---|---|---|---|
| `small/` (germline SNP·INDEL) | HG002 / GIAB | hap.py, rtg-tools vcfeval | `small/summary/tables/rtgtools/rtgtools.summary.csv`, `small/<sample>/benchmarks/happy/*.summary.csv` |
| `indel/` (somatic) | SEQC2 | som.py (sompy), rtg-tools vcfeval | `indel/summary/tables/{rtgtools,sompy}/*.csv` |
| `sv/`, `cnv/` | — | Truvari, SVanalyzer, Wittyer | not in the public megatest (optional DCs) |

## Module → final output → plot mapping

| nf-core module / tool | Final output | Format | Depictio plot |
|---|---|---|---|
| `RTGTOOLS_VCFEVAL` | `summary/tables/rtgtools/rtgtools.summary.csv` | CSV | grouped **bar** P/R/F1 (by sample / caller); **table**; **card** |
| `HAPPY_HAPPY` (hap.py) | `small/*/benchmarks/happy/*.summary.csv` | CSV | grouped **bar** by SNP/INDEL × PASS/ALL; **table** |
| hap.py ROC | `*.roc.Locations.SNP.PASS.csv.gz` | gz-CSV | **line** precision-recall sweep |
| `HAPPY_SOMPY` (som.py) | `indel/summary/tables/sompy/sompy.summary.csv` | CSV | **bar** by caller; **table**; **card** |
| som.py regions | `indel/summary/tables/sompy/sompy.regions.csv` | CSV | **heatmap** caller × allele-fraction bin |
| `TRUVARI_BENCH` (SV, optional) | `sv/summary/tables/truvari/truvari.summary.csv` | CSV | **bar** / table |
| `SVANALYZER_SVBENCHMARK` (SV, optional) | `sv/summary/tables/svbenchmark/svbenchmark.summary.csv` | CSV | **bar** / table |
| `WITTYER` (CNV, optional) | `cnv/summary/tables/wittyer/wittyer.summary.csv` | CSV | **heatmap** event type × size bin |

## Recipes (`../recipes/`)

All germline + somatic recipes were **validated offline against the real megatest CSVs**
(`execute_recipe` → schema check passes):

| Recipe | Source | Output schema | Status |
|---|---|---|---|
| `vcfeval_summary.py` | `rtgtools.summary.csv` (small; somatic via `source_overrides`) | label, caller, tp_base, tp_comp, fp, fn, precision, recall, f1 | ✅ validated |
| `happy_summary.py` | glob `small/*/benchmarks/happy/*.summary.csv` (pooled) | variant_type, filter, truth_tp, truth_fn, query_fp, recall, precision, f1 | ✅ validated |
| `happy_roc.py` | glob `small/*/benchmarks/happy/*.roc.Locations.SNP.PASS.csv.gz` | quality, recall, precision, f1 | ✅ validated |
| `sompy_summary.py` | `sompy.summary.csv` | caller, variant_type, tp, fp, fn, recall, precision, f1 (+CIs) | ✅ validated |
| `sompy_regions.py` | `sompy.regions.csv` | caller, af_bin, recall, precision, f1 (+counts) | ✅ validated |
| `truvari_summary.py` | `sv/.../truvari.summary.csv` | label, precision, recall, f1 (+counts) | ⚠️ no megatest data — tolerant matching |
| `svbenchmark_summary.py` | `sv/.../svbenchmark.summary.csv` | label, precision, recall, f1 | ⚠️ no megatest data — tolerant matching |
| `wittyer_summary.py` | `cnv/.../wittyer.summary.csv` | label, event_type, size_bin, precision, recall, f1 | ⚠️ no megatest data — tolerant matching |

> Note: hap.py per-sample summaries lack an internal sample column and the glob loader
> concatenates without a filename column, so `happy_summary.py` **pools** counts by
> `Type × Filter` and recomputes precision/recall/F1 (rtg-tools provides the per-sample view).
> `test3` (giab_beta) ships only rtg-tools output — the happy glob correctly matches test1/test2.

## Dashboard (`dashboards/base.yaml`) — 4 tabs

1. **Overview** — KPI cards (best F1 germline/somatic, sample count) + germline & somatic P/R/F1 bars.
2. **Germline (small variants)** — vcfeval bar + table, hap.py SNP/INDEL bar, hap.py PR-sweep line.
3. **Somatic (indels)** — som.py bar + table + best-F1 card, caller × AF-bin F1 heatmap.
4. **Structural & CNV** — optional Truvari / SVanalyzer / Wittyer panels (empty on the megatest).

## Advanced viz — reused + to develop

**Reused (existing kinds)** for benchmarking: `complex_heatmap` (stratified metrics),
`upset_plot` (common/unique TP·FP·FN across tools), `dot_plot` (precision↔recall scatter).
The current dashboard uses native `figure` bar/heatmap/line; advanced-viz kinds can be swapped in.

**Missing — recommended follow-up issues** (the real gap for benchmarking):

| Proposed viz_kind | Module / file | Role schema | Plot |
|---|---|---|---|
| `roc_curve` / `pr_curve` | hap.py `*.roc.Locations.*.csv.gz`, rtg `*_roc.tsv.gz` | threshold, tp, fp, fn → precision/recall/FPR | per-threshold ROC & PR curves |
| `confusion_matrix` | hap.py / sompy / truvari summaries | tp, fp, fn, unk per type/sample/caller | TP/FP/FN/UNK matrix |
| `metric_radar` | any `*.summary.csv` | tool, metric, value | multi-metric tool-comparison radar |
| bar with CI (extend `da_barplot`) | sompy `*_lower/_upper` | value, lower, upper | P/R bars with error bars (CIs already in sompy) |

## Validation scenarios

| Scenario | Expected DCs |
|---|---|
| germline + somatic (megatest `8b21c0…`) | germline_* + somatic_* (SV/CNV pruned, optional) |
| germline-only (earlier megatests) | germline_vcfeval_summary (+ happy if present); somatic_* pruned |
| SV / CNV run | sv_* / cnv_* populate (recipes need real-data schema pinning) |

## Relay / activation (run on a machine with AWS CLI + the depictio stack)

```bash
DIR=depictio/projects/nf-core/variantbenchmarking/1.4.0
# 1. Download the megatest tables
bash $DIR/download_test_data.sh ./vb-testdata
# 2. Sanity-check each recipe
depictio recipe run nf-core/variantbenchmarking/vcfeval_summary.py -d ./vb-testdata
depictio recipe run nf-core/variantbenchmarking/happy_summary.py   -d ./vb-testdata
depictio recipe run nf-core/variantbenchmarking/sompy_summary.py   -d ./vb-testdata
depictio recipe run nf-core/variantbenchmarking/sompy_regions.py   -d ./vb-testdata
# 3. Validate the template, then ingest (needs the running stack)
depictio run --template nf-core/variantbenchmarking/1.4.0 --data-root ./vb-testdata --dry-run --deep
depictio run --template nf-core/variantbenchmarking/1.4.0 --data-root ./vb-testdata
# 4. Snapshot the dashboards into .db_seeds/
bash $DIR/generate_seeds.sh ./vb-testdata
```

### Wire the seeds into fresh-boot seeding (after `.db_seeds/*.json` exist)

The IDs are already reserved in `db_init_reference_datasets.py`
(`STATIC_IDS["variantbenchmarking"]` + `DATASET_PATHS`). To make the dashboards load on a fresh
deployment, add — mirroring the ampliseq/viralrecon pattern:

1. In `db_init_reference_datasets.py`, add `"variantbenchmarking"` to the `all_datasets` list.
2. In `db_init.py`, add a `"variantbenchmarking"` branch to `_dataset_of_dashboard` (prefix match)
   and append the 4 dashboard entries to `dashboards_config`
   (`dashboard_overview/germline/somatic/sv_cnv.json` under the `.db_seeds/` path).
