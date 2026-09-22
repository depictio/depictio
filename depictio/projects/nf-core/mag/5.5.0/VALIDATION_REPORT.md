# nf-core/mag 5.5.0: template ingestion validation report

Date: 2026-09-22. Supersedes the 5.4.2 report entirely.

The 5.4.2 report described a template built on
`s3://nf-core-awsmegatests/mag/results-5dabb0159ac0104885e09f301db22126e8fcb394/`.
That prefix is a **truncated S3 sync**, not a thin pipeline run: 7554 keys, 987
non-zero objects, and a smallest non-zero object of 8.4 MB. Every object under
roughly 8 MB is missing or zero-byte, which is precisely the set of report
tables a dashboard reads. Its three findings MG-D1, MG-D2 and MG-D5, which
concluded that mag publishes no taxonomy, no assembly QC and no bin quality,
were conclusions about the sync and not about the pipeline. They are withdrawn.

## Data used

Prefix `results-171cf36971499cea4c9bccac4536cccbfc540e14`, 15 494 objects. It
is the 5.5.0 release candidate: `nextflow.config` at that commit carries
`manifest.version = '5.5.0'`, and the commit predates the 5.5.0 tag by four
days. It is the only complete mag megatest in the bucket. The tagged 5.5.0 run
(`56abab5b`) crashed after read QC and holds 52 objects; `8ac0a2cf` is 5.6.0dev.

```bash
bash depictio/projects/nf-core/mag/5.5.0/download_test_data.sh
python -m depictio.dev_scripts.multiqc_reprocess --src <DATA_ROOT> --dest <DATA_ROOT>
```

673 files, 65 MB. Three samples (CAPES_S7, CAPES_S11, CAPES_S21), short and
long reads, four assemblers (MEGAHIT, SPAdes, FLYE, METAMDBG) and five binners
(MetaBAT2, MaxBin2, CONCOCT, COMEBin, and the DAS Tool refinement).

## What the run publishes, and what it does not

Published and used: QUAST assembly and per-bin reports, CheckM2 quality
reports, GTDB-Tk classify summaries, jgi contig depth tables, Prokka per-bin
feature summaries and GFFs, fastp JSON, Bowtie2 logs, NanoStats, and a real
`pipeline_info/` with `params_2026-07-28_08-20-27.json`,
`nf_core_mag_software_mqc_versions.yml` and an execution trace.

Not published, and therefore not in the template:

| Missing | Consequence |
| --- | --- |
| `multiqc/` (the whole directory) | The report is re-generated locally with MultiQC 1.35 from the run's own raw inputs. Eight modules parse. |
| `GenomeBinning/bin_summary.tsv` | Rebuilt Depictio-side by `depictio/catalog/mag/bin_summary.py` as a four-way outer join. |
| `GenomeBinning/depths/bins/` | No per-bin depth table, so no bin-by-sample depth heatmap. |
| `busco_summary.tsv`, `GUNC/`, `BIgMAG/` | 5.5.0 publishes CheckM2 only; the other bin-QC tools did not run. |
| `GenomeBinning/contig_to_bin/contig_to_bin_map.tsv` | Exists only under `5dabb015` (1283 bins) and `8ac0a2cf`. Joining it onto this run's 479 bins would be wrong, so it is dropped. |

Prokka's GFF is not a substitute for the contig-to-bin map: Prokka renames
every contig to an internal `gnl|<centre>|<hash>_N`, so its coordinates join to
nothing outside the bin they came from.

## Discrepancies

- **MG-D6. The unit is the bin, not the sample.** Three samples produce 479
  bins, 74 055 contigs and 222 165 contig-by-sample coverage rows. A sample
  filter is the least selective control on the dashboard; assembler, binner,
  phylum and the quality thresholds are what actually narrow it.
- **MG-D7. The four bin tools see different bins.** QUAST measured 479,
  CheckM2 scored 427, Prokka annotated 449 and GTDB-Tk placed 150. The joined
  `bin_summary` therefore carries a `sources_present` column (1 to 4) rather
  than dropping rows: 10 bins are known to one tool, 54 to two, 274 to three
  and 141 to all four.
- **MG-D8. GTDB-Tk leaves `msa_percent` empty.** This run classified through
  ANI screening rather than pplacer, so `msa_percent` is null for every bin.
  The catalog card over it was moved to `closest_af`.
