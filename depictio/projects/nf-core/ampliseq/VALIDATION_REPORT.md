# nf-core/ampliseq 2.16.0 — Template Ingestion Validation Report

**Date:** 2026-06-15
**Branch:** `chore/amplicon-viralrecon-validation`
**Validator:** local depictio-cli (`depictio/cli/.venv`, v1.0.1) against the local docker stack
(instance `chore-amplicon-viralrecon-validation-100`, API `:8100`, MinIO `:9100`, Mongo `:27100`).

## Goal

Drive `depictio-cli run --template nf-core/ampliseq/2.16.0` against **real** nf-core/ampliseq
pipeline output (not the curated AWS-megatest seed bundle) across several scenarios, and find every
place the template's path / format / variable assumptions break against real output.

## Data used

| Scenario | DATA_ROOT | Notes |
|----------|-----------|-------|
| S0 | `depictio/projects/nf-core/ampliseq/2.16.0/` (bundled) | Seed bundle — **not ingestable** (see D6) |
| S1 | `~/Data/depictio-nfcore/ampliseq/2.16.0/run_16s_pe` | Complete `test` profile run, with metadata |
| S2 | same as S1, **no** `METADATA_FILE` | Exercises `if_var_absent` conditional removal |
| S3 | `~/Data/depictio-nfcore/ampliseq/2.16.0/run_16s_multi` | **Incomplete** run (dada2/fastqc only) |

Invocation that got furthest (S1):
```bash
depictio-cli run --CLI-config-path ~/.depictio/CLI.<instance>.yaml \
  --template nf-core/ampliseq/2.16.0 --data-root <run_16s_pe> \
  --var SAMPLESHEET_FILE=<run>/input/Samplesheet.tsv \
  --var METADATA_FILE=<run>/input/Metadata.tsv \
  --var GROUP_COL=treatment1 --overwrite --update-config
```

## S1 result: 14 / 20 data collections processed

**Processed OK (14):** multiqc_data, samplesheet*, metadata*, alpha_rarefaction,
taxonomy_composition, taxonomy_rel_abundance, taxonomy_heatmap, ancombc_results, embedding_pcoa,
complex_heatmap_canonical, upset_canonical, ma_canonical, bray_curtis_canonical,
phylogenetic_tree_canonical.
*`samplesheet` and `metadata` "succeed" but are silently broken — see D3/D4.*

**Failed (6):** stacked_taxonomy_canonical, rarefaction_canonical, alpha_diversity_multi_canonical,
sunburst_canonical, sankey_canonical, phylogenetic_tree_metadata_canonical — see D6/D7.

---

## Discrepancies

### D1 — Phylogenetic-tree path has a phantom `data/` prefix  ✅ FIXED
- **Template:** `{DATA_ROOT}/data/qiime2/phylogenetic_tree/tree.nwk` (`template.yaml`, phylo tree DC).
- **Real output:** `{DATA_ROOT}/qiime2/phylogenetic_tree/tree.nwk` (no `data/`).
- **Effect:** hard-fails *all* of config validation (ScanSingle existence check) before any DC processes.
- **Fix applied:** dropped the `data/` prefix in `template.yaml`. The prefix was an artifact of how the
  seed bundle was restructured; real nf-core output has no `data/`.

### D2 — `SAMPLESHEET_FILE` is `required` but its only default is dead config  ✅ FIXED
- `reference.vars` in the template (`SAMPLESHEET_FILE`, `METADATA_FILE`, `GROUP_COL` defaults) is
  **never read** — `resolve_template()` (`depictio/cli/cli/utils/templates.py:427`) builds vars only
  from `DATA_ROOT` + `--var`, and `reference` isn't even a field on `TemplateMetadata`
  (`depictio/models/models/templates.py:87`), so it's silently dropped.
- **Effect:** every invocation without `--var SAMPLESHEET_FILE=…` fails with
  *"Missing required template variables: SAMPLESHEET_FILE"*. The `/import-template` examples that pass
  only `--data-root` (+ `GROUP_COL`) would all fail. Viralrecon, by contrast, requires only `DATA_ROOT`
  and embeds paths via `{DATA_ROOT}` directly.
- **Recommended fix:** either embed the samplesheet path via `{DATA_ROOT}/input/…` (like the phylo DC)
  and make `SAMPLESHEET_FILE` optional, or delete the misleading `reference.vars` block. Needs the
  separator decision in D3 to be resolved together.

