# Samplesheets: CSV, TSV, YAML or JSON

`depictio ingest` reads a run's samplesheet (the pipeline's `--input` sheet) as
CSV or TSV, and also as YAML or JSON when the sheet is a list of records with
the same columns:

```yaml
- sample: test
  fastq_1: https://github.com/nf-core/test-datasets/raw/rnafusion/testdata/human/reads_1.fq.gz
  fastq_2: https://github.com/nf-core/test-datasets/raw/rnafusion/testdata/human/reads_2.fq.gz
  strandedness: forward
```

```json
[
  {
    "sample": "test",
    "fastq_1": "https://github.com/nf-core/test-datasets/raw/rnafusion/testdata/human/reads_1.fq.gz",
    "fastq_2": "https://github.com/nf-core/test-datasets/raw/rnafusion/testdata/human/reads_2.fq.gz",
    "strandedness": "forward"
  }
]
```

Each record is one row and each key one column. A key a record leaves out is
an empty cell. A cell must be a single value: a nested list or mapping is
refused, with the record and column named in the error.

The file extension decides how the sheet is read: `.yaml`, `.yml` or `.json`
is read as records, anything else as CSV/TSV, whatever format the template
declares. A YAML or JSON sheet is accepted wherever a CSV/TSV one is:

- `--var SAMPLESHEET_FILE=/path/to/samplesheet.yaml`, as a local path, an
  `http(s)://` URL or an `s3://` URL;
- auto-detection of `input/*samplesheet*` in a run folder. A CSV/TSV sheet
  still wins when the run has both;
- `depictio manifest from-table samplesheet.json`.

CSV and TSV sheets are read exactly as before.
