# Project migration and publishing

> Engineering reference for issue #1303: one instance (the *source*) pushes a
> project to another (the *target*). An admin on the target approves the push,
> and the target then serves the project as a published, read-only copy.

## The flow

1. **Source**: the project owner (or an admin) clicks *Send to another instance* in the project's settings > *Send*
   (the project card menu opens it) and picks a target. A preflight asks the target whether it will
   accept the project and how the data should travel.
2. **Source → target**: the source builds a bundle (the same ZIP as
   `/migrate/export-project`) and streams it to the target's
   `POST /migrate/inbound/requests`, authenticated by a pairing key.
3. **Target**: the request waits in *Admin > Migrations*. An admin approves it
   (with *Lock editing* ticked by default) or rejects it with a reason.
4. **Target**: approval runs the import in the background:
   - re-validate the bundle;
   - copy the data;
   - write the documents;
   - set the lock;
   - optionally make the project public;
   - delete the staged bundle.

   The source's push record follows the remote status.

With a pairing key, nothing reaches a project on the target before an admin
approves it. Until then, an inbound request writes only its `migration_requests`
record and the staged bundle at
`s3://<bucket>/<staging_prefix>/<request_id>/bundle.zip`.

With an **invite code** (below), the admin's approval is given in advance: the
import starts as soon as the bundle is accepted.

## Publishing with an invite code (two gestures)

One mechanism serves every target: a per-project SciLifeLab Serve app (one
Depictio per researcher, single-user mode) and a public multi-project instance
such as EMBL's. The differences are policy carried by the invite and by the
target's settings, never a code path of their own.

1. **On the target**, an admin clicks *Import* in the *Projects* page header and
   picks *From another instance* (or Admin > Migrations > *Invitations* > *Receive a project*). The dialog shows the
   instance URL and a code such as `7KQ2-M9XD-…` once, with copy buttons.
2. **On the source**, the project owner opens the project's settings > *Send*, clicks
   *Send to another instance*, pastes both, and sends.

The target imports at once, as the admin who issued the invite. The owner is
resolved as for an approval: the requester's account when one exists with that
email, else that admin. In single-user mode, that is the instance's only admin.

There is **one kind of code**. The first project sent with it is imported, and
the code is then bound to that project. Until it expires, the same code
publishes that project's **updates**: each re-push adds an `import` version.
It refuses any other project.

The rule to remember: **a project can only be updated with the code that
first brought it.** A new code for a project that is already here is refused.

- *Valid for*: 1 day, 30 days (the default, `INVITE_TTL_DAYS`) or 1 year. The
  API accepts any lifetime up to `INVITE_MAX_TTL_DAYS`.
- *Lock editing on import*: on by default.
- *Note*: optional.

**Security**
- The code is 24 symbols (120 bits) of Crockford base32. It is returned once;
  only its sha256 and its last 4 characters are stored. The lookup goes through
  the hash, and the stored hash is compared again in constant time.
- The code is claimed atomically once the bundle is valid and staged:
  - a refused upload leaves it untouched;
  - of two uploads of different projects racing on one fresh code, one binds
    it and the other gets 409, with its staged bundle deleted.
- Revoking an invite stops it everywhere.
- Invites work only while `INBOUND_ENABLED` is on. With inbound on, no
  `INBOUND_SOURCES` and no valid invite, every inbound call is a 403.
- An invite never gets a server-side copy: its data always travels inline.
- The source has no stored credential for an invite push, so the 202 returns a
  **request token**. It reads that one request's status
  (`X-Depictio-Request-Token`) and nothing else. The source stores it encrypted;
  the target stores its sha256.
- The request is recorded under `source_name: invite:<invite id>`, and that
  name is the project's lineage. A project imported with one code can be
  re-pushed with that same code, or through an admin approval. A different
  code would make it a `foreign` project.

**Source settings.** A typed destination must:
- be under a domain suffix of `DESTINATION_DOMAINS`, for example
  `["serve.scilifelab.se", "embl.org"]`. A host matches when it equals the
  suffix or ends with `.<suffix>`. Empty (the default) disables typed
  destinations;
- use https;
- pass the SSRF guard. Both checks run again before every call.

The LAN exception is a host on `UI_TARGET_HOST_ALLOWLIST`, which may use http
and a private address.

The code is handed to the background job in memory and never stored. *Publish
to…* remembers recent destination URLs, read from `migration_pushes`, never
codes. Retrying a failed push to a typed destination asks for a code again.

