# nf-core megatest status

Survey of the public AWS megatest bucket (`s3://nf-core-awsmegatests/`) for the
pipelines depictio templates or considered templating, taken on 2026-09-05 with
`scripts/nfcore_megatest.py` and re-surveyed on 2026-09-16 for the lot 2 pipelines
(sarek, scrnaseq, mag, nanoseq, eager, methylseq, hic, scdownstream), then on 2026-09-23 for
the wave 3 pipelines (riboseq, smrnaseq, genomeassembler, mhcquant, demultiplex, rnasplice,
seqinspector). Every release of a pipeline is expected at
`<pipeline>/results-<tag_sha>/`, where `tag_sha` is the release's sha in
<https://nf-co.re/pipelines.json>. In practice many release prefixes are empty
(only `pipeline_info/` plus zero-byte directory markers), truncated syncs (a few
multi-GB BAM/FASTQ intermediates, no reports) or simply absent, so the resolver
verifies each run before anything is downloaded.

For the other side of the question, which `-profile test*` datasets could exercise each
template, with sample counts, metadata and blockers, see `TEST_DATASETS.md`.

**Status column.** `ok` = the release's own prefix is a real run (at least 5 data
objects outside `pipeline_info/`, at least 5 of them under 50 MB); `empty` = the
prefix exists but fails that check (failed run or truncated sync); `missing` = no
prefix for the release sha; `partial` = passes the check but publishes only part
of the expected outputs. Object counts come from listings capped at 2000-3000 keys
and are lower bounds for the big runs.

## Latest release per pipeline