### D3 — Samplesheet format hardcoded `CSV`; real output is TSV  →  silent corruption  ✅ FIXED
- DC declares `format: "CSV"`; real `run_16s_pe/input/Samplesheet.tsv` is tab-separated.
- The reader only switches to a tab separator when `format == "tsv"`
  (`depictio/cli/cli/utils/deltatables.py:159`); there is **no** extension-based auto-detection.
- **Effect:** the entire tab-joined header is ingested as a **single column**
  `'sampleID\tforwardReads\treverseReads\tquant_reading'`. The `sampleID` column referenced by Link 1
  / Link 6 does not exist → samplesheet→multiqc and samplesheet→taxonomy_heatmap filters silently
  no-op. No error raised.
- Megatest seed uses `samplesheet.csv` (real comma-CSV), test profile uses `Samplesheet.tsv` — the
  format is genuinely dataset-dependent, so a single hardcoded value can't serve both.
- **Recommended fix (design decision):** auto-detect the separator from file extension for single-file
  Table scans, or expose a `SAMPLESHEET_FORMAT` var.

### D4 — Metadata join column is `sample` in the template, `ID` in real output  →  broken links  ✅ FIXED
- Template `metadata` DC + **all 15 metadata links** use `source_column: "sample"`; the megatest seed
  `Metadata_full.tsv` has a `sample` column. Real `run_16s_pe/input/Metadata.tsv` has `ID`
  (+ `treatment1`, `mix8`, `badpairwise10`, … — the standard nf-core test metadata).
- The template's own header comment says required column **"ID"**, while `columns_description` and the
  links say **"sample"** — internally inconsistent.
- **Effect:** metadata ingests (14 cols) but every metadata→* link matches nothing — the funnel
  filtering that the dashboards depend on is silently dead on real data.
- **Recommended fix (design decision):** standardise on the nf-core convention (`ID`), or parameterise
  the join column (`METADATA_ID_COL`, default `sample`) and substitute it into the 15 link
  `source_column` values.

### D5 — `GROUP_COL` reference default `habitat` doesn't exist in standard output
- Reference default `GROUP_COL: habitat`; ANCOMBC override paths use `Category-{GROUP_COL}-level-2/`.
- Real `test` profile only emits `Category-treatment1|mix8|badpairwise10-*`. Passing
  `--var GROUP_COL=treatment1` works; the default does not. (Workable, but the default and the
  `generate_validation_runs.sh` `detect_group_col()` — which reads `Metadata_full.tsv`, the wrong
  filename — both assume megatest naming.)

### D6 — 6 advanced-viz canonical DCs are not ingestable (undefined `dc_ref`s)  ✅ FIXED (skip)
- These recipes chain off upstream DCs **by tag** that the template never declares:
  - `stacked_taxonomy_canonical` → `rel_abundance_phylum/class/order/family/genus`
  - `rarefaction_canonical` → `alpha_rarefaction_shannon/observed_features/faith_pd`
  - `alpha_diversity_multi_canonical` → `alpha_diversity_shannon/observed_features/faith_pd/evenness`
  - `sunburst_canonical`, `sankey_canonical` → `rel_abundance_genus`
  - `phylogenetic_tree_metadata_canonical` → `qiime2_taxonomy`
- None of these intermediate DCs exist in `template.yaml`. The committed seed TSVs were produced by a
  **standalone script** (`generate_canonical_seeds.py`) that reads raw qiime2 files directly and calls
  each recipe's `transform()` with a hand-built source dict — bypassing the DC/`dc_ref` machinery
  entirely. So in production these DCs are populated **only** from committed `.db_seeds/*.json`, never
  by `depictio-cli run`.
- **Effect:** 6 DCs fail on every real ingestion with *"dc_ref '…' not found in workflow"*.
- **Recommended fix:** add the ~13 intermediate raw-file DCs to the template (taxonomy.tsv,
  `rel_abundance_tables/rel-table-{2..6}.tsv`, `alpha-rarefaction/*.csv`,
  `diversity/alpha_diversity/*_vector/*`), partially blocked by D7.

### D7 — Test data doesn't classify deep enough for sunburst/sankey
- `sunburst_canonical`/`sankey_canonical` need `rel_abundance_genus`, but `run_16s_pe` only has
  `rel-table-2/3/4` (phylum/class/order) — no `rel-table-5/6` (family/genus). Even with D6 fixed,
  these two cannot be satisfied on this dataset; they require a run whose taxonomy reaches genus.

