# Catalog — TODO / open work

Concise backlog for the bio-catalog. Current state: catalog core + guided-mode
preview (`catalog match`/`compose` + `software_versions.yml` scoping) are done
and on `claude/optimistic-mayer-iQrTO`. Direction v3 = module-granular,
pipeline-agnostic (see `docs/design/bioinformatics-catalog.md`).

## Free mode (UI) — DONE
- **The UI is no longer gated.** The advanced-viz builder ranks every kind by a
  graded backend fit score and presents a "suggest but tolerate" picker
  (Recommended + Other visualisations, nothing hidden/disabled); the user can
  pick any kind and bind columns by hand. Validation is tolerant — a castable
  dtype is a warning, not a blocker.
- The `ProjectDetailApp.tsx` `hasVizMatch` coords gating and the
  `AdvancedVizBuilder.tsx` producer-driven pre-selection are **removed**.

## Guided mode
- Wire `compose_run_dir()` into the real ingestion/scan path so it actually
  builds/proposes a dashboard (today it's a CLI preview only).
- `refresh-index`: the vendored `_index/{nf_core_modules,edam_terms}.txt` are
  **seeds**; run `depictio catalog refresh-index` (needs network) to make them
  authoritative so existence checks catch typos.

## Module-granular debt (v3)
- **Re-key `recipe` by module** — ✅ **done.** Module-owned reshapes now live
  in the catalog module folder (`depictio/catalog/<module>/<name>.py`) and are
  referenced `<module>/<name>.py`; the resolver (`depictio/recipes/__init__.py`)
  tries module-owned before the pipeline-keyed `projects/<pipeline>/recipes/`
  fallback. 9 reshapes moved (ivar/nextclade/pangolin/mosdepth×2/qiime2×4).
  Kept pipeline-keyed on purpose: `taxonomy_rel_abundance` (has a 2.14.0 version
  override) and the dashboard-composition recipes (sankey/upset/volcano/…) that
  are genuinely pipeline-specific. Templates + the seed-gen script were updated;
  `db_init` is unaffected (it converts recipe DCs → file-scan by `dc_tag`, never
  resolving the recipe file).
- **Re-key `find` by module** — still pipeline-coupled in template DCs; revisit
  with the scan wiring.
- Add typed **input schema** to recipes (`SOURCES`/`INPUT_SCHEMAS`) for input
  validation + fixture generation + nf-core drift detection (do this when
  wiring the scan). This is what lets one module own *N* reshape variants keyed
  by input shape, instead of duplicating a recipe per pipeline.

## Retire `suggest_producers` — DONE (backend + frontend)
- Column-fingerprint recognition was unreliable; `producers.py` +
  `suggest_producers` are **removed**. The React producer chips, the
  `producers` field/types, and the `/suggest-from-columns` endpoint are now
  **gone** too. `suggest_viz_kinds` (role/dtype based, now graded 0-1 scoring)
  is the single runtime suggestion engine; `/viz-suggestions` returns a ranked
  `viz_kinds` list with per-kind `score` + `role_candidates`.

## Render enrichment + preview
- `renders_as` now supports `figure` (UI `visu_type`/`dict_kwargs` **and** code
  mode `code`) + `card` (`column`/`aggregation`). `qiime2_alpha_diversity` is the
  flagship (code-mode multi-facet box + 3 metric cards). **TODO:** enrich the
  other entries with their figures/cards (ampliseq/viralrecon dashboards).
- **`fixture`** is now **co-located in the module folder** (`<output>.tsv` next
  to its YAML), pipeline-agnostic, committed with the catalog — each module is a
  self-contained unit (identity + outputs + fixtures).
  `catalog validate` grounds renders against them (Level-3); they also feed
  `preview`. A dedicated `catalog-ci` workflow + `depictio catalog validate` run
  on every catalog/recipe change.
- **`catalog preview <output>`** — **separate PR (owned by maintainer)**: load
  the `fixture` → build the component (advanced_viz / figure / card) → render the
  real viz. Reuses the component renderers + the figure code-mode executor
  (`simple_code_executor.execute_code(code, df)`). The `fixture` field is the
  contract this builds on.

## Catalog coverage of `use:` bindings (raise template adoption)
After templatising the ampliseq + viralrecon dashboards, the catalog covers the
advanced-viz tiles that bind a **tool output** (ivar variants → manhattan/
lollipop; qiime2 ancombc → volcano/da_barplot; qiime2 taxonomy →
stacked_taxonomy). The remaining tiles stay explicit (`viz_kind` + config); to
push more onto `use:`:
- **No catalog module for `sankey` / `embedding` / `upset_plot` / `phylogenetic`.**
  These are **dashboard figure-builders chained on derived `*_canonical` DCs**,
  not tool outputs — adding catalog modules for them is **dubious** (would blur
  the catalog = tool-output-adapter boundary). Decide deliberately before doing
  it; default is to leave them explicit.
- **Strict config models are narrower than the seeds.** Some tiles fall back to
  a stored dict because the authoring config (`extra="forbid"`) rejects rich
  display fields the seeds use — e.g. `RarefactionConfig` lacks `metric_options`,
  so `rarefaction` can't use `use: qiime2/rarefaction` without dropping it.
  Extending the relevant `*Config` models (add the missing display fields) would
  let those tiles bind via `use:` too.
- **Export `to_yaml()` is lossy for advanced_viz** (drops `viz_kind`/`config`),
  so an exported dashboard YAML can't be re-imported as-is — the ampliseq
  `base.yaml` had to be reconstructed from the `.db_seeds`. Fix the exporter to
  emit `viz_kind` + `config` (and collapse catalog-bindable tiles back to `use:`)
  for clean round-trips.

## Validation / CI hardening
- `match_run_dir` perf: single `os.walk` pass (currently one `rglob` per output)
  — only matters once the catalog/run grows.

## Authoring / AI helpers (nice-to-have)
- `catalog scaffold <nf-core-module>`: fetch the module `meta.yml` and emit a
  draft entry (identity + find + EDAM auto-filled; recipe/renders_as left TODO).
- `catalog suggest <recipe>`: from a recipe's output columns, propose viz + role
  bindings (reuses `suggest_viz_kinds`/`CANONICAL_SCHEMAS`) to help authors.
