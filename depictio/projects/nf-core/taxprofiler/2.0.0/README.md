# nf-core/taxprofiler — Depictio scaffold (v2.0.0 "Crazy Corgi")

**Tier 1 — zero-gap pipeline.** All viz tiles use Depictio's existing
advanced-viz components.

## Megatest

- Bucket: `s3://nf-core-awsmegatests/taxprofiler/`
  ([listing](https://nf-core-awsmegatests.s3.eu-west-1.amazonaws.com/?prefix=taxprofiler/))
- Docs: <https://nf-co.re/taxprofiler/2.0.0/docs/output>

## Dashboard inventory

| Tab | Component | `viz_kind` | DC |
|-----|-----------|-----------|----|
| MultiQC | MultiQC tiles | (built-in) | `multiqc_data` |
| Composition | Stacked taxonomy | `stacked_taxonomy` | `stacked_taxonomy_canonical` |
| Composition | Sunburst | `sunburst` | `sunburst_canonical` |
| Diversity | Rarefaction | `rarefaction` | `rarefaction_canonical` |
| Diversity | PCoA embedding | `embedding` | `embedding_pcoa` |
| Cross-Profiler Overlap | UpSet | `upset_plot` | `upset_canonical` |

## Assumed output tree (verify against megatest)

```
<DATA_ROOT>/
├── multiqc/multiqc_data/multiqc.parquet
├── samplesheet/samplesheet.csv
├── taxpasta/<tool>_<db>.standardised.tsv   → stacked_taxonomy / sunburst / embedding
├── classification/kraken2/<sample>.kraken2.report  → sunburst
└── classification/<tool>/<sample>...        → upset (cross-tool presence)
```

## Local handoff checklist

- [ ] Download megatest subset (small — `test` profile is single-digit GB).
- [ ] Implement recipes (mostly Polars + simple per-tool merges; PCoA needs scipy/scikit-bio).
- [ ] Register IDs in `STATIC_IDS` + `DATASET_PATHS`.
- [ ] Replace `TODO_WF_ID` / `TODO_DC_ID` placeholders in the UpSet config.
- [ ] Reseed: `python -m depictio.dev_scripts.reseed_project taxprofiler`.
- [ ] Verify in the app.
