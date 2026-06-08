# RFC — Reshape on the render (`recipe@render` + `materialize`)

**Status:** Draft / design only (no code).
**Audience:** maintainers.
**Related:** `docs/design/bioinformatics-catalog.md` (the catalog this extends),
`depictio/recipes/__init__.py` (the transform engine), `depictio/catalog/README.md`.

> This RFC is design-only. It is **not** a deliverable of the change that
> introduced it; it captures a direction to validate before any code is written.

## 1. Context

The bioinformatics catalog maps, per tool output:
`raw file (find) → recipe → bindable columns → dashboard component (renders_as)`.
"First-layer" vizs bind a tool's raw output directly (via `roles:`). "Second-layer"
vizs (sankey, upset, oncoplot, embedding, complex_heatmap, bray-curtis distance
matrix…) need the data **reshaped** first.

## 2. Problem

Today a viz-only reshape costs **three artifacts**:

1. a **recipe** (`projects/<pipeline>/recipes/<x>_canonical.py`),
2. a **materialised** Delta DC `<x>_canonical` (+ a pipeline step, + storage),
3. a catalog **output fiche** (`find` + `recipe` + `fixture` + `renders_as`),

plus the per-tile `config:`. For trivial, viz-only reshapes the materialised DC
and the extra fiche are mostly boilerplate, and they multiply a convention
(`*_canonical` DCs) that is a concept of its own to teach.

Concrete example surfaced during implementation: ampliseq's `complex_heatmap_canonical`
and `bray_curtis_canonical` are **both** derived DCs computed by recipes that
source from *other DCs* (`dc_ref`), not from a raw file. There is no raw
distance-matrix file to `find`. Modelling them as `find`-based outputs is
therefore fictional; reusing a generic `roles: {}` render is the pragmatic
workaround, but it doesn't express the reshape at all.

## 3. Proposal — two micro-adjustments, **zero new concept**

A decomposition of the friction shows the "connector" idea is really three
already-named ingredients: `render` (exists) + `recipe` (exists, but at the wrong
level — on the output) + a new `materialize: bool`. So:

1. **`recipe` may live on a `Render`** (today: only on `CatalogOutput`). A render
   then carries its own reshape, attached to the real tool output (one entry per
   tool output).
2. **`materialize: bool`** on the render:
   - `false` (default): reshape runs **lazily** at render time, cached by
     `(source DC version, params hash)` — **no Delta DC**.
   - `true`: current behaviour — produces a Delta DC that is a first-class member
     of the data plane (cross-filterable / joinable / inspectable).

### The three render types (the rule to teach)

| render | when | reshape | DC produced |
|---|---|---|---|
| **direct** (roles) | raw already bindable | none | — |
| **recipe lazy** | trivial, viz-only reshape | inline, at render | none (cache) |
| **recipe materialize** | DC serves the data plane | inline | Delta DC |

### Why it *reduces* concept count

```
 BEFORE (per viz)                         AFTER (recipe@render + lazy)
  ① project recipe                         ① recipe inline on the render
  ② *_canonical Delta DC          ───►       (lazy by default)
  ③ output fiche (find…)                   ④ tile config
  ④ tile config
  = 3 artifacts + the "*_canonical"         = 1 artifact; the "*_canonical"
    convention                                convention DISAPPEARS (viz-only)
```

This is the decisive criterion (documentation / explainability): done right, the
change removes the `*_canonical` convention and adds **no new noun**.

## 4. Alternatives considered

- **Introduce a "connector" object.** Rejected: it's an 11th concept and
  redundant with `render` + `recipe` (the catalog already "connects" output →
  component). More to document, not less.
- **Code every second-layer viz in core.** Rejected: kills the
  community-extensible "add a viz = a fiche, no core PR" promise.
- **Keep the status quo (`*_canonical` per viz).** Rejected: it's the friction
  this RFC targets, and it keeps a standalone convention alive.

## 5. Costs / open questions

- **Two possible recipe locations** (`recipe@output` vs `recipe@render`). To
  avoid re-creating debt: deprecate `recipe@output` for viz reshapes; the reshape
  lives on the render.
- **Lazy cache** keyed by `(source DC version, params hash)` — the pattern already
  exists (`compute_complex_heatmap`). Invalidation policy to define.
- **No data-plane integration when lazy** (no cross-filter/join/inspect) — this is
  exactly what `materialize: true` is for; the rule in §3 keeps it explicit.
- **Layer-1 / layer-2 boundary.** Layer 2 (Celery `compute_*`) already computes
  live (PCA, clustering); the lazy reshape inserts *before* it, behind a single
  "load a render's data" entry point.
- **`embedding`** (PCA computed live): becomes a render that **declares its
  computed columns** (`dim_1`, `dim_2`) so grounding stops being a special case.

## 6. Migration (incremental, no big bang)

1. Existing `*_canonical` recipes become `recipe@render` with `materialize: true`
   (zero behaviour change to start).
2. Add the lazy engine + cache.
3. Flip viz-only reshapes (sankey / upset / oncoplot, and the ampliseq
   complex_heatmap / bray-curtis derived matrices) to `materialize: false`.
4. `embedding` enters as a render declaring its computed `dim_*` columns.

## 7. Non-goals

- Not rewriting layer 2 (Celery/React viz compute).
- No new data structure or 4th/5th concept.
- Not merging the runtime suggestion engine (`suggest_viz_kinds`).
