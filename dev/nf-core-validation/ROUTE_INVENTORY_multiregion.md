# Route inventory — nf-core/ampliseq 2.16.0 **multiregion / SIDLE**

Divergent sub-workflow inventory for scoping route-overlay DCs. **Inventory + proposal only — no DCs/recipes/dashboards are authored here.**

- **Route trigger** (from `pipeline_info/params*.json`): `multiregion` set to a regions URL **and** `sidle_ref_taxonomy` set (e.g. `greengenes88`). Standard runs have `multiregion: None`. Introspection does **not** yet emit a flag for this — a new `IS_MULTIREGION`/`SIDLE` flag would be added in `depictio/cli/cli/utils/templates.py:_introspect_pipeline_params`.
- **Sample data**: `~/Data/ampliseq/validation-runs-2.16.0/run_multiregion/` — 3 samples (`set1,set2,set3`), `treatment` metadata, 5 primer regions, greengenes88 reference. SIDLE reconstructs one cross-region feature table from per-region ASVs.
- **Why it fails loud today**: `skip_qiime=False` + metadata present → the template keeps all standard QIIME2 DCs **required**, but the SIDLE route does **not** produce `qiime2/diversity/`, `qiime2/phylogenetic_tree/`, `qiime2/ancombc/`, or a clean `rel_abundance_tables`. Result: `4 processed, 9 failed` → exit 1. Failing DCs include `taxonomy_rel_abundance`, `ancombc_results`, `ma_canonical`, `bray_curtis_canonical`, `phylogenetic_tree_metadata_canonical`, `upset_canonical`. **Layout difference is structural**: the reconstructed community lives under `sidle/`, and `qiime2/` carries only a *subset* (barplot, rel_abundance_tables, ancom, abundance_tables) — no diversity/phylogeny.
- Inventory produced by `depictio/projects/nf-core/inventory_route.py` (298 files total).

Comparison baseline = the in-scope ampliseq DCs in `depictio/projects/nf-core/ampliseq/2.16.0/template.yaml`.

---

## Candidate data files (dashboard-worthy)

### `sidle/reconstructed/` — the route's core payload (cross-region reconstructed community)

| glob | fmt | rows×cols | columns | note |
|---|---|---|---|---|
| `sidle/reconstructed/reconstructed_merged.tsv` | tsv | 9×5 | `ID, Taxon, set1, set2, set3` | **Primary dashboard source.** Reconstructed feature × sample count table **with taxonomy** in one file. `ID` = reconstructed feature (may be `a|b` merged), `Taxon` = `k__…; p__…; …` lineage, `set*` = per-sample counts. This is the SIDLE analog of the standard `qiime2/barplot` composition. |
| `sidle/reconstructed/reconstructed_taxonomy.tsv` | tsv | 9×2 | `ID, Taxon` | **Dashboard-worthy (lookup).** Feature→taxonomy mapping; subset of `reconstructed_merged.tsv` (use the merged file if counts are needed too). |
| `sidle/reconstructed/reconstructed_feature-table.tsv` | tsv | 10×1 | header munged: `# Constructed from biom file` | Biom-exported counts; **header is biom boilerplate** (real header on line 2). `reconstructed_merged.tsv` is the clean equivalent — prefer it. |
| `sidle/reconstructed/reconstructed_feature-table.biom` | biom (binary) | — | — | **Noise** for depictio (binary; the `.tsv`/merged are the tabular sources). |
| `sidle/reconstructed/reconstruction_table/{feature,sample}-frequency-detail.csv` | csv | 9×2 / 3×2 | `"" , 0` (unlabeled index + value) | Per-feature / per-sample frequency totals (QIIME2 viz export). **Low priority** — derivable from `reconstructed_merged.tsv`. |
| `sidle/reconstructed/reconstruction_table/{feature,sample}-frequencies.{pdf,png}` | pdf/png | — | — | **Noise** — rendered figures. |

Sample (`reconstructed_merged.tsv`):
```
ID              Taxon                                    set1  set2  set3
173921          k__Bacteria; p__Firmicutes; c__Clostr…   328   326   327
183870|336012   k__Bacteria; p__Bacteroidetes; c__Bac…   986   975   981
```