| pipeline | latest release | tag_sha | megatest | run_root | MultiQC parquet | notes |
|---|---|---|---|---|---|---|
| ampliseq | 2.18.0 | `2723d4c2` | ok | `.` | yes (`multiqc/multiqc_data/`) | Shipped template (2.16.0, 2.18.0). Run wrote MultiQC 1.34. 2.14.0 to 2.17.0 prefixes are complete too. |
| viralrecon | 3.0.0 | `395079f1` | partial | `.` | no | Shipped template. Prefix holds 277 files / 7.9 GB (nanopore + artic layout: `artic_minion/`, `assembly/`, `fastp/`, `kraken2/`, `nanoplot/`) but no `multiqc.parquet`; the bundled `run_1/` comes from an EMBL cluster run (MultiQC 1.31). 2.x prefixes predate the parquet era. |
| variantbenchmarking | 1.5.0 | `8b21c017` | ok | `.` | no (no `multiqc/`) | Shipped template is 1.4.0 and pins this 1.5.0 run on purpose: it is the only run with both `small/` (germline) and `indel/` (somatic). The 1.4.0 release's own run (`68a32098`) is a truncated sync (7 files: rtg-tools reference SDF, two VCFs, one parquet under `small/multiqc/`, no summary tables) and resolves as `empty`. |
| differentialabundance | 2.0.0 | `30ed7741` | ok | `.` (outputs under `tables/<paramset>/`, paramset dirs contain commas) | none (no MultiQC by design) | **Selected.** 33 files / 134 MB. Every older release prefix (1.2.0 to 1.5.0) is empty. |
| funcscan | 4.0.0 | `aee3dc96` | ok | `.` | yes (`multiqc/multiqc_data/`) | **Selected.** 3769 files / 2.9 GB. Run wrote MultiQC 1.34 with an empty general-stats table. 3.0.0 and 2.x prefixes are empty. |
| airrflow | 5.1.1 | `8bc3e567` | missing | | | **Selected run is 5.1.0** (`e69d49e3`, 739 files / 12.2 GB, parquet at `multiqc/multiqc_data/`, MultiQC 1.34 with fastp + FastQC). 5.0.0 is complete too; 4.3.x runs predate the parquet; 4.2.0 and 4.1.0 prefixes are empty. |
| rnafusion | 4.1.3 | `76ad76e7` | ok | `.` | yes (`multiqc/multiqc_data/`) | **Selected.** 383 files / 624 MB, MultiQC 1.33 with full module exports. 4.1.1 is empty; 4.1.0 (10 files) and 4.0.0 (20 files) are partial syncs. |
| rnaseq | 3.26.0 | `e7ca4627` | ok | `aligner_star_salmon/` | yes (`multiqc/star_salmon/multiqc_report_data/`) | **Selected.** 1568 files / 114 GB across `aligner_star_salmon/` and `aligner_star_rsem/`. MultiQC 1.33 writes `multiqc_report_data/` (not `multiqc_data/`): the template pins it with a literal scan regex and the catalog matches it on `find.path_glob_alt` `**/multiqc/*/*_data/multiqc.parquet`. 3.24.0 and 3.25.0 are complete; 3.23.0 and older predate the parquet or are truncated. |
| taxprofiler | 2.0.1 | `70ecc15e` | ok | `.` | yes (`multiqc/multiqc_data/`) | **Selected.** 680 files / 3.1 GB, MultiQC 1.34 with 16 modules plus raw profiler txt outputs. 2.0.0 is complete too; 1.2.x predate the parquet. |
| chipseq | 2.1.0 | `76e2382b` | empty | | no | 2.1.0 (29 files / 199 GB, 1 small) and 2.0.0 (9 files / 51 GB) are truncated syncs of BAMs. **Selected run is 1.2.0** (`048fd685`, 871 files / 79.7 GB, run root `bwa/mergedLibrary/...`), which wrote **MultiQC 1.9** (`multiqc/{broadPeak,narrowPeak}/multiqc_data/multiqc_data.json`, no parquet) and must be reprocessed with 1.35. 1.2.1 (`0f487ed7`) exists and is a complete structural twin of 1.2.0 (same 871 files, same sizes, same layout); the selection stays on 1.2.0. The run's design is not published: copy the vendored `input/sample_metadata.tsv` into `{DATA_ROOT}/input/` and ingest with `--var GENOME=hg19`. |
| sarek | 3.10.0 | `8ccac7ad` | ok | `test_full_germline_ncbench_agilent/` (also `test_full_germline_aws/`) | yes (`test_full_germline_ncbench_agilent/multiqc/multiqc_data/`) | **Selected (lot 2).** 563 files / 104 GB; somatic profiles absent from the megatest, so ASCAT / ControlFREEC / MSIsensor outputs do not exist. 3.9.0 complete; 3.8.x and older predate the parquet. |
| crisprseq | 2.3.0 | `0e9f915c` | ok | `.` | not seen | Not in this lot. Flat layout with thousands of per-sample files at the prefix root (listing capped at 3000 keys, no parquet among them); screening workflow never published. Every 2.0.0 to 2.2.1 prefix is empty. |
| scrnaseq | 4.2.0 | `3fc17b4f` | ok | `aligner_*/` (`cellranger`, `kallisto`, `simpleaf`, `star`) | yes (per aligner `multiqc/multiqc_data/`) | **Selected (lot 2), run root `aligner_cellranger/`.** 421 files / 137 GB; three of the four aligner roots carry a parquet (`aligner_star/` has no MultiQC). No marker-gene table is published. 2.x prefixes are empty or a single BAM. |
| smrnaseq | 2.4.1 | `cb0af579` | ok | `.` | yes (`multiqc/multiqc_data/`) | **Templated (wave 3).** 163 files / 1.6 GB. The template reads the mirtop joined table, the miRDeep2 `result_*.csv` at the run root and the MultiQC 1.33 parquet; no mature / hairpin count matrices and no edgeR tables are published. Every older prefix (2.2.3 to 2.4.0) is empty. |
| oncoanalyser | 3.0.0 | `7c74c87a` | ok | `HCC1395/` (sample-named) | none (no MultiQC) | Not in this lot. 604 files / 272 GB; 2.3.0 and 2.2.0 complete, 2.1.0 and older empty. |
| methylseq | 4.2.0 | `5aa56467` | empty | | no | 5 intermediates (3 BAM, 2 `txt.gz`, 37.6 GB) and nine restart `params_*.json`; 4.0.0 empty, 3.0.0 truncated (9 BAMs / 92 GB). **Selected run is 2.3.0** (`93bc5811`, 2022, 1283 files, run root `bismark/`, pre-parquet MultiQC reprocessed with 1.35). `PRESEQ_LCEXTRAP` FAILED for 6 of the 7 samples in this run (only `SRR7961103` completed), so no Preseq collection is built into the template. The `results-<sha>-bismark-CPU` / `-ARM` / `-GPU` benchmark prefixes hold at most 5 data objects and are invisible to the resolver (bare 40-hex sha required). The run's design is not published: copy the vendored `input/sample_metadata.tsv` into `{DATA_ROOT}/input/`. |
| atacseq | 2.1.2 | `1a1dbe52` | empty | | no | 2.1.2 and 2.1.1 hold a single 12 GB object each. Last complete run is 1.2.2 (2022, 488 files, pre-parquet). |
| cutandrun | 3.2.2 | `6e1125d4` | empty | | no | 3.2.2, 3.2.1 and 3.2 hold directory markers only. Last complete run is 3.1 (2023, 415 files, pre-parquet). |
| quantms | 1.2.0 | `fa34d79f` | empty | | no | Markers for `mode_dia/`, `mode_lfq/`, `mode_tmt/` and nothing else. Last complete run is 1.1.1 (2023, 224 files). |
| bacass | 2.6.1 | `5ed7c2dd` | missing | | | No prefix for 2.6.1 and every older prefix (2.1.0 to 2.5.0) is empty: no usable megatest at all. |
| raredisease | 3.1.2 | `83f2699d` | empty | | no | Every release prefix (2.2.0 to 3.1.2) holds `pipeline_info/` only. |
| mag | 5.5.0 | `56abab5b` | partial | `.` | no | The tagged run crashed after read QC (52 objects). **Selected run is the 5.5.0 release candidate `171cf369`** (15,494 objects, same three CAPES samples, CheckM2 + GTDB-Tk + QUAST + Prokka + contig depths, no `multiqc/`, reprocessed with 1.35). The 5.4.2 prefix `5dabb015` (7554 keys, 987 non-zero objects) is a truncated sync that dropped every object under about 8 MB: the run produced the bin QC and taxonomy tables (its MultiQC `report_data_sources` lists them) but only the large FASTA / GenBank / COMEBin objects survived, which is why the first template looked "thin by construction". 5.2.0 and 5.3.0 empty. |
| phyloplace | 2.1.0 | `441e351e` | missing | | | 2.0.1 (`3e37f9d7`) is complete and small (25 files / 14.8 MB, parquet present but the MultiQC report carries no module data). 2.0.0 empty. |
| nanoseq | 3.1.0 | `6e563e54` | empty | | no | Two zero-sized data objects. **Selected run is 3.0.0** (`1e60482a`, 2022, 205 files / 17 GB, pre-parquet MultiQC under `multiqc/minimap2/multiqc_data/`, reprocessed with 1.35). The run's design is not published: copy the vendored `input/sample_metadata.tsv` into `{DATA_ROOT}/input/`. |
| eager | 2.5.3 | `cc66639a` | empty | | no | 2.5.0 to 2.5.3 hold `pipeline_info/` only. **Selected run is 2.4.5** (`42c9d5f8`, 302 files / 16.3 GB, DSL1, `multiqc/multiqc_data/multiqc_data.json` only, reprocessed with 1.35). 2.4.4 is a byte-identical twin of 2.4.5. |
| hic | 2.1.0 | `fe4ac656` | empty | | no | 2.1.0 is a truncated sync: two 14.6 GB BAMs and one 19.7 GB `allValidPairs`, every other directory (including `multiqc/`) a zero-byte marker. **Selected run is 2.0.0** (`b4d89cfa`, 144 files / 59.7 GB, `multiqc/multiqc_data/mqc_*.txt`, reprocessed with 1.35). 1.3.0 (`ac74763a`) is complete but tiny (35 files / 54 MB). |
| scdownstream | (dev) | `8e13eabb` | empty | | no | **No usable megatest at all.** The only prefix (`results-8e13eabb…`, 2024-08-01, not a release sha) holds six `pipeline_info/` files and nine zero-byte directory markers (`adata/`, `celda/`, `celltypes/`, `doublet/`, `integration/`, `qc/`, `scanpy/`, ...). Dropped from lot 2 until a run is published. |
| riboseq | 2.0.0 | `11d66a3b` | ok | `.` | yes (`multiqc/star/multiqc_report_data/`) | **Templated (wave 3).** About 150 GB in full; the tables-only fetch is 206 files / 104 MB. MultiQC 1.33. The samplesheet, contrasts and a derived design table are not published and are vendored under `input/`. |
| genomeassembler | 2.0.0 | `a72d47d9` | partial | `.` | no | **Templated (wave 3).** 961 GB / 45.8k objects, 42k of them BUSCO internals. LINKS failed on one sample (exit 255) and 22 tasks were aborted, so only 5 of 10 samples reached assembly QC. No MultiQC. Selective fetch about 8.6 MB. A cluster re-run with LINKS errors ignored is submitted. |
| mhcquant | 3.2.0 | `6ec12c97` | ok | `.` | yes (`multiqc/multiqc_data/`) | **Templated (wave 3).** `test_full` profile. MultiQC 1.33 parquet with mhcquant custom content only. 71 MB of tables fetched with `--max-file-mb 300`; the samplesheet is not published and is vendored under `input/`. |
| demultiplex | 1.8.0 | `daade37c` | ok | `.` | yes (`multiqc/multiqc_data/`) | **Templated (wave 3).** bcl2fastq route; 183 files / 34.6 MB without the FASTQ. The run-level `multiqcsav/` report holds no SAV sections (the MultiQC `sav` module found no `RunInfo.xml` next to `InterOp/`). |
| rnasplice | 1.0.4 | `1d0494ae` | partial | `.` | no | **Pending.** 494 objects, only 80 with data (95.9 GB, mostly alignments); no MultiQC and none of the differential splicing directories. The template waits for an EMBL cluster `test_full` run. |
| seqinspector | 1.1.2 | `6aa08aab` | ok | `.` | yes (`multiqc/global_report/multiqc_data/`, plus one per group under `multiqc/group_reports/`) | Fallback for rnasplice if its cluster run fails twice. 1899 objects / 678 MB, every data file under 50 MB. |

