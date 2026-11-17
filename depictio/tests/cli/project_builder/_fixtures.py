"""Scaffolding shared by the Project Builder core tests.

Not a ``test_*`` module, so pytest does not collect it. Everything here imports
only what the CLI-only install has: these tests run in the job that has no
FastAPI, Starlette or Celery.
"""

from __future__ import annotations

from depictio.project_builder.assemble import (
    DcDraft,
    ProjectDraft,
    TableProps,
    WorkflowDraft,
)

QUANT = b"gene\tcount\nA\t1\nB\t2\n"
SHEET = b"sample,condition\nS1,ctrl\nS2,treat\n"

# One pipeline run, with one file of each kind the builder can author.
RUN_TREE: dict[str, bytes] = {
    "samplesheet.csv": SHEET,
    "star/S1/quant.tsv": QUANT,
    "star/S2/quant.tsv": QUANT,
    "star/S3/quant.tsv": QUANT,
    "multiqc/multiqc_data/multiqc.parquet": b"PAR1",
    "trees/tree.nwk": b"((a,b),c);",
    "regions/areas.geojson": b'{"type": "FeatureCollection", "features": []}',
    "variants/S1.vcf.gz": b"x",
    "variants/S1.vcf.gz.tbi": b"x",
    "variants/S2.vcf.gz": b"x",
    "images/a.png": b"x",
    "images/b.png": b"x",
    "images.csv": b"sample,img\nS1,a.png\nS2,b.png\n",
}


def table_dc(tag: str = "sheet", *, path: str = "samplesheet.csv", **fields) -> DcDraft:
    """A single-file CSV table collection."""
    return DcDraft(
        tag=tag,
        type="table",
        mode="single",
        path=path,
        props=TableProps(format="csv", separator=","),
        **fields,
    )


def scan_dc(tag: str = "quant", regex: str = r"^quant\.tsv$", **fields) -> DcDraft:
    """A recursive TSV table collection."""
    return DcDraft(
        tag=tag,
        type="table",
        mode="recursive",
        regex=regex,
        props=TableProps(format="tsv", separator="\t"),
        **fields,
    )


def project(*collections: DcDraft, name: str = "Lab Run", **workflow) -> ProjectDraft:
    """A project of one workflow holding ``collections``."""
    return ProjectDraft(
        name=name,
        workflows=[WorkflowDraft(name="main", data_collections=list(collections), **workflow)],
    )
