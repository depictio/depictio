# Migrating an existing install from MinIO to SeaweedFS

Depictio's **bundled** object store is now [SeaweedFS](https://github.com/seaweedfs/seaweedfs)
(`weed mini`, Apache-2.0) instead of MinIO, whose community edition stopped
receiving releases in 2025 and was archived in 2026.

Nothing changes for you if:

- you point Depictio at an **external S3** (AWS, NetApp, Ceph, your own MinIO, …)
  via `DEPICTIO_S3_PUBLIC_URL` / `DEPICTIO_S3_EXTERNAL_SERVICE=true` or
  Helm `s3.enabled: false` (the legacy `DEPICTIO_MINIO_*` names and Helm
  `minio.enabled: false` still work): the S3 contract is untouched;
- this is a **fresh** install.

The config names are now store-neutral, and the old ones keep working:

- the compose service is `s3`, with a `minio` network alias, so
  `http://minio:9000` in existing CLI configs still resolves;
- the env prefix is `DEPICTIO_S3_*`; the legacy `DEPICTIO_MINIO_*` variables are
  still read as a fallback when the new one is unset (the new name wins when
  both are set);
- the Helm values key is `s3:`; a legacy `minio:` block (and
  `persistence.minio`, `secrets.minioRoot*`, `global.urlPattern.templates.minio`)
  is still merged in and renders the same manifests, with a deprecation warning
  in the install/upgrade notes.

### Renamed settings

| Old name | New name |
|----------|----------|
| `DEPICTIO_MINIO_ROOT_USER` | `DEPICTIO_S3_ROOT_USER` |
| `DEPICTIO_MINIO_ROOT_PASSWORD` | `DEPICTIO_S3_ROOT_PASSWORD` |
| `DEPICTIO_MINIO_BUCKET` | `DEPICTIO_S3_BUCKET` |
| `DEPICTIO_MINIO_PUBLIC_URL` | `DEPICTIO_S3_PUBLIC_URL` |
| `DEPICTIO_MINIO_EXTERNAL_SERVICE` | `DEPICTIO_S3_EXTERNAL_SERVICE` |
| `DEPICTIO_MINIO_VERIFY_TLS` | `DEPICTIO_S3_VERIFY_TLS` |
| `DEPICTIO_MINIO_EXTERNAL_HOST` / `_PORT` / `_PROTOCOL` | `DEPICTIO_S3_EXTERNAL_HOST` / `_PORT` / `_PROTOCOL` |
| `DEPICTIO_MINIO_SERVICE_NAME` / `_SERVICE_PORT` | `DEPICTIO_S3_SERVICE_NAME` / `_SERVICE_PORT` |
| `settings.minio` (Python) | `settings.s3` (`settings.minio` kept as an alias) |
| compose service `minio` | compose service `s3` (network alias `minio`) |
| compose port vars `MINIO_PORT` / `MINIO_CONSOLE_PORT` | `S3_PORT` / `S3_CONSOLE_PORT` |
| Helm `minio.*` (incl. `minio.env.DEPICTIO_MINIO_*`) | Helm `s3.*` (`s3.env.DEPICTIO_S3_*`) |
| Helm `persistence.minio` | Helm `persistence.s3` |
| Helm `secrets.minioRootUser` / `secrets.minioRootPassword` | Helm `secrets.s3RootUser` / `secrets.s3RootPassword` |
| Helm `global.urlPattern.templates.minio` | Helm `global.urlPattern.templates.s3` |

The Helm ConfigMaps export both the `DEPICTIO_S3_*` and the legacy
`DEPICTIO_MINIO_*` variables, so a backend image older than this rename keeps
working; the legacy copies will be dropped in a later release.

### Still named `minio` on purpose

Some names are part of live state, so renaming them would break upgrades:

- Helm: the `<release>-minio` Deployment and Service and their `app: minio`
  selector label (a Deployment selector is immutable, so `helm upgrade` would
  fail);
- Helm: the `<release>-minio-pvc` PVC (a new name would start the store on an
  empty volume);
- Helm: the `<release>-minio-ingress` / `<release>-minio-httproute` routes and
  the public host `<release>-minio.<domain>` (plus `-minio.gw.`): DNS records,
  TLS certificates and presigned URLs point at it;
- Helm: the Secret data keys `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`, through
  which the chart reads back the generated password so it stays stable across
  upgrades;
- compose: the backup-only `minio-backup` service and the
  `docker-compose.backup-minio.yaml` / `docker-compose.no-minio.yaml` /
  `docker-compose.minio-legacy.yaml` file names.

## Why a migration is needed

MinIO stores objects in its own on-disk layout (`xl.meta` + parts). SeaweedFS
cannot read it, so a pre-existing `minio_data` volume/directory is **not
reused**. The new store writes to a new `seaweedfs_data` volume/directory and
starts empty; your existing data stays intact in `minio_data` until you delete
it. Until you copy it over, dashboards backed by that data will show missing
Delta tables/images.