## Selected runs for this lot

The nine pipelines added in this lot, with the run each template is validated
against. `resolve` verifies the prefix; `fetch` mirrors the manifest subset
below the run root into `~/Data/depictio-nfcore/<pipeline>/<version>/megatest/`.

Two of them are pinned to an **older release than the latest**, because every
recent release of theirs published an empty or truncated prefix. `resolve` reports
that and prints the fallback table the pin was chosen from, so the mismatch is
deliberate and visible rather than silent.

| pipeline | version | results_sha | run_root | MultiQC |
|---|---|---|---|---|
| differentialabundance | 2.0.0 | `30ed7741fc392127156c2fb10cfa3d69d216b54b` | `.` (outputs under `tables/<paramset>/`) | none by design |
| funcscan | 4.0.0 | `aee3dc965eb0c77267435544dda30da858763913` | `.` | 1.34, general stats empty |
| airrflow | 5.1.0 | `e69d49e3f23f11a3391755b5fb7aa4283c0a2471` | `.` | 1.34 |
| rnafusion | 4.1.3 | `76ad76e7c39b2ba9edc35aa3602e3dc454d842ec` | `.` | 1.33 |
| rnaseq | 3.26.0 | `e7ca46272c8f9d5ceee3f71759f4ba551d3217a4` | `aligner_star_salmon/` | 1.33 at `multiqc/star_salmon/multiqc_report_data/` |
| taxprofiler | 2.0.1 | `70ecc15e49b4f1fcf79d876643b5d14b65c66178` | `.` | 1.34 |
| chipseq | 1.2.0 | `048fd6854fcc85b355c61dfc2e21da0bcc6399ea` | `.` (`bwa/mergedLibrary/...`) | 1.9, reprocessed with 1.35 |
| atacseq | 1.2.2 | `f327c86324427c64716be09c98634ae0bc8165f6` | `.` (`bwa/mergedLibrary/...`) | none, reprocessed with 1.35; raw inputs under `multiqc/broadPeak/multiqc_data/` |
| cutandrun | 3.1 | `42502fb44975e930eec865353c5481f472bcf766` | `.` (numbered stage dirs) | none, reprocessed with 1.35 |

