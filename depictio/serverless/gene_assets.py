"""Gene tables a bundle's genome tiles draw, shipped inside the bundle.

The genome_view, cnv_profile and sashimi renderers draw a gene lane (and
genome_view resolves a typed gene name) from
``depictio/viewer/public/assets/genomes/<assembly>.genes.json``, which the
server serves under the app's base URL. A static bundle is opened from disk,
where ``./assets/genomes/...`` is a file:// request that fails: the
"Alternative splicing" tab of an advanced-viz bundle made exactly that request.

So the producer ships the table of every assembly a genome tile names, as
``inline_blobs["genes_<assembly>"]`` (gzip, then base64: hg38 is 0.8 MB of
JSON and about 0.3 MB in the file), and the static runtime answers the
renderer's request from it (``static-runtime/genomeAssets.ts``). A tile whose
assembly has no table here, or one a reader picks later in the tile's
settings, draws no lane and makes no request.
"""

from __future__ import annotations

import base64
import gzip
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Assemblies a gene table exists for (``geneAnnotations.ts``'s
#: GENE_ASSET_ASSEMBLIES): any other name would never have been fetched.
GENE_ASSET_ASSEMBLIES = ("hg38", "hg19", "mm10")

#: advanced_viz kinds whose renderer reads a gene table.
GENE_TABLE_KINDS = frozenset({"genome_view", "cnv_profile", "sashimi"})

#: Config keys naming the assembly a tile reads genes for: the lane
#: (``annotation``) and genome_view's gene search (``assembly``).
_ASSEMBLY_KEYS = ("annotation", "assembly")

BLOB_PREFIX = "genes_"

_SOURCE_DIR = Path(__file__).resolve().parents[1] / "viewer" / "public" / "assets" / "genomes"
_DIST_DIR = Path(__file__).resolve().parents[1] / "viewer" / "dist" / "assets" / "genomes"


def blob_key(assembly: str) -> str:
    """The ``inline_blobs`` key of an assembly's table (``geneBlobKey`` in TS)."""
    return f"{BLOB_PREFIX}{assembly}"


def _kind(comp: dict[str, Any]) -> str:
    return str(comp.get("viz_kind") or (comp.get("config") or {}).get("viz_kind") or "")


def gene_assemblies(components: Iterable[dict[str, Any]]) -> set[str]:
    """The assemblies the genome tiles among ``components`` read genes for."""
    out: set[str] = set()
    for comp in components:
        if comp.get("component_type") != "advanced_viz" or _kind(comp) not in GENE_TABLE_KINDS:
            continue
        config = comp.get("config") or {}
        for key in _ASSEMBLY_KEYS:
            value = config.get(key)
            if isinstance(value, str) and value in GENE_ASSET_ASSEMBLIES:
                out.add(value)
    return out


def gene_asset_path(assembly: str, template_dir: Path | None = None) -> Path | None:
    """Where this process can read ``<assembly>.genes.json``, or None.

    The checked-in source first (a checkout and the images carry it), then the
    copy Vite puts in the SPA build (``viewer/dist/assets/genomes``, the one a
    wheel carries: shipping ``public/`` too counted every table twice), then the
    one beside the static template (``dist-static/assets/genomes``).
    """
    name = f"{assembly}.genes.json"
    candidates = [_SOURCE_DIR / name, _DIST_DIR / name]
    if template_dir is not None:
        candidates.append(template_dir / "assets" / "genomes" / name)
    for path in candidates:
        if path.is_file():
            return path
    return None


def encode_gene_table(raw: bytes) -> str:
    """gzip, then base64: what ``bundledGeneTable`` decodes."""
    return base64.b64encode(gzip.compress(raw, compresslevel=9, mtime=0)).decode("ascii")


def gene_blobs(
    components: Iterable[dict[str, Any]], template_dir: Path | None = None
) -> tuple[dict[str, str], list[str]]:
    """``(inline_blobs entries, assemblies left out)`` for these components.

    An assembly whose table this process cannot read is left out and logged:
    its tiles then draw no gene lane, which is what they do on a server that
    does not serve the asset either.
    """
    blobs: dict[str, str] = {}
    missing: list[str] = []
    for assembly in sorted(gene_assemblies(components)):
        path = gene_asset_path(assembly, template_dir)
        if path is None:
            missing.append(assembly)
            logger.warning(
                "serverless: no %s gene table to ship (%s.genes.json not found); its genome "
                "tiles draw no gene lane in the bundle",
                assembly,
                assembly,
            )
            continue
        blobs[blob_key(assembly)] = encode_gene_table(path.read_bytes())
    return blobs, missing
