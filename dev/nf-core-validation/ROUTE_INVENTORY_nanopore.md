# Route inventory — nf-core/viralrecon 3.0.0 **nanopore / ARTIC**

Divergent sub-workflow inventory for scoping route-overlay DCs. **Inventory + proposal only — no DCs/recipes/dashboards are authored here.**

- **Route trigger** (from `pipeline_info/params*.json`): `platform == "nanopore"` (+ `primer_set == "artic"`). Introspection already sets `IS_NANOPORE=true` (`depictio/cli/cli/utils/templates.py:474`), but no conditional/route consumes it yet.
- **Sample data**: `~/Data/viralrecon/validation-runs-3.0.0/run_nanopore/` — 9 SARS-CoV-2 samples (`SAMPLE_01`..`SAMPLE_09`, no `08`), ref `MN908947.3`, 98 ARTIC `nCoV-2019_*` amplicons.
- **Why it fails loud today**: the illumina template's **required** `summary_metrics` recipe (`depictio/catalog/multiqc/summary_metrics.py`) reads the MultiQC parquet expecting ivar/bowtie2 columns absent from a nanopore run → `1 processed, 1 failed (summary_metrics)` → exit 1. All ivar/mosdepth-genome DCs are `optional`, so they prune cleanly; the single required recipe is the loud-failure point. **Layout difference is structural**: variants/consensus/coverage live under `artic_minion/` (clair3 + ARTIC), not `variants/ivar` + top-level `mosdepth/`.
- Inventory produced by `depictio/projects/nf-core/inventory_route.py` (620 files total).

Comparison baseline = the in-scope illumina DCs in `depictio/projects/nf-core/viralrecon/3.0.0/template.yaml`.

---

## Candidate data files (dashboard-worthy)

### Coverage — `artic_minion/mosdepth/` (drop-in: same schema, only the path differs)

| glob | fmt | rows×cols | columns | note |
|---|---|---|---|---|
| `artic_minion/mosdepth/amplicon/all_samples.mosdepth.coverage.tsv` | tsv | 784×6 | `chrom,start,end,region,coverage,sample` | **Dashboard-worthy.** Identical schema to illumina `mosdepth_amplicon_coverage` (which globs `variants/bowtie2/mosdepth/amplicon/...`). Per-amplicon coverage, long form. |
| `artic_minion/mosdepth/genome/all_samples.mosdepth.coverage.tsv` | tsv | 1200×5 | `chrom,start,end,coverage,sample` | **Dashboard-worthy.** Identical schema to illumina `mosdepth_genome_coverage`. 200 bp windows. |
| `artic_minion/mosdepth/amplicon/all_samples.mosdepth.heatmap.tsv` | tsv | 8×99 | `sample, nCoV-2019_1 … nCoV-2019_98` (log10 cov) | **Dashboard-worthy.** Identical schema to illumina `mosdepth_amplicon_heatmap`; feeds `complex_heatmap_canonical`. |
| `artic_minion/mosdepth/{amplicon,genome}/*.mosdepth.coverage.tsv` | tsv | per-sample | same cols | Redundant per-sample split of the `all_samples` files above — **noise** (use the aggregated files). |
| `artic_minion/mosdepth/*/*.mosdepth.summary.txt` | tsv | 4×6 | `chrom,length,bases,mean,min,max` | Per-sample mosdepth summary; covered by MultiQC — **low priority**. |

Sample (`all_samples.mosdepth.amplicon.coverage.tsv`):
```
chrom        start  end  region        coverage  sample
MN908947.3   30     410  nCoV-2019_1   30        SAMPLE_01
MN908947.3   320    726  nCoV-2019_2   31        SAMPLE_01
```

### Lineage / clade — `artic_minion/{pangolin,nextclade}/` (per-sample; one file per sample)

| glob | fmt | rows×cols | columns | note |
|---|---|---|---|---|
| `artic_minion/pangolin/*.pangolin.csv` | csv | 1×16 | `taxon,lineage,conflict,ambiguity_score,scorpio_call,scorpio_support,scorpio_conflict,scorpio_notes,version,pangolin_version,scorpio_version,constellation_version,is_designated,qc_status,qc_notes,note` | **Dashboard-worthy.** Same Pangolin schema as illumina `pangolin_lineages`; only difference is one file **per sample** (illumina aggregates under `variants/ivar/consensus/bcftools/pangolin/`). `taxon` encodes the sample (`SAMPLE_01/MN908947.3/ARTIC/clair3 …`) → sample id must be parsed from filename or `taxon`. |
| `artic_minion/nextclade/*.csv` | csv (**`;`-delimited**) | 1×~90 | `index;seqName;clade;Nextclade_pango;qc.overallScore;qc.overallStatus;totalSubstitutions;totalDeletions;totalInsertions;totalFrameShifts;totalMissing;totalNonACGTNs;alignmentScore;coverage;…` | **Dashboard-worthy.** Maps to illumina `nextclade_results` columns, but **semicolon-separated** and per-sample. Recipe must set `separator=";"` and rename `qc.overallStatus→qc_overallStatus` etc. |