## Selected runs for lot 2

The seven pipelines added in lot 2 (2026-09-16). Four of them are pinned to an
older release than the latest for the same reason as above; scdownstream was
dropped because the bucket holds no run for it.

| pipeline | version | results_sha | run_root | MultiQC |
|---|---|---|---|---|
| sarek | 3.10.0 | `8ccac7ad37b05dd792447763bf9671b719824587` | `test_full_germline_ncbench_agilent/` | 1.35 native parquet |
| scrnaseq | 4.2.0 | `3fc17b4f971a89e47c88337de71d0e777ffad8cc` | `aligner_cellranger/` | 1.34 native parquet |
| mag | 5.5.0 (release candidate) | `171cf36971499cea4c9bccac4536cccbfc540e14` | `.` | none published, reprocessed with 1.35 |
| nanoseq | 3.0.0 | `1e60482a2c4621234393a6eef8e9a104309c20ae` | `.` | pre-parquet (`multiqc/minimap2/multiqc_data/`), reprocessed with 1.35 |
| eager | 2.4.5 | `42c9d5f8602e5e88fdcec28f194d2cd4cff61c75` | `.` | pre-parquet, reprocessed with 1.35 |
| methylseq | 2.3.0 | `93bc5811603c287c766a0ff7e03b5b41f4483895` | `bismark/` | pre-parquet, reprocessed with 1.35 |
| hic | 2.0.0 | `b4d89cfacf97a5835fba804887cf0fc7e0449e8d` | `.` | pre-parquet (`mqc_*.txt`), reprocessed with 1.35 |

