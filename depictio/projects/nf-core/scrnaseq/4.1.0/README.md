# nf-core/scrnaseq — Depictio scaffold (v4.1.0)

**Tier 2 — needs 1 new advanced-viz component (`knee_qc`).**

## Megatest

- Bucket: `s3://nf-core-awsmegatests/scrnaseq/`
- Docs: <https://nf-co.re/scrnaseq/4.1.0/docs/output>

## Dashboard inventory

| Tab | Component | `viz_kind` | Status |
|-----|-----------|-----------|--------|
| MultiQC | MultiQC tiles | (built-in) | ✓ |
| Cell QC | Barcode-rank knee + QC scatter | `knee_qc` | **PROPOSED** |
| Embedding | UMAP | `embedding` | ✓ |
| Marker Genes | Cluster × gene dot plot | `dot_plot` | ✓ |

See `depictio/models/components/advanced_viz/PROPOSED_COMPONENTS.md` for the `knee_qc`
config spec.

## Local handoff checklist

- [ ] Implement `knee_qc` viz_kind backend + renderer (see PROPOSED_COMPONENTS.md).
- [ ] Implement recipes — all 3 require anndata/scanpy.
- [ ] Register IDs in `STATIC_IDS` + `DATASET_PATHS`.
- [ ] Reseed + verify.
