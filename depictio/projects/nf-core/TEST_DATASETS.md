# nf-core test profiles and their datasets, per Depictio template

Every shipped template was built against exactly one dataset: the AWS megatest run its
`megatest.yaml` pins. This table answers the other question - **which other datasets
could exercise the same template**, using the `test*` profiles nf-core already ships.

Scope: the 12 pipelines under `depictio/projects/nf-core/`, each at the release the
template targets - 126 profiles over 123 rows (a few cloud aliases such as rnaseq's
`test_full` / `test_full_aws` share a row).

Survey date **2026-09-11**. Sources: `nf-co.re/pipelines.json` (latest releases, tag
shas), `raw.githubusercontent.com/nf-core/<pipeline>/<tag>/` (`nextflow.config`,
`conf/test*.config`, `docs/output.md`, `modules/nf-core/multiqc/environment.yml`),
the samplesheets themselves (row counts are recounted, not copied), and the local
`megatest.yaml` / `template.yaml` files.

Related: `MEGATEST_STATUS.md` (what each S3 bucket holds), `VALIDATION_SCENARIOS.md`
(analytical scenarios per pipeline), `TEMPLATE_BOTTLENECKS.md` (platform gaps).

## Verdicts

The verdict column says what the **1.10.0 Nextflow auto-trigger** would produce from
that run (`-c $(depictio-cli config nextflow)`, no manual `--var`):

| | |
|---|---|
| ✅ | every required data collection present - dashboard as designed |
| ⚠️ | only `optional: true` collections missing - dashboard with empty tiles, no error |
| ❌ | a required collection is absent - project created and scanned, **no dashboard**, exit 1 |
| 🚫 | the template never resolves, or its MultiQC predates the parquet |

Verdicts are **derived** from the template's conditionals and the profile's parameters.
None has been confirmed by an actual run; treat them as the prediction to test, not as
a result.

## Blocker codes

| code | meaning |
|---|---|
| `VER` | the latest nf-core release has no template directory → `-r <version>` is mandatory, or the trigger exits 1 |
| `MQC` | the run's MultiQC is below the parquet floor: 1.29 and 1.30 write `BETA-multiqc.parquet`, which no scan regex matches; 1.28 and older write no parquet at all. The CLI never reprocesses |
| `SHEET` | the pipeline does not publish its samplesheet into `outdir` → the samplesheet collection has no source |
| `RUNS` | template is `structure: sequencing-runs` → a plain `--outdir` holds no `run_*` directory |
| `SKIP` | the profile cuts a branch of the pipeline and the matching `SKIP_*` variable is not auto-detected |
| `SCOPE` | the profile takes a route the template does not bind at all |
| `S3` | reads or genome on `s3://ngi-igenomes` / `s3://nf-core-awsmegatests` |
| `DB` | large database download at runtime |
| `NET` | live third-party fetch (IMGT, NCBI, Ensembl FTP, figshare, ut.ee) |
| `DSL1` | DSL1 pipeline → needs `NXF_VER=22.10.8` or older |
| `KO` | profile broken upstream (missing config, missing input, CI-runner paths) |

---

## 1. Per pipeline

| pipeline | template version(s) | latest nf-core | `-r` needed | reference megatest | MultiQC written | `test*` profiles | structure | DCs (optional) |
|---|---|---|---|---|---|---|---|---|
| airrflow | 5.1.0 | 5.1.1 | **yes** | `e69d49e3` | 1.34 | 24 | flat | 12 (1) |
| ampliseq | 2.14.0 · 2.16.0 · 2.18.0 | 2.18.0 | no ¹ | `2723d4c2` | 1.34 | 17 | flat | 24 (13) |
| atacseq | 1.2.2 | 2.1.2 | **yes** | `f327c863` | **1.9** | 2 | flat | 19 (0) |
| chipseq | 1.2.0 | 2.1.0 | **yes** | `048fd685` | **1.9** | 2 | flat | 15 (0) |
| cutandrun | 3.1 | 3.2.2 | **yes** | `42502fb4` | **1.14** | 10 | flat | 14 (3) |
| differentialabundance | 2.0.0 | 2.0.0 | no | `30ed7741` | none by design | 13 | flat | 8 (2) |
| funcscan | 4.0.0 | 4.0.0 | no | `aee3dc96` | 1.34 (empty parquet) | 15 | flat | 15 (14) |
| rnafusion | 4.1.3 | 4.1.3 | no | `76ad76e7` | 1.33 | 3 | flat | 11 (1) |
| rnaseq | 3.26.0 | 3.26.0 | no | `e7ca4627` | 1.33 | 7 | flat | 6 (0) |
| taxprofiler | 2.0.1 | 2.0.1 | no | `70ecc15e` | 1.34 | 9 | flat | 12 (7) |
| variantbenchmarking | 1.4.0 (+ 3 categories) | 1.5.0 | **yes** | `8b21c017` ² | 1.32, absent from the megatest | 16 | flat | 9 (8) |
| viralrecon | 3.0.0 | 3.0.0 | no | partial prefix ³ | 1.31 | 8 | **sequencing-runs** | 14 (12) |

¹ ampliseq is at the latest release, but 2.15.0, 2.16.1 and 2.17.0 are nf-core releases
with no template directory - running one of those exits 1.
² the 1.4.0 template deliberately pins the **1.5.0** run; 1.4.0's own run (`68a32098`)
is a 7-file truncated sync.
³ no `megatest.yaml`; `download_test_data.sh` runs the pipeline locally instead.

"no `-r` needed" is true **today only**. The trigger forwards
`manifest.name/manifest.version` verbatim and `locate_template()` has no fallback, so
the next nf-core release of any of those pipelines turns the column to "yes" until a
template directory for it is added.

---

## 2. Per profile

### airrflow 5.1.0 - 24 profiles
Samplesheet published as `pipeline_info/samplesheet.valid.tsv` ✅. `--input` *is* the
AIRR metadata sheet, so grouping columns are always present. Nextflow floor `!>=26.04.1`.
The five `SKIP_*`/`ASSEMBLED_MODE` variables are **not** auto-detected and the trigger
cannot pass `--var`, so every profile that changes route is `SKIP`.

