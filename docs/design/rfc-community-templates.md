# RFC — Community template system (share-as-template + template registry)

**Status:** Draft / design only (no code).
**Audience:** maintainers.
**Related:** `depictio/models/models/templates.py` (template models),
`depictio/cli/cli/utils/templates.py` (`resolve_template`, `_strip_ids`,
`import_dashboards_from_template`), `depictio/api/v1/endpoints/migrate_endpoints/routes.py`
(project export/import bundles), `depictio/api/v1/db_init_reference_datasets.py`
(reference seeding), docs `usage/projects/templates.md` +
`developer/contributing-templates.md`.

> Design-only. Captures a direction to validate before any code is written.
> The goal is a system that lets (a) the community contribute **validated**
> templates that ship in the depictio repo, and (b) any user turn their own
> project into a template to share with colleagues — and to name precisely
> what blocks that today.

## 1. Context — what a "template" is today

A **template** is a `template.yaml` that ships inside the repo under
`depictio/projects/<pipeline>/<version>/`. It extends a normal project config
(`models/models/templates.py`) with three things:

1. a top-level `template:` metadata block — `template_id` (`<org>/<pipeline>/<version>`),
   `description`, `version` (semver), `variables[]`, `dashboards[]`, `conditional[]`,
   `structure` (`flat` | `sequencing-runs`);
2. `{VAR}` placeholders (always `{DATA_ROOT}`, plus template-specific vars like
   `{SAMPLESHEET_FILE}`, `{GROUP_COL}`) substituted at instantiation;
3. bundled dashboard YAMLs + recipe references that are auto-imported on first run.

It is instantiated with `depictio run --template <id> --data-root <path> [--var K=V]`.
`resolve_template()` (`cli/utils/templates.py:427`) does the work: locate → load →
build variables (+ metadata-header auto-detection) → validate required vars →
`{VAR}` substitution → apply conditionals (drop DCs / swap dashboards) →
**`_strip_ids()`** (so fresh ObjectIds are minted, `templates.py:139`) →
record `TemplateOrigin` with a frozen `config_snapshot` for provenance →
import dashboards by YAML to `/dashboards/import/yaml`.

Two reference templates exist today (`nf-core/ampliseq`, `nf-core/viralrecon`),
both authored by hand and checked into the repo.

There is a **documented contribution process** for these
(`developer/contributing-templates.md`): create dirs → write `template.yaml`
(only `{DATA_ROOT}`-relative paths, no absolutes) → write+validate recipes →
build dashboards in the UI then `dashboard seed` them → test end-to-end → open a
PR tagged `template`. A maturity ladder already exists in docs:
**Experimental → Verified → Official**.

### What is NOT a template field

There is **no `is_template` flag** on `Project` (`models/models/projects.py`).
Templates are a *filesystem* artifact discovered by `rglob` (`locate_template`,
`templates.py:35`); there is **no DB registry**. The only DB-level template
marker is `Project.template_origin` — populated *after* instantiation to record
that a template *was used*, not that a project *is* one.

## 2. The two flows the user wants — and the exact gap

| Want | Closest thing today | Gap |
|---|---|---|
| **(A) Community-validated templates** shipping in the depictio repo | `developer/contributing-templates.md` PR flow + the Experimental→Verified→Official ladder | The ladder and process are **documented but not enforced or surfaced**: no CI gate that validates a template, no badge stored anywhere, no in-app discovery/catalog. It's a maintainer-gated, manual, Git-only path. |
| **(B) Any user turns their project into a template** to share with colleagues | Nothing direct. Pieces exist: `_strip_ids()`, `migrate/export-project`, `TemplateMetadata`. | There is **no "export this project as a template" command/endpoint**. The migration bundle is a *clone* tool (admin-only, preserves source ObjectIds, only remaps owners), not a *parameterized-reusable-template* tool. Docs explicitly state there is **no end-user model** for sharing custom projects/dashboards. |

The system has all the right primitives but they were built for two narrower
jobs — *seed the reference datasets* (template resolution) and *move a project
between instances* (migration). Neither is "publish a reusable, parameterized,
trust-graded template that other people instantiate independently."

## 3. Limitations — what concretely blocks "share-as-template" today

Ordered by how hard each is to remove.

1. **No template-emit path.** Templates are hand-authored. There is no flow that
   takes a *live* project and emits `template.yaml` + dashboard YAMLs with IDs
   stripped and paths re-parameterized to `{DATA_ROOT}`/`{VAR}`. (The reverse —
   resolve a template into a project — is fully built.)
