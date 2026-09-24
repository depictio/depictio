# nf-core/rnasplice 1.0.4: template validation report

**Date:** 2026-09-24
**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-lot2`
**Scope:** offline checks, dry runs and one live ingest on the lot2 stack (port 8112).

## Data used

`-profile test_full` run on the EMBL cluster (`/scratch/tweber/NF_CORE/rnasplice/1.0.4/run_full`,
Nextflow 24.04.2, MultiQC 1.18), tables-only copy in
`~/Data/depictio-nfcore/rnasplice/1.0.4/test_full` (about 3.6 GB with the Salmon and featureCounts
per-sample tables). Six samples, two conditions, two mirrored contrasts, GRCh37 annotation
(`GENOME=hg19` for the UCSC link), both `star_salmon` and `salmon` routes, all five splicing
tools enabled. No AWS megatest results exist for 1.0.4, so `megatest.yaml` has `results_sha: null`.

MultiQC 1.18 writes no parquet: `multiqc/multiqc_data/multiqc.parquet` was rebuilt with
`depictio.dev_scripts.multiqc_reprocess` from the FastQC zips (raw and trimmed, 24), Trim
Galore reports, STAR logs, samtools stats, featureCounts summaries and Salmon folders:
6 modules, 78 sample rows. The design table is vendored under `input/metadata.tsv`.

## Recipes on the real data

| Recipe | Rows | Note |
| --- | --- | --- |
| recipes/samples | 6 | `_T1` run suffix stripped; design columns merged |
| salmon/sample_pca | 6 | star_salmon route |
| salmon/top_variable_genes | 500 | |
| dexseq/exon_genes | 42,693 | 2 contrasts, one row per gene, top bin by bin padj then abs log2 FC |
| edger/diffsplice_genes | 34,288 | gene F-test FDR plus Simes FDR |
| dexseq/dtu | 63,882 | star_salmon route |
| rmats/events | 324,702 | JCEC, events with 10 or more mean junction reads per replicate in both conditions |
| suppa/local_events | 225,674 | star_salmon route, NaN dPSI dropped |
| recipes/splicing_genes | 57,092 | on one contrast: 7,875 DEXSeq exon, 3,812 DTU, 6,387 edgeR, 921 rMATS, 1,578 SUPPA2 genes called; 246 genes called by all five |

Effect orientation was checked on the mirrored contrasts: after the recipes' sign handling,
every tool gives opposite effects for the two mirrors (treatment minus control throughout).

## Offline checks

- `pytest depictio/tests/models/test_shipped_dashboard_yamls.py depictio/tests/models/test_template_conventions.py -k rnasplice`: 16 passed.
- `pytest depictio/tests/catalog depictio/tests/models/test_catalog.py -p no:randomly`: 123 passed,
  4 failed, all in `test_conformance_project.py` because the conformance project has not been
  regenerated for the new catalog outputs (main-owned).
- `ruff format`, `ruff check` and `pre-commit run --files` on every new file: clean.
- Dry run with `METADATA_FILE` and `GENOME=hg19`: 8/8. Dry run without any variable: 8/8.

## Live ingest (lot2 stack)

`depictio-cli run --template nf-core/rnasplice/1.0.4 --project-name w3-rnasplice-1.0.4-test_full
--var METADATA_FILE=... --var GENOME=hg19`: 8/8 steps, every collection written with the row
counts above, dashboard imported with six tabs (MultiQC 27 components, Sample space 6,
Splicing overview 10, Exon usage 13, Transcript usage 9, Splicing events 17).

The backend was started before the new catalog tools existed: the `use:` tiles resolved by
the server for the new renders (`dexseq/exon_volcano`, `dexseq/dtu_volcano`,
`edger/gene_volcano`, `rmats/event_volcano`, `rmats/event_record`,
`suppa/local_event_volcano`) were stored without a `viz_kind`. The embedding, complex
heatmap, UpSet and inline record cards resolved. A backend restart and a re-import are needed.

## Pending

- Backend restart, re-import, then a live render pass of the six volcanoes and the event record.
- `.db_seeds/*.json` export after the re-import (main-owned).
