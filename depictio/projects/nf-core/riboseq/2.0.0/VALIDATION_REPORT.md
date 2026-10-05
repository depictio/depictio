# nf-core/riboseq 2.0.0: template validation report

**Date:** 2026-09-23
**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-lot2`
**Scope:** offline only (no ingestion, no live render). Live checks are pending.

## Data used

AWS megatest `s3://nf-core-awsmegatests/riboseq/results-11d66a3b8ae1f41f9c385af36bd431c35bf015ab/`,
fetched with `scripts/nfcore_megatest.py fetch --pipeline riboseq --version 2.0.0
--max-file-mb 200`: 206 files, about 104 MB (tables only). The samplesheet, contrasts and a
derived `metadata.tsv` are vendored under `input/`.

## Recipes on the real data

| Recipe | Rows | Note |
| --- | --- | --- |
| ribowaltz/library_summary | 6 | Ribo-seq libraries only; median frame 0 share in CDS about 55 %, median CDS share about 73 %, modal length 27 nt |
| ribowaltz/frames | 54 | 6 libraries, 3 regions, 3 frames |
| ribowaltz/psite_region | 18 | |
| ribowaltz/length_distribution | 89 | |
| ribowaltz/metaprofile_start, metaprofile_stop | 396 each | |
| anota2seq/results | 33,040 | 4 analyses x 8,260 genes, 1 contrast |
| anota2seq/regulation | 8,260 | 740 translation, 32 mRNA abundance, 7,488 not regulated, 0 buffering |
| recipes/translational_efficiency | 15,927 | |
| ribotish/orfs | 26,963 | |
| ribocode/orfs | 27,278 | |
| recipes/orf_calls | 64 | |
| recipes/orf_overlap | 11,258 | 8,855 Ribo-TISH, 8,445 RiboCode, 6,042 shared |
| recipes/samplesheet | 12 | |

The `chrom:strand:stop` key was checked against RiboCode's `ORF_gstop` on the real calls:
plus strand matches the Ribo-TISH GenomePos end, minus strand matches start + 1.

## Offline checks

- `pytest depictio/tests/models/test_shipped_dashboard_yamls.py -k riboseq`: pass.
- `pytest depictio/tests/models/test_template_conventions.py -k riboseq`: pass (two
  warn-only notes on medians of per-library percentages, intended).
- `pytest depictio/tests/recipes/test_riboseq_*.py`: pass.
- Catalog dirs `ribowaltz`, `anota2seq`, `ribotish`, `ribocode` and the MultiQC yamls
  `sortmerna`, `ribowaltz`, `ribotish`: validated (fixtures match schemas, no missing files).
- `resolve_template`: 18 DCs and 35 links with `METADATA_FILE`, 17 DCs and 23 links without.
- `depictio-cli run --template nf-core/riboseq/2.0.0 --data-root <dest>
  --var METADATA_FILE=<dest>/input/metadata.tsv --dry-run`: 8/8 checks pass.

## Pending (live)

- Ingestion against a running stack, dashboard render, advanced-viz kinds on real rows.
- `.db_seeds/*.json` export after the first live import.