### 2026-09-22 remediation wave

What changed in the manifests and pins during the lot 1 + lot 2 remediation:

- **mag re-pinned to the 5.5.0 release candidate** `171cf36971499cea4c9bccac4536cccbfc540e14`
  (not a tag sha: `manifest.version = '5.5.0'`, "chore: update full test resources", four
  days before the tag). 15,494 objects, same three CAPES samples as 5.4.2, and the report
  tables the 5.4.2 sync dropped (CheckM2, GTDB-Tk, QUAST, Prokka, contig depths). No
  `multiqc/` published: reprocessed with 1.35. The template moved to `mag/5.5.0`; 673 files /
  65 MB fetched. `resolve` warns about the non-tag sha and keeps the pin.
- **sarek** now fetches its VCFs: 196 files / 104.3 MB (was 185 / about 60 MB); the useful
  per-sample x caller `*.filtered.vcf.gz` / `*.variants.vcf.gz` and `*_snpEff.ann.vcf.gz`
  (20 files, 44 MB), gVCFs and VEP duplicates still excluded. Both FreeBayes
  `variant_calling/` VCFs are 196-byte symlink-target files on S3, not gzip (SK-D7).
  Manta's VCFs are real (57 and 72 SV records), contrary to an earlier reading.
- **differentialabundance**: GSEA report tables are not in the pinned prefix `30ed7741`
  (its parameter-set directory is only *named* `deseq2_rnaseq_gsea,deseq2_rnaseq_gprofiler2`;
  it publishes no `tables/gsea/` or `tables/gprofiler2/`). They come from the sibling prefix
  `47e3d923bbf2311ace0b9dea12d756287798275e`; the fetch command is in the template's
  megatest.yaml. No prefix of this pipeline publishes gprofiler2 TSVs (`3dd360fe` crashed
  with `pipeline_info/` only).
- **taxprofiler** megatest.yaml header said "12 profiler x database combinations"; the run
  has 20 declared and 18 written.
- **cutandrun 3.1** (`42502fb4`): 18 collections, 5 tabs, ingested clean on 2026-09-22.
- methylseq, nanoseq, eager, hic, scrnaseq: manifests unchanged; what changed is what the
  templates read from them (see each `VALIDATION_REPORT.md`).

### 2026-09-23 wave 2b (locus sections, new kinds, header controls)

Twelve template passes ran in parallel on the lot 2 stack (`PORT_OFFSET 112`) after
the wave 2a platform work (switchable views, `record_card`, `parallel_coordinates`,
region links, `indexed_file` tracks, `controls_placement: header`, slider histograms).
The stack was taken down before the last live checks, so every pipeline below has a
live pass still to run; see each `VALIDATION_REPORT.md` dated section for the exact
commands.

What changed in the manifests and mirrors:

- **sarek 3.10.0**: `megatest.yaml` gains the 10 `annotation/*/*/*_snpEff.ann.vcf.gz.tbi`
  keys. Eight SNV / indel annotated VCFs plus their index feed the `indexed_file`
  collection `snpeff_vcf_files` (Manta and TIDDIT excluded, `max_file_size_mb: 32`), read
  by the browser through presigned range requests.
- **cutandrun 3.1**: four `*.frags.cut.bed` (168 MB) fetched; the mirror is now about
  250 MB / 108 files. They feed the new catalog output `seacr/frags_profile` (fragment
  pile-up around the kept regions).
- **airrflow 5.1.0**: `clonal_analysis/repertoire_analysis/repertoire_analysis_report/repertoires/All_samples__repertoire-pass.tsv`
  (308 MB) fetched for the CDR3 spectratype and V-J usage recipes. The per-sample
  `vdj_annotation/*_db-pass.tsv` (860 MB) carry the same data and were not fetched.
- Every other manifest is unchanged; what changed is what the templates read.

What each template gained (ingest state at the moment the stack went down):