The copy goes through the S3 API: the old MinIO is started next to the new store
and `scripts/migrate_minio_to_seaweedfs.py` copies the bucket. Object keys are
identical on both sides, so MongoDB does not need to change.

## Docker Compose

1. Pull and start the new stack (the new store boots empty):

   ```bash
   docker compose pull
   docker compose up -d
   ```

2. Start the legacy MinIO side-car on its untouched data (loopback port 9100):

   ```bash
   # named-volume install (root docker-compose.yaml)
   docker compose -f docker-compose.yaml \
     -f docker-compose/docker-compose.minio-legacy.yaml up -d minio-legacy

   # bind-mount install (docker-compose.dev.yaml, data under ./data/minio_data)
   MINIO_LEGACY_DATA=./data/minio_data docker compose -f docker-compose.dev.yaml \
     -f docker-compose/docker-compose.minio-legacy.yaml up -d minio-legacy
   ```

   The dev compose publishes the new store on `127.0.0.1:9000`; the root
   `docker-compose.yaml` does not publish it, so for that install add a
   temporary port mapping (an override file with `ports: ["127.0.0.1:9000:9000"]`
   on the `s3` service) or run the script inside the backend container.

3. Dry run, copy, verify (credentials default to `DEPICTIO_S3_ROOT_USER` /
   `DEPICTIO_S3_ROOT_PASSWORD` from your `.env`, falling back to the legacy
   `DEPICTIO_MINIO_ROOT_*` names; bucket to `depictio-bucket`):

   ```bash
   set -a; source .env; set +a          # or docker-compose/.env for the dev stack
   uv run scripts/migrate_minio_to_seaweedfs.py --dry-run
   uv run scripts/migrate_minio_to_seaweedfs.py --verify
   ```

   Re-running with `--skip-existing` resumes an interrupted copy.

4. Open a dashboard and check Delta tables / images load.

5. Remove the side-car and, once satisfied, the old data:

   ```bash
   docker compose -f docker-compose.yaml \
     -f docker-compose/docker-compose.minio-legacy.yaml rm -sf minio-legacy
   docker volume rm "$(docker compose config --format json | jq -r .name)_minio_data"   # named volume
   # or: rm -rf ./data/minio_data                                                    # bind mount
   ```

Rollback: check out the previous release's compose files; `minio_data` is untouched.

## Helm

The chart keeps the `<release>-minio` Deployment/Service/PVC names, so an
upgrade re-uses the same PVC. That PVC is `ReadWriteOnce`: the old MinIO pod and
the new SeaweedFS pod cannot mount it at the same time, so copy in two hops via a
local directory.

```bash
# 1. BEFORE upgrading — old MinIO still running
kubectl port-forward svc/<release>-minio 9100:9000 &
uv run scripts/migrate_minio_to_seaweedfs.py \
  --source-access-key "$(kubectl get secret <release>-depictio-secrets -o jsonpath='{.data.MINIO_ROOT_USER}' | base64 -d)" \
  --source-secret-key "$(kubectl get secret <release>-depictio-secrets -o jsonpath='{.data.MINIO_ROOT_PASSWORD}' | base64 -d)" \
  --export-dir ./s3-export

# 2. Upgrade the chart (SeaweedFS starts on the same PVC and ignores MinIO's files)
helm upgrade <release> ./helm-charts/depictio -f values.yaml

# 3. Import
kubectl port-forward svc/<release>-minio 9000:9000 &
uv run scripts/migrate_minio_to_seaweedfs.py \
  --target-endpoint http://127.0.0.1:9000 \
  --target-access-key "$(kubectl get secret <release>-depictio-secrets -o jsonpath='{.data.MINIO_ROOT_USER}' | base64 -d)" \
  --target-secret-key "$(kubectl get secret <release>-depictio-secrets -o jsonpath='{.data.MINIO_ROOT_PASSWORD}' | base64 -d)" \
  --import-dir ./s3-export --verify

# 4. Reclaim the space used by MinIO's old layout on the PVC
kubectl exec deploy/<release>-minio -- sh -c 'rm -rf /data/.minio.sys /data/depictio-bucket'
```

Alternatively, if you have a second bucket on an external S3, copy there first
(`--target-endpoint https://…`) and import from it after the upgrade.

## Notes on the new store

- S3 API is on port 9000 as before (`weed mini -s3.port=9000`); WebDAV is off.
- The SeaweedFS admin UI (port 9001 in the dev compose, off in prod compose and
  Helm by default: `s3.adminUI.enabled`) is protected with the root
  access/secret key pair.
- Root credentials are re-applied from the environment on every start, so
  rotating `DEPICTIO_S3_ROOT_*` + restart works as it did with MinIO.
- Health check: `GET http://<host>:9000/healthz` (replaces `/minio/health/live`).
- Very large object counts: pass `-volume.index=leveldb` (Helm `s3.extraArgs`)
  to move the volume index off memory.