### D8 — Recipe/runtime dependencies not declared  →  install required to proceed  ✅ FIXED
- `plotly` (imported by `depictio/catalog/qiime2/taxonomy_heatmap.py`) is **not** a declared CLI
  dependency; `multiqc` is an optional extra (`multiqc==1.35`) not installed in the venv by default.
- **Effect:** `multiqc_data` + `taxonomy_heatmap` (and everything that `dc_ref`s the heatmap) fail with
  `No module named 'multiqc' / 'plotly'`.
- **Worked around** by installing both into the CLI venv. **Recommended:** add `plotly` to CLI deps
  and document/ship the `multiqc` extra for template ingestion.

### D9 — Per-DC failures and validation aborts are reported as success (exit 0)  ✅ FIXED
- S1: 6 DCs failed yet the CLI printed *"completed successfully! (8/8 steps)"* and exited **0**.
- S3: config validation failed (missing tree.nwk), processing never ran, yet exit code was **0**.
- **Effect:** CI/automation cannot detect partial or total ingestion failure from the exit code.
- **Recommended fix:** return a non-zero exit when any DC fails to process or a step fails.

### D10 — `ma_canonical` not pruned when metadata absent  ✅ FIXED  (found in S2)
- With no `METADATA_FILE`, the conditional correctly removes `metadata`, `alpha_rarefaction`,
  `ancombc_results`. But `ma_canonical` (MA plot) `dc_ref`s the now-removed `ancombc_results` and so
  fails.
- **Fix applied:** added `ma_canonical` to the `if_var_absent: METADATA_FILE` `remove_dc_tags` list.
  Re-verified in S2 — `ma_canonical` is now pruned, no longer a failure.

### D11 — Non-optional phylo DC aborts partial runs  (found in S3)
- The phylo-tree DC uses `ScanSingle` with a hard existence check at config-validation time. Any run
  missing `tree.nwk` (incomplete run, `--skip_qiime`, no phylogeny) aborts the whole ingestion before
  processing the DCs that *are* present.
- **Note:** marking the DC `optional: true` does **not** help — the `ScanSingle` existence check is a
  Pydantic validator that fires during config validation, before optionality/file-scanning removal is
  considered (and that removal is disabled, per the TODO at `templates.py:523`). A real fix needs the
  existence check moved out of config validation, or the file-scanning DC removal re-enabled for
  optional DCs.

## Scenario outcomes

