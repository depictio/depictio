# Indexed files (VCF, BAM, bigWig, GFF3)

Some genomic outputs are too dense to become a table. A sarek run publishes a
filtered VCF per sample with its tabix index; chipseq, atacseq, cutandrun,
nanoseq and methylseq publish bigWig coverage. Loading those into a delta table
means materialising millions of rows to draw a few kilobases of them.

The `indexed_file` data-collection type takes the other route: the files are
copied to object storage as they are, and the browser reads only the window the
reader is looking at, with HTTP range requests through the file's own index.
That is what GenomeSpy's lazy data sources do, and a `genome_view` component
with `source: file` is what draws them.

## Declaring the collection

```yaml
data_collections:
  - data_collection_tag: sarek_filtered_vcf
    description: Filtered VCF per sample, with its tabix index
    config:
      type: indexed_file
      metatype: metadata
      scan:
        mode: recursive
        scan_parameters:
          regex_config:
            pattern: .*\.filtered\.vcf\.gz$
      dc_specific_properties:
        format: vcf          # vcf | bam | bigwig | bigbed | gff3 | fasta | tabix
        assembly: hg38
        sample_regex: variant_calling/[^/]+/(?P<sample>[^/]+)/
        max_file_size_mb: 512
```

Notes:

- `format` picks the lazy source. There is no CRAM source, so a sarek CRAM
  cannot be shown this way; mirror BAM if you need alignments.
- The index sidecar is found next to the primary file, by suffix: `.tbi` for
  vcf, gff3 and tabix, `.bai` for bam, `.fai` for fasta. bigWig and bigBed carry
  their index inside the file. Override with `index_suffix` (`.csi`, for
  example); set it to an empty string to declare a self-indexed format.
- One object per sample. `sample_regex` names the sample from the file path
  through a named `sample` group; without it the file name is used, with its
  format and compression suffixes stripped. A file whose sample is already taken
  is skipped rather than silently overwriting the first one.
- `max_file_size_mb` (default 512) caps what ingest will push.
- A file with no index beside it is skipped, with the reason in the CLI log.

## Where the objects land

`s3://<bucket>/indexed_files/<dc_id>/<sample>/<file name>`, plus the index under
the same prefix. The prefix is deliberately not the collection id at the bucket
root: the orphan cleanup deletes any 24-hex top-level prefix that has no
deltatable and no MultiQC document, and an `indexed_file` collection has
neither. Phylogeny trees sit outside the root for the same reason.

## Serving them to the browser

Two routes, both gated by the same project-level read check as the other
data-collection routes:

- `GET /depictio/api/v1/files/indexed/{dc_id}` returns the manifest: the format,
  the assembly, and one entry per sample with a presigned URL for the object and
  one for its index.
- `GET /depictio/api/v1/files/{dc_id}/{sample}/{name}` returns a presigned URL
  for a single object.

Presigned URLs live 15 minutes. They are signed against the storage endpoint the
*browser* can reach (`DEPICTIO_MINIO_PUBLIC_URL`, or
`DEPICTIO_MINIO_EXTERNAL_HOST` and `DEPICTIO_MINIO_EXTERNAL_PORT`), because a
SigV4 signature covers the host: a URL signed for the in-cluster endpoint is
rejected when a browser uses it, even if the bytes are reachable another way.

## CORS on the storage

The bytes never pass through the API, so the storage itself has to answer the
browser. It needs to allow the viewer's origin and to serve range requests.

Dev compose already sets it on the MinIO service:

```yaml
MINIO_API_CORS_ALLOW_ORIGIN: ${DEPICTIO_MINIO_CORS_ALLOW_ORIGIN:-*}
```

MinIO's own default for `api.cors_allow_origin` is already `*`; the variable is
spelled out so a deployment can narrow it to the viewer's origin without editing
compose. Equivalent settings elsewhere:

- MinIO outside compose: `mc admin config set <alias> api
  cors_allow_origin="https://viewer.example.org"` then `mc admin service restart
  <alias>`.
- Helm: the chart's configmap is an allowlist, so a variable that is not listed
  is dropped. Add `MINIO_API_CORS_ALLOW_ORIGIN` to the MinIO deployment's `env`
  in `helm-charts/depictio/templates/deployments.yaml` and expose it through
  `values.yaml` under `minio.env`. Nothing new is needed on the API side.
- AWS S3: a bucket CORS rule allowing `GET` and `HEAD` from the viewer's origin,
  with `Range` in `AllowedHeaders` and `Content-Range`, `Content-Length`,
  `Accept-Ranges` and `ETag` in `ExposeHeaders`.
- NetApp StorageGRID and other gateways: the same CORS configuration, and check
  that range requests are not rewritten. The EMBL gateway's quirks are covered
  in the deployment notes.

A deployment that does not set any of this simply does not show file tracks:
`genome_view` falls back to `source: table`.

## Drawing them

Bind a `genome_view` component to the collection and set `source: file`. The
per-format layouts follow GenomeSpy's own examples: VCF as sticks and balls,
bigWig as per-pixel coverage bars, GFF3 as packed transcripts, bigBed and tabix
as packed intervals, BAM as a coverage profile or a read pileup.

The `file_*` options on the component config tune it: `file_info_fields` and
`file_category_field` promote VCF INFO keys and rank the variants by one of
them, `file_window_size` moves the zoom level at which fetching starts,
`file_max_lanes` caps the stacked samples, `file_tabix_columns` names the
columns of a bgzip and tabix indexed interval file, and `file_bam_view` chooses
coverage or pileup.

A file-backed tile loads the full GenomeSpy bundle (the format parsers), through
a dynamic import taken only when a tile declares `source: file`. Table-backed
tiles keep the lean bundle and their current download size.

## Gene annotation for file-backed tracks

The bundled JSON gene table (`assets/genomes/<assembly>.genes.json`) is a flat
gene list, which is what keeps it under a megabyte. A file-backed track can
instead read a tabix-indexed GENCODE GFF3 and draw real transcript models:

```bash
python dev/advanced_viz_kinds/build_genome_gene_assets.py --format gff3 --assembly hg38
```

It needs `bgzip` and `tabix` from htslib; without them the script prints the
equivalent shell pipeline and skips. The output is tens of megabytes and is not
committed: host it wherever the browser can reach it with CORS and range
requests.