Sample (`pangolin/SAMPLE_01.pangolin.csv`): `taxon=SAMPLE_01/MN908947.3/ARTIC/clair3…, lineage=B, conflict=0.5, qc_status=pass`.

### Variants — `artic_minion/freyja/variants/`, `artic_minion/snpeff/`

| glob | fmt | rows×cols | columns | note |
|---|---|---|---|---|
| `artic_minion/freyja/variants/*.variants.tsv` | tsv | ~5k×20 | `REGION,POS,REF,ALT,REF_DP,REF_RV,REF_QUAL,ALT_DP,ALT_RV,ALT_QUAL,ALT_FREQ,TOTAL_DP,PVAL,PASS,GFF_FEATURE,REF_CODON,REF_AA,ALT_CODON,ALT_AA,POS_AA` | **Dashboard-worthy (raw).** Per-sample ivar-style variant calls. Analog of illumina `variants_long`, but **unannotated** (no `GENE`/`EFFECT`/`AA` from snpEff merge) — `GFF_FEATURE`/`*_AA` are mostly `NA`. New recipe needed (different schema than the annotated `variants_long_table.csv`). |
| `artic_minion/snpeff/*.snpsift.txt` | tsv | 0×26 (empty in test) | `CHROM,POS,REF,ALT,ANN[*].GENE,ANN[*].IMPACT,ANN[*].EFFECT,…,EFF[*].EFFECT,EFF[*].FUNCLASS,EFF[*].AA` | **Dashboard-worthy (the real annotated-variant source).** This is the ARTIC analog of illumina's annotated `variants_long`. **Empty in the test dataset** (0 rows) — verify on a real run before modelling. |
| `artic_minion/*.{merged,pass,fail,primers,normalised,pass.unique}.vcf[.gz]` (+`.tbi`) | vcf/gzip | — | — | **Noise** — raw/intermediate VCFs; the `.variants.tsv`/`.snpsift.txt` are the tabular sources. |
| `artic_minion/freyja/demix/*.tsv` | tsv | 5×2 | (transposed: row labels + `<sample>.variants.tsv`) | Freyja lineage-abundance deconvolution (wastewater/mixed). **Niche** — awkward transposed layout; skip for a first overlay. |
| `artic_minion/freyja/variants/*.depth.tsv` | tsv | 29902×4 | `MN908947.3,1,A,0` (headerless per-base depth) | **Noise** — per-base depth, headerless; mosdepth files cover coverage better. |

### Consensus assembly QC — `artic_minion/quast/`

| glob | fmt | rows×cols | columns | note |
|---|---|---|---|---|
| `artic_minion/quast/transposed_report.tsv` | tsv | 8×56 | `Assembly,# contigs,Largest contig,Total length,Reference length,GC (%),N50,…,Genome fraction (%),Duplication ratio,# N's per 100 kbp,# mismatches per 100 kbp,# indels per 100 kbp,…` | **Dashboard-worthy.** One row per sample (`Assembly=SAMPLE_01.consensus`). Best per-sample consensus-quality table for the route — `Genome fraction (%)`, `# N's per 100 kbp`, `N50` are the headline metrics. No illumina equivalent DC (illumina surfaces QUAST only via MultiQC). |
| `artic_minion/quast/report.tsv` | tsv | 55×9 | `Assembly, SAMPLE_01.consensus … SAMPLE_09.consensus` | Same data, **wide/transposed** (metrics as rows). Prefer `transposed_report.tsv`. |
| `artic_minion/quast/report.{html,pdf,tex,txt}`, `quast/{aligned,basic,contigs,genome}_stats/*`, `icarus_viewers/*` | html/pdf/… | — | — | **Noise** — rendered reports + intermediates. |

Sample (`transposed_report.tsv`): `Assembly=SAMPLE_01.consensus, Total length=29903, GC (%)=38.03, N50=29903, Genome fraction (%)=82.039, # N's per 100 kbp=17961.41`.

### Nanopore read QC — `nanoplot/`, `pycoqc/` (route-specific; no illumina analog)