### `sidle/DB/3_reconstructed/` — reconstruction quality

| glob | fmt | rows×cols | columns | note |
|---|---|---|---|---|
| `sidle/DB/3_reconstructed/reconstruction_summary/metadata.tsv` | tsv | 18×6 | `feature-id, num-regions, total-kmers-mapped, mean-kmer-per-region, stdv-kmer-per-region, mapped-asvs` | **Dashboard-worthy (route-specific QC).** Per-reconstructed-feature confidence: how many of the 5 regions mapped, kmer support. **Row 1 is a QIIME2 `#q2:types` type-declaration row** that must be skipped on read. |

Sample (skipping the `#q2:types` row): `feature-id=173921, num-regions=3, total-kmers-mapped=3, mean-kmer-per-region=1, mapped-asvs=ad73af2a…`.

### `sidle/per_region/` — per-region detail (pre-reconstruction)

| glob | fmt | rows×cols | columns | note |
|---|---|---|---|---|
| `sidle/per_region/ASV_table_region*.tsv` | tsv | ~7–10×4 | `ASV_ID, set1, set2, set3` | Per-region ASV × sample counts (5 files, one per primer region; region encoded in filename: `region1_TGGCGAACGGGTGAGTAA_CCGTGTCTCAGTCCCARTG`). **Medium value** — useful for a per-region coverage/contribution view; needs the region parsed from the filename. |
| `sidle/per_region/DADA2_table_region*.tsv` | tsv | ~7–10×5 | `ASV_ID, set1, set2, set3, sequence` | Same as above + ASV `sequence`. **Noise-ish** — the `sequence` column is not dashboard-useful; prefer `ASV_table_region*`. |
| `sidle/per_region/ASV_seqs_region*.fasta` | fasta | — | — | **Noise** — sequences. |

### `qiime2/` subset present in this route

| glob | fmt | rows×cols | columns | note |
|---|---|---|---|---|
| `qiime2/barplot/level-{1..7}.csv` | csv | 3×(2–9) | `index, <taxon columns>, treatment, name` | **Dashboard-worthy (and same as standard 16S).** Standard QIIME2 barplot per taxonomic level; `index` = sample, one column per taxon, plus `treatment`/`name` metadata. The existing `taxonomy_composition`/`taxonomy_rel_abundance`/`taxonomy_heatmap` recipes already target `qiime2/barplot` + `rel_abundance_tables` — these **could ingest** for multiregion (they were only dragged down by sibling required DCs failing). |
| `qiime2/rel_abundance_tables/rel-table-{2,3,ASV}.tsv` | tsv | 3–10×1 | header munged: `# Constructed from biom file` | Relative-abundance tables, **biom-boilerplate header** (real header line 2) → needs `skip_rows=1`. Standard 16S runs read these too. |
| `qiime2/ancom/Category-treatment-level-{2,3}/data.tsv` | tsv | 2–4×3 | `id, clr, W` | **Dashboard-worthy (differential abundance) — but different schema.** This route runs **ANCOM** (W statistic + CLR), *not* **ANCOM-BC** (lfc/q_val/se/w slices) that the template's `ancombc_results` expects. Not drop-in compatible. |
| `qiime2/ancom/Category-treatment-level-*/percent-abundances.tsv` | tsv | 3–5×11 | `Percentile,0.0,25.0,50.0,75.0,100.0,…` | Per-taxon abundance percentiles for the ANCOM volcano. **Low priority.** |
| `qiime2/abundance_tables/count_table_filter_stats.tsv` | tsv | 0×6 (empty in test) | `sample,input_tax_filter,filtered_tax_filter,lost,retained_percent,lost_percent` | Taxonomy-filtering QC. **Low priority** (empty here; verify on real data). |

### NOT produced by this route (why the standard template fails)
`qiime2/diversity/` (alpha/beta vectors, PCoA), `qiime2/phylogenetic_tree/tree.nwk`, `qiime2/alpha-rarefaction/`, `qiime2/ancombc/` (ANCOM-BC slices) — **all absent**. The required `alpha_rarefaction`, `taxonomy_rel_abundance` (biom-header), `ancombc_results`, and the `phylogenetic_tree*` / `bray_curtis` / `ma` canonicals therefore fail.