| pipeline | wave 2b content | live state on 2026-09-23 |
|---|---|---|
| sarek 3.10.0 | Cohort QC locus section on TP53 (`chr17:7,400,000-8,000,000`): mosdepth window navigator, per-target coverage, per-caller calls, range-read VCF track; mutation spectra; callset QC parallel coordinates; VAF density; rainfall manhattan; variant record card | first ingest validated live (34 DCs, 4 somatic optional skipped); locus columns then renamed to `chrom` / `pos`, re-ingest pending |
| scrnaseq 4.2.0 | marker violin per cluster, gene record card (FCER1A), cluster QC parallel coordinates, group comparison opening on C1 vs C2, header controls, slider histograms | dashboard re-imported in place, validated live |
| mag 5.5.0 | MIMAG quadrants, contig coverage density, per-assembly Nx curve, assembly by sample recruitment heatmap, bin record card | re-ingested (`lot2-mag`), 2 of 7 tab screenshots |
| nanoseq 3.0.0 | Nx ladder per library, DESeq2 volcano with MA and QQ views, DEXSeq QQ view and transcript usage bars | re-ingested, validated live |
| eager 2.4.5 | Coverage locus section (Qualimap depth navigator, MAPQ track through a region link, `NC_044048.1` whole contig), library QC parallel coordinates, endogenous DNA vs clonality | ingested as `lot2-eager-w2b` beside the old `lot2-eager`; three later YAML edits not re-imported |
| methylseq 2.3.0 | Global methylome locus section on NKX2-1 (`chr14:35,500,000-37,500,000`): group-difference navigator, per-library binned lanes, manhattan; QC parallel coordinates; per-context M-bias panels; volcano / QQ switch | two earlier layouts validated live; final layout (navigator moved to the group-compare DC) pending re-ingest |
| hic 2.0.0 | Contact maps tab as locus section on HoxD (`chr2:65,000,000-85,000,000`): TAD navigator, multi-resolution triangle (500 kb + 1 Mb partitions, 875,318 rows), insulation and E1 tracks through region links; P(s) with derivative | ingested twice, Contact maps validated live; TADs tab default region added after the last ingest |
| chipseq 1.2.0 | Locus tab on TFF1 (`chr21:43,600,000-44,000,000`, hg19), summit-centred profiles (new catalog output `macs2/summit_profile`), FRiP per sample, one volcano tile with MA and QQ views | re-ingested, default region validated live; brush walk and full-height screenshots pending |
| atacseq 1.2.2 | Peak locus tab on HIST1 (`chr6:26,000,000-26,300,000`, hg19), FRiP and peak-count bars, one volcano / MA / QQ tile | re-ingested, region links validated live through the cards; screenshots pending |
| cutandrun 3.1 | Peak calls locus section (`chr9:130,850,000-131,350,000`): SEACR navigator, fragment pile-up, MACS2 and consensus tracks; fragment pile-up metagene; samtools flagstat duplication | ingested 22/22; final YAML (navigator without assembly, pile-up moved to Signal) not ingested; first import hit the stale catalog cache (section 13 of `TEMPLATE_BOTTLENECKS.md`) |
| funcscan 4.0.0 | BGC map keeps `genome_view` only, header controls, histograms on 17 sliders | re-ingested 18/18, validated live; two tab screenshots pending |
| taxprofiler 2.0.1 | Krona-style rings per classifier, header controls, histograms on 11 sliders | re-ingested 14/14, validated live |
| airrflow 5.1.0 | CDR3 spectratype, V by J pairing heatmap, native diversity ribbon profile | re-ingested 14/14 under the template name, validated live |
| rnaseq 3.26.0 | MultiQC general-stats parallel coordinates, mean-variance plane with a gene record card (HBG2) | ingested 8/8, top-of-tab screenshots only |
| differentialabundance 2.0.0 | volcano / MA switch, QQ view, p-value histogram per contrast, record card per contrast (Uchl1) | ingested 8/8, top-of-tab screenshots only |

`test_no_double_track_binding` is enforced since this wave: no shipped template binds
`coverage_track` and `genome_view` on one collection in one tab any more.

### 2026-09-23 wave 3 (five new templates, family reworks)

Five pipelines were templated from their AWS megatest, all at their latest release, so none
needs a fallback pin. Their design is not published by the pipeline and is vendored next to
each template under `input/`, then passed as `METADATA_FILE`. None was ingested live in this
wave: each `VALIDATION_REPORT.md` records an offline validation (recipes on the real files,
template lint, CLI dry run 8/8).

| pipeline | version | results_sha | run_root | MultiQC |
|---|---|---|---|---|
| riboseq | 2.0.0 | `11d66a3b8ae1f41f9c385af36bd431c35bf015ab` | `.` | 1.33 at `multiqc/star/multiqc_report_data/` |
| smrnaseq | 2.4.1 | `cb0af579b24cb8d5a3accd87b2f14ea93fe04832` | `.` | 1.33 |
| genomeassembler | 2.0.0 | `a72d47d9cdb50f21b97882dfb2abf4af8f4c74ad` | `.` | none published; the template declares no MultiQC collection |
| mhcquant | 3.2.0 | `6ec12c97f7889a3e1f09ab89930723045c6bac68` | `.` | 1.33, custom content only |
| demultiplex | 1.8.0 | `daade37c4a75a4c1709ccf12434deb3424141319` | `.` | 1.35 native parquet |