Env-declared pairing-key targets keep working unchanged.

**One round trip.** Before building, the source calls
`POST /migrate/inbound/check`, which answers `/info`, `/preflight` and, when a
server-side copy is possible, `/probe` together. Targets from before slice 2 are
still served by those three routes (the source falls back on a 404).

## Publishing manually (Serve and EMBL)

There is no automatic lock when an instance goes public (for now). The steps:

1. **Push with an invite.** For a Serve app, issue the invite with *Lock
   editing on import* off if the researcher still wants to adjust the project
   on the target; otherwise leave it on.
2. **Lock.** On the target, open the project's *Permissions* page and turn on
   *Editing: locked* (admin only; `POST /projects/{id}/lock`).
3. **Make the project public.** Use *Public* on the same page. An admin may
   change the visibility of a locked project, because visibility is not
   content and snapshots never hold it. An owner who is not an admin still
   meets the lock (409).
4. **Make the app public on Serve.** Serve then switches the app to
   `DEPICTIO_AUTH_PUBLIC_MODE=true` / `DEPICTIO_AUTH_SINGLE_USER_MODE=false`.
   Only a Serve admin can switch it back.

With the chart defaults, an admin in single-user mode reaches every control
involved: *Admin > Migrations* (Invitations, Requests, Sent), *Receive a
project*, and the *Editing* switch.

## Following a push (source)

- *Admin > Migrations > Sent* lists every push: status, destination, dates and
  the target's status. It refreshes while a push is in flight or still
  importing on the target.
- The project page has a *Publications* history; owners see their own pushes.
- `GET /migrate/push` refreshes the remote status of a few submitted pushes on
  each call.
- A project can have only one push in flight: a second one while one is
  `building`/`uploading` answers 409. A partial unique index on
  `migration_pushes.in_flight` closes the race.
- **Restarts.** On API startup, pushes still `building`/`uploading`, and
  requests still `importing`, whose last update is older than
  `INTERRUPTED_AFTER_MINUTES` (60) become `failed` with
  `interrupted by a restart`:
  - the push keeps a **Retry** action, which starts a new push with the same
    project, target and message;
  - the request is `retryable`: its staged bundle was kept, and *Retry* on the
    target (`POST /migrate/requests/{id}/retry`) re-runs the import with its
    original decision.

## Helm chart defaults

`helm-charts/depictio/values.yaml` turns receiving and the UI on in
`backend.env`:

```yaml
DEPICTIO_MIGRATION_INBOUND_ENABLED: "true"
DEPICTIO_MIGRATION_UI_ENABLED: "true"
```

The code defaults in `MigrationConfig` stay off. This is safe because inbound
with no `INBOUND_SOURCES` accepts nothing until an admin of the instance issues
an invite. `configmaps.yaml` forwards every `DEPICTIO_MIGRATION_*` key of
`backend.env` except `TARGETS` and `INBOUND_SOURCES`, which carry pairing keys
and belong in a Secret.

> **Note for the Serve team.** Serve does not use `values-serve.yaml`. Set the
> two variables above in each Depictio app's `k8s_values` (`backend.env`) so
> that a researcher's app can receive their project from EMBL with an invite
> code.

## Configuration

Everything is under `DEPICTIO_MIGRATION_*` (`MigrationConfig` in
`depictio/api/v1/configs/settings_models.py`), and everything is off by default.
List settings take JSON.