| glob | fmt | note |
|---|---|---|
| `nanoplot/*/NanoStats.txt` | text (key:value) | **Dashboard-worthy (route-specific).** Per-sample nanopore read-length/quality stats (mean read length, N50, median quality, #reads). Not CSV/TSV — needs a small key:value parser. One dir per sample. |
| `nanoplot/*/*.html` | html | **Noise** — interactive plots (length-vs-quality, histograms). |
| `pycoqc/pycoqc.json` | json | **Dashboard-worthy (route-level).** Run-level basecalling/QC summary (per-barcode read counts, quality). Single file. |
| `pycoqc/pycoqc.html` | html | **Noise** — rendered report. |

### MultiQC (shared)

| glob | fmt | note |
|---|---|---|
| `multiqc/multiqc_data/multiqc.parquet` | parquet | **Present** and the existing `multiqc_data` DC glob matches — but the nanopore module set differs (no `ivar`/`bowtie2`; has nanopore tools). The MultiQC DC ingests, but the downstream **required** `summary_metrics` recipe is what fails. A nanopore route needs its own summary recipe (or to relax `summary_metrics` to optional + add a nanopore variant). |

### Excluded as provenance/noise (not data sources)
`*.consensus.fasta`, `artic_minion/bcftools_stats/*.txt`, `artic_minion/samtools_stats/*.{stats,flagstat,idxstats}`, `artic_minion/snpeff/*.{csv,genes.txt,summary.html,vcf.gz}`, `*.bam`, `pipeline_info/*`, `.nextflow*/`, `work/`.

---

## Proposed route DCs (nanopore / ARTIC)

Reuse illumina tag/column conventions wherever the schema matches; the gating route flag would be `IS_NANOPORE` (already introspected). "Adapt" = existing catalog recipe + a route-specific glob/separator override; "New" = no existing recipe fits.

| Proposed tag | Glob | Format | Key columns | Recipe |
|---|---|---|---|---|
| `mosdepth_amplicon_coverage` *(route override)* | `artic_minion/mosdepth/amplicon/all_samples.mosdepth.coverage.tsv` | TSV | `chrom,start,end,region,coverage,sample` | **Adapt** (no recipe — direct scan; only the glob changes vs illumina). Reuse the existing tag. |
| `mosdepth_genome_coverage` *(route override)* | `artic_minion/mosdepth/genome/all_samples.mosdepth.coverage.tsv` | TSV | `chrom,start,end,coverage,sample` | **Adapt** — glob-only change. |
| `mosdepth_amplicon_heatmap` *(route override)* | `artic_minion/mosdepth/amplicon/all_samples.mosdepth.heatmap.tsv` | TSV | `sample, nCoV-2019_*` | **Adapt** — glob-only change; still feeds `complex_heatmap_canonical`. |
| `pangolin_lineages` *(route override)* | `artic_minion/pangolin/*.pangolin.csv` | CSV (per-sample) | `lineage,conflict,scorpio_call,qc_status` + `sample` (from filename/`taxon`) | **Adapt** `depictio/catalog/pangolin/pangolin_lineages.py` — same schema, new glob + sample-from-filename parse (illumina derives sample similarly). |
| `nextclade_results` *(route override)* | `artic_minion/nextclade/*.csv` | CSV **`;`-sep** (per-sample) | `clade,Nextclade_pango,totalSubstitutions,totalMissing,coverage,qc_overallStatus` | **Adapt** `depictio/catalog/nextclade/nextclade_results.py` — add `separator=";"`, dotted→underscore rename, new glob. |
| `summary_metrics` *(route variant)* | derive from `artic_minion/mosdepth/*/summary` + `pangolin` + `quast/transposed_report.tsv` | CSV | `sample,coverage_median,pct_genome_covered_*,lineage,…` | **New** recipe — nanopore MultiQC lacks the ivar/bowtie2 columns the illumina `summary_metrics` reads. This is the DC to make `optional` (or route-gate) so the route stops failing loud. |
| `consensus_quast` | `artic_minion/quast/transposed_report.tsv` | TSV | `Assembly(sample),Genome fraction (%),# N's per 100 kbp,N50,Total length` | **New** — no illumina equivalent; high value as a per-sample consensus-quality table/cards. |
| `artic_variants_long` | `artic_minion/snpeff/*.snpsift.txt` (annotated) **or** `freyja/variants/*.variants.tsv` (raw) | TSV (per-sample) | snpsift: `CHROM,POS,REF,ALT,ANN[*].GENE,EFF[*].EFFECT,EFF[*].FUNCLASS`; raw: `REGION,POS,REF,ALT,ALT_FREQ,TOTAL_DP,PASS` | **New** — ARTIC analog of `variants_long`. Prefer snpsift (annotated) to keep gene/effect columns aligned with illumina `variants_long`, but it is **empty in the test data** — confirm on a real run; fall back to the raw `freyja/variants` tsv for AF/depth. |
| `nanoplot_read_stats` | `nanoplot/*/NanoStats.txt` | key:value text → table | `sample,mean_read_length,read_n50,median_quality,n_reads` | **New** — route-specific read QC; needs a key:value parser. Nice-to-have. |

**Downstream canonical DCs**: `complex_heatmap_canonical` (← `mosdepth_amplicon_heatmap`), `coverage_track_canonical` (← `mosdepth_genome_coverage`), and `sankey_canonical` (← `pangolin_lineages` + `nextclade_results`) all work unchanged once their upstream route-override DCs above are populated. `oncoplot_canonical`/`upset_canonical`/`variant_feature_matrix_canonical` depend on an annotated `variants_long`-equivalent — only viable if `artic_variants_long` (snpsift) is non-empty on real data.

**Recommendation**: the cheapest correctness fix is the three mosdepth glob overrides + pangolin/nextclade recipe adaptations + making `summary_metrics` route-gated. `consensus_quast` and `nanoplot_read_stats` are the two genuinely new, high-value nanopore tables worth a dedicated DC.
