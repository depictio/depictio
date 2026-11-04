# Project migration and publishing

> Engineering reference for issue #1303: one instance (the *source*) pushes a
> project to another (the *target*). An admin on the target approves the push,
> and the target then serves the project as a published, read-only copy.

## The flow

1. **Source**: the project owner (or an admin) clicks *Migrate…* in the
   project page head (or the project card menu) and picks a target. A preflight asks the target whether it will
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

Nothing reaches a project on the target before an admin approves it. Until then,
an inbound request writes only its `migration_requests` record and the staged
bundle at `s3://<bucket>/<staging_prefix>/<request_id>/bundle.zip`.

## Configuration

Everything is under `DEPICTIO_MIGRATION_*` (`MigrationConfig` in
`depictio/api/v1/configs/settings_models.py`), and everything is off by default.
List settings take JSON.

| Variable | Side | Default | Meaning |
| --- | --- | --- | --- |
| `UI_ENABLED` | both | `false` | Show the controls: *Migrate…*, *Admin > Migrations*, push targets, the *Lock editing* switch. Off hides them only; the API follows the settings below. A project already locked keeps its *Read-only* badge and its unlock switch |
| `INSTANCE_LABEL` | both | public URL host | Name recorded in provenance hops |
| `TARGETS` | source | `[]` | `[{"name", "url", "pairing_key"}]`, trusted by the operator |
| `ALLOW_UI_TARGETS` | source | `false` | Let admins add targets in *Admin > Settings* |
| `UI_TARGET_HOST_ALLOWLIST` | source | `[]` | Hosts a UI target may reach over http or on a private IP |
| `INBOUND_ENABLED` | target | `false` | Accept pushes. When off, every inbound route returns 404 |
| `INBOUND_SOURCES` | target | `[]` | `[{"name", "pairing_key", "allowed_source_buckets", "max_pending", "max_per_day", "max_bundle_bytes"}]` |
| `LOCK_IMPORTED_DEFAULT` | target | `true` | Initial state of *Lock editing* |
| `MAX_BUNDLE_BYTES` | both | 10 GiB | Bundle size cap (413 above it) |
| `STAGING_PREFIX` | target | `_migration_staging` | S3 prefix for staged bundles. Must be one path segment, not an ObjectId |
| `PENDING_TTL_DAYS` | target | `14` | Pending requests older than this expire, and their bundle is deleted |
| `SPOOL_DIR` | both | system temp | Where bundles are written while in flight |
| `HTTP_TIMEOUT_S` | source | `60` | Timeout for calls to a target |

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

For `inline` pushes behind an ingress, raise the body size limit to at least
`MAX_BUNDLE_BYTES`. With nginx, that is `client_max_body_size`; with
ingress-nginx, the annotation is `nginx.ingress.kubernetes.io/proxy-body-size`.

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

Only an admin can lift it, with `POST /projects/{id}/unlock`. In the UI, the
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

## Known gaps

- Dashboard logos live in `branding_assets`, which the bundle does not carry.
- The requester's email is asserted by the source. Approval by an admin, and
  claims through SSO only, limit what a forged email can do.
- MongoDB has no transaction around the import: a failure halfway can leave a
  partial import. The "before" capture makes it restorable, and the request ends
  as `failed`.

## Testing on a LAN

`dev/migration_lan_test/` starts two `depictio local up` stacks and runs the
whole flow against them (`check.py`).

On one machine, with both instances reached through its LAN address:

```bash
dev/migration_lan_test/run.sh demo
```

The script header shows the two-machine variant.