rnasplice 1.0.4 is **pending**: its megatest prefix `1d0494ae` holds 494 objects of which only
80 carry data, with no MultiQC and no differential splicing output, so the template waits for an
EMBL cluster `test_full` run. If that run fails twice, seqinspector 1.1.2 (`6aa08aab`, complete,
five MultiQC parquets) takes its place. With rnasplice, the shipped set reaches 25 templates;
24 are built today.

What changed in the manifests of the reworked templates:

- **`forbidden_terms`** in every `megatest.yaml`: the run's sample ids, organism, assembly and
  counts, which `test_template_conventions.py` keeps out of every dashboard text. viralrecon has
  no manifest, so its texts are checked by hand.
- **Design copies.** methylseq, chipseq and nanoseq no longer read their design from the sample
  names: each design table is vendored as `input/sample_metadata.tsv` and must be copied into
  `{DATA_ROOT}/input/` and passed as `METADATA_FILE` before the ingest, like smrnaseq, riboseq and
  mhcquant.
  demultiplex reads its vendored `input/library_metadata.tsv` straight from the template
  directory.
- **`GENOME`.** chipseq and atacseq were aligned to hg19, which is not the template default
  (hg38): their megatest commands pass `--var GENOME=hg19`, and `reference.vars` sets it for
  the bundled reference. hic sets `GENOME: mm10` the same way.
- **sarek** no longer ships a copy of the megatest samplesheet: the sample hub is built from
  the `csv/` files the pipeline publishes.
- **genomeassembler** fetches a flagstat file that no collection reads; left in the manifest
  for now.

## How to use

```bash
# Which run backs a release? Prints prefix, tag, sha, object counts, parquet path.
python scripts/nfcore_megatest.py resolve --pipeline ampliseq --version 2.18.0
python scripts/nfcore_megatest.py resolve --pipeline rnaseq --version latest --run-root aligner_star_salmon
# Exit code 3 plus a table of the newest real runs when the release's run is empty or missing:
python scripts/nfcore_megatest.py resolve --pipeline methylseq --version 4.2.0

# Explore a run before writing its manifest.
python scripts/nfcore_megatest.py ls --pipeline taxprofiler --version 2.0.1 --top-dirs
python scripts/nfcore_megatest.py ls --pipeline rnaseq --version 3.26.0 --ext tsv parquet --grep 'salmon' --sizes
python scripts/nfcore_megatest.py ls --pipeline chipseq --results-hash 048fd6854fcc85b355c61dfc2e21da0bcc6399ea --prefix multiqc

# Fetch the manifest subset (megatest.yaml next to the template); --dry-run plans only.
python scripts/nfcore_megatest.py fetch --pipeline ampliseq --version 2.18.0 --dry-run
python scripts/nfcore_megatest.py fetch --pipeline ampliseq --version 2.18.0 --dest ~/Data/depictio-nfcore/ampliseq/2.18.0/megatest
python scripts/nfcore_megatest.py fetch --pipeline rnaseq --version 3.26.0 --key 'star_salmon/salmon.merged.*.tsv'
```

`fetch` renames timestamped provenance files (`pipeline_info/params_*.json` to
`params.json`, `*software*versions*.yml` to `software_versions.yml`, newest
wins), keeps files whose size already matches, refuses objects above
`--max-file-mb` (500) and mirrors `prefix_keys` (files outside a nested run
root) into the same destination. The release index is cached for 6 hours under
`~/.cache/depictio-nfcore/`; `--index FILE` or `$NFCORE_PIPELINES_JSON` point
at a local copy.

## Known gaps

These are gaps in what the **bucket publishes**. The gaps in **Depictio itself** that
this lot exposed (recipe provenance, `dc_ref` ordering, catalog loading, the MultiQC
version gate, seeding, missing visualisation kinds) are in
[`TEMPLATE_BOTTLENECKS.md`](TEMPLATE_BOTTLENECKS.md).