| profile | dataset | n | grouping columns | reference | class | codes | verdict |
|---|---|---|---|---|---|---|---|
| `test` | `testdata-bcr/Metadata_small_test_airr.tsv` | 6 | subject_id, intervention, collection_time_point_relative, cell_subset, tissue, sex, age | imgtdb/igblast zips | CI | - | ✅ |
| `test_nocluster` | same | 6 | same | same | CI | `SKIP` | ❌ |
| `test_maskprimers_extract` | same | 6 | same | same | CI | - | ✅ |
| `test_maskprimers_align` | same | 6 | same | same | CI | - | ✅ |
| `test_raw_immcantation_devel` | same | 6 | same | `immcantation/suite:devel` | CI | mutable tag | ✅ |
| `test_tcr` | `testdata-tcr/TCR_metadata_airr.tsv` | 2 | subject_id, tissue, sex, age | zips | CI | - | ✅ |
| `test_no_umi` | `testdata-no-umi/Metadata_test-no-umi_airr.tsv` | 1 | subject_id, tissue, sex, age | zips | CI | `SKIP` | ⚠️ |
| `test_assembled_hs` | `testdata-reveal/test_assembled_metadata_hs.tsv` | 2 | subject_id, tissue, sex, age | zips | CI | `SKIP` | ❌ |
| `test_assembled_mm` | `testdata-reveal/test_assembled_metadata_mm.tsv` | 1 | same | zips | CI | `SKIP` | ❌ |
| `test_assembled_immcantation_devel_hs` | `..._metadata_hs.tsv` | 2 | same | `:devel` | CI | `SKIP` | ❌ |
| `test_assembled_immcantation_devel_mm` | `..._metadata_mm.tsv` | 1 | same | `:devel` | CI | `SKIP` | ❌ |
| `test_fetchimgt` | `..._metadata_hs.tsv` | 2 | same | live IMGT | CI | `SKIP` `NET` | ❌ |
| `test_fetch_airrc_imgt` | `..._metadata_hs.tsv` | 2 | same | live AIRR-C/IMGT | CI | `SKIP` `NET` | ❌ |
| `test_reassign_false` | `testdata-reveal/test_assembled_metadata_assigned.tsv` | 2 | same | zips | CI | `SKIP` | ❌ |
| `test_embeddings_H` | `testdata-reveal/test_assembled_metadata_tiny.tsv` | 1 | same | protein-LM weights | CI | `SKIP` `DB` | ❌ |
| `test_embeddings_HL` | same | 1 | same | protein-LM weights | CI | `SKIP` `DB` | ❌ |
| `test_10x_sc` | `testdata-sc/10x_sc_raw.tsv` | 1 | subject_id, tissue, sex, age | cellranger VDJ GRCh38 | CI | `SKIP` | ⚠️ |
| `test_takara_smartseq_umi_bcr` | `testdata-clontech/samplesheet.tsv` | 1 | subject_id, tissue, sex, age | zips | CI | - | ✅ |
| `test_nebnext_umi` | `testdata-neb/samplesheet.tsv` | 1 | same | zips | CI | - | ✅ |
| `test_genotyping` | `testdata-genotyping/test_genotyping_metadata.tsv` | 3 | subject_id, tissue, sex, age | zips | CI | `SKIP` | ❌ |
| `test_genotyping_small` | `..._metadata_small.tsv` | 1 | same | zips | CI | `SKIP` | ❌ |
| `test_rnaseq_bulk` | `testdata-rnaseq/rnaseq_metadata.tsv` | 1 | subject_id, tissue, sex, age | none (TRUST4) | CI | `SKIP` | ❌ |
| `test_rnaseq_sc` | `testdata-rnaseq/sc_rnaseq_metadata.tsv` | 1 | same | none (TRUST4) | CI | `SKIP` | ❌ |
| `test_full` | `testdata-bcr/metadata_pcr_umi_airr_300.tsv` | 10 | **subject_id, treatment, tissue, population, sex, age** | zips, primers on S3 | full (16 cpu / 60 GB / 24 h) | `S3` | ✅ |

### ampliseq 2.18.0 - 17 profiles
The only template whose pipeline publishes `input/` (samplesheet + metadata + fasta), so
`SAMPLESHEET_FILE` and `METADATA_FILE` auto-resolve on a live run. `IS_NANOPORE`,
`SKIP_QIIME`, `SKIP_TAXONOMY`, `SKIP_ALPHA_RAREFACTION`, `SKIP_ANCOM` and
`IS_MULTIREGION` are read from `pipeline_info/params.json`. Grouping lives in the
separate `--metadata` file; without it, 6 collections are pruned cleanly (`if_var_absent`).
`GROUP_COL` is interpolated into the ANCOM-BC paths, so it must match a real column.

| profile | dataset (`--input`) | n | `--metadata` | grouping columns | reference | class | codes | verdict |
|---|---|---|---|---|---|---|---|---|
| `test` | `samplesheets/Samplesheet_standardized.tsv` | 4 | `Metadata.tsv` (4) | **treatment1**, mix8, num6, num7 | GTDB R07-RS207 + greengenes85 | CI | `DB` | ✅ |
| `test_single` | `samplesheets/Samplesheet.tsv` | 4 | - | - | dada ref tax | CI | - | ⚠️ |
| `test_multi` | `samplesheets/Samplesheet_multi.tsv` | 4 | - | `run` (batch, in the sheet) | dada ref tax | CI | - | ⚠️ |
| `test_doubleprimers` | `Samplesheet_double_primer.tsv` | 2 | - | - | dada ref tax | CI | - | ⚠️ |
| `test_pacbio_its` | `Samplesheet_pacbio_ITS.tsv` | 3 | `Metadata_pacbio_ITS.tsv` (3) | var1, var2, var3 | UNITE fungi | CI | `DB` | ✅ |
| `test_iontorrent` | `Samplesheet_it_SE_ITS.tsv` | 3 | - | - | sintax ref on ut.ee | CI | `NET` | ⚠️ |
| `test_fasta` | `testdata/ASV_seqs.fasta` (347 seqs) | n/a | - | - | dada ref tax | CI | `SKIP` | ❌ |
| `test_failed` | `Samplesheet_failed_sample.tsv` | 5 | `Metadata_failed_sample.tsv` (5) | treatment1 | dada ref tax | CI | broken on purpose | ❌ |
| `test_reftaxcustom` | `Samplesheet.tsv` | 4 | - | - | Zenodo RDP + Greengenes13.5 | CI | `NET` | ⚠️ |
| `test_qiimecustom` | `Samplesheet.tsv` | 4 | - | - | custom QIIME ref | CI | - | ⚠️ |
| `test_novaseq` | `Samplesheet_novaseq.tsv` | 2 | - | - | dada ref tax | CI | - | ⚠️ |
| `test_pplace` | `Samplesheet.tsv` | 4 | `Metadata.tsv` (4) | treatment1, mix8 | pplace refs | CI | - | ✅ |
| `test_pplace_sheet` | `Samplesheet.tsv` | 4 | - (`pplace_sheet`, 5 rows) | - | figshare | CI | `NET` | ⚠️ |
| `test_sintax` | `Samplesheet_pacbio_ITS.tsv` | 3 | `Metadata_pacbio_ITS.tsv` (3) | var2, var3 | UNITE (sintax) | CI | `DB` | ✅ |
| `test_vsearch_lca` | `Samplesheet_pacbio_ITS.tsv` | 3 | `Metadata_pacbio_ITS.tsv` (3) | var1–var3 | UNITE | CI | `DB` | ✅ |
| `test_multiregion` | `samplesheet_multiregion.tsv` | 3 | `metadata_multiregion.tsv` (3) | treatment, name | SIDLE ref + regions sheet (5) | CI | - | ✅ |
| `test_full` | `Samplesheet_full.tsv` | 12 | `Metadata_full.tsv` (12) | **habitat, Riv_vs_Gro, Sed_vs_Soil** | sbdi-gtdb | full | `S3` `DB` | ✅ |

`test_full` is the closest public relative of the megatest the template was authored on
(same 12 samples, same `habitat` grouping) and the only profile that turns on
`ancombc`/`ancombc2`/`picrust`.

### atacseq 1.2.2 - 2 profiles · 🚫 all
DSL1, MultiQC 1.9, and 19 collections with **none** optional.

| profile | dataset | n | grouping columns | reference | class | codes | verdict |
|---|---|---|---|---|---|---|---|
| `test` | `test-datasets/atacseq/design.csv` | 4 | group (`OSMOTIC_STRESS_T0/T15`), replicate | explicit fasta + gtf | CI | `MQC` `DSL1` `VER` | 🚫 |
| `test_full` | `test-datasets/atacseq/design_full.csv` | 6 | group (`GM12878_STD/OMNI/FAST`), replicate | iGenomes hg19 | full | `MQC` `DSL1` `VER` `S3` | 🚫 |