### Excluded as provenance/noise
`*.qza`, `*.biom`, `dada2/*`, `fastqc/*`, `cutadapt/*`, `*/q2templateassets/*`, `*/css|js|fonts|img|licenses/*`, `*.rds`, `*.svg`, `*.html`, `barplot/dist/*`, `pipeline_info/*`, `.nextflow*/`, `work/`.

---

## Proposed route DCs (multiregion / SIDLE)

Reuse ampliseq tag/column conventions where possible; the gating route flag would be a new `IS_MULTIREGION` (or presence of `sidle/`). "Adapt" = existing recipe + glob/skip-rows override; "New" = SIDLE-specific.

| Proposed tag | Glob | Format | Key columns | Recipe |
|---|---|---|---|---|
| `sidle_reconstructed` | `sidle/reconstructed/reconstructed_merged.tsv` | TSV | `ID, Taxon, set1, set2, set3` (samples vary) | **New** — the route's primary table. After a melt (`sample,count,Taxon`) it maps onto the existing `taxonomy_composition` schema (`sample,taxonomy,count`); a thin recipe can emit the canonical composition shape and reuse the **downstream** stacked-bar / sunburst / sankey / complex-heatmap canonicals. |
| `sidle_taxonomy` | `sidle/reconstructed/reconstructed_taxonomy.tsv` | TSV | `ID, Taxon` | **New (lookup)** — only needed if a feature→lineage join is kept separate from `sidle_reconstructed`. |
| `sidle_reconstruction_qc` | `sidle/DB/3_reconstructed/reconstruction_summary/metadata.tsv` | TSV | `feature-id, num-regions, total-kmers-mapped, mean-kmer-per-region, mapped-asvs` | **New** — route-specific reconstruction confidence (cards/table). Recipe must `skip_rows` the `#q2:types` row. No ampliseq equivalent. |
| `sidle_per_region_asv` | `sidle/per_region/ASV_table_region*.tsv` | TSV | `ASV_ID, set1, set2, set3` + `region` (from filename) | **New (optional)** — per-region contribution view; region parsed from filename. Nice-to-have. |
| `taxonomy_composition` *(reused)* | `qiime2/barplot/level-*.csv` | CSV | `index(sample), <taxa>, treatment, name` | **Adapt** — the existing `depictio/catalog/qiime2/taxonomy_composition.py` already targets `qiime2/barplot`; present in this route. Lift `required→optional` (or route-gate) so it survives. |
| `taxonomy_rel_abundance` *(reused)* | `qiime2/rel_abundance_tables/rel-table-2.tsv` | TSV | (biom header) | **Adapt** — existing recipe, but confirm it handles the `# Constructed from biom file` boilerplate header (`skip_rows=1`). Present in this route. |
| `ancom_results` | `qiime2/ancom/Category-{GROUP_COL}-level-2/data.tsv` | TSV | `id, clr, W` | **New** — distinct from `ancombc_results` (ANCOM vs ANCOM-BC). If a differential-abundance view is wanted for this route, model ANCOM separately (`W`/`clr`, no `lfc`/`q_val`); the existing `ancombc`/`ma_canonical` recipes are **not** reusable. |

**What to drop/gate for the route**: `alpha_rarefaction`, `ancombc_results`, `ma_canonical`, `bray_curtis_canonical`, `phylogenetic_tree_canonical`, `phylogenetic_tree_metadata_canonical` — none of their inputs (`qiime2/diversity`, `tree.nwk`, ANCOM-BC slices) exist on the SIDLE route, so a `multiregion` conditional should `remove_dc_tags` these (mirroring the existing `SKIP_QIIME` block in `template.yaml:58-66`).

**Recommendation**: the route's signature value is `sidle_reconstructed` (composition) + `sidle_reconstruction_qc` (a genuinely new, SIDLE-specific quality table). Both the QIIME2 barplot/rel-abundance DCs can be **reused as-is** once a `multiregion` conditional prunes the diversity/phylogeny/ANCOM-BC DCs that this sub-workflow never produces — making this primarily a *pruning + two new DCs* effort rather than a full re-model.
