# Bioinformatics tool → visualisation catalog

**Status:** Design proposal + landed prototype (phase 1)
**Branch:** `claude/optimistic-mayer-iQrTO`
**Audience:** maintainers, before the catalog grows past the seed entries.
**Related:** `docs/design/advanced-viz.md` (the viz family this maps *into*),
`depictio/recipes/__init__.py` (the transform engine this maps *through*).

---

## 1. Goal

Automatically associate the **output of a bioinformatics tool** with the
**depictio visualisation** that best renders it — like MultiQC, but (a) not
limited to QC, (b) driven by an **evolutive catalog the community can extend**,
and (c) able to cover tools that have **many running modes and many outputs**
(QIIME 2 being the stress test).

Concretely: a user ingests a file from `pangolin`, `mosdepth`, `DESeq2`,
`ANCOM-BC`, `MetaPhlAn`, a QIIME 2 artefact… and depictio should say *"this
looks like X — render it as a volcano / coverage track / stacked taxonomy / …"*,
pre-wire the column→role binding, and — when the raw file isn't already in the
right shape — know **what reshape (melt/pivot/aggregate/recipe)** gets it there.

---

## 2. What already exists (and what it's missing)

depictio already has the spine of this system. The mapping is real today; it's
just hand-maintained and blind to upstream tool identity.

| Layer | File | Role |
|---|---|---|
| **Viz contract** | `models/components/advanced_viz/schemas.py` → `CANONICAL_SCHEMAS` | Per-viz required **roles** → accepted dtypes (volcano, manhattan, oncoplot, stacked_taxonomy, sunburst, da_barplot, lollipop, rarefaction, complex_heatmap, embedding, …). The "beyond-QC" surface. |
| **Tool→viz registry** | `models/components/advanced_viz/producers.py` → `KNOWN_PRODUCERS` | ~25 `Producer`s. Each fingerprints a tool output by **column names**, declares `feeds_viz`, and a role→column `role_mapping`. |
| **Auto-mapping** | `schemas.py` → `suggest_producers()` / `suggest_viz_kinds()` | Reverse lookup from a DC's schema. Wired into the API (`/datacollections/suggest`, `/suggest-from-columns`) and the React DC card's "Suggested visualisations" chips. |
| **Reshape engine** | `recipes/__init__.py` + `projects/nf-core/*/recipes/*.py` | A 2-tier DAG: raw tool file → typed DC → canonical-schema DC. Each recipe declares `SOURCES` (glob/path/dc_ref), `EXPECTED_SCHEMA`, `transform()`. |

**The four gaps**, mapped to the asks:

1. **No upstream identity.** `Producer.tool` is free text. There's no link to
   the nf-core module, the `biotools:` id, or EDAM ontology terms — even though
   nf-core `meta.yml` *already publishes all three* per output channel. Without
   identity we can't auto-discover, dedupe, or reason semantically.
2. **Not community-extensible.** The catalog is a hardcoded Python tuple; its
   own header argues *against* a "package-manager" approach. Growing it
   currently means a Python PR by someone who knows the internals.
3. **No model for many-modes tools.** A `Producer` is a single (columns → viz)
   fact. QIIME 2 emits dozens of differently-shaped artefacts depending on the
   subcommand; the ampliseq recipes paper over this with hardcoded paths like
   `qiime2/ancombc/differentials/Category-habitat-level-2/lfc_slice.csv`.
4. **Reshape is implicit.** `suggest_producers` matches a *DC that already has
   the right columns*. The gap between "raw file on disk" and "bindable DC" —
   the melt/pivot/aggregate — lives only as prose in `Producer.notes` and as
   bespoke per-pipeline recipes. It is neither declared nor validated as part
   of the mapping.

---

## 3. Design: a declarative catalog layer over the producer registry

Add a **catalog** layer that sits *above* `producers.py` and *compiles down* to
it. The producer registry stays the runtime primitive; the catalog is the
authoring/extension surface that carries the things a bare producer can't.

```
 nf-core meta.yml ─┐                        ┌─ suggest_producers() ─→ API ─→ React "Suggested viz"
 bio.tools / EDAM ─┤  importer (offline)    │
                   ▼                        │
          depictio/catalog/*.yaml  ──compile──→  Producer  ──merge──→ all_producers()
          (community-extensible)     (entry_to_producers)      (curated wins)
                   │
                   └─ reshape: melt/pivot/aggregate/recipe ──→ recipes/  ──→ canonical DC ──→ advanced_viz
```

