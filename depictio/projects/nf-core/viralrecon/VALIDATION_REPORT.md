# nf-core/viralrecon 3.0.0 — Template Ingestion Validation Report

**Date:** 2026-06-15
**Branch:** `chore/amplicon-viralrecon-validation`
**Validator:** local depictio-cli (`depictio/cli/.venv`, v1.0.1) against the local docker stack
(instance `chore-amplicon-viralrecon-validation-100`, API `:8100`, MinIO `:9100`, Mongo `:27100`).

## Goal

Drive `depictio-cli run --template nf-core/viralrecon/3.0.0` against **real** nf-core/viralrecon
pipeline output across scenarios and find every place the template breaks. Companion to the ampliseq
report (`depictio/projects/nf-core/ampliseq/VALIDATION_REPORT.md`).

## Data used

The viralrecon template uses `data_location.structure: "sequencing-runs"` (`runs_regex: "run_.*"`),
so `DATA_ROOT` is the **parent** of the per-run directories.

| Scenario | DATA_ROOT | Notes |
|----------|-----------|-------|
| VR-S1 | `~/Data/depictio-nfcore/viralrecon/3.0.0/` (parent of both runs) | Multi-run aggregation: `run_illumina_amplicon` (complete ivar amplicon) + `run_nanopore` (divergent artic/medaka) |
| VR-S2 | a parent containing only `run_nanopore` | Divergent protocol alone (out-of-scope for this ivar template) |

```bash
depictio-cli run --CLI-config-path ~/.depictio/CLI.<instance>.yaml \
  --template nf-core/viralrecon/3.0.0 \
  --data-root ~/Data/depictio-nfcore/viralrecon/3.0.0 --overwrite --update-config
```

## Starting point — viralrecon is a much cleaner template than ampliseq

No path / format / variable discrepancies were found (contrast with ampliseq D1–D5):
- Only `DATA_ROOT` is required; no `reference.vars`, no required file-path vars, no metadata-column
  coupling.
- mosdepth DCs declare `format: "TSV"` and the files are genuinely tab-separated — they parse
  correctly (the D3 extension-based separator fix from the ampliseq pass also covers them).
- `summary_metrics`, `mosdepth_amplicon_coverage/genome_coverage/amplicon_heatmap`, and the
  `complex_heatmap`/`coverage_track` canonicals all ingest correctly with real row counts.

## VR-S1 result: 7 / 14 data collections processed, 7 skipped-optional, exit 0

**Processed OK (7):** `multiqc_data`, `summary_metrics` (3 samples), `mosdepth_amplicon_coverage`
(294 rows), `mosdepth_genome_coverage` (450 rows), `mosdepth_amplicon_heatmap`,
`complex_heatmap_canonical` (6×101), `coverage_track_canonical` (900 rows).

**Skipped-optional (7):** see VR-D1.

The `run_nanopore` directory was scanned (2/2 runs) but matched none of the ivar/mosdepth/multiqc
globs, so it contributed nothing without error — graceful multi-run handling.

## Discrepancies

### VR-D1 — SARS-CoV-2 lineage/variant DCs hard-fail when their outputs are absent  ✅ FIXED (skip)
- The illumina test run has `skip_pangolin=false`, `skip_nextclade=false`,
  `skip_variants_long_table=false`, yet produced **no** `variants/ivar/variants_long_table.csv`, no
  `*.pangolin.csv`, and no nextclade output — the synthetic test consensus is too poor to yield
  lineage/variant calls (only the pangolin **database** dir exists, no result CSV).
- Before the fix these 7 DCs hard-failed and the run exited 1:
  - base: `variants_long` (`variants/ivar/variants_long_table.csv`), `pangolin_lineages`
    (`*.pangolin.csv`), `nextclade_results` (nextclade `*.csv`)
  - canonical (cascade via `dc_ref`): `oncoplot_canonical`, `upset_canonical`,
    `variant_feature_matrix_canonical` (→ `variants_long`), `sankey_canonical`
    (→ `pangolin_lineages` + `nextclade_results`)
- These are **real** viralrecon outputs that are legitimately absent on poor-quality test data,
  non-SARS-CoV-2 pathogens (HIV/EV produce no pangolin/nextclade), or with `--skip_*` flags — i.e. the
  classic graceful-DC-handling case.
- **Fix applied:** marked all 7 DCs `optional: true` in `template.yaml`. Combined with the CLI
  graceful-skip added in the ampliseq pass (`process.py`), a run lacking these outputs now ingests
  what it has and **skips** the rest. Re-verified VR-S1: 7 processed, 7 skipped, 0 failures, exit 0.
  A complete SARS-CoV-2 run still ingests them normally (the skip only triggers on absent inputs).

### VR-D2 — Divergent nanopore-only run fails loudly (correct, not softened)  — VR-S2
- Pointing `DATA_ROOT` at a parent containing only `run_nanopore` (artic/medaka — no
  multiqc/variants/mosdepth) fails at processing: the **non-optional** core DCs `multiqc_data`,
  `summary_metrics`, `mosdepth_*` have no data → **exit 1** with clear messages.
- This is the **correct** outcome: the template is explicitly "designed for nf-core/viralrecon
  amplicon (ivar) workflow outputs", so a nanopore/artic run is out of scope and should fail loudly
  rather than silently create an empty project. The lineage/variant DCs skip gracefully (VR-D1); the
  core QC DCs remain required. Not softened.

## Generic CLI fixes (from the ampliseq pass) that also benefit viralrecon
- **D9** non-zero exit on DC/step failure — VR-S1 (pre-fix) and VR-S2 both correctly return exit 1
  when DCs fail.
- **D6** optional-DC graceful skip in `cli/utils/process.py` — the mechanism VR-D1 relies on.
- **D8** `plotly` declared as a CLI dependency.
- **D3** extension-based separator detection — covers the mosdepth TSVs.

## Final scenario status (after fix)
- **VR-S1** (multi-run, illumina + nanopore): 7 processed, 7 skipped-optional, 0 failures, **exit 0**.
- **VR-S2** (nanopore-only, out-of-scope): core DCs fail loudly, **exit 1** (correct).

## Changes made for viralrecon
- `template.yaml`: marked 7 data-dependent DCs `optional: true` (VR-D1). No CLI code changes were
  needed — the ampliseq-pass CLI fixes already cover viralrecon.
