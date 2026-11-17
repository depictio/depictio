# Using Google Cloud Storage

Depictio uses Google Cloud Storage (GCS) in two ways:

- **As the instance's own storage, natively** (`DEPICTIO_STORAGE_BACKEND=gcs`): Delta
  tables, MultiQC reports, images and every other object Depictio writes live in a GCS
  bucket, stored as `gs://` locations, with **no static key**. This is the section below.
- **As a source of pipeline results, through the S3 API** (`storage.googleapis.com`),
  while the instance keeps its own S3 store. See [Reading pipeline results from a GCS
  bucket](#reading-pipeline-results-from-a-gcs-bucket).

## GCS as the instance's storage (native backend)

The instance bucket is reached through one storage interface
(`depictio/models/storage/`, issue [#1358](https://github.com/depictio/depictio/issues/1358)).
The GCS backend uses [`obstore`](https://github.com/developmentseed/obstore), the
Python bindings of the same Rust `object_store` that Polars and delta-rs read and
write Delta tables with.

### Configuration

```bash
DEPICTIO_STORAGE_BACKEND=gcs
DEPICTIO_GCS_BUCKET=<existing bucket>
# Optional: a service-account key file. Unset: Application Default Credentials.
DEPICTIO_GCS_SERVICE_ACCOUNT_PATH=/var/run/secrets/gcs/key.json
```

No `DEPICTIO_S3_*` secret is required in this mode. The bucket must exist: creating
one needs a project and a location, so Depictio only checks it at startup (it can list
it, then write and delete `.depictio/write_test`).

Credentials, in order:

1. `DEPICTIO_GCS_SERVICE_ACCOUNT_PATH`, a key file;
2. otherwise Application Default Credentials: the GKE / GCE metadata server (Workload
   Identity), `GOOGLE_APPLICATION_CREDENTIALS`, or `gcloud auth application-default login`
   on a laptop.

External-account Workload Identity Federation (a workload *outside* GCP exchanging its
own token) is not supported by `object_store` yet, so Delta writes cannot use it.

### Permissions

On the bucket, the service account needs **Storage Object Admin**
(`roles/storage.objectAdmin`). For presigned URLs (3D structures and genome browser
tracks read straight from the bucket) without a key file, it signs through IAM
`signBlob`: grant it **Service Account Token Creator** on itself. Otherwise set
`DEPICTIO_S3_BROWSER_ACCESS=proxy` and the API streams those files instead. Browsers
fetching signed URLs need a CORS rule on the bucket allowing `GET`, `HEAD` and the
`Range` header from the viewer's origin.

### Helm (GKE Workload Identity)

```yaml
storage:
  backend: gcs
gcs:
  bucket: my-depictio-bucket
s3:
  enabled: false          # no bundled SeaweedFS
serviceAccount:
  create: true
  annotations:
    iam.gke.io/gcp-service-account: depictio@<project>.iam.gserviceaccount.com
```

Bind the Kubernetes service account to the Google one
(`roles/iam.workloadIdentityUser`) as GKE's Workload Identity documentation describes.

### What is stored

Locations are real `gs://bucket/key` URIs (`delta_table_location`, MultiQC
`s3_location`, image `s3_base_folder`, ...). The field names keep their `s3_` prefix.
An instance on S3 keeps `s3://` locations; nothing is migrated. Delta commits rely on
GCS preconditions, so concurrent writers are safe without `AWS_S3_ALLOW_UNSAFE_RENAME`.

### Not available on a GCS instance yet

- Project migration between instances and S3-to-S3 backups: they refuse with a clear
  message (both are S3-only).
- Reading *pipeline results* from a private `gs://` folder with the instance's own
  credentials: run folders and remote reads still go through the S3 API (below).

### Testing

`depictio/tests/storage/` runs the storage contract against a GCS emulator and a public
bucket; CI runs it in the `storage-gcs` job:

```bash
docker run -d -p 4443:4443 tustvold/fake-gcs-server -scheme http -backend memory -public-host localhost:4443
DEPICTIO_TEST_GCS_EMULATOR=http://localhost:4443 DEPICTIO_TEST_GCS_PUBLIC=1 \
  uv run --extra dev pytest depictio/tests/storage
```

The emulator must be that build: upstream `fsouza/fake-gcs-server` refuses the XML-API
uploads `object_store` sends. It also ignores GCS preconditions, so the concurrent-commit
test, and presigned URLs, run only against a real bucket: set `DEPICTIO_TEST_GCS_BUCKET`
(with Application Default Credentials) to enable the `gcs_live` tests.

## Reading pipeline results from a GCS bucket

The instance keeps its own storage (the bundled SeaweedFS, or any S3) and **reads** its
sources from a GCS bucket. Give the endpoint as the project's storage settings, or as
`remote_storage_options` in the CLI configuration:

```yaml
# CLI configuration (e.g. the one `depictio local up` writes)
remote_storage_options:
  endpoint_url: https://storage.googleapis.com
  bucket: <bucket>
  # access_key_id / secret_access_key: an HMAC key for a private bucket
  # (Cloud Storage → Settings → Interoperability, a service account with
  # Storage Object Viewer on the bucket). Leave both out for a public bucket:
  # it is read without a signature.
```

Then point a data collection at an `s3://<bucket>/<key>` location (`scan: {mode: url}`,
`s3_prefix` or a manifest).

Checked on 2026-10-30 against the public `gs://gcp-public-data--broad-references`
bucket with `depictio local up` and `depictio ingest --project-config-path` (a `url`
scan of a 7,558-row BED file): no keys were needed, the read went through
`storage.googleapis.com`, and the table was ingested into the instance's Delta store.
The project storage test (`POST /projects/{id}/storage/test`) passes with the same
settings.

### Limits

- The run-folder browser and *create a project from a run* ask for keys on a bucket
  outside the instance's allowlist. `DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS` reads its
  buckets on the AWS endpoint only, so it cannot open a public GCS bucket.
- Reading with an HMAC key (private bucket) uses the same path, signed. It has not been
  checked against a real private bucket yet.

## Instance storage through the S3 API (HMAC keys)

Prefer the native backend above. Pointing `DEPICTIO_S3_*` at
`https://storage.googleapis.com` with an HMAC key is untested end to end. Depictio
handles two known incompatibilities of that API:

- **Checksums.** boto3 >= 1.36 adds CRC checksums to every upload by default, and GCS
  rejects them. Depictio sets `AWS_REQUEST_CHECKSUM_CALCULATION` and
  `AWS_RESPONSE_CHECKSUM_VALIDATION` to `when_required` (the pre-1.36 behaviour, still
  valid on AWS) when it loads its settings. A value you set yourself wins.
- **Bulk delete.** The GCS XML API has no multi-object delete (`DeleteObjects`). Every
  cleanup (data collections, projects, MultiQC reports, prerendered figures, backups)
  falls back to deleting one object at a time when the bulk call fails.

Still to validate: Delta commits (delta-rs with `AWS_S3_ALLOW_UNSAFE_RENAME`, no lock),
multipart uploads, the region in the signature, presigned URLs and bucket CORS,
`ListBuckets` in the S3 checks, and `depictio data vacuum`, which relies on bulk delete.
