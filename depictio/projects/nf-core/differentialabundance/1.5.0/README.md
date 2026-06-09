# nf-core/differentialabundance — Depictio scaffold (v1.5.0)

**Tier 1 — zero-gap pipeline.** All 5 viz tiles use Depictio's existing
advanced-viz components.

## Megatest

- Bucket: `s3://nf-core-awsmegatests/differentialabundance/`
  ([listing](https://nf-core-awsmegatests.s3.eu-west-1.amazonaws.com/?prefix=differentialabundance/))
- Docs: <https://nf-co.re/differentialabundance/1.5.0/docs/output>

## Dashboard inventory

| Tab | Component | Existing `viz_kind` | DC |
|-----|-----------|----------------------|----|
| MultiQC | MultiQC tiles | (built-in) | `multiqc_data` |
| Differential Expression | Volcano | `volcano` | `volcano_canonical` |
| Differential Expression | MA plot | `ma` | `ma_canonical` |
| Expression Heatmap | Clustered heatmap | `complex_heatmap` | `vst_matrix_canonical` |
| Pathway Enrichment | Enrichment dot plot | `enrichment` | `enrichment_canonical` |
| Sample Embedding | PCA scatter | `embedding` | `embedding_pca` |

## Assumed output tree (verify against megatest)

```
<DATA_ROOT>/
├── multiqc/multiqc_data/multiqc.parquet
├── samplesheet/samplesheet.csv
├── samplesheet/contrasts.csv
├── tables/differential/<contrast>.tsv      → volcano / MA recipes
├── tables/processed_abundance/vst.tsv      → vst_matrix recipe
├── tables/gsea/<contrast>/<src>.tsv        → enrichment recipe
└── plots/exploratory/pca.csv               → embedding recipe
```

## Local handoff checklist

- [ ] Download a megatest subset:
      `aws s3 sync s3://nf-core-awsmegatests/differentialabundance/results-<sha>/ ./data/`
- [ ] Implement each recipe in `recipes/*.py` against the real columns.
- [ ] Register IDs:
      add `differentialabundance` block to
      `depictio/api/v1/db_init_reference_datasets.py::STATIC_IDS` and to
      `ReferenceDatasetRegistry.DATASET_PATHS`.
- [ ] Replace `TODO_WF_ID` / `TODO_DC_ID` placeholders in
      `dashboards/base.yaml` (complex_heatmap config) with the static IDs.
- [ ] Run:
      `docker compose -f docker-compose.dev.yaml exec depictio-backend \
        python -m depictio.dev_scripts.reseed_project differentialabundance`
- [ ] Verify in the app — open the dashboard, check every tile renders.
- [ ] Extend `depictio/tests/api/v1/test_reference_seed_dashboards.py` (auto-covered
      once the project lands in `STATIC_IDS` + `DATASET_PATHS`).