### 3.1 The data model (`models/components/advanced_viz/catalog.py`)

Structured like **MultiQC modules**: a single-output tool is one flat YAML file;
a multi-output tool is a folder with `module.yaml` + one file per output. A
`CatalogModule` owns many `CatalogOutput`s:

- **`CatalogModule`** — `id`, `name`, `homepage`, **`nf_core_module`**,
  **`biotools_id`**, **`edam_topics`**. Resolvable identity (`biotools_id` →
  `https://bio.tools/<id>`, `nf_core_module` → the nf-core/modules tree).
- **`CatalogOutput`** — one file in one running **`mode`**, carrying:
  - **`find`** (`CatalogFind`) — how depictio-cli *recognises* the file
    (`filename` / `path_glob` / `content_contains` / `required_columns`), the
    catalog analogue of MultiQC's `search_patterns`.
  - **`file_schema`** — the columns + dtypes the tool writes (raw, as-emitted).
  - **`reshape`** (`CatalogReshape`) — raw file → viz-ready shape (see §3.3).
  - `nf_core_module`/`biotools_id` overrides, `edam_*`, `pipelines` — provenance.
  - `feeds_viz` + `role_mapping` — viz affinity + pre-filled bindings.

`entry_to_producers()` compiles each output whose `find.required_columns` is set
to a `Producer`; `all_producers()` merges those with `KNOWN_PRODUCERS`, **curated
winning on any name collision** so the catalog can only *add* coverage, never
silently override a vetted fingerprint. `match_run_dir()` is the ingest-time
recognition step (`depictio catalog match <dir>`).

### 3.2 Many modes per tool (the QIIME 2 answer)

The crux of the brief. We model a heavyweight tool exactly the way the upstream
ecosystems already do:

- **nf-core** models a module as a set of named **output channels**.
- **bio.tools** models a tool as a set of **EDAM operations**, each consuming/
  producing EDAM data with an EDAM format.

So: **one `CatalogModule`, many `CatalogOutput`s, each tagged with its `mode`**.
The `depictio/catalog/qiime2/` folder carries `taxa-barplot`, `rel-abundance`,
`diversity`, `alpha-rarefaction`, `composition/ancombc`, and `phylogeny` as
independent output files — each with its own `find`, `file_schema`, reshape and
viz affinity. Adding QIIME 2's next mode is adding one file, not touching code.
This scales to the full QIIME 2 surface (and to any multi-subcommand tool:
bcftools, samtools, seqkit…) without the registry
becoming a wall of near-duplicate fingerprints.

`mode` + `edam_operations` are the disambiguators: two QIIME 2 outputs can share
a column shape but differ by mode, and the suggestion UI can group them under
the tool.

### 3.3 Reshape as a first-class, validated step

Real tool outputs rarely land in the long/wide shape a viz wants — they need a
melt, pivot, or aggregate first. The catalog makes that explicit:

```yaml
reshape:
  kind: melt              # identity | melt | pivot | aggregate | recipe
  id_vars: [clade_name, NCBI_tax_id]
  variable_name: sample_id
  value_name: abundance
```

`CatalogReshape` validates its own parameters (a `melt` needs `id_vars`; a
`pivot` needs `on` + `values`; an `aggregate` needs `group_by` + `agg`). For
transforms too complex to express declaratively, `kind: recipe` points at an
existing `projects/<pipeline>/recipes/<name>.py` — so the catalog *links* the
mapping to the recipe DAG instead of duplicating it. This directly answers the
"we may need to validate and ask for reformatting (pivot/melt/aggregate)
compared to the tool's raw output" requirement: the reshape is declared,
type-checked, and (for the declarative kinds) executable without bespoke code.

A consequence worth stating: **fingerprints describe the post-reshape /
post-read shape**. An output whose raw file isn't reliably fingerprintable
(QIIME 2's per-contrast ANCOM-BC slices; a wide barplot whose taxon columns vary
per run) sets `fingerprint: null` and relies on its `reshape.recipe` to produce
an already-known canonical shape. That's honest about where column-name matching
stops and a recipe must take over.

### 3.4 Upstream sync: vendored snapshots + offline importer