2. **Hardcoded identity in seeds.** `.db_seeds/*.json` embed the admin
   `$oid`+email (`projects/init/iris/.db_seeds/dashboard.json:11`) and component
   `dc_id`/`wf_id` as concrete ObjectIds; `STATIC_IDS` pin reference IDs
   (`db_init_reference_datasets.py:33`). A community template must ship
   YAML-with-placeholders (which `resolve_template` rewrites), **not** seed JSON
   (which is trusted verbatim). i.e. the **shareable transport is YAML, not JSON
   seeds.**
3. **Data is ObjectId-keyed in S3.** Delta tables live at `s3://{bucket}/{dc_id}`
   (`deltatables_utils.py:28`). Re-instantiating with fresh DC IDs requires
   *re-ingesting* from the user's `--data-root`, or re-pathing data. Migration
   only normalizes the bucket prefix (`_normalize_s3_path`, `migrate routes.py:83`),
   not the DC-id segment. **A template ships config + dashboards + recipes, not
   data** — the consumer brings their own `--data-root`, or the template bundles
   small sample fixtures (the iris/penguins pattern). This is a *feature*, not a
   bug, but it has to be made explicit in the UX.
4. **Admin-only + public-mode gates.** Project import is admin-only
   (`migrate routes.py:599`); dashboard import is blocked in public/demo mode
   (`dashboards routes.py:3613`). Self-service "a colleague instantiates my
   shared template" doesn't work for non-admins on a hosted instance today.
5. **No version-compatibility gate, and `extra="forbid"` everywhere.** Backup
   stamps a literal `"0.1.0"` (`backup routes.py:246`) that's never checked.
   Models forbid extra fields (`DataCollectionConfig`, `models/data_collections.py:181`),
   so a template authored on a newer depictio with a new field is *rejected* by
   an older instance — a silent cross-version break with no migration layer.
6. **Data-leak surface.** Dashboards embed `stored_metadata` with column names
   (and sometimes cached values). Even a "metadata-only" template leaks schema /
   column structure — needs a scrub/redaction step + a consent UX.
7. **Trust / provenance.** A user-shared template is arbitrary config + arbitrary
   **recipe Python** (`transform()` executed during `run`). Recipes are code;
   instantiating a stranger's template = running their code. This is the single
   biggest security limitation for an open "community hub."

## 4. Proposal

Two products that share one format, shipped in order.

### 4.1 Format: reuse `template.yaml`, add a portable bundle

Do **not** invent a new schema. A shareable template = a directory (or a single
`.depictio-template.zip`) containing exactly what the repo templates contain:

```
<template_id>/
  template.yaml          # template: block + {VAR} placeholders, IDs stripped
  dashboards/*.yaml       # YAML (NOT .db_seeds JSON) — portable, ID-free
  recipes/*.py            # optional transforms
  data/*                  # OPTIONAL small sample fixtures
  TEMPLATE.md             # provenance, required vars, expected data layout, screenshot
  manifest.json           # depictio_version range, checksum, author, maturity, recipe-hash
```

The `manifest.json` is the new piece (addresses limitations 5 & 7): records the
depictio version range it was authored/validated against, a content hash, the
author identity, the maturity badge, and a hash of every recipe so a consumer
(and CI) can detect tampering and pin trust.

### 4.2 Product 1 — "Export project as template" (covers want B)

A new command/endpoint that inverts `resolve_template`:

- **CLI**: `depictio template export --project "<name>" --out ./my-template/`
  and **API**: `POST /templates/export-project` (reuse the cascade in
  `migrate/export-project:319`).
- Steps: pull project + workflows + DCs + dashboards → run an **inverse of
  `_strip_ids`** (delete `_id`/`wf_id`/`dc_id`, rewrite component references to
  DC *tags* — the `tag:` placeholder resolution that `run.py:362` already does
  forward) → re-parameterize absolute/data paths to `{DATA_ROOT}` + prompt the
  author to mark which literals become `--var`s → export dashboards as **YAML**
  (reuse `/dashboards/export/yaml:3801`, *not* JSON seeds) → **scrub
  `stored_metadata`** of cached values (limitation 6) → write `manifest.json`
  with recipe hashes → zip.
- Output is instantiable immediately by the **existing** `depictio run --template`
  path pointed at a local dir (extend `locate_template` to accept a filesystem
  path / zip, not only repo `rglob`).

This is the smallest end-to-end win: it makes "turn my project into something a
colleague can `depictio run`" real, using machinery that already exists in both
directions.

### 4.3 Product 2 — Template registry + in-app catalog (covers want A)

- **`is_template` becomes a first-class concept** via a small Beanie document
  `TemplateRegistryEntry` (id, `template_id`, version, author, maturity badge,
  source = `repo` | `user`, manifest, location/URI, screenshot). Repo templates
  are indexed into it at `db_init` time (replace the `rglob` discovery with a
  registry populated from the same dirs); user-exported templates register
  themselves on upload.
