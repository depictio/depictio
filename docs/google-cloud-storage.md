# Using Google Cloud Storage

Depictio talks to object storage over the S3 protocol. Google Cloud Storage (GCS) serves
that protocol through its [XML API](https://cloud.google.com/storage/docs/interoperability)
at `https://storage.googleapis.com`. No GCS-specific backend is involved.

> **Status:** Depictio **reads** pipeline results from a GCS bucket; this was checked
> end to end (see below). Using GCS as the **instance's own storage** (where Depictio
> writes its tables) is not supported yet; it is tracked in
> [#1298](https://github.com/depictio/depictio/issues/1298), along with a native `gs://`
> backend (service-account or Workload Identity auth, no HMAC keys).

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

## Not supported yet: GCS as the instance's storage

Pointing `DEPICTIO_S3_*` at `https://storage.googleapis.com` is not supported yet
([#1298](https://github.com/depictio/depictio/issues/1298)). Depictio already handles two
known incompatibilities, so that work starts from there:

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