- **Empty release prefixes** (failed runs or truncated syncs, to report to
  nf-core): methylseq 4.2.0 / 4.0.0 / 3.0.0, chipseq 2.1.0 / 2.0.0, atacseq
  2.1.1 / 2.1.2, cutandrun 3.2 / 3.2.1 / 3.2.2, quantms 1.2.0, bacass 2.1.0 to
  2.5.0, raredisease (every release), nanoseq 3.1.0, rnafusion 4.1.1,
  variantbenchmarking 1.3.0 and 1.4.0, differentialabundance 1.2.0 to 1.5.0,
  funcscan 2.x / 3.0.0, smrnaseq 2.2.3 to 2.4.0, scrnaseq 2.x, crisprseq 2.0.0 to
  2.2.1, taxprofiler 1.2.2 / 1.2.4, airrflow 4.1.0 / 4.2.0, oncoanalyser 1.0.0 to
  2.1.0, mag 5.2.0 / 5.3.0.
- **Missing runs** (no prefix for the release sha): airrflow 5.1.1, phyloplace
  2.1.0, bacass 2.6.1. viralrecon 3.0.0 has a prefix but no MultiQC parquet.
- **Partial runs**: mag 5.5.0 tag run `56abab5b` (crashed after read QC; the 5.5.0 release candidate `171cf369` is complete and is the pin),
  viralrecon 3.0.0 (nanopore layout only), phyloplace 2.0.1 (parquet without
  module data), sarek (germline only, somatic profiles never run), genomeassembler
  2.0.0 (one failed task aborted the assembly QC of half the samples), rnasplice 1.0.4
  (alignments and quantification only, no MultiQC, no splicing results).
- **Reports without their sections**: demultiplex 1.8.0 publishes a `multiqcsav/` report
  whose SAV module found no `RunInfo.xml`, and InterOp only as binaries, so the run-level
  sequencer metrics have no table to read.
- **Nested run roots**: rnaseq `aligner_star_salmon/` (and `aligner_star_rsem/`),
  scrnaseq `aligner_{cellranger,kallisto,simpleaf,star}/`, sarek
  `test_full_germline_ncbench_agilent/` and `test_full_germline_aws/`,
  oncoanalyser `HCC1395/`, differentialabundance `tables/<paramset>/` with commas
  in directory names (URLs must be quoted; `fetch` does). The manifest `run_root`
  plus `prefix_keys` (for `pipeline_info/` outside the root) cover these.
- **MultiQC layout and version variance**: rnaseq writes
  `multiqc/star_salmon/multiqc_report_data/multiqc.parquet`, which no shipped
  scan regex or catalog `**/multiqc/multiqc_data/multiqc.parquet` glob matches;
  chipseq 1.2.x wrote MultiQC 1.9 (JSON only) and needs a 1.35 reprocess; funcscan
  1.34 and phyloplace ship parquets with empty general-stats or module tables;
  runs span MultiQC 1.31 to 1.35 and are read by a 1.35 reader with no version
  gate in code (the scan regex is the only gate, see the Conventions block in
  `VALIDATION_SCENARIOS.md`).
- **Defective objects inside otherwise complete runs**: the mag 5.4.2 sync
  (`5dabb015`) dropped every object under about 8 MB (987 non-zero objects, smallest
  8.4 MB; `Taxonomy/`, `GenomeBinning/QC/` and `QC_shortreads/` exist as zero-byte
  markers although the run's own MultiQC `report_data_sources` lists QUAST x1283 bins,
  Prokka x1279 and CheckM2), and sarek's two FreeBayes `variant_calling/` VCFs are
  196-byte symlink targets. A complete-looking listing is not a complete run; check the
  size floor and a few small objects before pinning. Both are worth an nf-core issue
  (5.4.2 re-sync; 5.5.0 tagged megatest crashed at 52 objects and was never re-run).
- **Bucket behaviour**: intermittent 503 SlowDown answers (every request here is
  retried with backoff), listings of the big runs run to tens of thousands of keys
  (rnaseq, crisprseq, funcscan), and the same release can be re-synced with a
  different `LastModified`, so pins are by `results_sha`, never by recency.
- **variantbenchmarking**: the shipped 1.4.0 template pins the 1.5.0 run because
  the 1.4.0 release's own run is a truncated sync; `fetch` warns about the
  release mismatch and keeps the pin.
- **An empty latest release does not mean the pipeline is untemplatable.** atacseq
  and cutandrun both publish nothing usable on every recent release, but atacseq
  1.2.2 (488 objects) and cutandrun 3.1 (415 objects) are complete runs, so both
  are templated against those. `resolve` exits 3 and prints the fallback table
  precisely so an older usable run can be found instead of the pipeline being
  written off. Worth re-checking the other `empty` rows above the same way.
