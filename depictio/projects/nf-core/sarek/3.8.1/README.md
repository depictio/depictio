# nf-core/sarek — Depictio scaffold (v3.8.1 "Laitaure")

**Tier 1 — zero-gap pipeline.** All viz tiles use Depictio's existing
advanced-viz components.

## Megatest

- Bucket: `s3://nf-core-awsmegatests/sarek/`
  ([listing](https://nf-core-awsmegatests.s3.eu-west-1.amazonaws.com/?prefix=sarek/))
- Docs: <https://nf-co.re/sarek/3.8.1/docs/output>

## Dashboard inventory

| Tab | Component | `viz_kind` | DC |
|-----|-----------|-----------|----|
| MultiQC | MultiQC tiles | (built-in) | `multiqc_data` |
| Variant Manhattan | Manhattan + QQ | `manhattan`, `qq` | `variants_manhattan_canonical`, `qq_canonical` |
| Coverage Track | Mosdepth coverage | `coverage_track` | `coverage_canonical` |
| Variant Lollipop | Per-gene aa lollipop | `lollipop` | `lollipop_canonical` |
| Oncoplot | Sample × gene mutations | `oncoplot` | `oncoplot_canonical` |

## Assumed output tree (verify against megatest)

```
<DATA_ROOT>/
├── multiqc/multiqc_data/multiqc.parquet
├── samplesheet/samplesheet.csv
├── variant_calling/<caller>/<sample>/<sample>.vcf.gz   → manhattan / qq / oncoplot / lollipop
├── preprocessing/mosdepth/<sample>/<sample>.regions.bed.gz  → coverage
└── annotation/snpeff|vep/<sample>/<sample>.ann.vcf.gz  → lollipop / oncoplot
```

## Local handoff checklist

- [ ] Download a megatest subset (e.g. `test_full` or `test_targeted`).
- [ ] Implement recipes — they all need a VCF reader; `cyvcf2` is the lightest.
- [ ] Decide on the somatic vs germline scope for the oncoplot (or carry both as a tab).
- [ ] Register IDs in `STATIC_IDS` + `DATASET_PATHS`.
- [ ] Reseed: `python -m depictio.dev_scripts.reseed_project sarek`.
- [ ] Verify in the app.
- [ ] Extend `test_reference_seed_dashboards.py` (auto-covered on registration).
