# Template versioning

A template is a bundle: `template.yaml` (data collections, variables, conditionals),
`dashboards/*.yaml`, and the recipes its collections run. `template.version` in
`template.yaml` is the revision of that whole bundle, a semver of its own. It is not the
version of the pipeline the template targets, which is the last segment of the template id
(`nf-core/nascent/2.3.0`).

## The rule

Bump `template.version` in the same commit as the change:

| Bump  | When                                                                                                    | What it asks of a user                    |
| ----- | ------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| major | a data collection, a column or a template variable changes (added, removed, renamed, retyped)           | ingest the project again                  |
| minor | dashboards, figures or recipes change and every collection keeps its columns                            | import the dashboards again               |
| patch | text only: titles, captions, prose, descriptions                                                        | nothing                                   |

## Where the revision is recorded and shown

- The project records the revision it was ingested with: `template_origin.template_version`.
  The project page shows it as a `template vX.Y.Z` badge beside the template chip.
- Each dashboard the template import writes records `template_origin`
  (`template_id`, `template_version`, `imported_at`). It is provenance, not content: it is not
  in the YAML export, not in a dashboard version, and a save from the viewer cannot change it.
  Dashboards built in the viewer, imported from a plain file, or imported before this existed
  have none. The dashboard's Settings, under About, shows the revision, and a warning when the
  dashboard was imported from another revision than the one the project was ingested with
  (`depictio ingest --reset-dashboards` brings it up to date, and loses viewer edits).
- A dashboard the import keeps as it is (what `depictio ingest` does unless `--reset-dashboards`
  is given) keeps its stamp: it was not imported from the new revision.

## The guard

`depictio/projects/template_versions.lock.json` maps every template (its directory under
`depictio/projects/`) to its `version` and a `content_hash`. The hash covers `template.yaml`,
`dashboards/**/*.yaml`, the version's own `recipes/` and the pipeline's shared `recipes/`; docs,
test data, `megatest.yaml`, `.db_seeds` and `__pycache__` are left out, line endings are
normalised and paths are taken relative to the template.

```bash
python scripts/update_template_lock.py --check   # what the test and the pre-commit hook run
python scripts/update_template_lock.py --write   # after bumping: refresh the lock
```

`--check` fails on a template whose content changed under an unchanged version, on a version
that went down or is not `X.Y.Z`, and on a lock that is out of date. `--write` refuses the
unbumped case unless given `--force`. A recipe in a pipeline's shared `recipes/` moves the hash
of every version of that pipeline, so each of them is bumped. The platform code the recipes
import (`depictio/recipes/lib`) is not part of the hash.

Catalog modules carry their own revision: `version` in `depictio/catalog/<module>/module.yaml`,
same semver rules (major: an output column changes; minor: a reader, recipe or render changes;
patch: text only). `depictio/catalog/catalog_versions.lock.json` holds each module's version and
a hash of its `.py` and `.yaml` files (fixtures are not part of it), and the same script checks
and writes it. A template's hash covers the **version** of each module it consumes (a
`recipe: <module>/<name>` that resolves in the catalog, a dashboard `use: <module>/...` or
`catalog_source.toolId`, a recipe importing `depictio.catalog.<module>`), and its lock entry
lists them under `catalog`. Editing a module therefore fails twice, on purpose: bump the module,
then bump every template that consumes it. A `use:` is expanded into the dashboard at import, so
an imported dashboard only picks up a module change through a re-import of its template.

The guard is `depictio/tests/unit/test_template_lock.py` (skipped while the lock file does not
exist) and the `check-template-versions` hook in `.pre-commit-config.yaml`.