- **MG-D9. No read-level table.** fastp publishes JSON and NanoPlot publishes
  a free-text `NanoStats.txt`; neither is a format a table data collection can
  read. Read QC therefore exists only as MultiQC panels on the landing tab,
  and the dashboard has no Reads tab.
- **MG-D10. Prokka GFFs are 1.1 GB.** Each of the 449 files carries the bin's
  whole FASTA after `##FASTA`. Only METAMDBG's 44 GFFs are fetched, 54 MB,
  which bounds the whole fetch at 65 MB and still gives a real locus map.

## Data collections and row counts

All counts are from the fetched megatest, verified recipe by recipe.

| Data collection | Kind | Rows |
| --- | --- | --- |
| `samples` | transformed (samplesheet) | 3 |
| `multiqc_data` | MultiQC | 1 report, 8 modules |
| `quast_assembly_raw` | scan | 10 files |
| `assembly_report` | transformed | 10 |
| `length_ladder` | transformed | 60 |
| `mag_contig_depths_raw` | scan | 10 files |
| `contig_depths` | transformed | 222 165 |
| `checkm2_quality_raw` | scan | 24 files |
| `checkm2_quality_report` | transformed | 427 |
| `quast_bins_raw` | scan | 24 files |
| `quast_bins_summary` | transformed | 479 |
| `gtdbtk_summary_raw` | scan | 26 files |
| `gtdbtk_summary` | transformed | 150 |
| `gtdbtk_rank_composition` | transformed | 421 |
| `prokka_summary_raw` | scan | 449 files |
| `prokka_summary` | transformed | 449 |
| `prokka_gff_raw` | scan | 44 files |
| `prokka_gene_track` | transformed | 47 878 |
| `bin_summary` | transformed (`dc_ref` x4) | 479 |

`bin_summary` MIMAG tiers: 9 high-quality drafts, 154 medium, 248 low, 16
contaminated, 52 unknown. GTDB-Tk phyla: Bacillota 67, Bacteroidota 44,
Pseudomonadota 20, Actinomycetota 17, Bacillota_I 1, one unplaced.

## Catalog modules authored

Five new tool directories, ten outputs, all pipeline-agnostic (any workflow
running these tools recognises them):

- `depictio/catalog/checkm2/`: `quality_report`
- `depictio/catalog/quast/`: `assembly_report`, `length_ladder`, `bins_summary`
- `depictio/catalog/gtdbtk/`: `summary`, `rank_composition`
- `depictio/catalog/prokka/`: `summary`, `gene_track`
- `depictio/catalog/mag/`: `bin_summary`, `contig_depths`
- `depictio/catalog/multiqc/gtdbtk.yaml`: the MultiQC GTDB-Tk panel

Shared helpers: `depictio/recipes/lib/mag_bins.py` (bin identity parsing and
the MIMAG tier rule) and `depictio/recipes/lib/quast_report.py` (QUAST column
folding, which differs between QUAST versions and between assembly and bin
reports).

## Validation run

```bash
uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py   # 873 passed
uv run pytest depictio/tests/models/test_catalog.py                    # mag entries pass
uv run python -m depictio.cli dev catalog validate                     # no mag findings
uv run python -m depictio.cli run --template nf-core/mag/5.5.0 \
  --data-root ~/Data/depictio-nfcore/mag/5.5.0/megatest --dry-run      # 8/8 steps
```

## Open questions

1. The 5.4.2 prefix should be re-synced upstream; its report tables exist, the
   sync dropped them. Worth an nf-core issue.
2. The tagged 5.5.0 megatest crashed and was never re-run, which is why this
   template pins a release candidate rather than a tag sha.
3. Whether a future mag release publishes `bin_summary.tsv` and
   `GenomeBinning/depths/bins/` again. If it does, the catalog recipe already
   recognises the former by its own glob and a bin-by-sample depth heatmap
   becomes possible.

## 2026-09-22 review fixes

- `dashboards/base.yaml`: tab-local, non-persistent `Glance scope` section on the main tab, a
  `MultiSelect` on `bin_summary.mimag_tier` (the DC behind the pinned bin strip), so the
  MultiQC tab has its own control beside the two pinned scopes.
- No new pinned samplesheet factor: `group` is `0` on all three rows of
  `input/samplesheet.full.v4.csv`, so a filter on it would be dead on the reference run. It
  stays in the hub table.
- `test_shipped_dashboard_yamls.py -k mag` passes.
