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

Each record is one row and each key one column header. The YAML above is the
same sheet as this CSV:

```csv
sample,fastq_1,fastq_2,strandedness
test,https://github.com/nf-core/test-datasets/raw/rnafusion/testdata/human/reads_1.fq.gz,https://github.com/nf-core/test-datasets/raw/rnafusion/testdata/human/reads_2.fq.gz,forward
```

A key a record leaves out is an empty cell. A cell must be a single value: a
nested list or mapping is refused, with the record and key named in the error.

## Value types

A YAML or JSON sheet reads to exactly the table the same CSV would. Every value
is taken as the text of its cell, then typed the way a CSV column is: `1` and
`2.5` are numbers, `true`/`false` booleans, and everything else is text. YAML's
own typing does not apply, so `yes`, `on`, `Off`, `null` or `2024-01-05` stay
text, as they would in a CSV. Nothing needs quoting.

## Validating a sheet

A template checks a samplesheet's fields through a recipe: the source's
`input_schema` names the fields it needs and their types, and the check runs on
the table once read, whatever its format. A YAML/JSON sheet missing one is
refused with its keys named:

```
Recipe demo: source 'samplesheet' lacks input key(s) ['strandedness']. Got keys: ['sample', 'fastq_1']
```

(a CSV/TSV sheet gets the same message with "column(s)"). A plain `Table`
collection, such as rnafusion's `samplesheet`, does not check its columns, in
any format.

The file extension decides how the sheet is read: `.yaml`, `.yml` or `.json`
is read as records, anything else as CSV/TSV, whatever format the template
declares. A YAML or JSON sheet is accepted wherever a CSV/TSV one is:

- `--var SAMPLESHEET_FILE=/path/to/samplesheet.yaml`, as a local path, an
  `http(s)://` URL or an `s3://` URL;
- auto-detection of `input/*samplesheet*` in a run folder. A CSV/TSV sheet
  still wins when the run has both;
- `depictio manifest from-table samplesheet.json`.

CSV and TSV sheets are read exactly as before.
