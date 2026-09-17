# nf-core/mag 5.4.2: template ingestion validation report

**Date:** 2026-09-17
**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-lot2` (`feat/nfcore-templates-lot2`)
**Validator:** recipe transforms run directly against the local `DATA_ROOT`
(`uv run python`), `pytest` against `depictio/tests/models/test_shipped_dashboard_yamls.py`
and `test_catalog.py`, `depictio-cli run --dry-run`. No server, no ingestion (per brief).

## Goal

Build the mag 5.4.2 template from a megatest run already fetched locally
(`~/Data/depictio-nfcore/mag/5.4.2/megatest/`). The existing `megatest.yaml` (written before
anyone had looked at the real S3 layout) guessed a rich set of directories, `Taxonomy/`,
`QC_shortreads/`, `QC_longreads/`, `Assembly/`, a bin-quality/bin-summary/depths family under
`GenomeBinning/`: that turned out not to match what the run actually publishes.

## Data used

```bash
python scripts/nfcore_megatest.py fetch --pipeline mag --version 5.4.2 \
  --dest ~/Data/depictio-nfcore/mag/5.4.2/megatest
# or:
bash depictio/projects/nf-core/mag/5.4.2/download_test_data.sh
```

Local `DATA_ROOT` as found (21 files, ~355 MB, never listed against S3, inspected only with
`find`/`head`/`wc -l` per policy):

```
input/samplesheet.full.v4.csv                                          683 B
pipeline_info/params.json                                             41.5 KB
pipeline_info/software_versions.yml                                    2.4 KB
multiqc/multiqc_data/multiqc.parquet                                    9.5 MB
multiqc/multiqc_data/multiqc_data.json                                 16.1 MB
GenomeBinning/contig_to_bin/contig_to_bin_map.tsv                      25.9 MB (344,633 rows)
GenomeBinning/COMEBin/stats/<assembler>-COMEBin-<sample>/embeddings.tsv     (7 files, 9.5-38 MB each)
GenomeBinning/COMEBin/stats/<assembler>-COMEBin-<sample>/covembeddings.tsv (7 files, 9.5-37 MB each)
```

Three samples (CAPES_S7, CAPES_S11, CAPES_S21), each hybrid short+long read, co-assembled
with FLYE, MEGAHIT, METAMDBG and SPAdes, binned with COMEBin, MaxBin2, MetaBAT2, MetaBinner
and SemiBin2 (5 binners x up to 4 assemblers x 3 samples = up to 60 assembly/binner
combinations; 53 actually produced bins, 1283 bins total).

## `megatest.yaml`: corrected keys

The original manifest (see the file's own revision-history comment for the itemised diff)
assumed directories the run does not publish and a `params_*.json` glob that could never have
matched the real `params.json` (no underscore-separated suffix). Corrected:

| Key removed | Why |
|---|---|
| `Taxonomy/*.{tsv,txt,csv,summary}` | 0 objects under this path, no GTDB-Tk/Kraken2/Centrifuge/CAT output published for this run |
| `QC_shortreads/*.{zip,json,log,txt}` | 0 objects, no standalone FastQC/fastp report files |
| `QC_longreads/*.{txt,log}` | 0 objects, no standalone Porechop_ABI/Filtlong report files |
| `Assembly/*report.{tsv,txt}`, `Assembly/*/QUAST/*` | 0 objects locally. **Not independently confirmed against S3** (policy: never list it), may genuinely not be produced, or may need a fresh fetch. Flagged below as an open question rather than asserted. |

| Key kept, note added | Why |
|---|---|
| `pipeline_info/params_*.json` -> `pipeline_info/params*.json` | The real file is `params.json`, no underscore suffix; the old glob never matched it |
| `GenomeBinning/*.{tsv,txt,csv,summary,json}` | Correct as written, `fnmatch`'s `*` crosses `/`, so it already matches nested files. Confirmed it mirrors everything actually published: `contig_to_bin_map.tsv` + COMEBin's raw embeddings. No per-binner depth table, no `bin_summary.tsv`, no BUSCO/CheckM/GUNC file exists anywhere under `GenomeBinning/` for this run |
| `Annotation/*.{txt,tsv}` | Kept, real on S3 (**917 files**, per the task brief), but **not present in the local `DATA_ROOT`** this template was built and tested against. No Annotation-based catalog output could therefore be authored or validated. See "Open questions" below |

## What the local data actually supports

1. **`GenomeBinning/contig_to_bin/contig_to_bin_map.tsv`** (344,633 rows: `assembly_id`,
   `contig_id`, `binner`, `bin_id`), the only binning table the run publishes. No
   completeness/contamination, no depth, no per-binner summary file sits beside it. Built as
   `mag_contig_to_bin_raw` (raw scan) -> `bin_summary.py` (one row per bin, contig count) ->
   `binner_comparison.py` (one row per sample/assembler/binner, bin count and
   contigs-per-bin spread). Both recipes were run directly against the real file:
   `bin_summary`: 1283 rows; `binner_comparison`: 53 rows. Schemas match `EXPECTED_SCHEMA`
   exactly (`pl.len()` cast to `Int64`).
2. **`GenomeBinning/COMEBin/stats/<assembler>-COMEBin-<sample>/{embeddings,covembeddings}.tsv`**
, COMEBin's own raw per-contig neural embeddings (128 dimensions, one row per contig,
   ~7,900 rows/file x 7 files). **Not used.** See "Discrepancies" below for why.
3. **`multiqc/multiqc_data/multiqc.parquet`** (MultiQC 1.31, 18,381 rows), carries
   `general_stats_table` rows for `bowtie2`, `checkm2`, `fastp`, `fastqc`, `porechop`,
   `prokka` and `quast`, i.e. exactly the QC/assembly-QC/bin-QC/annotation signal the brief
   asked to favour, just not as standalone files. `quast` additionally has its own
   `quast_table`/`quast_table-1` table plots (73 and 7,699 rows, assembly-level and
   per-bin, respectively) and `checkm2` has its own `checkm2-first-table` (13 rows). Their
   exact MultiQC plot titles could not be confirmed, every `pconfig`/`config` cell for
   those anchors is `null` in this trimmed parquet, so the dashboard binds only the
   universal `general_stats` plot (title `"General Statistics"`, the one title that is safe
   to assume across every MultiQC module) rather than guess at per-module titles that might
   silently render empty.
4. **`input/samplesheet.full.v4.csv`**: 3 rows, already sample-level. `samples.py` just
   renames `sample` -> `sample_id` and derives `has_long_reads`.

## Discrepancies (`MG-D<n>`)

- **MG-D1**: Brief's suggested favourites (bin QC via BUSCO/CheckM/GUNC, GTDB-Tk
  classification, depth tables, standalone QUAST assembly QC) do not exist anywhere in the
  local `DATA_ROOT`. Confirmed with `find DATA_ROOT -type f` (21 files total, enumerated
  above) before writing any YAML.
- **MG-D2**: Taxonomy is entirely absent (no `Taxonomy/` directory, 0 files), so it cannot
  be bound to `stacked_taxonomy`/`sunburst` as the brief suggested if present. No taxonomy
  tab was built.
- **MG-D3**: COMEBin's raw embeddings (`GenomeBinning/COMEBin/stats/*/embeddings.tsv`,
  `covembeddings.tsv`) are real, sizeable (9.5-38 MB/file) per-**contig** data, not
  per-sample. The `embedding` kind's canonical usage across the catalog (`taxpasta/embedding`,
  `ampcombi/embedding`, `deeptools/sample_pca`, ...) is one point per **sample**-run
  (tens of points); binding thousands of raw per-contig points per partition would misuse
  the kind's intended scale and (since the 128 dimensions are COMEBin's own learned latent
  space, not directly interpretable) would add a plot whose axes mean nothing to a reader
  without also computing something derived (e.g. bin centroids + a shared PCA across
  partitions). That derived-centroid design was considered but not built: it is a genuine,
  non-trivial recipe (join per-contig embeddings to bin membership, aggregate to per-bin
  centroids, run one global `dimreduction.run_pca`: the helper and `umap-learn` dependency
  already exist in `depictio/recipes/lib/dimreduction.py`) that deserved a scoped follow-up
  rather than a rushed addition. Left as an open question below.
- **MG-D4**: `Annotation/` (Prokka) is real on S3 (917 files, per the task brief) but is
  not in the local `DATA_ROOT`. No Annotation-based catalog output exists; Prokka's summary
  numbers only reach the dashboard through MultiQC's general-stats columns
  (`Coding_Density`, `Total_Coding_Sequences`, `CDS`, `Genome_Size`, `Average_Gene_Length`).
- **MG-D5**: `Assembly/*report.tsv`/`QUAST/*` matched 0 local files, same as Taxonomy, but
, unlike Taxonomy/QC_shortreads, this was not something the task brief explicitly
  confirmed absent on S3. Removed from `megatest.yaml` on the same evidence (0 local
  objects) but flagged here as lower-confidence: it may need a fresh, larger fetch rather
  than being genuinely unpublished.
- **MG-D6**: Original `megatest.yaml`'s `pipeline_info/params_*.json` key could never have
  matched the real `pipeline_info/params.json` (no underscore). Fixed to `params*.json`.

## Catalog / recipes

No shared `depictio/catalog/<tool>/` module was created: the contig-to-bin map is
mag-internal glue (an aggregation across five binners' outputs), not a standalone tool with
its own identity/homepage, so `bin_summary.py`/`binner_comparison.py`/`samples.py` are
pipeline-local recipes under `depictio/projects/nf-core/mag/recipes/` (same idiom as
`cutandrun/recipes/caller_agreement.py`), no catalog `use:` on their dashboard tiles, by
design (matches the `caller_agreement` precedent).

Three MultiQC catalog panels were added (modules with no existing
`depictio/catalog/multiqc/<module>.yaml`, copying `preseq.yaml`'s shape exactly): `checkm2`,
`porechop`, `prokka`. `bowtie2`, `fastp`, `fastqc` and `quast` already existed and needed no
changes.

`use:` coverage: 1/12 dashboard tiles that render data carry a `use:` (the MultiQC
general-stats panel, `multiqc/general_stats`). The brief's ~90% target assumes a catalog-rich
pipeline; this run's local data does not support that, the binning tables are pipeline-local
by design (see above) and the MultiQC panels beyond general-stats were not bound (MG-D3-
adjacent: unconfirmed plot titles).

## Validation run

```bash
uv run python <inline> # bin_summary.py, binner_comparison.py, samples.py transforms
                        # run directly against the real files, see below
uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py -x -q
uv run pytest depictio/tests/models/test_catalog.py -x -q
depictio/cli/.venv/bin/depictio-cli run --template nf-core/mag/5.4.2 \
  --data-root ~/Data/depictio-nfcore/mag/5.4.2/megatest --dry-run
uv run ruff format <files> && uv run ruff check <files>
pre-commit run --files <files>
```

Recipe transforms, run directly against the real local files:

- `samples.py`: 3 rows, schema matches `EXPECTED_SCHEMA` exactly.
- `bin_summary.py`: 1283 rows, schema matches.
- `binner_comparison.py`: 53 rows, schema matches.

(See the "Validate" section results and any failures in the agent's final report to the
orchestrating session, this file is written before the pytest/dry-run passes are re-checked
by the caller, since this worktree also has five other pipelines' work landing concurrently.)

## Open questions

1. Should `Annotation/` (Prokka, 917 files) be fetched into the local `DATA_ROOT` so a real
   per-bin annotation table/catalog output can be built and tested, rather than leaving Prokka
   as general-stats-only?
2. Is `Assembly/*report.tsv` genuinely unpublished for this run (like Taxonomy/QC_shortreads),
   or does it need a fresh/larger fetch? Not confirmed either way (MG-D5).
3. Is a COMEBin bin-centroid embedding (derived: per-bin mean of the 128-dim contig vectors,
   one global PCA via `depictio/recipes/lib/dimreduction.run_pca`, bound to the `embedding`
   kind with `cluster`/`color` = binner) worth a follow-up? It would be the first genuinely
   novel use of the local COMEBin data beyond bin/contig counts, but it is a new analytical
   choice beyond what any existing catalog tool does, so it deserves its own review rather
   than landing inside this template's first pass.
