# Catalog — TODO / open work

Concise backlog for the bio-catalog. Current state: catalog core + guided-mode
preview (`catalog match`/`compose` + `software_versions.yml` scoping) are done
and on `claude/optimistic-mayer-iQrTO`. Direction v3 = module-granular,
pipeline-agnostic (see `docs/design/bioinformatics-catalog.md`).

## Free mode (UI — frontend PR)
- **Do not gate the UI.** The user must always be able to map an advanced viz
  directly onto a file's columns (role → column) **by hand, with no condition**
  — even when nothing is recognised/suggested.
- Applies in **two places**: the **project data manager** and the
  **advanced viz section**.
- Suggestions may *pre-fill* the binding, but must never *block* manual mapping.
- Check/relax gating in `ProjectDetailApp.tsx` (`hasVizMatch`) and
  `AdvancedVizBuilder.tsx` (producer-driven pre-selection).

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

## Retire `suggest_producers` (frontend PR)
- Column-fingerprint recognition is unreliable; currently only de-scoped in
  docs. Actual removal touches the API (`/viz-suggestions`,
  `/suggest-from-columns`) + the React "suggested producer" chips. Keep
  `suggest_viz_kinds` (role/dtype based).

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

## Validation / CI hardening
- `match_run_dir` perf: single `os.walk` pass (currently one `rglob` per output)
  — only matters once the catalog/run grows.

## Authoring / AI helpers (nice-to-have)
- `catalog scaffold <nf-core-module>`: fetch the module `meta.yml` and emit a
  draft entry (identity + find + EDAM auto-filled; recipe/renders_as left TODO).
- `catalog suggest <recipe>`: from a recipe's output columns, propose viz + role
  bindings (reuses `suggest_viz_kinds`/`CANONICAL_SCHEMAS`) to help authors.