### chipseq 1.2.0 - 2 profiles · 🚫 all
DSL1, MultiQC 1.9, 15 collections with none optional. Richest ChIP design of the set,
wasted on a template that cannot read the run.

| profile | dataset | n | grouping columns | reference | class | codes | verdict |
|---|---|---|---|---|---|---|---|
| `test` | `test-datasets/chipseq/design.csv` | 6 | group (`SPT5_T0/T15/INPUT`), replicate, **antibody**, **control** | explicit fasta + gtf (borrowed from atacseq test data) | CI | `MQC` `DSL1` `VER` | 🚫 |
| `test_full` | `test-datasets/chipseq/design_full.csv` | 16 | group (`FOXA1_IP_VEH/E2`, `EZH2_IP_NTKO/TKO`, 4 INPUT), replicate, antibody, control | iGenomes hg19 | full | `MQC` `DSL1` `VER` `S3` | 🚫 |

### cutandrun 3.1 - 10 profiles · 🚫 all
MultiQC 1.14 with `reprocess: true` and `multiqc_data` required. Samplesheet header
everywhere: `group,replicate,fastq_1,fastq_2,control`.

| profile | dataset | n | grouping columns | reference | class | codes | verdict |
|---|---|---|---|---|---|---|---|
| `test` | `cutandrun/samplesheet_2_0/test-GSE145187-small.csv` | 2 | group, replicate, control | hg38-chr20 + E. coli spike-in | CI | `MQC` `VER` | 🚫 |
| `test_fasta_only` | same | 2 | same | fasta + bowtie2 only | CI | `MQC` `VER` | 🚫 |
| `test_no_genome` | same | 2 | same | iGenomes GRCh38 + K12-MG1655 | CI | `MQC` `VER` `S3` | 🚫 |
| `test_tech_reps` | `test-GSE145187-small-tech-reps.csv` | 3 | same (merged technical reps) | explicit | CI | `MQC` `VER` | 🚫 |
| `test_no_control` | `test-GSE145187-noigg-small.csv` | 1 | group, replicate (`use_control=false`) | explicit | CI | `MQC` `VER` | 🚫 |
| `test_local_zip` | `test-GSE145187-small.csv` | 2 | same | CI-runner local paths | CI | `MQC` `VER` `KO` | 🚫 |
| `test_full_small` | `test-GSE145187-all-small.csv` | 6 | group (`h3k27me3`, `h3k4me3`, `igg_ctrl`), replicate, control | explicit, seacr+MACS2 | CI | `MQC` `VER` | 🚫 |
| `test_full_small_local_zip` | `test-GSE145187-all-small.csv` | 6 | same | CI-runner local paths | CI | `MQC` `VER` `KO` | 🚫 |
| `test_full` | `test-GSE145187-all.csv` | 6 | same | iGenomes GRCh38 | full | `MQC` `VER` `S3` | 🚫 |
| `test_full_multi` | `test-GSE145187-all-multi-rep.csv` | 8 | same, extra replicates | iGenomes GRCh38 | full | `MQC` `VER` `S3` | 🚫 |

`test_full_small` is the best mid-size design here (6 samples, 2 marks × 2 reps + IgG,
no S3) and would be the one to use if the template is ever re-pinned - see Annex B.

### differentialabundance 2.0.0 - 13 profiles
Profiles are composed: a method profile (`conf/profile/…`) plus a dataset profile
(`conf/testdata/<type>.config`). The template binds the **DESeq2 route only**, so limma /
propd / dream profiles write differently named tables (`SCOPE`). No MultiQC by design.
The observation sheet is never published into `outdir` (`SHEET`), and `samples` is a
required collection - so every profile is ❌ until the sheet is copied into
`<outdir>/input/`. With that one copy, the DESeq2 profiles become ✅.

| profile | dataset (`--input`) | n | grouping columns | annotation | class | codes | verdict |
|---|---|---|---|---|---|---|---|
| `test` | `SRP254919.samplesheet.csv` | 6 | **treatment** (mCherry/hND6), sample_title, instrument_model | Ensembl GRCm38.81 GTF | CI | `SHEET` `NET` | ❌ → ✅ |
| `test_rnaseq_deseq2_gsea` | same | 6 | same | + `mh.all…Mm.symbols.gmt` | CI | `SHEET` `NET` | ❌ → ✅ |
| `test_rnaseq_deseq2_gprofiler2` | same | 6 | same | same | CI | `SHEET` `NET` | ❌ → ✅ |
| `test_rnaseq_limma_gsea` | same | 6 | same | same | CI | `SCOPE` `SHEET` | ❌ |
| `test_rnaseq_limma_gprofiler2` | same | 6 | same | same | CI | `SCOPE` `SHEET` | ❌ |
| `test_rnaseq_limma_decoupler` | same | 6 | same | + progeny mouse network | CI | `SCOPE` `SHEET` | ❌ |
| `test_rnaseq_propd_grea` | same | 6 | same | same | CI | `SCOPE` `SHEET` | ❌ |
| `test_rnaseq_dream_decoupler` | `variancepartition_dream/metadata.tsv` | 24 | **genotype, treatment, time, batch** | Ensembl GTF + progeny | CI | `SCOPE` `SHEET` | ❌ |
| `test_affy_limma_gsea` | `GSE50790.csv` | 8 | **phenotype** (lesional/uninvolved), **patient** | none (Affy platform) | CI | `SCOPE` `SHEET` | ❌ |
| `test_affy_limma_gprofiler2` | same | 8 | same | none | CI | `SCOPE` `SHEET` | ❌ |
| `test_maxquant` | `MaxQuant_samplesheet.tsv` | 15 | **Celltype**, fakeBatch | none | CI | `SCOPE` `SHEET` | ❌ |
| `test_soft` | `GSE50790.csv` + live `querygse` | 8 | phenotype, patient | none | CI | `SCOPE` `SHEET` `NET` | ❌ |
| `test_full` | `rnaseq_featurecounts_sample_preparations.tsv` | 24 | **Condition genotype, Condition treatment, Condition time, batch** | Ensembl GRCm38.81 + gmt | full (matrix-based, not hours) | `SHEET` `NET` | ❌ → ✅ |

`test_full` carries the richest sample metadata of the whole survey (4 factors × 24
samples) and, being matrix-based rather than FASTQ-based, is not actually expensive.

### funcscan 4.0.0 - 15 profiles
14 of 15 collections are optional, so a partial run degrades rather than fails; only
`screening_summary` is required. No grouping metadata in any funcscan samplesheet -
`sample,fasta` and nothing else. Samplesheet not published (`SHEET`) but its collection
is optional.