- **S0 (seed bundle):** not ingestable — `data/` contains only `phylogenetic_tree/`; raw qiime2 inputs
  the recipes need are absent. It is a seed bundle, not a run. (Reframes the plan's "baseline".)
- **S1 (run_16s_pe + metadata):** 14/20 DCs processed after D1/D8 fixes; samplesheet + metadata links
  silently broken (D3/D4); 6 canonical DCs fail (D6/D7).
- **S2 (no metadata):** ✅ conditional removal works; `ma_canonical` regresses (D10).
- **S3 (incomplete run):** fails loudly at validation with a clear message (D1-style existence check),
  but exit code 0 (D9) and aborts before any present DC (D11).

## Fixes applied in this pass (all re-verified by re-ingesting S1/S2/S3)

| ID | Fix | Where |
|----|-----|-------|
| D1 | Phylo tree path `data/` prefix removed | `template.yaml` |
| D2 | `SAMPLESHEET_FILE` made optional + auto-resolved from `{DATA_ROOT}/input/`; dead `reference.vars` block removed | `template.yaml`, `templates.py` (`resolve_template` step 3c) |
| D3 | Separator inferred from file extension for single-file Table scans (a `.tsv` no longer parses as one comma column) | `cli/utils/deltatables.py:read_single_file_lazy` |
| D4 | `METADATA_ID_COL` auto-detected from the metadata first column and substituted into the 15 metadata-link `source_column`s | `templates.py` (`_auto_detect_metadata_columns`), `template.yaml` |
| D6 | 6 seed-only canonical DCs marked `optional`; CLI now **skips** optional DCs whose inputs (missing `dc_ref`/file) are unavailable instead of hard-failing | `template.yaml`, `cli/utils/process.py` |
| D8 | `plotly` declared as a CLI dependency | `cli/pyproject.toml` (+ `uv.lock`) |
| D9 | Run now exits **non-zero** on any DC/step failure (per-DC failures surfaced, early aborts and incomplete summary raise `typer.Exit(1)`) | `cli/commands/run.py`, `cli/utils/process.py` |
| D10 | `ma_canonical` added to the no-metadata `remove_dc_tags` | `template.yaml` |

## Not changed (deliberate)
- **D7** — test-data limitation: `run_16s_pe` only classifies to order level (no `rel-table-5/6`),
  so `sunburst`/`sankey`/`stacked_taxonomy` cannot be produced from it regardless. With D6 they now
  skip cleanly. Producing them needs a run whose taxonomy reaches genus **and** the intermediate-DC
  layer below.
- **D11** — incomplete runs (missing `tree.nwk`/`multiqc`) still fail at config validation. That is
  the *correct* loud behaviour for a genuinely incomplete run, and it now exits non-zero (D9). Not
  softened to a silent skip.

## To actually ingest the 6 canonical viz DCs at runtime (future work)
They were authored as seed-only (built by `generate_canonical_seeds.py`, loaded from `.db_seeds`).
Ingesting them via `depictio-cli run` would require adding ~10 intermediate raw-file DCs **before**
the canonical DCs (each `dc_ref` reads the upstream DC's processed Delta table):
`qiime2_taxonomy` (`taxonomy/taxonomy.tsv`), `rel_abundance_{phylum,class,order,family,genus}`
(`rel_abundance_tables/rel-table-{2..6}.tsv`, `skip_rows=1`),
`alpha_rarefaction_{shannon,observed_features,faith_pd}` (`alpha-rarefaction/*.csv`),
`alpha_diversity_{shannon,observed_features,faith_pd,evenness}`
(`diversity/alpha_diversity/*_vector/alpha-diversity.tsv`). Deferred: it adds significant DC clutter,
the recipe transforms would need to tolerate the extra Delta columns, and `family`/`genus` are
unavailable on the test data (D7).

## Final scenario status (after fixes)
- **S1** (metadata): 14 DCs processed, 6 skipped-optional, 0 failures, **exit 0**.
- **S2** (no metadata): 10 DCs processed (4 metadata-gated removed), 6 skipped-optional, **exit 0**.
- **S3** (incomplete): fails loudly at validation with a clear message, **exit 1**.

## Self-adapting dashboards (Layer 1 + Layer 2)

After the discrepancy fixes, two further layers make one template + one dashboard adapt to whatever
a run produced (instead of a dashboard full of red "Figure failed" boxes):

- **Layer 1 — import-time hiding** (`api/.../dashboards_endpoints/routes.py:_filter_unresolved_components`):
  a dashboard component bound to an absent DC (removed by a conditional) or to an *optional* Table DC
  that was skipped (no `deltatables` record) is dropped at import; a child tab left with no
  visualisation components is not created. **Gated**: a missing *non-optional* DC is kept (renders a
  visible error) — graceful hiding never masks a broken pipeline (verified: `run_iontorrent` without
  the SKIP_QIIME path exits 1, dashboard never imported).
- **Layer 2 — params.json introspection** (`cli/.../templates.py:_introspect_pipeline_params`):
  reads `pipeline_info/params*.json` and auto-fills `METADATA_FILE` (no more `--var` for metadata
  runs) and sets `SKIP_QIIME` for sintax/ITS runs. A new `if_var_present: SKIP_QIIME` conditional
  drops all QIIME2-derived DCs, so `run_iontorrent`/`run_its_pacbio` ingest their MultiQC + samplesheet
  cleanly (MultiQC-only dashboard) instead of hard-failing — while normal 16S runs keep those DCs
  required.

### Final 5-run matrix (self-adapting)
| Run | Exit | Outcome |
|-----|------|---------|
| `run_16s_pe` (16S + metadata) | 0 | full dashboard (14 DCs); metadata auto-detected, no `--var` |
| `run_16s_multi` (16S, no metadata, no tree) | 0 | Alpha-Diversity / Differential-Abundance / Phylogeny tabs hidden |
| `run_iontorrent` (ITS/IonTorrent, skip_qiime) | 0 | MultiQC-only (QIIME2 DCs removed via SKIP_QIIME) |
| `run_its_pacbio` (ITS/PacBio, skip_qiime) | 0 | MultiQC + metadata (QIIME2 DCs removed) |
| `run_multiregion` (16S SIDLE) | 1 | **out of scope** — SIDLE emits a different QIIME2 layout the recipes don't match; fails loud (needs dedicated SIDLE recipes) |

## Dashboard-review pass (2026-06-18)

Live review of each per-run dashboard, fixing rendering/layout rough edges surfaced in the dev stack.

### D-R1 — `group_col is not defined` in the relative-abundance bars (all metadata routes)  ✅ FIXED
The Community/Alpha figures used an `if group_col in df.columns: … else: …` block in code-mode. The
code-mode parser (`api/.../figure/code_mode.py`) is a **line classifier**: it strips indentation and
keeps only `fig = …`, `fig.…`, and `df_`/`df_modified` lines — it silently **drops** plain
assignments (`group_col = '{GROUP_COL}'`) and `if/else` control flow. The dropped assignment left
`df_mean = df.group_by([group_col, …])` referencing an undefined name → `name 'group_col' is not
defined` at execution (the reported error), independent of whether `{GROUP_COL}` was substituted.

**Fix:** rewrote the two rel-abundance bars + the alpha-diversity box plot to **flat, parser-safe**
code using a single-line ternary that synthesises a facet/group column and falls back when the group
column is absent:
```python
df_grp = df.with_columns(pl.col('{GROUP_COL}').alias('_facet')) if '{GROUP_COL}' in df.columns else df.with_columns(pl.lit('All samples').alias('_facet'))
df_modified = df_grp.group_by(['_facet', 'Phylum']).agg(...)
fig = px.bar(df_modified.to_pandas(), ..., facet_row='_facet', ...)
```
Verified through `SimpleCodeExecutor` with the group column present (faceted) and absent (single
"All samples" facet) — both succeed.

### D-R2 — placeholder leak + degenerate grouping on no-metadata runs (`run_16s_multi`)  ✅ FIXED
- `resolve_template` now always sets `GROUP_COL` (sentinel `__no_group__`) and `GROUP_COL_DISPLAY`
  (`Group`), so the `{GROUP_COL}` / `{GROUP_COL_DISPLAY}` placeholders never leak into seeded
  dashboards; the sentinel makes the ternary above fall to the ungrouped branch.
- `upset_canonical` is a taxa × `GROUP_COL` presence matrix — with no metadata it collapses to a
  single useless bar, so it is now pruned in the `if_var_absent: METADATA_FILE` conditional (it was
  already pruned for skip_qiime / multiregion).

### D-R3 — SIDLE "Reconstructed Community" tab had no filter  ✅ FIXED
Added a `Phylum` `MultiSelect` (bound to `sidle_reconstructed`) so the SIDLE tab has a real filter
to slice the reconstructed composition. (The `_tab_meets_minimum` rule keeps a tab when it has a
filter+viz **or** ≥2 visualisations, so the three-viz SIDLE tab would survive regardless — but a
route-signature tab deserves an actual filter.)

### D-R4 — self-adapting layout (shared engine, also benefits viralrecon)
- **`_recompact_main_grid`** re-packs the main grid after drops so no half-width card is left alone
  on a row (the "var1 groups card alone" / orphaned-MultiQC cases); React `widenLoneRows` mirrors it.
- **`_tab_meets_minimum`** enforces the mandatory minimum — every surviving tab keeps **≥1 filter
  AND ≥1 non-metadata visualisation**. To satisfy this on every route, tab filters are curated to
  bind to route-surviving DCs:
  - **Main MultiQC tab** sample filter → the always-present `multiqc_data` DC (options served from the
    ingested sample list via `GET /deltatables/unique_values`, which now handles MultiQC DCs); so
    no-metadata runs (16S-Multi, IonTorrent) keep a working sample filter.
  - **Ordination** gains a `Phylum` filter on `complex_heatmap_canonical` (non-metadata, present on
    every QIIME2 route) so it keeps a filter when the metadata-bound sample/group filters prune away.
  - **SIDLE** Phylum filter (above). Verified: across all 10 per-run projects, **every** tab (main +
    secondary) has ≥1 filter + ≥1 right-panel component.

### Answer: which tree feeds the Phylogeny tab (PE route)?
`phylogenetic_tree_canonical` scans `{DATA_ROOT}/qiime2/phylogenetic_tree/tree.nwk` — the QIIME2
ASV-level tree (MAFFT alignment → FastTree), tips = ASV identifiers, taxonomy joined via
`phylogenetic_tree_metadata_canonical` (`tree_metadata_canonical.py`).

### Still to verify live (needs the running stack + ingested data)
- `run_16s_multi` Ordination "tax heatmap failed to render" (`complex_heatmap_canonical`) — a
  render-time failure; repro against the ingested delta table and fix the data-shape/empty case.
