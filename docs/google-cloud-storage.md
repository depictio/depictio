# Using Google Cloud Storage

Depictio talks to object storage over the S3 protocol. Google Cloud Storage (GCS) serves
that protocol through its [XML API](https://cloud.google.com/storage/docs/interoperability)
at `https://storage.googleapis.com`, authenticated with **HMAC keys**. So Depictio can use
a GCS bucket with the usual `DEPICTIO_S3_*` settings. No GCS-specific backend is involved.

> **Status:** these steps have not yet been checked against a real GCS bucket. Items
> marked **[to be validated]** are what such a test needs to confirm. A native `gs://`
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