| profile | dataset | n | grouping columns | databases | class | codes | verdict |
|---|---|---|---|---|---|---|---|
| `test` | `funcscan/samplesheet_reduced.csv` | 2 | - | AMRFinderPlus + DeepARG downloads | CI | `SHEET` `DB` | ⚠️ |
| `test_bakta` | `samplesheet_reduced.csv` | 2 | - | Bakta light (~1.5 GB) | CI | `SHEET` `DB` | ⚠️ |
| `test_prokka` | `samplesheet_reduced.csv` | 2 | - | AMRFinderPlus + DeepARG | CI | `SHEET` `DB` | ⚠️ |
| `test_minimal` | `samplesheet_reduced.csv` | 2 | - | none (everything skipped) | CI | `SHEET` `SKIP` | ❌ |
| `test_cazyme_pyrodigal` | `samplesheet_reduced.csv` | 2 | - | dbCAN | CI | `SHEET` | ⚠️ |
| `test_taxonomy_bakta` | `samplesheet_reduced.csv` | 2 | - | Bakta light | CI | `SHEET` `DB` | ⚠️ |
| `test_taxonomy_prokka` | `samplesheet_reduced.csv` | 2 | - | - | CI | `SHEET` | ⚠️ |
| `test_taxonomy_pyrodigal` | `funcscan/samplesheet_hits.csv` | 2 | - | - | CI | `SHEET` | ⚠️ |
| `test_bgc_bakta` | `samplesheet_hits.csv` | 2 | - | Bakta light + trimmed antiSMASH | CI | `SHEET` `DB` `SKIP` | ⚠️ |
| `test_bgc_prokka` | `samplesheet_hits.csv` | 2 | - | trimmed antiSMASH | CI | `SHEET` `SKIP` | ⚠️ |
| `test_bgc_pyrodigal` | `samplesheet_hits.csv` | 2 | - | trimmed antiSMASH | CI | `SHEET` `SKIP` | ⚠️ |
| `test_preannotated` | `samplesheet_preannotated.csv` | 3 | - (`sample,fasta,protein,gbk`) | - | CI | `SHEET` | ⚠️ |
| `test_preannotated_bgc` | `samplesheet_preannotated.csv` | 3 | - | trimmed antiSMASH | CI | `SHEET` `SKIP` | ⚠️ |
| `test_preannotated_cazyme` | `samplesheet_preannotated.csv` | 3 | - | dbCAN | CI | `SHEET` | ⚠️ |
| `test_full` | `funcscan/samplesheet_full.csv` | 19 | - | DeepARG + AMRFinderPlus, reads on S3 | full | `SHEET` `S3` `DB` | ⚠️ |

### rnafusion 4.1.3 - 3 profiles
Samplesheet pinned at `{DATA_ROOT}/input/samplesheet.csv` and never published (`SHEET`);
that collection is required, so all three are ❌ without a copy. One sample everywhere -
cohort behaviour is untested by any public profile.

| profile | dataset | n | grouping columns | reference | class | codes | verdict |
|---|---|---|---|---|---|---|---|
| `test` | `${projectDir}/tests/csv/fastq.csv` | 1 | - | `genomes_base = ${params.outdir}/references` (absent unless `test_build` ran) | stub | `SHEET` `KO` | ❌ |
| `test_build` | same | 1 | - | STAR-Fusion minigenome, `references_only=true` | CI | `SHEET` `SCOPE` | ❌ |
| `test_full` | `rnafusion/testdata/human/samplesheet_valid.csv` | 1 | - | full reference bundle, COSMIC credentials required | full | `SHEET` `S3` `NET` | ❌ |

### rnaseq 3.26.0 - 7 profiles
6 collections, **none optional**, and the samplesheet is read from
`{DATA_ROOT}/input/samplesheet.csv`. Verified against the megatest listing: rnaseq 3.26.0
publishes no `samplesheet.valid.csv` and no `input/` - the `docs/output.md` boilerplate
that mentions it is stale. So every profile is ❌ until the sheet is copied in; with that
copy, `test` becomes the cheapest ✅ of the whole survey.
The megatest's `aligner_star_salmon/` run root is an artefact of the multi-aligner
megatest; a local run writes `star_salmon/` and `multiqc/star_salmon/multiqc_report_data/`
straight under `--outdir`, which is what the template's scan regex expects.

| profile | dataset | n | grouping columns | reference | class | codes | verdict |
|---|---|---|---|---|---|---|---|
| `test` | `test-datasets/samplesheet/v3.10/samplesheet_test.csv` | 7 rows / 5 samples | - (groups implicit in `WT_REP1`, `RAP1_IAA_30M_REP1`…) | explicit fasta/gtf/gff/salmon/hisat2 + tiny kraken db | CI | `SHEET` | ❌ → ✅ |
| `test_gpu` | same | 7 / 5 | same | same | CI (8 cpu / 30 GB) | `SHEET` | ❌ → ✅ |
| `test_prokaryotic` | `rnaseq/samplesheet/prokaryotic/samplesheet_test.csv` | 2 | - | `SL1344_sub` fasta + gff, `pseudo_aligner=null`, `skip_deseq2_qc=true` | CI | `SHEET` `SKIP` | ❌ |
| `test_full` / `test_full_aws` | `samplesheet/v3.10/samplesheet_full.csv` | 8 | - (GM12878/K562/MCF7/H1 × 2 reps, in the names) | iGenomes GRCh37 | full | `SHEET` `S3` | ❌ → ✅ |
| `test_full_gcp` | `samplesheet_full_gcp.csv` | 8 | same | iGenomes GRCh37 | full | `SHEET` `S3` | ❌ → ✅ |
| `test_full_azure` | `samplesheet_full_azure.csv` (`az://`) | 8 | same | iGenomes GRCh37 | full | `SHEET` `S3` | ❌ → ✅ |

### taxprofiler 2.0.1 - 9 profiles
Samplesheet and database sheet are both optional collections, so `SHEET` only degrades.
The 5 taxpasta collections and `multiqc_data` are required, so any profile that runs no
profiler fails. Samplesheet header: `sample,run_accession,instrument_platform,fastq_1,fastq_2,fasta`.

| profile | dataset | n | grouping columns | databases | class | codes | verdict |
|---|---|---|---|---|---|---|---|
| `test` | `taxprofiler/samplesheet.csv` | 7 | run_accession, instrument_platform (ILLUMINA / OXFORD_NANOPORE) | `database_v2.1.csv` (18 rows, tiny public tarballs) | CI | `SHEET` | ⚠️ |
| `test_nopreprocessing` | same | 7 | same | 18 | CI | `SHEET` `SKIP` | ⚠️ |
| `test_minimal` | same | 7 | same | 18, every profiler off | CI | `SHEET` `SKIP` | ❌ |
| `test_malt` | `taxprofiler/samplesheet_malt.csv` | 2 | same | 18 | CI | `SHEET` | ⚠️ |
| `test_fastpnonpareilkrakenuniq` | `taxprofiler/samplesheet.csv` | 7 | same | `database_krakenuniq.csv` (1) | CI | `SHEET` `SKIP` | ⚠️ |
| `test_alternativepreprocessing` | `samplesheet_shortreadfastqpairsonly.csv` | 6 | same | 18 | CI | `SHEET` | ⚠️ |
| `test_falcobbduk` | `samplesheet_shortreadfastqpairsonly.csv` | 6 | same | 18 | CI | `SHEET` | ⚠️ |
| `test_motus` | `taxprofiler/samplesheet.csv` | 7 | same | `database_motus.csv` **absent from the repo**, needs the multi-GB mOTUs DB | CI | `KO` `DB` | ❌ |
| `test_full` | `taxprofiler/samplesheet_full.csv` | 7 | same | `database_full_v2.1.csv` (20 rows, all on S3) | full | `SHEET` `S3` `DB` | ⚠️ |

### variantbenchmarking 1.4.0 - 16 profiles
Nine of them live under `conf/tests/` and are **not** named `test*`, so they are invisible
to a `conf/test*.config` listing. The grouping dimension here is `caller`, not a
biological factor. Every profile sets `genome = GRCh37|GRCh38` → iGenomes on S3, and
every one hard-codes `outdir = 'results'`, which fights a `--outdir` override.
The template's one required collection is `germline_vcfeval_summary`, so somatic / SV /
CNV profiles have nothing required to produce.