| Variable | Side | Default | Meaning |
| --- | --- | --- | --- |
| `UI_ENABLED` | both | `false` (chart: `true`) | Show the controls: *Send*, *Import*, *Admin > Migrations*, push targets, the *Lock editing* switch. Off hides them only; the API follows the settings below. A project already locked keeps its *Read-only* badge and its unlock switch |
| `INSTANCE_LABEL` | both | public URL host | Name recorded in provenance hops |
| `TARGETS` | source | `[]` | `[{"name", "url", "pairing_key"}]`, trusted by the operator |
| `ALLOW_UI_TARGETS` | source | `false` | Let admins add targets in *Admin > Settings* |
| `UI_TARGET_HOST_ALLOWLIST` | source | `[]` | Hosts a UI target may reach over http or on a private IP |
| `INBOUND_ENABLED` | target | `false` (chart: `true`) | Accept pushes from `INBOUND_SOURCES` and from valid invite codes. When off, every inbound route returns 404 |
| `INBOUND_SOURCES` | target | `[]` | `[{"name", "pairing_key", "allowed_source_buckets", "max_pending", "max_per_day", "max_bundle_bytes"}]` |
| `LOCK_IMPORTED_DEFAULT` | target | `true` | Initial state of *Lock editing* |
| `DESTINATION_DOMAINS` | source | `[]` | Domain suffixes an owner may publish to with a URL + invite code |
| `INVITE_TTL_DAYS` | target | `30` | Default lifetime of an invite code (its project's first push, then its updates) |
| `INVITE_MAX_TTL_DAYS` | target | `365` | Longest lifetime an admin may give an invite |
| `INTERRUPTED_AFTER_MINUTES` | both | `60` | Startup recovery threshold for pushes and imports |
| `MAX_BUNDLE_BYTES` | both | 10 GiB | Bundle size cap (413 above it) |
| `STAGING_PREFIX` | target | `_migration_staging` | S3 prefix for staged bundles. Must be one path segment, not an ObjectId |
| `PENDING_TTL_DAYS` | target | `14` | Pending requests older than this expire, and their bundle is deleted |
| `SPOOL_DIR` | both | system temp | Where bundles are written while in flight |
| `HTTP_TIMEOUT_S` | source | `60` | Timeout for calls to a target |
| `UPLOAD_TIMEOUT_S` | source | `1800` | How long the source waits for the target's answer after sending a bundle (the target stages it on S3 first) |

Pairing keys are at least 32 characters. Both sides hold the same key: it is in
the source's `TARGETS` entry and in the target's `INBOUND_SOURCES` entry. The
target compares keys in constant time.

The name a request is recorded under comes from the matched key, never from the
request body.

Example (target):

```bash
DEPICTIO_MIGRATION_INBOUND_ENABLED=true
DEPICTIO_MIGRATION_INBOUND_SOURCES='[{"name": "lab", "pairing_key": "<64 hex>"}]'
```

Example (source):

```bash
DEPICTIO_MIGRATION_TARGETS='[{"name": "public", "url": "https://depictio.example.org", "pairing_key": "<same key>"}]'
```

### Targets added in the UI

UI targets are checked on every outbound call (SSRF guard in
`services/outbound_http.py`):

- **Allowed**: https only, and redirects are never followed.
- **Refused**: hosts that resolve to loopback, private, link-local, CGNAT,
  multicast, reserved or cloud-metadata addresses.
- **Exception**: a host in `UI_TARGET_HOST_ALLOWLIST` may use http and a private
  address. This is the LAN case.

The key is stored encrypted, and the API only ever returns a fingerprint.

Targets from `TARGETS` are trusted by the operator and skip the guard.

## How the data travels

The target picks the mode in its preflight answer:

- **`inline`** (the default): the objects are carried in the bundle's `s3_data/`.
  The target writes them to its own bucket, rewriting every
  `s3://<source bucket>/` into `s3://<target bucket>/`.
- **`server_side_copy`**: used when both instances use the **same S3 endpoint**,
  and the source's bucket is listed in that source's `allowed_source_buckets`
  and is not the target's own bucket. The bundle then carries only a manifest
  (key, size, etag). After approval, the target copies each object with its own
  credentials:
  - every copy uses `CopySourceIfMatch=<etag>`;
  - `_delta_log/` keys are copied last, so a half-copied table is never visible
    as a valid table.

  If the source data changed after the push, the copy fails and the request
  ends as `failed` with MongoDB untouched.

The source never receives the target's write keys. For `server_side_copy`, grant
the target's S3 user **read-only** access to the source bucket, for example:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:GetObject", "s3:ListBucket"],
    "Resource": ["arn:aws:s3:::lab-bucket", "arn:aws:s3:::lab-bucket/*"]
  }]
}
```

A push lands on the target's public URL, the one the *Import* dialog shows, which is
the viewer's. The viewer's nginx passes the bundle upload (`POST
/depictio/api/v1/migrate/inbound/requests`) to the API unbuffered and without its
200 MB cap; the API enforces `MAX_BUNDLE_BYTES`. The ingress in front of that host
still has to let the bundle through.

For `inline` pushes behind an ingress, raise the body size limit to at least
`MAX_BUNDLE_BYTES` (or `"0"` and let the API enforce it). With nginx, that is `client_max_body_size`; with
ingress-nginx, the annotation is `nginx.ingress.kubernetes.io/proxy-body-size`.

A bundle of several GB also needs time. The target answers only once it has staged
the whole bundle on S3, so every hop between the two APIs must wait that long:
`UPLOAD_TIMEOUT_S` on the source, and on the target's ingress
`nginx.ingress.kubernetes.io/proxy-read-timeout` and `proxy-send-timeout` (seconds,
for example `"1800"`). Without it the ingress answers 504 after 60 s while the
target is still working, and the source records a failed push for a bundle the
target may go on to accept.

## On the target

**Owner.** The owner is the account whose email matches the requester the source
reports. If no such account exists:

- the approving admin becomes owner;
- `pending_owner_email` is set;
- the first SSO login (or admin-provisioned account) with that email claims the
  project (`projects_endpoints/pending_owner.py`).

Password self-registration does **not** claim it, because that email is not
verified.

**Version history.** The import records the state it replaces, then an `import`
version labelled "Migrated from X (Depictio vY)". Pushing the same project again
(same lineage: the last import hop came from the same source) therefore adds a
version rather than overwriting history.

**Provenance.** `project.provenance.imported_from` gains a hop that records:

- source instance;
- source and target Depictio versions;
- bundle format;
- bundle sha256;
- request id.

The project header shows it as a version badge.

**Collisions.** An `_id` that collides with another project's document blocks the
request.

**Expiry and cleanup.**

- Pending requests expire after `PENDING_TTL_DAYS`.
- The hourly orphan S3 sweep treats the collections of a request in `importing`
  as live, so it does not delete data mid-import.

## The published lock

`project.published_lock` makes a project read-only through the API. The guards in
`projects_endpoints/publish_lock.py` return **409**, and the lock covers:

- dashboards: edit, save, tabs, appearance, logo, import, delete, version restore;
- data collections, deltatables, MultiQC, files, runs and links;
- project edit, project delete, and visibility changes.

Only an admin can lift it, with `POST /projects/{id}/unlock`. An admin may
still change a locked project's visibility (publishing a release); anyone else
meets the 409. In the UI, the
lock is the *Editing* row of the project's Permissions page, beside *Public /
Private*: visibility says who may view the project, the lock whether anyone,
owners included, may change it. The two are independent, and a published
version is usually both public and locked. The project shows a *Read-only*
badge while it is locked.

A viewer's *copy* of a locked dashboard stays editable: a dashboard is locked
only when its id, or its `parent_dashboard_id`, is in
`published_lock.dashboard_ids`.

The approved migration is the one writer past the lock: it records the replaced
state, writes, and sets the lock again.

Anyone holding the S3 keys directly can still change the data; the lock is an
API guarantee only.

## What a bundle carries

- **Documents**: the project (with its workflows and data collections), files,
  Delta tables, runs, every dashboard tab, MultiQC and JBrowse records.
- **Dashboard logos** (`branding_assets`, keyed by dashboard id, which an import
  keeps).
- **Comment threads with their annotations** (`comment_threads`). A re-push
  upserts them; threads written on the target are kept.
- **Data** for the six collection types: Delta tables, MultiQC parquet, JBrowse
  tracks stored in S3 (`https://` tracks stay links), image folders, GeoJSON
  objects, phylogeny trees and genomic-track prefixes. Every
  `s3://<source bucket>/` reference is rewritten to the target's bucket.

Bundles without the logo and comment sections still import, and an older
target ignores them, so they need no new bundle format.

**Compatibility check.** Two instances can share a bundle format and still
differ in what a dashboard may hold. The target refuses, before anything is
written, a bundle whose dashboards use a component type or an advanced-viz kind
it does not know, and says which version to update to. `/check` also warns when
the source runs a newer Depictio than the target.

## Known gaps

- Version history (`dashboard_versions`) is not carried: the target starts
  from an `import` version and adds one per update.
- Comment authors keep the user id they had on the source; the email shows who
  wrote it.
- The requester's email is asserted by the source. Approval by an admin, and
  claims through SSO only, limit what a forged email can do.
- MongoDB has no transaction around the import: a failure halfway can leave a
  partial import. The "before" capture makes it restorable, and the request ends
  as `failed`.

## Testing on a LAN

`dev/migration_lan_test/` starts three `depictio local up` stacks and runs
the whole flow against them (`check.py`):
- A, the source;
- B, a pairing-key target with an approval queue;
- C, a target with the chart defaults, for the invite scenario.

On one machine, with both instances reached through its LAN address:

```bash
dev/migration_lan_test/run.sh demo
```

The script header shows the two-machine variant.
