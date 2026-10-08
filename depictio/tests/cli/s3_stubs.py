"""One stubbed S3 for every CLI test that needs a remote data root.

``DataRoot``, the ``s3_prefix`` scan and remote recipe reads all reach S3
through :func:`depictio.cli.cli.utils.data_root.s3_read_client`, so replacing
that one factory is enough to run the whole remote path with no network: the
key list handed in here *is* the bucket.

Not a ``test_*`` module on purpose. Pytest does not collect it, and test
modules import their shared scaffolding from here rather than from each other.
"""

import io
import json
from pathlib import Path
from types import SimpleNamespace

from depictio.cli.cli.utils import data_root as data_root_module
from depictio.cli.cli.utils.data_root import data_root_for

# ── the stub ─────────────────────────────────────────────────────────────────


class StubS3Client:
    """Serves a fixed key list the way ``list_objects_v2`` does.

    Honours ``Prefix``, because an S3 prefix is a plain string match: a root
    that forgot its trailing slash would list a sibling prefix as its own.

    ``page_size`` splits the keys across pages, which is what the pagination
    and key-budget tests need. ``is_truncated`` sets ``IsTruncated`` on every
    page; left as ``None`` the key is absent, exactly as a stub that never
    thought about it would leave it.

    ``pages_served`` and ``get_object_calls`` are what the "one listing answers
    everything" and "the client is built once" tests assert on.
    """

    def __init__(self, bodies: dict[str, bytes], page_size: int = 100, is_truncated=None):
        self.bodies = bodies
        self.page_size = page_size
        self.is_truncated = is_truncated
        self.pages_served = 0
        self.get_object_calls: list[str] = []

    def _pages_for(self, prefix: str):
        keys = [key for key in self.bodies if key.startswith(prefix)]
        for start in range(0, len(keys), self.page_size):
            page: dict = {
                "Contents": [
                    {"Key": key, "Size": len(self.bodies[key]), "ETag": f'"{key}-etag"'}
                    for key in keys[start : start + self.page_size]
                ]
            }
            if self.is_truncated is not None:
                page["IsTruncated"] = self.is_truncated
            yield page

    def get_paginator(self, _name):
        client = self

        class _Paginator:
            def paginate(self, Bucket=None, Prefix="", **_kwargs):  # noqa: N803
                for page in client._pages_for(Prefix):
                    client.pages_served += 1
                    yield page

        return _Paginator()

    def get_object(self, Bucket, Key):  # noqa: N803 - boto3's own spelling
        self.get_object_calls.append(Key)
        return {"Body": io.BytesIO(self.bodies[Key])}


def install_s3_listing(
    monkeypatch, tree: dict[str, bytes], key_prefix: str = "", **client_kwargs
) -> StubS3Client:
    """Stub every S3 read with ``tree``, keyed relative to ``key_prefix``.

    ``key_prefix`` defaults to "" so a caller can pass whole keys instead.
    """
    client = StubS3Client(
        {f"{key_prefix}{rel}": body for rel, body in tree.items()}, **client_kwargs
    )
    monkeypatch.setattr(data_root_module, "s3_read_client", lambda _url, _cfg: client)
    return client


def s3_cli_config():
    """A config with per-project credentials, so no allowlist entry is needed."""
    return SimpleNamespace(
        remote_storage_options={
            "aws_access_key_id": "k",
            "aws_secret_access_key": "s",
            "endpoint_url": "https://s3.example",
        },
        s3_storage=None,
    )


def write_tree(base: Path, tree: dict[str, bytes]) -> Path:
    """The same fixture on disk, so local and remote can be compared directly."""
    for rel, body in tree.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return base


# ── the shared megatest fixture ──────────────────────────────────────────────
#
# Resolving a template against an ``s3://`` prefix has to be proved on a real
# shipped template: the value of the feature is that a template written for a
# directory works unchanged against a prefix. So the tree below is shaped like
# the nf-core/ampliseq AWS megatest prefix the template documents - the
# samplesheet and metadata under input/, the run's params under pipeline_info/,
# the MultiQC parquet, and one QIIME2 output per recipe family - while the data
# itself stays synthetic.

S3_BUCKET = "nf-core-awsmegatests"
S3_KEY_PREFIX = "ampliseq/results-3d5c7e5b/"
S3_ROOT = f"s3://{S3_BUCKET}/{S3_KEY_PREFIX.rstrip('/')}"

MEGATEST_PARAMS = {
    "metadata": "s3://nf-core-awsmegatests/ampliseq/Metadata_full.tsv",
    "FW_primer": "GTGYCAGCMGCCGCGGTAA",
    "ancombc": False,
}

MEGATEST_TREE: dict[str, bytes] = {
    "input/samplesheet.csv": b"sampleID,forwardReads\nS1,S1_R1.fastq.gz\n",
    "input/Metadata_full.tsv": b"sample\thabitat\ttreatment\nS1\tsoil\tcontrol\n",
    "pipeline_info/params_2026-01-16_12-00-00.json": json.dumps(MEGATEST_PARAMS).encode(),
    "multiqc/multiqc_data/multiqc.parquet": b"PAR1",
    "qiime2/barplot/level-2.csv": b"index,Bacteria\nS1,42\n",
    "qiime2/phylogenetic_tree/tree.nwk": b"(S1);",
}


def install_megatest_listing(monkeypatch, tree: dict[str, bytes] | None = None) -> StubS3Client:
    """Serve ``tree`` (``MEGATEST_TREE`` by default) under the megatest prefix."""
    return install_s3_listing(
        monkeypatch, MEGATEST_TREE if tree is None else tree, key_prefix=S3_KEY_PREFIX
    )


def s3_data_root(monkeypatch, tree: dict[str, bytes], location: str = S3_ROOT):
    """A remote :class:`DataRoot` over ``tree``, served from the megatest prefix."""
    install_megatest_listing(monkeypatch, tree)
    return data_root_for(location, s3_cli_config())