| profile | dataset | n | grouping column | genome / truth | class | codes | verdict |
|---|---|---|---|---|---|---|---|
| `test` | `assets/samplesheet.csv` (in-repo) | 3 | caller (delly, lumpy…) | GRCh37 + HG002 SV Tier1 chr21 | CI | `VER` `S3` | ⚠️ |
| `germline_small` | `samplesheet_small_germline_hg38.csv` | 2 | caller | GRCh38 + HG002 v4.2 chr21 | CI | `VER` `S3` | ✅ |
| `germline_sv` | `samplesheet_sv_germline_hg37.csv` | 3 | caller | GRCh37 + HG002 SV | CI | `VER` `S3` | ⚠️ |
| `germline_bnd` | `samplesheet_sv_germline_hg37_bnd.csv` | 4 | caller | GRCh37 + HG002 SV | CI | `VER` `S3` | ⚠️ |
| `somatic_snv` | `samplesheet_snv_somatic_hg38.csv` | 3 | caller, subsample | GRCh38 + SEQC2 sSNV | CI | `VER` `S3` `NET` | ❌ |
| `somatic_indel` | `samplesheet_indel_somatic_hg38.csv` | 3 | caller, subsample | GRCh38 + SEQC2 sINDEL | CI | `VER` `S3` `NET` | ❌ |
| `somatic_sv` | `sarek/3.5.1/samplesheet_sarek_somatic_sv.csv` | 2 | caller | GRCh38 | CI | `VER` `S3` | ❌ |
| `somatic_cnv` | `sarek/3.5.1/samplesheet_sarek_somatic_cnv.csv` | 4 | caller | GRCh38 | CI | `VER` `S3` | ❌ |
| `liftover_test` | `samplesheet_sv_germline_hg37_liftover.csv` | 5 | caller, liftover | GRCh37 + Ensembl chain | CI | `VER` `S3` `NET` | ⚠️ |
| `liftover_truth` | `samplesheet_small_germline_hg38.csv` | 2 | caller | GRCh38 + GATK `master` chain | CI | `VER` `S3` `NET` | ⚠️ |
| `test_happy` | `samplesheet_small_germline_hg38.csv` | 2 | caller | GRCh38 + stratification | CI | `VER` `S3` | ✅ |
| `test_ga4gh` | `samplesheet_small_germline_hg38.csv` | 2 | caller | GRCh38, pinned wave container | CI | `VER` `S3` | ✅ |
| `concordance` | `samplesheet_small_germline_hg38.csv` | 2 | caller | GRCh38, no truth VCF | CI | `VER` `S3` `SCOPE` | ❌ |
| `test_full` | `samplesheet_full_small.csv` | 3 | caller | GRCh37 + GIAB CMRG v1.00 (NCBI ftp) | full | `VER` `S3` `NET` | ⚠️ |
| `test_full_sv` | `samplesheet_full_sv.csv` | 2 | caller | GRCh37 + NIST SV v0.6 | full | `VER` `S3` `NET` | ⚠️ |
| `test_full_somatic` | `samplesheet_full_somatic.csv` | 3 | caller, subsample | GRCh38 + SEQC2 | full | `VER` `S3` `NET` | ❌ |

Samplesheet headers differ per profile family - `id,test_vcf,caller` at the simplest,
up to 16 columns for the SV ones. The template reads none of them; it reads the summary
tables.

### viralrecon 3.0.0 - 8 profiles
The only `sequencing-runs` template: `runs_regex: run_.*`, and `scan.py` iterates only
matching subdirectories. A plain `--outdir results` contains none, so **every** profile
carries `RUNS` and needs `params.depictio_data_root` pointing at a parent that holds
`run_*/`. 12 of 14 collections are optional; `multiqc_data` and `summary_metrics` are
required. `IS_NANOPORE` is auto-detected from `params.json`. No samplesheet or metadata
collection exists at all.

| profile | dataset | n | grouping columns | reference | class | codes | verdict |
|---|---|---|---|---|---|---|---|
| `test` | `samplesheet/v2.6/samplesheet_test_amplicon_illumina.csv` | 4 | - (`sample,fastq_1,fastq_2`) | `MN908947.3` (pipeline-local igenomes), artic v1, tiny kraken2 | CI | `RUNS` | ✅ |
| `test_sispa` | `samplesheet_test_metagenomic_illumina.csv` | 4 | - | `MN908947.3`, metagenomic, bcftools | CI | `RUNS` | ⚠️ |
| `test_nanopore` | `samplesheet_test_amplicon_nanopore.csv` | 11 | - (`sample,barcode`) | `MN908947.3`, artic v3; `fastq_dir` + `sequencing_summary` on S3 | CI | `RUNS` `S3` | ⚠️ |
| `test_full` / `test_full_aws` / `test_full_illumina` | `samplesheet_full_amplicon_illumina.csv` | 48 | - | `MN908947.3`, artic v3 | full | `RUNS` `S3` | ✅ |
| `test_full_nanopore` | `samplesheet_full_amplicon_nanopore.csv` | 49 | - | `MN908947.3`, artic v3 | full | `RUNS` `S3` | ⚠️ |
| `test_full_sispa` | - | - | - | - | - | `KO` (`conf/test_full_sispa.config` is 404 at tag 3.0.0) | 🚫 |

`test` and `test_sispa` are the only two viralrecon profiles that need no S3 access at
all - even the "tiny" `test_nanopore` pulls its FAST5/summary from `ngi-igenomes`.

---

## Annex A - why the codes exist

**`VER`** - `depictio.config` forwards `--pipeline-id <manifest.name>/<manifest.version>`
verbatim; `run.py` calls `locate_template()`, and
`templates.py:_resolve_template_id_in` resolves `latest` only when the version directory
exists. There is no fallback to the newest template, and `normalize_pipeline_version`
(`models/models/nextflow.py`) is never called on this path, so `v3.26.0` and `3.26.0dev`
fail too. Fix at the pipeline call site: `-r <pinned version>`.

