#!/usr/bin/env python3
"""Build the compact gene tables the ``genome_view`` annotation lane reads.

``@genome-spy/core`` ships chromosome *sizes* only (``genome/genomes.js``
exports ``getContigs(assembly)``), no gene models, so the annotation lane needs
an asset of its own. This script streams a GENCODE ``basic`` GTF over HTTP,
keeps the ``gene`` features whose ``gene_type`` is ``protein_coding`` on the
primary contigs, and writes one small JSON per assembly to
``depictio/viewer/public/assets/genomes/<assembly>.genes.json``.

The asset is deliberately array-of-arrays rather than array-of-objects: the
keys repeat once in ``columns`` instead of once per gene, which is what keeps
both files comfortably under the 1.5 MB budget the lane is allowed to download.

Nothing at runtime depends on this script; it is a build-time producer whose
output is committed. Re-run it only to move to a newer GENCODE release.

Examples
--------
    python dev/advanced_viz_kinds/build_genome_gene_assets.py --assembly hg38
    python dev/advanced_viz_kinds/build_genome_gene_assets.py \
        --assembly mm10 --release M25 --max-bytes 1500000

Sources (both CC BY 4.0, mirrored by EMBL-EBI):
    hg38 / GRCh38 -> Gencode_human/release_<N>/gencode.v<N>.basic.annotation.gtf.gz
    mm10 / GRCm38 -> Gencode_mouse/release_M25/gencode.vM25.basic.annotation.gtf.gz
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import urllib.request
from pathlib import Path

# Assembly -> (GENCODE species directory, default release, primary contigs).
# The contig list mirrors ``@genome-spy/core``'s built-in chrom.sizes tables so
# every gene in the asset lands on a contig the locus scale actually has.
ASSEMBLIES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "hg38": (
        "Gencode_human",
        "47",
        tuple(f"chr{c}" for c in [*range(1, 23), "X", "Y", "M"]),
    ),
    "mm10": (
        # M25 is the last GENCODE mouse release on GRCm38 (= mm10). Newer
        # releases are GRCm39 (= mm39), whose coordinates do not transfer.
        "Gencode_mouse",
        "M25",
        tuple(f"chr{c}" for c in [*range(1, 20), "X", "Y", "M"]),
    ),
}

BASE_URL = "https://ftp.ebi.ac.uk/pub/databases/gencode"

_ATTR = re.compile(r'(\S+) "([^"]*)"')


def gtf_url(assembly: str, release: str) -> str:
    species, _, _ = ASSEMBLIES[assembly]
    return f"{BASE_URL}/{species}/release_{release}/gencode.v{release}.basic.annotation.gtf.gz"


def parse_genes(handle, contigs: tuple[str, ...]) -> list[list[object]]:
    """Protein-coding ``gene`` rows on the primary contigs, in genome order."""
    keep = set(contigs)
    order = {name: i for i, name in enumerate(contigs)}
    rows: list[list[object]] = []
    for raw in handle:
        line = raw.decode("utf-8", "replace")
        if line.startswith("#"):
            continue
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 9 or parts[2] != "gene" or parts[0] not in keep:
            continue
        attrs = dict(_ATTR.findall(parts[8]))
        if attrs.get("gene_type") != "protein_coding":
            continue
        name = attrs.get("gene_name") or attrs.get("gene_id", "")
        if not name:
            continue
        rows.append([name, parts[0], int(parts[3]) - 1, int(parts[4]), parts[6]])
    rows.sort(key=lambda r: (order[str(r[1])], r[2]))
    return rows


def build(assembly: str, release: str, out_path: Path, max_bytes: int) -> int:
    species, _, contigs = ASSEMBLIES[assembly]
    url = gtf_url(assembly, release)
    print(f"[{assembly}] streaming {url}", file=sys.stderr)
    with urllib.request.urlopen(url) as resp, gzip.open(resp, "rb") as gz:
        genes = parse_genes(gz, contigs)
    print(f"[{assembly}] {len(genes)} protein-coding genes", file=sys.stderr)

    payload = {
        "assembly": assembly,
        "source": f"GENCODE {release} basic annotation ({species}), protein-coding genes",
        "url": url,
        "generated_by": "dev/advanced_viz_kinds/build_genome_gene_assets.py",
        "columns": ["name", "chrom", "start", "end", "strand"],
        "genes": genes,
    }
    # `separators` drops the space after every comma: ~4 % of the file.
    text = json.dumps(payload, separators=(",", ":"))
    size = len(text.encode("utf-8"))
    if size > max_bytes:
        raise SystemExit(
            f"[{assembly}] {size} bytes exceeds the {max_bytes} byte budget. "
            f"Raise --max-bytes deliberately, or narrow the gene set."
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text + "\n", encoding="utf-8")
    print(f"[{assembly}] wrote {out_path} ({size} bytes)", file=sys.stderr)
    return size


def main() -> None:
    repo = Path(__file__).resolve().parents[2]
    default_out = repo / "depictio" / "viewer" / "public" / "assets" / "genomes"

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--assembly",
        action="append",
        choices=sorted(ASSEMBLIES),
        help="Assembly to build; repeatable. Default: every known assembly.",
    )
    parser.add_argument(
        "--release",
        default=None,
        help="GENCODE release for the single assembly being built (default: per-assembly)",
    )
    parser.add_argument("--out-dir", type=Path, default=default_out)
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=1_500_000,
        help="Refuse to write an asset larger than this (default: 1500000)",
    )
    args = parser.parse_args()

    assemblies = args.assembly or sorted(ASSEMBLIES)
    if args.release and len(assemblies) != 1:
        parser.error("--release applies to a single --assembly")

    for assembly in assemblies:
        release = args.release or ASSEMBLIES[assembly][1]
        build(
            assembly,
            release,
            args.out_dir / f"{assembly}.genes.json",
            args.max_bytes,
        )


if __name__ == "__main__":
    main()
