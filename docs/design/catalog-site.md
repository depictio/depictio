# Catalog site

The Tools Catalog is published as a static site, separate from the documentation. It has
one directory per Depictio release plus `latest/` (the catalog on `main`), and each catalog
module carries its own version history across them. This page is the contract between the
three parts that make the site: the exporter, the publisher and the hosting.

| Part      | What                                                                 | Where                                    |
| --------- | -------------------------------------------------------------------- | ---------------------------------------- |
| exporter  | one release of the catalog, as a self-contained directory            | `depictio catalog export-site`           |
| publisher | merges that directory into the site tree, deduplicated, with history | `scripts/publish_catalog_site.py`        |
| hosting   | serves the tree; knows nothing of the catalog                        | `deploy-catalog.yaml` (GitHub Pages now) |

The publisher only writes a directory. Pushing it somewhere is the hosting's job, so moving
the site (to a Kubernetes cluster, an S3 bucket) changes the last step of the workflow and
nothing else.

## The export (one slot)

`depictio catalog export-site --out-dir DIR --version X.Y.Z` writes a directory that works
on its own (serve it and open it):

```
index.html, assets/*          the site bundle (build:catalog-site), chunks content-hashed
data/index.json               every tool, output and render, without their data
data/outputs/<output_id>.json each output's {fixturePreview, data}, fetched when it is shown
```

`data/index.json` has `version`, `tools[]` (each with the module `version` from its
`module.yaml`) and, per output, `ok` (and `error` when its previews could not be built).

The export is **reproducible**: the same catalog gives the same bytes, in any process. The
measured `compute_ms` of the computed renders (upset, sankey, embedding) is written as `0`,
and the Sankey kernel keeps its groups in input order and breaks ties on the label. An export
whose computed renders fail is not complete: the stats of `export_site_data` carry
`render_errors` (renders holding `_error`, inside outputs that are otherwise `ok`) and
`render_error_ids` (the first 20, as `output_id:index`), and `export-site --strict` fails on
those as it does on a failed output.

## The site tree

```
index.html                    redirect to latest/
versions.json                 {"latest": "latest", "versions": ["v1.23.0", "v1.22.0", ...]} newest first
releases.json                 per slot: version, date, and what changed since the previous release
assets/<name>-<hash>.js|css   every slot's chunks, shared (names are content hashes)
objects/<sha256>.json         every output's {fixturePreview, data}, stored once per content
modules/<tool_id>.json        a module's version history
latest/  v1.22.0/  ...        one per slot:
  index.html                  the slot's bundle entry, loading ../assets/
  data/index.json             as exported, each output with "dataRef": "<sha256>"
  assets.json                 the shared asset files this slot's bundle needs: a JSON array of names under assets/
  assets.previous.json        latest/ only: the assets of the latest/ it replaced (grace period)
  objects.previous.json       latest/ only: the dataRefs of the latest/ it replaced (grace period)
  assets/<file>               files whose name carries no content hash (e.g. genomes/hg38.genes.json)
```

Only a file named like a Vite chunk (`<name>-<hash>.<ext>`, a hash of 8 or more characters
from `[A-Za-z0-9_-]`) is moved to the shared `assets/`: the same name then means the same
content, and a hashed name that arrives with other content is refused. Any other file stays
in its slot's own `assets/`, where the code finds it by a URL relative to the document; it is
not listed in `assets.json`, and the slot's `index.html` keeps pointing at it as `./assets/`.

- An output whose data did not change between two releases points at the same object, and a
  bundle that did not change at the same chunks. A release that changes nothing costs its
  `index.json` (~230 KB gzip). Every release is kept.
- The viewer reads an output from `../objects/<dataRef>.json` when its entry has a `dataRef`,
  else from `data/outputs/<id>.json` (a bare export).
- `assets/` and `objects/` only grow while a slot references them. The publisher drops what
  no slot references any more, except the assets of the `latest/` it replaces, kept for one
  more deploy so a tab opened before it can still load its chunks and data: the publisher
  records the replaced `assets.json` as `latest/assets.previous.json` and the `dataRef`s of
  the replaced index as `latest/objects.previous.json` (a redeploy of the same bundle, or of the
  same data, carries the previous grace list over), and counts both as references.