**`MQC`** - Depictio scans for the literal name `multiqc.parquet`, and there are three
bands, not two. MultiQC introduced the parquet in **1.29** and calls the format stable
from that release, but wrote it as `multiqc_data/BETA-multiqc.parquet` in 1.29 and 1.30;
**1.31** renamed it (MultiQC CHANGELOG, v1.31: "The parquet format is stable since 1.29,
renaming the output file from `BETA-multiqc.parquet` to `multiqc.parquet`").

- **1.31 and later** - read directly.
- **1.29 and 1.30** - the data exists, under a name no template scan regex matches. A
  rename is all that separates such a run from being ingestible; whether the 1.29 schema
  parses cleanly under the reader's MultiQC has not been tested here, so treat it as a
  one-line experiment rather than a documented path.
- **1.28 and older** - no parquet at all. Only
  `python -m depictio.dev_scripts.multiqc_reprocess` produces one, and it is a maintainer
  script the `run` command never invokes.

`cli/utils/multiqc_processor.py` reads the parquet and nothing else, so a pipeline
release pinning an older MultiQC cannot be ingested by the trigger on any profile, only
through the manual fetch-and-reprocess route.

**`SHEET`** - `templates.py` auto-resolves `SAMPLESHEET_FILE` (and `METADATA_FILE`) from
`{DATA_ROOT}/input/`. Only ampliseq publishes that directory
(`docs/output.md` § Input). airrflow, cutandrun, chipseq and atacseq instead expose the
sheet under `pipeline_info/`, which their templates already read. Everywhere else the
sheet exists only as the URL in `params.json`, which is why every `megatest.yaml`
`post_fetch_help` curls it into `input/`. Workaround for a live run: copy the sheet into
`<outdir>/input/` before the pipeline finishes.

**`RUNS`** - `scan.py` walks only subdirectories matching `runs_regex` when
`data_location.structure` is `sequencing-runs`. viralrecon is the only such template.
The trigger passes `--data-root params.outdir`, so it needs
`params.depictio_data_root` set to a parent directory holding `run_*/`.

**`SKIP`** - `_introspect_pipeline_params` derives route flags for ampliseq and
viralrecon only (`IS_NANOPORE`, `IS_METAGENOMIC`, `SKIP_QIIME`, `SKIP_TAXONOMY`,
`SKIP_ALPHA_RAREFACTION`, `SKIP_ANCOM`, `IS_MULTIREGION`, `METADATA_FILE`). airrflow's
five, rnafusion's six, funcscan's four and rnaseq's three are not derived, and
`depictio.config` has no parameter that forwards `--var`. A profile that cuts a branch
therefore leaves a required collection with no source.

**`SCOPE`** - the profile runs a route the template never bound: limma / propd / dream in
differentialabundance (DESeq2 only), `references_only` in rnafusion, `concordance` in
variantbenchmarking.

---

## Annex B - re-pinning chipseq, atacseq and cutandrun

These three are 🚫 on every profile, for the same reason: the release the template
targets predates the MultiQC parquet (1.9 / 1.9 / 1.14) and `multiqc_data` is a required
collection in all three (19, 15 and 14 collections, with 0, 0 and 3 optional). chipseq
1.2.0 and atacseq 1.2.2 are additionally DSL1, so they need `NXF_VER=22.10.8` or older -
the locally installed Nextflow is 26.04.6.

They were pinned there on purpose: `MEGATEST_STATUS.md` records that the recent megatests
are empty or truncated (chipseq 2.1.0 and 2.0.0 are BAM-only syncs, atacseq 2.1.x holds a
single 12 GB object, cutandrun 3.2.x holds directory markers), while 1.2.0 / 1.2.2 / 3.1
are complete runs. The reprocessing step in their `megatest.yaml` exists exactly to buy
back the parquet.

**What re-pinning would cost**

- *Input schema.* chipseq 2.x replaces `group,replicate,fastq_1,fastq_2,antibody,control`
  with `sample,fastq_1,fastq_2,replicate,antibody,control,control_replicate`; atacseq 2.x
  makes the same move. Both templates' `design_reads` / `sample_design` collections and
  the recipes that derive sample tables from them would have to be rewritten.
- *Output tree.* The DSL2 rewrites move everything: `bwa/mergedLibrary/…` becomes
  `bowtie2/merged_library/…` and the MACS2 / consensus / DESeq2 subtrees are renamed.
  Every scan regex and `source_overrides` glob in the two templates is affected.
- *No parquet on the other side either.* This is the finding that decides the question.
  The latest release of each of the three still pins a MultiQC below the 1.29 parquet
  floor: **chipseq 2.1.0 uses MultiQC 1.23** (`modules/nf-core/multiqc/environment.yml`),
  **atacseq 2.1.2 uses 1.13** and **cutandrun 3.2.2 uses 1.19** (both
  `modules/local/multiqc.nf`). None of the three has cut a release since MultiQC 1.29
  (May 2025): their last releases are 2024-10, 2023-08 and 2024-02. Re-pinning would
  therefore buy the DSL2 rewrite and drop the `-r`, but would **not** remove the `MQC`
  blocker. Reprocessing stays mandatory on every release that exists today.
- *Upside.* The DSL1 constraint disappears and `-r` is no longer needed once the template
  directory matches the latest release.
- *The catch.* None of the three can be validated on a megatest of a recent release,
  because those prefixes hold no usable run.

### The route that does work: reprocess MultiQC locally

🚫 is a verdict on the **trigger**, not on the template. `multiqc_reprocess` re-parses the
pipeline's **raw tool outputs** (it skips every `multiqc*` directory and the `work/` tree
on purpose) with the repo-pinned MultiQC 1.35, so it needs those inputs on disk - which a
local pipeline run has by definition, and more completely than any megatest subset. The
three templates are therefore testable today, in three steps, on their own `-profile test`
data:

```bash
# 1. run the pipeline WITHOUT the trigger: simply omit `-c $(depictio-cli config nextflow)`.
#    Only if the handler was installed globally (`config nextflow --install`) does it need
#    switching off, and then through a config rather than a bare `--depictio_enabled`,
#    which nf-schema would flag as an unrecognised parameter:
#      echo 'params.depictio_enabled = false' > off.config   # then add: -c off.config
nextflow run nf-core/chipseq -r 1.2.0 -profile test,docker \
  --outdir ~/Data/depictio-nfcore/chipseq/1.2.0/test

# 2. produce the parquet the template scans for
python -m depictio.dev_scripts.multiqc_reprocess \
  --src ~/Data/depictio-nfcore/chipseq/1.2.0/test \
  --dest ~/Data/depictio-nfcore/chipseq/1.2.0/test

# 3. ingest by hand
depictio-cli run --template nf-core/chipseq/1.2.0 \
  --data-root ~/Data/depictio-nfcore/chipseq/1.2.0/test
```

The datasets to use are the ones in the tables above: `chipseq -profile test` (6
libraries, group/replicate/antibody/control, explicit references, no S3),
`atacseq -profile test` (4 libraries, group/replicate, no S3) and
`cutandrun -profile test_full_small` (6 samples, 2 marks × 2 reps + IgG, no S3). All three
are minutes-long CI datasets needing no credentials, so this validates the templates
against data that is *not* the megatest they were written on - which was the whole point.

Two local caveats. chipseq 1.2.0 and atacseq 1.2.2 are DSL1 and need `NXF_VER=22.10.8` or
older; cutandrun 3.1 is DSL2 and does not. And on an arm64 machine the 2020-2023
biocontainers are amd64-only, so Docker emulates them: it works, slowly, and
`docker.runOptions = '--platform=linux/amd64'` makes the behaviour explicit rather than
warning-driven. Step 2 runs in the local venv, not in a container, so it is unaffected.

**Verdict: do not re-pin, for now.** What makes the three 🚫 is the MultiQC version, and
no release of any of them clears the 1.29 floor. A re-pin would pay for a full template
rewrite (new input schema, new output tree, validation moved from megatest to local
`-profile test`) and still need the reprocess step afterwards. cutandrun 3.1 → 3.2.2
looked like the cheap one until its 1.19 pin showed up: it is a version bump that changes
nothing about the blocker.

What would change the picture is a new upstream release pinning MultiQC 1.29 or later.
Until then all three stay on the manual route, which already works:
`python scripts/nfcore_megatest.py fetch` → `python -m depictio.dev_scripts.multiqc_reprocess`
→ `depictio-cli run --template …`. The cheap follow-up is not a re-pin but making that
reprocess reachable from `depictio-cli run` itself, which would unblock these three and
every other pre-1.29 run a user brings.

---

## Reading the tables against the trigger

Two things decide most verdicts, and neither is about the data:

1. **The pipeline version must have a template directory.** Today 7 of 12 pipelines sit
   at their latest release, so `nextflow run nf-core/<pipe> -profile test` resolves. That
   is a moving property: the next nf-core release of any of them breaks it until a
   template directory is added. `-r <pinned version>` is the safe habit.
2. **The samplesheet must be inside the results directory.** Only ampliseq publishes
   `input/`; airrflow, cutandrun, chipseq and atacseq publish it under `pipeline_info/`
   and their templates read it there. For rnaseq, rnafusion and differentialabundance -
   the three templates with a required samplesheet collection and no published sheet -
   a single copy into `<outdir>/input/` turns ❌ into ✅.

