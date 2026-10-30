# Using Google Cloud Storage

Depictio talks to object storage over the S3 protocol. Google Cloud Storage (GCS) serves
that protocol through its [XML API](https://cloud.google.com/storage/docs/interoperability)
at `https://storage.googleapis.com`, authenticated with **HMAC keys**. So Depictio can use
a GCS bucket with the usual `DEPICTIO_S3_*` settings. No GCS-specific backend is involved.

> **Status:** reading a public GCS bucket was checked end to end (see below). Using
> GCS as the instance's own storage (HMAC keys, writes, deletes) has not been yet:
> items marked **[to be validated]** are what such a test needs to confirm. A native `gs://`
> backend (service-account or Workload Identity auth, no HMAC keys) is not available.

## 1. Prepare the bucket

1. Create the bucket in GCP yourself (any location). Depictio creates its bucket at
   startup only when it is missing, and creating one through the XML API needs a
   project and a location that Depictio does not send.
2. Create a service account with **Storage Object Admin** on that bucket.
3. Create an HMAC key for it (*Cloud Storage → Settings → Interoperability*). You get
   an access ID (`GOOG1…`) and a 40-character secret.

## 2. Configure Depictio

```bash
DEPICTIO_S3_PUBLIC_URL=https://storage.googleapis.com
DEPICTIO_S3_EXTERNAL_SERVICE=true
DEPICTIO_S3_ROOT_USER=GOOG1...          # HMAC access ID
DEPICTIO_S3_ROOT_PASSWORD=<HMAC secret>
DEPICTIO_S3_BUCKET=<your-bucket>
```

With `EXTERNAL_SERVICE=true` the API, the worker and the CLI all use the public URL.
Don't start the bundled `s3` service.

## Reading pipeline results from a GCS bucket

This is separate from the instance storage above: the instance can stay on SeaweedFS
(or anything else) while it **reads** its sources from a GCS bucket. Give the
endpoint as the project's storage settings, or as `remote_storage_options` in the CLI
configuration:

```yaml
# CLI configuration (e.g. the one `depictio local up` writes)
remote_storage_options:
  endpoint_url: https://storage.googleapis.com
  bucket: <bucket>
  # access_key_id / secret_access_key: an HMAC key for a private bucket.
  # Leave both out for a public bucket: it is read without a signature.
```

and point a data collection at an `s3://<bucket>/<key>` location (`scan: {mode: url}`,
`s3_prefix` or a manifest). Checked on 2026-10-30 against the public
`gs://gcp-public-data--broad-references` bucket, with `depictio local up` and
`depictio ingest --project-config-path` (a `url` scan of a 7,558-row BED file): no
keys, the read went through `storage.googleapis.com` and the table was ingested into
the instance's Delta store. The project storage test
(`POST /projects/{id}/storage/test`) passes with the same settings.

The run-folder browser and *create a project from a run* ask for keys on a bucket
outside the instance's allowlist. `DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS` reads its buckets
on the AWS endpoint only, so it cannot open a public GCS bucket.

## What Depictio adjusts for GCS

- **Checksums.** boto3 >= 1.36 adds CRC checksums to every upload by default, and
  GCS rejects them. Depictio sets `AWS_REQUEST_CHECKSUM_CALCULATION` and
  `AWS_RESPONSE_CHECKSUM_VALIDATION` to `when_required` (the pre-1.36 behaviour, still
  valid on AWS) when it loads its settings. A value you set yourself wins.
- **Bulk delete.** The GCS XML API has no multi-object delete (`DeleteObjects`). Every
  cleanup (data collections, projects, MultiQC reports, prerendered figures, backups)
  falls back to deleting one object at a time when the bulk call fails.

## Known limits

- **`depictio data vacuum` is not supported.** delta-rs deletes old files with a bulk
  delete, which GCS refuses. Vacuum is a manual command, never run by ingestion, so
  tables still read and write; old files just stay. **[to be validated]**
- **One writer per Delta table at a time.** Depictio commits with
  `AWS_S3_ALLOW_UNSAFE_RENAME=true` (no lock), the same as on the bundled SeaweedFS.
  Two concurrent ingests into the same data collection can lose a commit.
- **Region.** Clients sign with region `us-east-1`. GCS documents `auto`, and is
  expected to accept any region in the signature. **[to be validated]**
- **Multipart uploads** (large Parquet, MultiQC and image files) use the S3 multipart
  API, which GCS supports. **[to be validated]**
- **Presigned URLs** (indexed files, images) are SigV4 URLs on
  `storage.googleapis.com`. A browser reading them directly (JBrowse) needs a CORS
  policy on the bucket. **[to be validated]**
- **`depictio` S3 checks** call `ListBuckets`, which for an HMAC key lists the
  service account's project. **[to be validated]**