- Republishing a **release** gives no grace period: the slot is replaced and what no slot
  references any more is dropped at once. Only `latest/` is expected to change under a reader.
- The publisher normalises every slot on each run, idempotently: a slot in the earlier format
  (`data/outputs/` and `assets/` inside the slot, no `dataRef`) is converted to the layout
  above. An export is refused when an `ok` output has no `data/outputs/<id>.json`, or when
  an output id (ok or not), a tool id or a slot name could not name a file.
- Before deleting anything the publisher checks that every `dataRef` of every slot exists in
  `objects/` and every name in every `assets.json` exists in `assets/` (and stays inside it);
  otherwise it stops with nothing deleted. It also computes `modules/` and `releases.json`
  before the first deletion, so an error there does not leave the tree half-cleaned.
- **The publisher is not atomic.** It edits the tree in place (the slot is replaced, shared
  files move, then files are dropped and the derived files written), so a crash in the middle
  can leave a mixed tree. A host that publishes in place (rather than from a fresh checkout it
  can discard) should run the publisher on a copy of the tree and switch to the copy.

### `modules/<tool_id>.json`

```json
{
  "id": "ivar",
  "name": "iVar",
  "versions": [
    {
      "version": "1.1.0",
      "bump": "minor",
      "releases": ["latest", "v1.23.0"],
      "outputs": [{"id": "ivar_variants", "name": "...", "renders": [{"index": "...", "component_type": "...", "_yaml": "..."}]}]
    },
    {"version": "1.0.0", "bump": null, "releases": ["v1.22.0"], "outputs": [...]}
  ]
}
```

Newest first by semver. `releases` lists the slots that ship that version, so the viewer can
open the module in a release that had it. `bump` is the semver step from the version below it
(`major`: an output column changed, `minor`: a reader, recipe or render, `patch`: text).

A version that went back (say `latest` ships `1.0.0` while `v1.23.0` shipped `1.1.0`) stays in
the history at its semver place and `releases` stays exact: `1.0.0` lists `latest`. The step
from a higher version to a lower one, which only `releases.json` computes, is `"downgrade"`.

A tool whose index entry has **no `version`** (an index exported before module versions, such
as the v1.22.0 export) has an *unknown* version, not `1.0.0`: that slot adds no entry to the
module's history, and a module no slot knows a version of gets no `modules/<id>.json`.

### `releases.json`

```json
{
  "releases": [
    {
      "slot": "v1.23.0", "version": "1.23.0", "published": "2026-11-20T10:00:00Z",
      "previous": "v1.22.0",
      "changes": {
        "added": ["bakta"], "removed": [],
        "bumped": [{"id": "ivar", "from": "1.0.0", "to": "1.1.0", "bump": "minor"}],
        "outputs_added": ["bakta_annotation"], "outputs_removed": []
      }
    }
  ]
}
```

`latest` compares with the newest release, so it reads as "unreleased changes". The oldest
release has `previous: null` and empty `changes`. `published` is the UTC time that slot was
last published, kept across runs for the slots not republished (a slot the publisher meets
for the first time, e.g. a migrated one, gets the time of that run). `bumped[].bump` is
`major`, `minor`, `patch` or `downgrade` (the version went down). A tool whose version is
unknown on either side (no `version` in its index) is never in `bumped`: nothing is computed
against an unknown version; it still appears in `added` / `removed` and in the output lists.

## Hosting

Any static host works. It should:

- serve `.json`, `.js` and `.css` compressed (`index.json` is 1.8 MB raw, 230 KB gzip);
- cache `assets/` and `objects/` as immutable, and revalidate `index.html`, `*.json` at the
  slot level, `versions.json`, `releases.json` and `modules/`;
- sit on the same origin as the documentation (`docs.example.org/catalog/` rather than
  `catalog.example.org`): the docs page reads the catalog iframe's location to keep the view
  across a theme switch, and the stubs that archived docs versions embed read their parent's.

Today `deploy-catalog.yaml` pushes the tree to the `depictio/depictio-catalog` GitHub Pages
repository, and uploads it as a workflow artifact, which is what another host can take.