The cheapest end-to-end checks, if only a few are to be run: **ampliseq `-profile test`**
(✅ as-is, metadata included), **rnaseq `-profile test`** (✅ after the samplesheet copy -
and the clearest demonstration of the `SHEET` failure if run without it), and
**viralrecon `-profile test`** (✅ once `depictio_data_root` points at a `run_*` parent).

---

## How these profiles are actually executed

The table above says what *could* be run. `scripts/nfcore_validation_hpc.py` is what
runs it: eleven profiles, one per pipeline, submitted to SLURM on the EMBL cluster,
rsynced back, then reprocessed and ingested locally. rnafusion is the one pipeline with
no usable light profile (`test` is a stub, `test_build` is `references_only`, `test_full`
needs COSMIC credentials), so it stays on its megatest.

The cluster rather than a laptop because the only two local runs ever attempted both died
on `no space left on device` inside the container VM, and because the cluster already
carries a SLURM config, a shared Singularity cache and a DSL1-capable Nextflow.

Separately, `scripts/nfcore_trigger_stub.py` answers the other half of the question.
Whether a pipeline produces the files a template wants is a data question, answered by
running it. Whether the 1.10.0 handler turns a completed run into the right
`depictio-cli run` is not, and needs no pipeline at all: a ten-line workflow wearing the
right `manifest {}` exercises the whole path in seconds. Both modes pass on all fourteen
template directories, and the must-fail cases below fail for the right reason.

### Two traps in the harness, not in the templates

Both cost a run and neither says anything about a template, but both will bite anyone
running nf-core pipelines under Singularity on a shared cluster.

**TMPDIR has to be per task.** Nextflow forwards the host `TMPDIR` into the container
verbatim, the task launcher writing `${TMPDIR:+SINGULARITYENV_TMPDIR="$TMPDIR"}`, while
`autoMounts` binds only the run root. A node-local `TMPDIR` is therefore a path that does
not exist inside the image, and nf-core/differentialabundance dies in `QUARTONOTEBOOK`
with `NotFound: No such file or directory (os error 2): tmpdir`. Pointing `TMPDIR` at one
fixed directory inside the bind fixes that pipeline and breaks the next one:
nf-core/ampliseq died at `QIIME2_DIVERSITY_ALPHA` with `OSError: [Errno 121] Remote I/O
error: .../qiime2/<user>/LOCK`, because QIIME2 writes its cache lock to the *fixed* path
`$TMPDIR/qiime2/$USER/LOCK` rather than going through `mkdtemp`, so every concurrent
QIIME2 task on every node contends for one lock file over the network filesystem. The
value that satisfies both is `$NXF_TASK_WORKDIR`: inside the bind, and unique per task.
It survives either escaping behaviour, since the variable is defined on the host before
`nxf_launch` and forwarded into the container as `SINGULARITYENV_NXF_TASK_WORKDIR`.

**The head job builds the images.** A Nextflow head job submitted with a modest memory
request is fine until a pipeline needs a large container that is not yet in the cache:
building the SIF runs `mksquashfs` in the head job, and both ampliseq (QIIME2) and
airrflow (immcantation) were killed with `mksquashfs command failed: exit status 137` at
6 GB. Twenty-four gigabytes covers them. The symptom is easy to misread as a pipeline
failure because Nextflow reports it as a failed pull.

### What running it turned up

Three things the analytical survey could not have known, all confirmed against the
pipelines' own `nextflow.config`:

**Nextflow floors, not just template versions.** Four pipelines declare
`nextflowVersion = '!>=25.10.4'` (ampliseq 2.18.0, taxprofiler 2.0.1, funcscan 4.0.0,
differentialabundance 2.0.0) and airrflow 5.1.0 declares `!>=26.04.1`. The `!` makes
these hard failures, not warnings. This is a second version axis alongside the template
directory one, and it moves independently.

**atacseq 1.2.2 cannot resolve, and no revision pin fixes it.** nf-core tagged 1.2.2
without bumping its manifest, so `nextflow run nf-core/atacseq -r 1.2.2` reports
`manifest.version = '1.2.1'`. The trigger forwards the *manifest*, not the revision, so
the pipeline id is `nf-core/atacseq/1.2.1` and the template directory is `1.2.2`.
Verified: the CLI answers `No bundled depictio template matches pipeline
'nf-core/atacseq/1.2.1'` and exits 1. So atacseq carries a `VER` blocker on top of its
`MQC` one, and the only fixes are a `1.2.1` template directory or an explicit
`--depictio_template`.

**ampliseq 2.14.0 declares `SAMPLESHEET_FILE` as `required: true`**, where 2.16.0 and
2.18.0 declare it `required: false`. On a real run this is invisible, because the
resolver auto-detects the sheet from `{DATA_ROOT}/input/` and ampliseq is the one pipeline
that publishes it. But 2.14.0 has no fallback if that directory is ever missing or the
file is not named `*samplesheet*`, while the two later versions degrade instead.

**A 1.10.0 CLI cannot ingest into a 1.9.2 server.** The trigger's own CLI sends run
provenance the older API has never heard of, and the project models are `extra=forbid`,
so the server answers `extra_forbidden` on `workflows[].config.engine_name`,
`pipeline_version`, `nextflow_version`, `tools_executed` and on top-level `triggered_by`,
and the run dies at step 4 of 8 with the project not created. It is a hard failure, not a
degraded ingestion. So the pair has to match: validating a template's *data* wants the
branch's own CLI against the branch's own stack, while validating the *trigger*
end to end wants a 1.10.0 server. The two cannot be the same instance until this branch
carries 1.10.0.

### Verified end to end

rnaseq 3.26.0 `-profile test`, submitted to SLURM, repatriated, ingested: **6/6 data
collections processed and the dashboard imported**. This is the table's `SHEET` prediction
confirmed from both sides - the run publishes no samplesheet, and copying the one named by
`pipeline_info/params.json` into `input/` is the whole difference between ❌ and ✅.

### Measured results

One profile per pipeline, run on the EMBL cluster, repatriated and ingested. "DCs" is
data collections processed over declared; a skipped collection is `optional: true` and
degrades the dashboard, a failed one aborts the run.

| pipeline / profile | DCs | predicted | measured |
|---|---|---|---|
| rnaseq `test` | 6/6 | ❌ → ✅ | ✅ |
| viralrecon `test` | 14/14 | ✅ | ✅ |
| differentialabundance `test_full` | 8/8 | ❌ → ✅ | ✅ |
| cutandrun `test_full_small` | 14/14 | 🚫 trigger, ✅ manual | ✅ |
| taxprofiler `test` | 10/12 | ⚠️ | ⚠️ |
| funcscan `test` | 8/15 | ⚠️ | ⚠️ |
| variantbenchmarking `germline_small` | 3/9 | ✅ germline | ✅ |
| chipseq `test` | 15/15 | ✅ | ✅ (after the HOMER fix) |
| atacseq `test` | 19/19 | 🚫 (`MQC`) | ✅ (after the HOMER fix) |
| airrflow `test` | 12/12 | ✅ | ✅ |
| ampliseq `test` | 12/23 | ✅ (`DB`) | **⚠️** |

### The defect a megatest could never have caught

chipseq and atacseq both fail on the same two collections, `homer_annotated_peaks` and
`homer_tss_distance_profile`, with `polars.exceptions.DuplicateError: column 'chr' is
duplicate`. `homer_tss_distance_profile` is collateral: its source is
`RecipeSource(ref="peaks", dc_ref=...)`, so it only falls because the collection it
derives from falls.