- **In-app catalog page**: browse/search templates, filter by maturity, "Use
  this template" → a guided form that reads `template.variables[]` and collects
  `--data-root` + each `--var` (today only available as raw CLI flags), then
  drives the existing instantiation pipeline.
- **Maturity ladder, enforced not just documented**: badge stored on the registry
  entry. `Experimental` = user-submitted / CI-validated; `Verified` = core-team
  reviewed; `Official` = repo-shipped + tested against reference data. Surface the
  badge in the catalog so trust is visible.

### 4.4 Make community contribution real (covers want A, repo side)

- **CI gate** that runs the documented checklist automatically on any PR touching
  `depictio/projects/**/template.yaml`: validate `template_id` format, assert no
  absolute paths (only `{DATA_ROOT}`), run each recipe against the committed
  reference fixture (`depictio recipe run … --head 10`), validate dashboards
  (`dashboard validate`), and verify YAML↔`.db_seeds` JSON are in sync (the
  CLAUDE.md regeneration rule — catch the classic "forgot to regenerate seeds"
  bug). Passing CI = auto-assign the `Experimental` badge.
- A `depictio template lint <dir>` command so contributors get the same checks
  locally before opening a PR.

### 4.5 Trust & safety for user-shared templates (limitation 7)

- **Recipes are code.** For colleague-to-colleague sharing (the primary B use
  case), default to **same-instance / trusted-org** sharing where the recipe risk
  is acceptable, and show a clear "this template runs the following recipe code"
  confirmation listing recipe hashes from the manifest.
- For any *public* community hub, require recipe review before a template can
  leave `Experimental`, and consider a **recipe-free template tier** (config +
  dashboards + `source: transformed` only via *already-shipped* repo recipes, no
  arbitrary author Python) that can be auto-trusted.

### 4.6 Relax the gates (limitation 4)

Add a project-level permission "members may instantiate shared templates" so
non-admins can `Use template` on a hosted instance, decoupled from the admin-only
*migration* path. Keep full project *import* (clone with data) admin-only;
template *instantiation* (fresh IDs, user becomes owner, user brings data) is
inherently safer and already mints clean IDs via `_strip_ids`.

## 5. Implementation points (phased)

**Phase 0 — foundations (low risk, unblocks everything)**
- Extend `locate_template` (`cli/utils/templates.py:35`) to accept a filesystem
  path or `.zip`, not only repo `rglob`.
- Add `manifest.json` model + a `depictio template lint <dir>` command reusing
  existing validators.
- Define the portable bundle layout (§4.1) and document it alongside
  `contributing-templates.md`.

**Phase 1 — export-as-template (want B, MVP)**
- `POST /templates/export-project` + `depictio template export` (§4.2), reusing
  `migrate/export-project` cascade and `/dashboards/export/yaml`.
- Inverse-`_strip_ids` + component-ref→tag rewrite + `stored_metadata` scrub.
- Path→`{DATA_ROOT}`/`{VAR}` re-parameterization (interactive: author confirms
  which literals are variables).
- Round-trip test: export project → `depictio run --template ./bundle` → assert
  equivalent dashboards with fresh IDs.

**Phase 2 — registry + catalog (want A, in-app)**
- `TemplateRegistryEntry` Beanie doc + index repo templates at `db_init`.
- Catalog UI page (browse/search/filter by badge) + "Use this template" variable
  form driving the existing pipeline.
- Registration of user-exported templates.

**Phase 3 — community contribution hardening (want A, repo)**
- CI workflow validating `template.yaml` PRs end-to-end (§4.4), auto-badging
  `Experimental`; YAML↔seed-JSON sync check.
- Maturity badge stored + surfaced; Verified/Official promotion workflow.

**Phase 4 — cross-version + trust**
- Read real `depictio_version` into manifests; check the range on instantiate;
  add a migration/compat shim for `extra="forbid"` drift.
- Recipe-hash trust UX + recipe review gate for public templates;
  optional recipe-free tier.

## 6. Open questions / decisions for maintainers

1. **Scope of "community"**: same-instance/org sharing first (low trust risk),
   or a public cross-instance hub (needs recipe review + signing)? Recommend
   org-first.
2. **Data fixtures**: do user-exported templates ever bundle data, or always
   bring-your-own `--data-root`? Recommend bring-your-own by default, optional
   small fixtures with an explicit size cap (the viralrecon 4.7 GB exclusion is
   the precedent).
3. **Where do user templates live**: registry-only (URI to a bundle in S3) vs.
   committed back to the repo for Verified+? Recommend S3-backed registry for
   user templates; repo only for Verified/Official.
4. **Recipe execution trust model**: confirmation + hashes enough for org sharing,
   or mandatory review even there?
5. **Single dashboard vs whole project** as the unit of sharing — the dashboard
   YAML export already exists and is lighter; should "share a dashboard" be a
   distinct, lower-friction Product 0?
