# nf-core/oncoanalyser 3.0.0 template validation report

Validated offline against the AWS megatest `results-7c74c87a43749952b38c9a18915947570f0595a0`
(the 3.0.0 release run, test_full profile: one WGTS subject, a tumor/normal DNA pair plus tumor
RNA, through the full WiGiTS toolkit on GRCh38). The run is 272 GB, almost all BAMs; the
manifest selects 29 tables and VCFs, 33 MB (`bash download_test_data.sh`).

## Checks

| Check | Result |
| --- | --- |
| Every recipe on the megatest via `execute_recipe` on the resolved template (dc_ref order) | pass, 19 transformed collections |
| Column descriptions against the recipe outputs and the scanned CHORD / TEAL tables | every column described, none stale |
| Every dashboard column reference (cards, figures, tables, filters, viz roles, record sections) | all present |
| `test_shipped_dashboard_yamls.py` and `test_template_conventions.py`, `-k oncoanalyser` | 18 passed |
| `depictio/tests -k "nfcore_megatest or template_yaml or templates"` | 237 passed |
| `test_catalog.py` | 97 passed; 2 failures are the stale committed `catalog.schema.json` / `output.schema.json` from the protein-kind registry work, not these entries |
| `depictio-cli run --template nf-core/oncoanalyser/3.0.0 --data-root ... --dry-run` | 8/8 steps |
| `nfcore_megatest.py fetch --dry-run` | 29 files, 32.7 MB |
| `ruff format`, `ruff check`, `pre-commit run --files` on the template and its catalog entries | pass |

## Collection sizes on the megatest

| Collection | Rows |
| --- | --- |
| samples | 3 |
| purple_purity | 1 |
| purple_cnv_segments | 2755 |
| purple_gene_copy_number | 39072 |
| purple_drivers | 410 |
| purple_somatic_variants | 43040 |
| purple_protein_changes | 478 |
| linx_svs | 1421 |
| linx_fusions | 139 |
| linx_fusion_structure | 554 |
| cuppa_predictions | 320 |
| cuppa_classifier_matrix | 40 |
| sigs_allocation | 13 |
| chord_prediction | 1 |
| teal_telomere_length | 2 |
| lilac_alleles | 14 |
| neo_neoepitopes | 566 |
| hmf_bamtools_summary | 2 |
| hmf_bamtools_coverage_profile | 502 |
| hmf_bamtools_fragment_length | 352 |
| qsee_status | 29 |

## Findings

- **Tumor fit.** Purity 1.0 (the test tumor is a cell line), ploidy 2.82 with whole-genome
  duplication, MSS, 14.8 mutations per Mb, PURPLE QC PASS, about half the genome under LOH.
- **Sequencing.** Tumor about 81x and normal about 41x mean coverage, duplicate shares under 4%;
  QSEE passes 28 of 29 checks with one WARN.
- **Drivers.** 410 catalog entries, 35 reported; most unreported entries are LOH and germline
  rows of the full catalog, which is why the Drivers tab leads with the reported count.
- **Small variants.** 43040 PASS calls, 478 protein changes over 458 genes (333 missense, 109
  synonymous, 36 nonsense or frameshift).
- **Structural variants.** 1421 SVs, mostly resolved to deletions and duplications; 126 single
  breakends have no partner and stay out of the chord diagram. 139 candidate fusions, none
  reported, so the fusion structure panel shows the in-frame candidates first.

## Open issues

- **No domain track.** LINX `vis_protein_domain` gives domains in genomic coordinates without a
  CDS offset, so there is no residue-level domain collection for the lollipop or the 3D tile.
- **Virus.** The megatest virus interpretation table is header-only, so no virus collection was
  built or tested; Isofox, PEACH, CIDER and ORANGE are not read yet.
- **GENOME outside hg38.** The copy-number locus view and the genome view gene lane accept
  `hg38` or `mm10` only; a GRCh37 run (`GENOME=hg19`) needs `annotation: none` on those two tiles.
- **Structure lookup.** The 3D tile resolves the picked protein by gene symbol for human (taxon
  9606); it needs network access to AlphaFold DB or ESMFold at render time.
- **Residue linking.** Lollipop to 3D residue highlighting relies on the cross-filter platform
  work that emits `residue_selection` from the lollipop; not verified in a live viewer here.
- **Parameter introspection.** The CLI's generic introspection logs `SKIP_ANCOM` and
  `SAMPLESHEET_FILE` as undeclared variables on this run; harmless, both are ignored.