The cause is the source glob of the shared catalog recipe,
`**/*.annotatePeaks.txt` in `depictio/catalog/homer/annotate_peaks.py`. On a real run it
matches three different file shapes, only two of which are HOMER tables:

| file | columns | identity column | coordinates |
|---|---|---|---|
| `<sample>_peaks.annotatePeaks.txt` | 19 | `PeakID (cmd=...)` | `Chr`, `Start`, `End` |
| `<prefix>consensus_peaks<...>.annotatePeaks.txt` | 19 | `PeakID (cmd=...)` | `Chr`, `Start`, `End` |
| `<prefix>consensus_peaks<...>.boolean.annotatePeaks.txt` | 43 to 47 | `interval_id` | `chr`, `start`, `end` |

The third is not an `annotatePeaks.pl` output at all: it is the consensus boolean matrix
with the HOMER annotation columns appended, and its coordinate columns are lower case.
`_resolve_glob_source` concatenates matches with `pl.concat(..., how="diagonal_relaxed")`,
a union of columns, so the combined frame carries `chr` and `Chr` side by side (5382 x 57
for chipseq, 13211 x 68 for atacseq). The recipe's `rename({"Chr": "chr", ...})` then
collides with a column that is already there, and both collections abort, taking the whole
ingestion with them.

Note what is *not* the problem. The plain consensus table is handled on purpose: the
recipe's docstring says "consensus-level tables, whose ids are `Interval_12`, fall back to
`consensus`", and `_CONSENSUS_LABEL` implements it. Only the boolean variant is foreign.

The fix therefore narrows the glob to `**/*_peaks.annotatePeaks.txt`, which excludes
`.boolean.annotatePeaks.txt` structurally without a negative pattern, plus a
`source_overrides` entry in each template to pin the aggregation level the template's own
header comment already claims:

```yaml
transform:
  recipe: "homer/annotate_peaks.py"
  source_overrides:
    annotation:
      glob_pattern: "bwa/mergedLibrary/macs/*/*_peaks.annotatePeaks.txt"
```

That second half is not cosmetic. atacseq publishes the whole peak tree twice, per merged
library (`.mLb.clN`) and per merged replicate (`.mRp.clN`), and
`atacseq/1.2.2/template.yaml` states that "only the merged-library level is bound here".
Nothing was enforcing it: the template scopes no path, so the recipe's unanchored glob was
the only selector and it took both levels.

Measured against all four repatriated datasets, the narrowed glob is a no-op everywhere
the current one works:

| glob | chipseq test | chipseq megatest | atacseq test | atacseq megatest |
|---|---|---|---|---|
| `**/*.annotatePeaks.txt` | DuplicateError | 258986 rows | DuplicateError | 224137 rows |
| `**/*_peaks.annotatePeaks.txt` | 4107 rows | 258986 rows | 6403 rows | 224137 rows |
| with the template override | 2832 rows, 4 samples | 258986 rows | 3839 rows, 4 samples | 224137 rows |

The fix is applied. `annotate_peaks.py` and both catalog YAMLs now glob
`**/*_peaks.annotatePeaks.txt`, and `chipseq/1.2.0/template.yaml` and
`atacseq/1.2.2/template.yaml` pin the merged-library level through
`source_overrides`. Re-ingested, chipseq `test` goes to 15 of 15 collections and
atacseq `test` to 19 of 19, both above the predicted 13 and 17, and the megatests
are byte-identical to before at 258986 and 224137 rows.

What makes this worth writing down is why it was invisible. `chipseq/1.2.0/megatest.yaml`
says, in its own comment: *"The consensus-level annotatePeaks.txt files are not fetched:
the dashboard reads the consensus boolean matrix instead."* The fetch manifest performs
the filtering the recipe should be doing, so the template passes on the megatest precisely
because the files that break it are never downloaded, which is exactly what the two
megatest columns above show. No amount of megatest-based validation can find this class of
defect; only a real pipeline run can.

### A documented caveat that costs seven collections

ampliseq `test` is the one profile whose measured verdict is worse than predicted, and
the cause is neither a template defect nor a harness artefact. The run ends with
`taxonomy_rel_abundance` failing on a missing file:

    qiime2/rel_abundance_tables/rel-table-3.tsv

The template pins that path deliberately, and its own comment explains why and predicts
this exact situation:

> ampliseq 2.18.0 classifies against `sbdi-gtdb` by default, whose DADA2 taxlevels are
> Domain,Kingdom,Phylum ... one rank deeper than the 7-rank databases earlier releases
> defaulted to. QIIME2's collapsed outputs are addressed by DEPTH, so the Phylum that used
> to sit at level 2 now sits at level 3. [...] A run that overrides `--dada_ref_taxonomy`
> with a 7-rank database (rdp, silva, unite ...) must point these back at level 2.

The CI profile does both halves of that. `params.json` records
`dada_ref_taxonomy = gtdb=R07-RS207`, a 7-rank database rather than the 8-rank default,
and `tax_agglom_min = tax_agglom_max = 2`, which caps agglomeration so level 3 is never
written at all. Only `rel-table-2.tsv` exists, holding exactly two ranks
(`Bacteria;Omnitrophota`), which is the Phylum depth the collection wants.

So the `DB` blocker code the profile table already carries is correct. What the table got
wrong is its weight. `DB` was read as "degrades", and the verdict stayed ✅; the measured
result is 12 of 23 collections, because `taxonomy_rel_abundance` is not `optional` and six
further collections reach it through `dc_ref`:

| collection | recipe |
|---|---|
| `taxonomy_heatmap` | `qiime2/taxonomy_heatmap.py` |
| `embedding_pcoa` | `qiime2/embedding_pcoa.py` |
| `complex_heatmap_canonical` | `nf-core/ampliseq/complex_heatmap_canonical.py` |
| `upset_canonical` | `nf-core/ampliseq/upset_canonical.py` |
| `ma_canonical` | `nf-core/ampliseq/ma_canonical.py` |
| `bray_curtis_canonical` | `nf-core/ampliseq/bray_curtis_canonical.py` |

They fail with `Failed to read dc_ref 'taxonomy_rel_abundance' from Delta Lake`, which is a
true statement about a table that was never written and tells a reader nothing about the
cause seven collections upstream.

Two things follow. A collection that others derive from should be `optional: true` when
its source path is route-dependent, so a documented caveat degrades one tile instead of a
subtree. And the agglomeration depth is exactly the kind of thing that belongs in the
template's variables rather than in a pinned path: it is readable from `params.json`
(`tax_agglom_min`/`tax_agglom_max` and `dada_ref_taxonomy`), which is the same source the
template already uses to auto-detect `SKIP_QIIME` and `IS_MULTIREGION`.

### Two further version traps

**chipseq needs `--narrow_peak`, which is not the pipeline default.** `narrow_peak = false`
in nf-core/chipseq 1.2.0, so a plain `-profile test` run writes `macs/broadPeak/`. The
template binds the narrowPeak route only, and because its scans match on file *name*
rather than path (deliberately, so a different aligner still resolves), the broadPeak
files are collected anyway and fail on schema instead of skipping as out of scope. The
template's own header calls `--narrow_peak` "the default for a transcription factor",
which is true biologically and false for nf-core.

**atacseq 1.2.2 will not run on Nextflow 22.10.6.** It is rejected by its own
`main.nf:377` with "Channel `design_multiple_samples` has been used as an input by more
than a process or an operator": a DSL1 rule that tightened after the pipeline was
written. `NXF_VER=21.10.6` runs it. chipseq 1.2.0 has no such problem on 22.10.6.