bio.tools/nf-core are **authoring-time** inputs, not a runtime dependency
(restricted networks must still work; this environment's allowlist already
blocks the bio.tools API). `meta_yml_to_entry()` turns a parsed nf-core module
`meta.yml` into a **draft** `CatalogEntry`: it infers tool identity, the
`biotools:` id, EDAM formats, and file patterns, and leaves `fingerprint` +
`feeds_viz` as TODOs (those genuinely can't be derived from module metadata).
`depictio catalog import-meta <meta.yml>` prints/writes the scaffold; the
committed catalog is then self-contained.

---

## 4. Community contribution workflow

Adding a tool (or a new mode of an existing tool) is a PR that adds/edits one
YAML file under `depictio/catalog/` — no Python:

1. `depictio catalog import-meta path/to/meta.yml -o depictio/catalog/<tool>.yaml`
   (or hand-write from `depictio/catalog/README.md`).
2. Fill in each output's `fingerprint.required_columns`, `reshape`, `feeds_viz`,
   `role_mapping`.
3. `depictio catalog validate` (CI-friendly; non-zero on schema violation).
4. Add a one-line assertion in `tests/models/test_catalog.py` (a column schema →
   expected producer) and open the PR.

CI runs `catalog validate` + the suggestion test, so a malformed or
viz-incompatible entry fails fast. The barrier is now "write a YAML file and a
one-line test", not "understand the producer registry's internals".

---

## 5. Prototype landed in this branch

Phase-1, additive and backward-compatible (existing producers and the
suggestion tests are untouched and still green):

- `models/components/advanced_viz/catalog.py` — the model, flat-file + folder
  loader, `find`-based `match_run_dir()`, `entry_to_producers`, and the offline
  `meta_yml_to_entry` importer.
- `models/components/advanced_viz/producers.py` — `all_producers()` merge
  accessor (curated wins); `get_producer()` now consults it.
- `models/components/advanced_viz/schemas.py` — `suggest_producers()` now spans
  curated **+** catalog producers.
- MultiQC-style modules: single-output tools as flat files (`pangolin`,
  `nextclade`, `ivar`, `metaphlan`, `multiqc`, `fastqc`) + multi-output folders
  (`qiime2/` with 6 outputs, `mosdepth/` with 3) covering the viralrecon +
  ampliseq tool surface.
- `depictio/catalog/catalog.schema.json` + `SCHEMA.md` + `README.md` — contract,
  field reference, contributor guide.
- `cli/cli/commands/catalog.py` — `depictio catalog list | info | validate | match | import-meta | schema`.
- `tests/models/test_catalog.py` — schema/reshape validation, merge semantics,
  end-to-end suggestion, importer round-trip.

---

## 6. Phased roadmap

- **Phase 1 (done):** model + loader + merge + 2 seed tools + importer + CLI +
  tests. Catalog producers flow into the existing suggestion surfaces with no
  frontend change.
- **Phase 2 — execute declarative reshapes.** Teach the recipe/ingest path to
  run `CatalogReshape` (melt/pivot/aggregate) directly, so a catalog entry with
  a declarative reshape needs *no* `.py` recipe. Validate the post-reshape
  schema against `feeds_viz`' `CANONICAL_SCHEMAS` at catalog-load time.
- **Phase 3 — EDAM-semantic suggestions.** Use `edam_operations` / `edam_topics`
  as a secondary match signal (and to *group* suggestions by tool/operation in
  the UI) when column fingerprints are ambiguous.
- **Phase 4 — bulk import + coverage.** Run `import-meta` across the nf-core
  modules registry to scaffold the long tail; track catalog coverage per
  pipeline (viralrecon/ampliseq first, already seeded).
- **Phase 5 — external catalog repo (optional).** If community volume warrants,
  split the catalog into its own `nf-core/modules`-style repo and vendor
  snapshots, keeping this loader as the consumer.

---

## 7. Open questions for maintainers

1. **Catalog home & packaging.** `depictio/catalog/` ships as package data
   (like `depictio/projects/`). Confirm the wheel includes it, or relocate
   under `projects/` if co-location with recipes is preferred.
2. **Curated vs catalog boundary.** Should the existing `KNOWN_PRODUCERS`
   eventually *migrate* into catalog YAML (one source of truth), or stay as a
   vetted core the catalog only extends? Phase 1 keeps both; merge semantics
   already make either viable.
3. **Reshape executor ownership (Phase 2).** Should declarative reshapes run in
   the CLI ingest path, the Celery worker, or both? Affects where
   `CatalogReshape` → polars lives.
4. **Versioning.** Tools/outputs drift across versions (QIIME 2 especially).
   Mirror the recipe system's `{tool}/{version}/` override fallback in the
   catalog, or pin via an `applies_to_versions` field on the output?
